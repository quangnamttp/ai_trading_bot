"""📰 Bot Tin tức: chat riêng từng người — tin tự động, lịch tuần, thị trường, coin đáng chú ý, hỏi AI crypto.

Dùng chung danh sách người dùng với Bot Tín hiệu: phải được duyệt ở Bot Tín hiệu mới dùng được; bị chặn/xóa ở đó
thì bên này cũng vậy. Tin tự động do reports.broadcast_news gửi qua bot này (mỗi người tự tắt từng loại tin).
"""
from __future__ import annotations

import asyncio
import logging
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from app import assistant, events, reports, storage
from app.bot import extra
from app.config import settings

log = logging.getLogger(__name__)
B = InlineKeyboardButton

BTN_LATEST = "📰 Tin mới nhất"
BTN_CAL = "📅 Lịch tuần"
BTN_MARKET = "🌍 Thị trường 24h"
BTN_HOT = "🔥 Coin đáng chú ý"
BTN_AI = "🤖 Hỏi AI crypto"
BTN_SETTINGS = "⚙️ Cài đặt tin"
BTN_HELP = "ℹ️ Hướng dẫn"
BTN_BROADCAST = "📣 Gửi thông báo"
MENU_VERSION = "news-2026-09-25"

HELP = (
    "📰 <b>Bot Tin tức</b>\n\n"
    "<b>Tự động gửi</b> (tắt/bật từng loại ở ⚙️ Cài đặt tin):\n"
    "• 07:00 thị trường 24h + funding cực đoan · lịch kinh tế trong ngày chỉ khi có tin mạnh (lịch tuần ghim đầu chat)\n"
    "• Tin vĩ mô Mỹ: trước 1 giờ và 1 giờ sau khi ra tin (BTC/ETH phản ứng thật)\n"
    "• Tin gấp, báo ngay: ⚡ tin nóng ảnh hưởng xu hướng · 💰 tiền lớn vào/ra (stablecoin) · 🆕 coin niêm yết Binance/Upbit\n"
    "• 🚀 Dấu hiệu sớm (kèm ảnh): coin sắp biến động mạnh (gom hàng / ép short), chưa rõ hướng — bấm nút để Bot Tín "
    "hiệu kết luận có nên vào LONG/SHORT không\n"
    "• 📈 Coin Top 20 chạy mạnh (tối đa 1 tin / 4 giờ) · BTC ±3%/giờ · Chủ nhật 20:00 tổng kết tuần\n\n"
    "<b>📖 Đọc tin</b>: bấm vào tin bất kỳ → bản tóm tắt tiếng Việt, có nút mở bài gốc.\n\n"
    f"<b>🤖 Hỏi AI</b>: gõ câu hỏi bất kỳ về crypto — coin nào đang mạnh, tin tức, vĩ mô… "
    f"({settings.ai_news_daily_limit} câu/ngày, câu ngoài chủ đề không tính lượt).\n"
    "Tín hiệu vào lệnh, danh mục, 🔍 phân tích coin: ở 🤖 Bot Tín hiệu."
)


def is_admin(uid: int) -> bool:
    return uid in settings.admin_ids


def menu(user: dict | None) -> ReplyKeyboardMarkup:
    rows = [[BTN_LATEST, BTN_CAL], [BTN_MARKET, BTN_HOT], [BTN_AI, BTN_SETTINGS], [BTN_HELP]]
    if user and is_admin(user["chat_id"]):
        rows[-1].append(BTN_BROADCAST)
    return ReplyKeyboardMarkup([[KeyboardButton(t) for t in r] for r in rows], resize_keyboard=True, is_persistent=True)


async def _reply(update: Update, text: str, **kw) -> None:
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True, **kw)


async def _member(update: Update, ctx: ContextTypes.DEFAULT_TYPE | None = None) -> dict | None:
    """Người được dùng Bot Tin tức (admin đã bật quyền 📰, không bị chặn). Chưa có quyền -> gửi yêu cầu duyệt
    về 👥 Quản lý (Bot Tín hiệu). None -> đã báo lý do."""
    tg = update.effective_user
    uid = tg.id
    user = await storage.upsert_user(uid, tg.username, tg.full_name)
    if user["banned"] and not is_admin(uid):
        await _reply(update, "⛔ Tài khoản này không dùng được bot.")
        return None
    if user.get("news_ok") or is_admin(uid):
        if not user.get("news_started"):
            await storage.update_user(uid, news_started=True)
            user = await storage.get_user(uid)
        return user
    if ctx is not None:
        await extra.request_approval(update, ctx, user, "n")
    else:
        await _reply(update, "⏳ Bạn cần được admin duyệt để dùng Bot Tin tức. Bấm /start để gửi yêu cầu.")
    return None


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _member(update, ctx)
    if not user:
        return
    if ctx.args and ctx.args[0].startswith("nw_"):  # bấm tiêu đề tin -> tóm tắt tiếng Việt
        await read_news(update, ctx.args[0][3:])
        return
    await _reply(update, "👋 <b>Chào mừng đến Bot Tin tức!</b>\n\n" + HELP, reply_markup=menu(user))


async def read_news(update: Update, nid: str) -> None:
    from app import newsread
    msg = await update.effective_message.reply_text("⏳ Đang tóm tắt tin bằng tiếng Việt...")
    got = await newsread.summary(nid)
    if not got:
        await msg.edit_text("Tin này đã cũ, không còn trong bộ nhớ. Bấm 📰 Tin mới nhất để xem tin mới.")
        return
    text, url = got
    markup = InlineKeyboardMarkup([[B("🔗 Đọc bài gốc (tiếng Anh)", url=url)]]) if url else None
    try:
        await msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup, disable_web_page_preview=True)
    except TelegramError as exc:
        log.warning("Gửi tóm tắt tin lỗi: %s", exc)


# ---------------------------------------------------------------- ⚙️ cài đặt tin
def settings_view(user: dict) -> tuple[str, InlineKeyboardMarkup]:
    off = reports.news_off(user)
    rows = [[B(("🔕 " if k in off else "🔔 ") + name, callback_data=f"nset:{k}")] for k, name in reports.NEWS_CATS.items()]
    return ("⚙️ <b>Cài đặt tin tự động</b>\nBấm để bật 🔔 / tắt 🔕 từng loại tin. Tin thường ban đêm (22h–6h) gửi "
            "không chuông; tin gấp (⚡ 💰 🆕) luôn có chuông."), InlineKeyboardMarkup(rows)


async def on_setting(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    user = await storage.get_user(q.from_user.id)
    if not user or user["banned"]:
        await q.answer()
        return
    cat = q.data.split(":")[1]
    off = reports.news_off(user)
    off ^= {cat}
    await storage.update_user(user["chat_id"], news_prefs=storage.dumps(sorted(off)))
    await q.answer(("Đã tắt " if cat in off else "Đã bật ") + reports.NEWS_CATS.get(cat, cat))
    text, markup = settings_view(await storage.get_user(user["chat_id"]))
    try:
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    except BadRequest:
        pass


# ---------------------------------------------------------------- tin nhắn
async def _slow(update: Update, ctx: ContextTypes.DEFAULT_TYPE, make) -> None:
    """Nội dung cần tải dữ liệu vài giây: hiện '⏳' ngay rồi sửa thành kết quả."""
    msg = await update.effective_message.reply_text("⏳ Đang tổng hợp dữ liệu...")
    try:
        await msg.edit_text(await make(), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except TelegramError as exc:
        log.warning("Gửi nội dung lỗi: %s", exc)


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _member(update, ctx)
    if not user:
        return
    text = (update.effective_message.text or "").strip()
    if ctx.user_data.pop("await_bc", False) and is_admin(user["chat_id"]):
        await _broadcast(update, ctx, text)
        return
    if text == BTN_LATEST:
        await _slow(update, ctx, reports.latest_news_text)
    elif text == BTN_CAL:
        await extra.calendar_cmd(update, ctx)
    elif text == BTN_MARKET:
        await _slow(update, ctx, reports.morning_text)
    elif text == BTN_HOT:
        await _slow(update, ctx, reports.hot_coins_text)
    elif text == BTN_AI:
        await _reply(update, "🤖 Gõ câu hỏi về crypto, ví dụ: <i>Coin nào đang mạnh?</i> · <i>CPI tối nay ảnh hưởng BTC thế nào?</i> · "
                             "<i>ETH tuần này ra sao?</i>")
    elif text == BTN_SETTINGS:
        t, markup = settings_view(user)
        await _reply(update, t, reply_markup=markup)
    elif text == BTN_HELP:
        await _reply(update, HELP, reply_markup=menu(user))
    elif text == BTN_BROADCAST and is_admin(user["chat_id"]):
        ctx.user_data["await_bc"] = True
        await _reply(update, "📣 Gõ nội dung thông báo gửi tới tất cả người dùng Bot Tin tức:")
    else:
        await ctx.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        answer, buttons = await assistant.answer_market(user["chat_id"], text, "news")
        await _reply(update, answer, reply_markup=_links(buttons, answer))


def _links(buttons: list[tuple[str, str]], answer: str) -> InlineKeyboardMarkup | None:
    rows = [[B(t, url=d)] for t, d in buttons if d.startswith("http")]
    if "Bot Tín hiệu" in answer and reports.SIGNAL_USERNAME:
        rows.append([B("🤖 Mở Bot Tín hiệu", url=f"https://t.me/{reports.SIGNAL_USERNAME}")])
    return InlineKeyboardMarkup(rows) if rows else None


async def _broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    n = 0
    for u in await storage.news_users():
        try:
            await ctx.bot.send_message(u["chat_id"], f"📣 {escape(text)}", parse_mode=ParseMode.HTML)
            n += 1
        except TelegramError:
            pass
        await asyncio.sleep(0.05)
    await _reply(update, f"✅ Đã gửi {n} người.")


async def on_event(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """ℹ️ chi tiết tin kinh tế / 🤖 AI phân tích (dùng lượt hỏi của Bot Tin tức)."""
    q = update.callback_query
    await q.answer()
    kind, _, key = q.data.partition(":")
    e = await reports.find_event(key)
    if not e:
        await q.message.reply_text("Tin này đã qua tuần hoặc không còn trong lịch.")
        return
    if kind == "ev":
        markup = InlineKeyboardMarkup([[B("🤖 Hỏi AI phân tích sâu hơn", callback_data=f"evai:{key}")]]) \
            if assistant.ai.enabled() else None
        await q.message.reply_text(await events.detail_text(e), parse_mode=ParseMode.HTML, reply_markup=markup)
    else:
        await ctx.bot.send_chat_action(q.message.chat_id, ChatAction.TYPING)
        await q.message.reply_text(await assistant.explain_event(q.from_user.id, e, "news"), parse_mode=ParseMode.HTML)


async def refresh_menus(bot) -> None:
    """Gửi bàn phím mới cho người dùng Bot Tin tức khi bố cục menu đổi (1 lần mỗi phiên bản)."""
    if await storage.kv_get("news_menu_version") == MENU_VERSION:
        return
    await storage.kv_set("news_menu_version", MENU_VERSION)
    for u in await storage.news_users():
        try:
            await bot.send_message(u["chat_id"], "🔄 Menu đã cập nhật 👇", reply_markup=menu(u), disable_notification=True)
        except TelegramError:
            pass
        await asyncio.sleep(0.05)


def register(app: Application) -> None:
    from app.bot.handlers import on_error
    private = filters.ChatType.PRIVATE
    app.add_handler(CommandHandler(["start", "menu", "help"], start, filters=private))
    app.add_handler(CallbackQueryHandler(on_setting, pattern=r"^nset:"))
    app.add_handler(CallbackQueryHandler(on_event, pattern=r"^(ev|evai):"))
    app.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
