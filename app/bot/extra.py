"""Tính năng người dùng mở rộng: duyệt người dùng mới, 🪙 coin của tôi, 📅 lịch sự kiện, 🤖 hỏi AI, nhóm Topic."""
from __future__ import annotations

import logging
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from app import assistant, reports, storage
from app.config import settings
from app.data import binance

log = logging.getLogger(__name__)

MODE_TEXT = {"top": "🔝 Top 20", "mine": "🎯 Chỉ coin của tôi", "both": "➕ Top 20 + coin của tôi"}


def is_admin(uid: int) -> bool:
    return uid in settings.admin_ids


async def _reply(update: Update, text: str, **kw) -> None:
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True, **kw)


# ---------------------------------------------------------------- duyệt người dùng mới
async def request_approval(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user: dict) -> None:
    await _reply(update, "⏳ Bot đang ở chế độ riêng tư. Yêu cầu của bạn đã gửi tới admin, vui lòng chờ duyệt.")
    key = f"pending:{user['chat_id']}"
    if await storage.kv_get(key):
        return
    await storage.kv_set(key, "1")
    u = update.effective_user
    name = escape(u.full_name if u else "?")
    uname = f" (@{escape(u.username)})" if u and u.username else ""
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Duyệt", callback_data=f"appr:{user['chat_id']}:1"),
                                    InlineKeyboardButton("❌ Từ chối", callback_data=f"appr:{user['chat_id']}:0")]])
    for admin in settings.admin_ids:
        try:
            await ctx.bot.send_message(admin, f"🙋 <b>Người dùng mới muốn dùng bot</b>\nTên: {name}{uname}\n"
                                              f"ID: <code>{user['chat_id']}</code>", parse_mode=ParseMode.HTML,
                                       reply_markup=markup)
        except TelegramError as exc:
            log.warning("Không báo được admin %s: %s", admin, exc)


async def auto_approve_member(bot, chat_id: int) -> bool:
    """Người đã là thành viên nhóm (nhóm có topic 📰 / 💬 của bot) -> tự duyệt, không cần admin bấm."""
    groups = {t[0] for t in [await reports.group_target("news"), await reports.group_target("ai")] if t}
    for g in groups:
        try:
            m = await bot.get_chat_member(g, chat_id)
        except TelegramError:
            continue
        if m.status in ("member", "administrator", "creator", "restricted"):
            await storage.update_user(chat_id, approved=True, banned=False)
            await storage.kv_set(f"pending:{chat_id}", "")
            for admin in settings.admin_ids:
                try:
                    await bot.send_message(admin, f"✅ Tự duyệt <code>{chat_id}</code> (đã là thành viên nhóm).",
                                           parse_mode=ParseMode.HTML)
                except TelegramError:
                    pass
            return True
    return False


async def _set_approved(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, ok: bool) -> None:
    await storage.update_user(chat_id, approved=ok, banned=not ok)
    await storage.kv_set(f"pending:{chat_id}", "")
    try:
        await ctx.bot.send_message(chat_id, "✅ Bạn đã được duyệt! Gõ /start để mở menu." if ok
                                   else "❌ Yêu cầu dùng bot của bạn chưa được chấp nhận.")
    except TelegramError:
        pass


async def on_approve(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("Chỉ admin")
        return
    _, uid, ok = q.data.split(":")
    await _set_approved(ctx, int(uid), ok == "1")
    await q.answer("Đã cập nhật")
    await q.edit_message_text(q.message.text_html + ("\n\n✅ <b>Đã duyệt</b>" if ok == "1" else "\n\n❌ <b>Đã từ chối</b>"),
                              parse_mode=ParseMode.HTML)


async def allow_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args or not ctx.args[0].isdigit():
        await _reply(update, "Cú pháp: /allow ID (người đó cần bấm Start bot trước)")
        return
    uid = int(ctx.args[0])
    if not await storage.get_user(uid):
        await storage.upsert_user(uid, None)
    await _set_approved(ctx, uid, True)
    await _reply(update, f"✅ Đã duyệt <code>{uid}</code>")


# ---------------------------------------------------------------- 🪙 coin của tôi
async def coins_view(user: dict) -> tuple[str, InlineKeyboardMarkup]:
    coins = await storage.user_coins_of(user["chat_id"])
    mode = user.get("coin_mode", "top")
    lines = ["🪙 <b>Coin của tôi</b>", f"Nhận tín hiệu: <b>{MODE_TEXT.get(mode, mode)}</b>", ""]
    if coins:
        for c in coins:
            lines.append(f"• {escape(binance.split_symbol(c['symbol'])[0])}" + (" · 📌 đang giữ" if c["holding"] else ""))
    else:
        lines.append("Chưa có coin nào — đang nhận tín hiệu Top 20.")
    lines += ["", f"Tối đa {settings.max_user_coins} coin. 📌 = coin bạn đang giữ (Spot): bot cảnh báo khi xu hướng đổi "
                  "chiều, thủng vùng giá quan trọng, OI/funding bất thường, có tin xấu.",
              "<i>Coin ngoài Top 20 chưa được backtest riêng — dùng cùng chiến lược.</i>"]
    rows = [[InlineKeyboardButton(("📌 " if c["holding"] else "📍 ") + binance.split_symbol(c["symbol"])[0],
                                  callback_data=f"coin:hold:{c['symbol']}"),
             InlineKeyboardButton("🗑 Xóa", callback_data=f"coin:del:{c['symbol']}")] for c in coins]
    rows.append([InlineKeyboardButton("➕ Thêm coin", callback_data="coin:add")])
    if coins:
        rows.append([InlineKeyboardButton(("✅ " if mode == k else "") + t, callback_data=f"cmode:{k}")
                     for k, t in (("top", "Top 20"), ("mine", "Chỉ coin của tôi"), ("both", "Cả hai"))])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def coins_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user: dict) -> None:
    text, markup = await coins_view(user)
    await _reply(update, text, reply_markup=markup)


async def add_coin_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user: dict, raw: str) -> None:
    from app.bot.handlers import normalize_symbol
    coins = await storage.user_coins_of(user["chat_id"])
    added, bad = [], []
    perps = await binance.perpetual_symbols()
    for token in raw.replace(",", " ").split():
        sym = normalize_symbol(token)
        sym = sym if sym in perps else f"1000{sym}" if f"1000{sym}" in perps else None
        if not sym:
            bad.append(token.upper())
            continue
        if len(coins) + len(added) >= settings.max_user_coins:
            bad.append(f"{token.upper()} (đã đủ {settings.max_user_coins} coin)")
            continue
        if await storage.add_user_coin(user["chat_id"], sym):
            added.append(binance.split_symbol(sym)[0])
    msg = []
    if added:
        msg.append("✅ Đã thêm: " + ", ".join(added))
    if bad:
        msg.append("❌ Không thêm được (không có trên Binance Futures?): " + ", ".join(bad))
    await _reply(update, "\n".join(msg) or "Không có gì thay đổi.")
    user = await storage.get_user(user["chat_id"])
    if added and not coins and user.get("coin_mode", "top") == "top":
        await _reply(update, "Bạn muốn nhận tín hiệu thế nào?", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 Chỉ coin của tôi (tắt Top 20)", callback_data="cmode:mine")],
            [InlineKeyboardButton("➕ Cả hai: Top 20 + coin của tôi", callback_data="cmode:both")]]))
    else:
        await coins_menu(update, ctx, user)


async def on_coin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    user = await storage.get_user(q.from_user.id)
    if not user or not user.get("approved") or user.get("banned"):
        await q.answer()
        return
    parts = q.data.split(":")
    if parts[0] == "cmode":
        await storage.update_user(user["chat_id"], coin_mode=parts[1])
        await q.answer(f"Đã chọn: {MODE_TEXT[parts[1]]}")
    elif parts[1] == "add":
        ctx.user_data["await_coin"] = True
        await q.answer()
        await q.message.reply_text("✍️ Gõ tên coin muốn thêm (có thể nhiều coin, vd: <code>SOL PEPE LINK</code>):",
                                   parse_mode=ParseMode.HTML)
        return
    elif parts[1] == "del":
        await storage.remove_user_coin(user["chat_id"], parts[2])
        await q.answer("Đã xóa")
    elif parts[1] == "hold":
        await storage.toggle_holding(user["chat_id"], parts[2])
        await q.answer("Đã cập nhật 📌")
    elif parts[1] == "menu":
        await q.answer()
        await coins_menu(update, ctx, user)
        return
    text, markup = await coins_view(await storage.get_user(user["chat_id"]))
    try:
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    except BadRequest:
        await q.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


# ---------------------------------------------------------------- 📅 lịch sự kiện
async def calendar_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from app import events
    evs = await events.week_events()
    text, markup = reports.calendar_message(evs, "📅 <b>Lịch sự kiện kinh tế Mỹ tuần này</b>")
    await _reply(update, text, reply_markup=markup)


async def on_event(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from app import events
    q = update.callback_query
    await q.answer()
    kind, _, key = q.data.partition(":")
    e = await reports.find_event(key)
    if not e:
        await q.message.reply_text("Tin này đã qua tuần hoặc không còn trong lịch.")
        return
    if kind == "ev":
        markup = None
        if assistant.ai.enabled():
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("🤖 Hỏi AI phân tích sâu hơn", callback_data=f"evai:{key}")]])
        await q.message.reply_text(await events.detail_text(e), parse_mode=ParseMode.HTML, reply_markup=markup)
    else:
        await ctx.bot.send_chat_action(q.message.chat_id, ChatAction.TYPING,
                                       message_thread_id=q.message.message_thread_id)
        await q.message.reply_text(await assistant.explain_event(q.from_user.id, e), parse_mode=ParseMode.HTML)


# ---------------------------------------------------------------- 🤖 hỏi AI
async def ai_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ctx.user_data["await_ai"] = True
    await _reply(update, "🤖 <b>Trợ lý giao dịch</b> — gõ câu hỏi, ví dụ:\n"
                         "• <i>Lập kế hoạch DCA cho SOL</i> (Spot)\n"
                         "• <i>Vùng vào lệnh đẹp cho ETH ở đâu?</i>\n"
                         "• <i>Lệnh đang mở của tôi nên làm gì?</i>\n"
                         "• Reply vào tin tín hiệu để hỏi về đúng lệnh đó\n\n"
                         "Mốc giá do bot tính từ dữ liệu Binance, AI chỉ giải thích. Câu hỏi thị trường chung → topic "
                         f"💬 Hỏi đáp AI của nhóm. {settings.ai_daily_limit} câu/ngày, câu ngoài phạm vi không tính lượt.")


async def ai_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE, question: str, *, user: dict | None = None,
                    signal: dict | None = None) -> None:
    """user != None -> trợ lý giao dịch (chat riêng); None -> trợ lý thị trường (topic nhóm)."""
    msg = update.effective_message
    await ctx.bot.send_chat_action(msg.chat_id, ChatAction.TYPING, message_thread_id=msg.message_thread_id)
    text = await assistant.answer(update.effective_user.id, question, scope="trade" if user else "market",
                                  user=user, signal=signal)
    await msg.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def on_why(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer("Đang phân tích...")
    sig = await storage.get_signal(int(q.data.split(":")[1]))
    if not sig:
        return
    await ctx.bot.send_chat_action(q.message.chat_id, ChatAction.TYPING)
    user = await storage.get_user(q.from_user.id)
    await q.message.reply_text(await assistant.explain_signal(q.from_user.id, sig, user), parse_mode=ParseMode.HTML)


async def ai_ping_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if is_admin(update.effective_user.id):
        await _reply(update, await assistant.ping())


# ---------------------------------------------------------------- nhóm có Topic
async def set_target(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/set_news hoặc /set_ai gõ trong đúng topic của nhóm (chỉ admin)."""
    msg = update.effective_message
    if not is_admin(update.effective_user.id):
        await msg.reply_text("⛔ Chỉ admin dùng được lệnh này.")
        return
    if msg.chat.type == "private":
        await msg.reply_text("Hãy gõ lệnh này bên trong topic của nhóm Telegram.")
        return
    kind = "news" if msg.text.startswith("/set_news") else "ai"
    await storage.kv_set(f"{kind}_target", f"{msg.chat_id}:{msg.message_thread_id}")
    await msg.reply_text("✅ Từ giờ tin tức, lịch sự kiện và cảnh báo thị trường sẽ gửi vào topic này." if kind == "news"
                         else "✅ Từ giờ bot trả lời câu hỏi về thị trường crypto trong topic này bằng AI "
                              f"({settings.ai_daily_limit} câu/người/ngày).")


async def group_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Tin nhắn trong nhóm: chỉ trả lời ở topic Hỏi đáp AI; các topic khác bỏ qua.
    Thành viên nhóm hỏi được luôn (đã vào nhóm = đã được admin nhóm cho phép)."""
    msg = update.effective_message
    target = await reports.group_target("ai")
    if not target or msg.chat_id != target[0] or msg.message_thread_id != target[1]:
        return
    await ai_answer(update, ctx, msg.text)


async def news_dm_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    user = await storage.get_user(q.from_user.id)
    if not user:
        await q.answer()
        return
    await storage.update_user(user["chat_id"], news_dm=not user.get("news_dm", False))
    await q.answer("📰 Đã TẮT tin tức ở chat riêng" if user.get("news_dm", False) else "📰 Đã BẬT tin tức ở chat riêng")
    from app.bot.handlers import mode_keyboard, mode_text
    user = await storage.get_user(user["chat_id"])
    try:
        await q.edit_message_text(mode_text(user), parse_mode=ParseMode.HTML, reply_markup=mode_keyboard(user))
    except BadRequest:
        pass


def register(app: Application) -> None:
    private = filters.ChatType.PRIVATE
    app.add_handler(CommandHandler(["set_news", "set_ai"], set_target))
    app.add_handler(CommandHandler("allow", allow_cmd, filters=private))
    app.add_handler(CommandHandler(["lich", "calendar"], calendar_cmd))
    app.add_handler(CommandHandler("ai_ping", ai_ping_cmd, filters=private))
    app.add_handler(CallbackQueryHandler(on_approve, pattern=r"^appr:"))
    app.add_handler(CallbackQueryHandler(on_coin, pattern=r"^(coin|cmode):"))
    app.add_handler(CallbackQueryHandler(on_event, pattern=r"^(ev|evai):"))
    app.add_handler(CallbackQueryHandler(on_why, pattern=r"^why:"))
    app.add_handler(CallbackQueryHandler(news_dm_toggle, pattern=r"^newsdm$"))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, group_text))
