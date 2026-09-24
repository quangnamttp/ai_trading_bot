"""Tính năng người dùng mở rộng: duyệt người dùng mới, 🪙 coin theo dõi (Futures), 📅 lịch sự kiện, 🤖 hỏi AI,
topic 📰 Tin tức của nhóm."""
from __future__ import annotations

import logging
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, filters

from app import assistant, reports, storage
from app.config import settings
from app.data import binance

log = logging.getLogger(__name__)

MODE_TEXT = {"top": "🔝 Top 20", "mine": "🎯 Chỉ coin của tôi", "both": "➕ Top 20 + coin của tôi"}
B = InlineKeyboardButton


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
    groups = {t[0] for t in [await reports.group_target("news")] if t}
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
    lines = ["🪙 <b>Coin theo dõi (Futures)</b>", f"Nhận tín hiệu: <b>{MODE_TEXT.get(mode, mode)}</b>", ""]
    if coins:
        lines += [f"• {escape(binance.split_symbol(c['symbol'])[0])}" for c in coins]
    else:
        lines.append("Chưa có coin nào — đang nhận tín hiệu Top 20.")
    lines += ["", f"Tối đa {settings.max_user_coins} coin. Bot quét thêm các coin này mỗi giờ bằng cùng chiến lược.",
              "<i>Coin ngoài Top 20 chưa được backtest riêng. Coin đang giữ Spot: chuyển sang chế độ Spot → 💼 Danh mục.</i>"]
    rows = [[B("🗑 " + binance.split_symbol(c["symbol"])[0], callback_data=f"coin:del:{c['symbol']}")
             for c in coins[i:i + 3]] for i in range(0, len(coins), 3)]
    rows.append([B("➕ Thêm coin", callback_data="coin:add")])
    if coins:
        rows.append([B(("✅ " if mode == k else "") + t, callback_data=f"cmode:{k}")
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
    from app.bot import portfolio_ui
    q = update.callback_query
    user = await storage.get_user(q.from_user.id)
    if not user or not user.get("approved") or user.get("banned"):
        await q.answer()
        return
    parts = q.data.split(":")
    if parts[0] == "cmode":
        await storage.update_user(user["chat_id"], coin_mode=parts[1])
        await q.answer(f"Đã chọn: {MODE_TEXT[parts[1]]}")
        user = await storage.get_user(user["chat_id"])
        if user["mode"] == "spot":
            await portfolio_ui.show_list(update, ctx, user, edit=True)
            return
    elif parts[1] == "add":
        ctx.user_data["await_coin"] = True
        await q.answer()
        await q.message.reply_text("✍️ Gõ tên coin muốn thêm (có thể nhiều coin, vd: <code>SOL PEPE LINK</code>):",
                                   parse_mode=ParseMode.HTML)
        return
    elif parts[1] == "del":
        await storage.remove_user_coin(user["chat_id"], parts[2])
        await q.answer("Đã xóa")
    elif parts[1] == "menu":
        await q.answer()
        await coins_menu(update, ctx, user)
        return
    else:
        await q.answer()
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
def _markup(buttons: list[tuple[str, str]]) -> InlineKeyboardMarkup | None:
    return InlineKeyboardMarkup([[B(t, callback_data=d)] for t, d in buttons]) if buttons else None


async def ai_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await storage.get_user(update.effective_user.id)
    spot = user and user.get("mode") == "spot"
    personal = ("💼 Về danh mục của tôi" if spot else "📊 Về tín hiệu của tôi")
    ctx.user_data["await_ai"] = "personal"
    await _reply(update,
                 "🤖 <b>Hỏi AI</b> — chọn mục rồi gõ câu hỏi (chỉ bạn thấy câu hỏi và câu trả lời):\n\n"
                 + ("💼 <b>Danh mục của tôi</b> (Spot): coin trong danh mục — nên DCA bao nhiêu, ở đâu, giá vốn, lời/lỗ.\n"
                    "   Vd: <i>Nên DCA SOL thế nào?</i>\n" if spot else
                    "📊 <b>Tín hiệu của tôi</b> (Futures): lệnh bot đã gửi và còn mở — vì sao LONG/SHORT, khi nào về bờ.\n"
                    "   Vd: <i>Lệnh ETH khi nào về bờ?</i> · hoặc reply thẳng vào tin tín hiệu.\n")
                 + "🌍 <b>Thị trường chung</b>: tin tức, lịch sự kiện, dữ liệu thị trường, mọi coin.\n\n"
                 f"<i>{settings.ai_daily_limit} câu/ngày · câu ngoài phạm vi không tính lượt.</i>",
                 reply_markup=InlineKeyboardMarkup([[B(personal, callback_data="aimode:personal"),
                                                     B("🌍 Thị trường chung", callback_data="aimode:market")]]))


async def ai_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE, question: str, *, user: dict,
                    signal: dict | None = None, kind: str = "personal") -> None:
    """kind='personal': Spot -> danh mục, Futures -> tín hiệu của tôi · kind='market': thị trường chung."""
    msg = update.effective_message
    await ctx.bot.send_chat_action(msg.chat_id, ChatAction.TYPING)
    ctx.user_data["ai_q"] = question  # để nút 🌍 / chọn lệnh dùng lại câu hỏi
    if kind == "market":
        text, buttons = await assistant.answer_market(user["chat_id"], question)
    else:
        text, buttons = await assistant.answer_personal(user, question, signal)
    await msg.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=_markup(buttons))


async def on_ai(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """aimode:personal|market (chọn mục) · aisig:<id> (chọn lệnh để hỏi) · aimkt (hỏi lại câu vừa rồi ở Thị trường chung)."""
    q = update.callback_query
    user = await storage.get_user(q.from_user.id)
    if not user or not user.get("approved") or user.get("banned"):
        await q.answer()
        return
    kind, _, value = q.data.partition(":")
    if kind == "aimode":
        ctx.user_data["await_ai"] = value
        await q.answer("Đã chọn")
        await q.message.reply_text("🌍 Gõ câu hỏi về thị trường chung:" if value == "market" else
                                   ("💼 Gõ câu hỏi về coin trong danh mục của bạn:" if user["mode"] == "spot"
                                    else "📊 Gõ câu hỏi về tín hiệu bạn đang có:"))
        return
    question = ctx.user_data.get("ai_q")
    await q.answer()
    if not question:
        await q.message.reply_text("Hãy gõ lại câu hỏi nhé.")
        return
    await ctx.bot.send_chat_action(q.message.chat_id, ChatAction.TYPING)
    if kind == "aisig":
        sig = await storage.get_signal(int(value))
        text, buttons = await assistant.answer_personal(user, question, sig) if sig else ("Không tìm thấy lệnh.", [])
    else:
        text, buttons = await assistant.answer_market(user["chat_id"], question)
    await q.message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=_markup(buttons))


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
    """/set_news gõ trong topic 📰 của nhóm (chỉ admin)."""
    msg = update.effective_message
    if not is_admin(update.effective_user.id):
        await msg.reply_text("⛔ Chỉ admin dùng được lệnh này.")
        return
    if msg.chat.type == "private":
        await msg.reply_text("Hãy gõ lệnh này bên trong topic Tin tức của nhóm Telegram.")
        return
    await storage.kv_set("news_target", f"{msg.chat_id}:{msg.message_thread_id}")
    await msg.reply_text("✅ Từ giờ tin tức, lịch sự kiện và cảnh báo thị trường sẽ gửi vào topic này.")


def register(app: Application) -> None:
    private = filters.ChatType.PRIVATE
    app.add_handler(CommandHandler("set_news", set_target))
    app.add_handler(CommandHandler("allow", allow_cmd, filters=private))
    app.add_handler(CommandHandler(["lich", "calendar"], calendar_cmd))
    app.add_handler(CommandHandler("ai_ping", ai_ping_cmd, filters=private))
    app.add_handler(CallbackQueryHandler(on_approve, pattern=r"^appr:"))
    app.add_handler(CallbackQueryHandler(on_coin, pattern=r"^(coin|cmode):"))
    app.add_handler(CallbackQueryHandler(on_event, pattern=r"^(ev|evai):"))
    app.add_handler(CallbackQueryHandler(on_why, pattern=r"^why:"))
    app.add_handler(CallbackQueryHandler(on_ai, pattern=r"^(aimode|aisig|aimkt)"))
