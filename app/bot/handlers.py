"""Menu và lệnh Telegram."""
from __future__ import annotations

import asyncio
import logging
import re
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from app import reports, service, storage
from app.bot import extra, texts
from app.config import settings
from app.strategy.core import describe
from app.strategy.scanner import analyze_symbol, bucket_stats, calibration

log = logging.getLogger(__name__)

BTN_OPEN = "📊 Lệnh đang chạy"
BTN_ANALYZE = "🔍 Phân tích coin"
BTN_MODE = "⚙️ Chế độ & rủi ro"
BTN_STATS = "📈 Thống kê"
BTN_MARKET = "🌍 Thị trường"
BTN_WATCH = "🪙 Coin của tôi"
BTN_CAL = "📅 Lịch sự kiện"
BTN_AI = "🤖 Hỏi AI"
BTN_HELP = "ℹ️ Hướng dẫn"
BTN_SUB = "🔔 Bật/Tắt tín hiệu"


def is_admin(chat_id: int) -> bool:
    return chat_id in settings.admin_ids


def menu() -> ReplyKeyboardMarkup:
    rows = [[BTN_OPEN, BTN_ANALYZE], [BTN_MODE, BTN_STATS], [BTN_MARKET, BTN_WATCH], [BTN_CAL, BTN_AI],
            [BTN_HELP, BTN_SUB]]
    return ReplyKeyboardMarkup([[KeyboardButton(t) for t in r] for r in rows], resize_keyboard=True)


async def _reply(update: Update, text: str, **kw) -> None:
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True, **kw)


async def _user(update: Update, *, allow_pending: bool = False) -> dict | None:
    """Người dùng (chat riêng). None nếu bị chặn hoặc chưa được admin duyệt (chế độ riêng tư)."""
    chat, tg = update.effective_chat, update.effective_user
    user = await storage.upsert_user(chat.id, tg.username if tg else None, tg.full_name if tg else None)
    if user["banned"] and not is_admin(chat.id):
        return None
    if not user.get("approved", True) and not is_admin(chat.id):
        return user if allow_pending else None
    return user


def normalize_symbol(text: str) -> str:
    s = re.sub(r"[^A-Z0-9]", "", text.upper())
    s = s.removesuffix("USDT").removesuffix("PERP")
    return f"{s}USDT"


# ---------------------------------------------------------------- commands
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _user(update, allow_pending=True)
    if not user:
        return
    if not user.get("approved", True) and not is_admin(user["chat_id"]):
        await extra.request_approval(update, ctx, user)
        return
    await _reply(update,
                 "👋 <b>Chào mừng đến bot tín hiệu swing crypto!</b>\n\n"
                 "Bot quét Top 20 coin (và coin bạn tự chọn) mỗi giờ, gửi tín hiệu có điểm vào, SL, TP, trailing stop, "
                 "biểu đồ và theo dõi lệnh tới khi đóng.\n\n"
                 "• ⚙️ Chế độ Spot/Futures, % rủi ro, kiểu swing · 🪙 Coin của tôi\n"
                 "• 📅 Lịch sự kiện kinh tế · 🤖 Hỏi AI về thị trường, tin tức\n\n"
                 f"Chế độ hiện tại: <b>{user['mode'].upper()}</b> · rủi ro {user['risk_pct']:g}%/lệnh\n"
                 "Đổi ở nút ⚙️. Đọc ℹ️ Hướng dẫn trước khi giao dịch.",
                 reply_markup=menu())


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if await _user(update):
        await _reply(update, texts.HELP, reply_markup=menu())


def mode_keyboard(user: dict) -> InlineKeyboardMarkup:
    """Mỗi chế độ 1 hàng, rủi ro 2 hàng x 2 nút, chữ ngắn để Telegram không cắt bớt trên màn hình hẹp."""
    mark = lambda cond: "✅ " if cond else ""  # noqa: E731
    risk = lambda r: InlineKeyboardButton(f"{mark(user['risk_pct'] == r)}{r:g}%", callback_data=f"risk:{r}")  # noqa: E731
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{mark(user['mode'] == 'spot')}Spot — chỉ MUA", callback_data="mode:spot")],
        [InlineKeyboardButton(f"{mark(user['mode'] == 'futures')}Futures — LONG & SHORT", callback_data="mode:futures")],
        [risk(0.25), risk(0.5)],
        [risk(1.0), risk(2.0)],
        [InlineKeyboardButton(f"{mark(user.get('style', 'both') == k)}{t}", callback_data=f"style:{k}")
         for k, t in (("short", "⚡ Ngắn"), ("long", "🌙 Dài"), ("both", "Cả hai"))],
        [InlineKeyboardButton("🪙 Coin của tôi", callback_data="coin:menu")],
        [InlineKeyboardButton(f"📰 Tin tức ở chat riêng: {'BẬT' if user.get('news_dm', True) else 'TẮT'}",
                              callback_data="newsdm")],
    ])


STYLE_TEXT = {"short": "⚡ Swing ngắn", "long": "🌙 Swing dài", "both": "⚡ Ngắn + 🌙 Dài"}


def mode_text(user: dict) -> str:
    mode = "Spot (chỉ MUA)" if user["mode"] == "spot" else "Futures (LONG &amp; SHORT)"
    style = STYLE_TEXT.get(user.get("style", "both"), "")
    return ("⚙️ <b>Chế độ giao dịch &amp; rủi ro mỗi lệnh</b>\n\n"
            f"Đang chọn: <b>{mode}</b> · rủi ro <b>{user['risk_pct']:g}%</b>/lệnh · <b>{style}</b>\n\n"
            "• Rủi ro = % vốn mất nếu lệnh chạm SL. Người mới nên dùng <b>0.25–0.5%</b>.\n"
            "• ⚡ Swing ngắn: 1–3 tín hiệu/ngày (6h–22h), giữ vài giờ → vài ngày.\n"
            "• 🌙 Swing dài: khoảng 1 tín hiệu/tuần, giữ vài ngày → vài tuần (chỉ Futures — Spot backtest yếu).\n"
            "Bấm nút bên dưới để đổi:")


async def mode_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _user(update)
    if user:
        await _reply(update, mode_text(user), reply_markup=mode_keyboard(user))


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    user = await _user(update)
    if not user:
        await q.answer()
        return
    kind, _, value = q.data.partition(":")
    if kind == "mode":
        await storage.update_user(user["chat_id"], mode=value)
    elif kind == "risk":
        await storage.update_user(user["chat_id"], risk_pct=float(value))
    elif kind == "style" and value in STYLE_TEXT:
        await storage.update_user(user["chat_id"], style=value)
    user = await storage.get_user(user["chat_id"])
    await q.answer("Đã lưu ✅")
    try:
        await q.edit_message_text(mode_text(user), parse_mode=ParseMode.HTML, reply_markup=mode_keyboard(user))
    except BadRequest:  # bấm lại đúng lựa chọn cũ -> nội dung không đổi
        pass


async def toggle_sub(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _user(update)
    if user:
        await storage.update_user(user["chat_id"], subscribed=not user["subscribed"])
        await _reply(update, "🔕 Đã TẮT nhận tín hiệu." if user["subscribed"] else "🔔 Đã BẬT nhận tín hiệu.")


async def open_signals(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _user(update)
    if not user:
        return
    sigs = [s for s in await storage.open_signals() if service.receives(user, s)]
    if not sigs:
        await _reply(update, "📊 Hiện không có lệnh nào đang chạy.")
        return
    lines = ["📊 <b>Lệnh đang chạy</b>"]
    for s in sigs:
        st = storage.loads(s["state"])["trade"]
        mult = s["multiplier"] if user["mode"] == "spot" else 1
        emoji = "🟢" if s["side"] > 0 else "🔴"
        flags = " · đã về hòa vốn" if st["be_done"] else ""
        flags += " · đã TP1" if st["hit"] else ""
        lines.append(f"{emoji} <b>{escape(s['display'])}</b> entry {texts.price(s['entry'] / mult)} · "
                     f"SL hiện tại {texts.price(st['stop'] / mult)}{flags} · lãi tối đa {st['max_r']:+.1f}R")
    await _reply(update, "\n".join(lines))


async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _user(update):
        return
    parts = [texts.stats_message(await storage.closed_signals(days=d), t)
             for d, t in ((7, "7 ngày"), (30, "30 ngày"), (None, "Từ đầu"))]
    cal = calibration()
    names = {"short": "⚡ Swing ngắn", "long": "🌙 Swing dài"}
    for key, st in cal.get("styles", {}).items():
        s = st.get("summary", {})
        if s.get("n"):
            parts.append(f"🧪 <b>Backtest {names.get(key, key)}</b> ({cal.get('data', '')}): {s['n']} lệnh, "
                         f"{s['win']:.0%} có lời, TB {s['avgR']:+.2f}R/lệnh (nửa đầu {s['first_half_avgR']:+.2f} · "
                         f"nửa sau {s['second_half_avgR']:+.2f}), sụt giảm tối đa {s['DD']}R, tháng lỗ {s['lose_m']}")
    await _reply(update, "\n\n".join(parts))


async def market(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if await _user(update):
        msg = await update.effective_message.reply_text("⏳ Đang tổng hợp dữ liệu...")
        await msg.edit_text(await reports.morning_text(), parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def watch_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _user(update)
    if user:
        await extra.coins_menu(update, ctx, user)


async def analyze(update: Update, ctx: ContextTypes.DEFAULT_TYPE, symbol_text: str | None = None) -> None:
    user = await _user(update)
    if not user:
        return
    if not symbol_text:
        ctx.user_data["await_symbol"] = True
        await _reply(update, "🔍 Gõ tên coin muốn phân tích (vd: <code>SOL</code>, <code>PEPE</code>):")
        return
    symbol = normalize_symbol(symbol_text)
    msg = await update.effective_message.reply_text(f"⏳ Đang phân tích {symbol}...")
    try:
        res = await analyze_symbol(symbol)
    except ValueError:
        alt = f"1000{symbol}"
        try:
            res = await analyze_symbol(alt)
        except Exception:  # noqa: BLE001
            await msg.edit_text(f"❌ Không tìm thấy {symbol} trên Binance Futures.")
            return
    except Exception as exc:  # noqa: BLE001
        log.exception("analyze")
        await msg.edit_text(f"❌ Lỗi lấy dữ liệu: {exc}")
        return
    await msg.edit_text(analysis_text(res), parse_mode=ParseMode.HTML)


def analysis_text(res: dict) -> str:
    coin, cand, rows, th = res["coin"], res["candidate"], res["rows"], res["threshold"]
    lines = [f"🔍 <b>{coin.display}</b> · giá {texts.price(rows[1]['entry'])}"]
    for side, name in ((1, "LONG"), (-1, "SHORT")):
        r = rows[side]
        lines.append(f"\n<b>{name}</b>: điểm thô {r['raw']:.0f}/100 — xu hướng {r['trend']:.0f}/30, "
                     f"động lượng {r['momentum']:.0f}/15, setup {r['setup']:.0f}/20, dòng tiền {r['flow']:.0f}/15")
    d = res["deriv"]
    if d:
        lines.append("\n💹 <b>Phái sinh</b>: " + " · ".join(filter(None, [
            f"funding {d['funding']:.4%}" if "funding" in d else "",
            f"OI 24h {d['oi_chg']:+.1%}" if "oi_chg" in d else "",
            f"tỉ lệ long/short đám đông {d['ls']:.2f}" if "ls" in d else "",
            f"top trader {d['top_ls']:.2f}" if "top_ls" in d else "",
        ])))
        lines.append("<i>Bot chỉ vào lệnh khi OI biến động ≥5%, hoặc đám đông nghiêng ≥3:1 về phía ngược lại, "
                     "hoặc setup Retest.</i>")
    n = res["news"]
    if n["count"]:
        lines.append(f"📰 Tin 24h: {n['count']} bài, sentiment {n['sentiment']:+.2f}")
    if cand and not cand.vetoed and cand.score >= th:
        stats = bucket_stats(cand.score)
        lines.append(f"\n✅ <b>Có setup {cand.side_name}</b> điểm {cand.score:.0f} (ngưỡng {th:.0f})")
        lines += [f"• {escape(x)}" for x in describe(cand)]
        r = cand.row
        lines.append(f"Entry {texts.price(r['entry'])} · SL {texts.price(r['sl'])} · TP1 {texts.price(r['tp1'])}")
        if stats:
            lines.append(f"Backtest mức điểm này: {stats['win_rate']:.0%} có lời, TB {stats['avg_r']:+.2f}R")
    elif cand and cand.vetoed:
        lines.append(f"\n⛔ Có setup {cand.side_name} nhưng bị chặn: {escape(cand.vetoed)}")
    else:
        best = max(rows.values(), key=lambda r: r["raw"])
        lines.append(f"\n⏸ <b>Chưa có điểm vào đạt chuẩn</b> (ngưỡng {th:.0f}). "
                     + ("Chưa có setup hồi/retest hợp lệ." if best["setup"] == 0 else "Dòng tiền hoặc bộ lọc chưa ủng hộ."))
    lines.append("\n<i>Phân tích tự động, không phải lời khuyên đầu tư.</i>")
    return "\n".join(lines)


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.effective_message.text or "").strip()
    user = await _user(update, allow_pending=True)
    if not user:
        return
    if not user.get("approved", True) and not is_admin(user["chat_id"]):
        await _reply(update, "⏳ Bạn đang chờ admin duyệt. Khi được duyệt, bot sẽ nhắn cho bạn.")
        return
    routes = {BTN_OPEN: open_signals, BTN_MODE: mode_cmd, BTN_STATS: stats, BTN_MARKET: market,
              BTN_WATCH: watch_list, BTN_HELP: help_cmd, BTN_SUB: toggle_sub, BTN_CAL: extra.calendar_cmd,
              BTN_AI: extra.ai_prompt}
    if text in routes:
        for k in ("await_symbol", "await_coin", "await_ai"):
            ctx.user_data.pop(k, None)
        await routes[text](update, ctx)
    elif text == BTN_ANALYZE:
        await analyze(update, ctx)
    elif ctx.user_data.pop("await_symbol", False):
        await analyze(update, ctx, text)
    elif ctx.user_data.pop("await_coin", False):
        await extra.add_coin_text(update, ctx, user, text)
    elif ctx.user_data.pop("await_ai", False):
        await extra.ai_answer(update, ctx, text)
    else:
        await _reply(update, "Chọn chức năng trong menu bên dưới 👇 (muốn hỏi AI thì bấm 🤖 Hỏi AI)", reply_markup=menu())


async def analyze_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await analyze(update, ctx, " ".join(ctx.args) if ctx.args else None)


# ---------------------------------------------------------------- admin
def admin_only(fn):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not is_admin(update.effective_chat.id):
            await _reply(update, "⛔ Lệnh chỉ dành cho admin.")
            return
        await fn(update, ctx)
    return wrapper


@admin_only
async def scan_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, "⏳ Đang quét thị trường...")
    await _reply(update, escape(await service.run_scan(ctx.bot, ("short", "long"), force=True)))


@admin_only
async def add_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from app.data import binance
    if not ctx.args:
        await _reply(update, "Cú pháp: /add SOL")
        return
    perps = await binance.perpetual_symbols()
    sym = normalize_symbol(ctx.args[0])
    sym = sym if sym in perps else f"1000{sym}" if f"1000{sym}" in perps else None
    if not sym:
        await _reply(update, "❌ Coin không có trên Binance Futures.")
        return
    ok = await storage.add_watch(sym, update.effective_chat.id)
    await _reply(update, f"✅ Đã thêm {sym}" if ok else f"{sym} đã có trong danh sách")


@admin_only
async def remove_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if ctx.args:
        sym = normalize_symbol(ctx.args[0])
        ok = await storage.remove_watch(sym) or await storage.remove_watch(f"1000{sym}")
        await _reply(update, f"🗑 Đã xóa {sym}" if ok else "Không có trong danh sách")


@admin_only
async def users_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    us = await storage.all_users()
    lines = [f"👥 <b>{len(us)} người dùng</b> (⛔ chặn · ⏳ chờ duyệt · 🔔 nhận tín hiệu · 🔕 tắt)"]
    for u in us[-40:]:
        flag = "⛔" if u["banned"] else "⏳" if not u.get("approved", True) else "🔔" if u["subscribed"] else "🔕"
        n = len(await storage.user_coins_of(u["chat_id"]))
        name = escape(u.get("full_name") or u["username"] or "-")
        lines.append(f"{flag} <code>{u['chat_id']}</code> {name} · {u['mode']} · {u['risk_pct']:g}% · "
                     f"{u.get('coin_mode', 'top')} ({n} coin)")
    lines.append("\nDuyệt: /allow ID · Chặn: /ban ID · Mở: /unban ID")
    await _reply(update, "\n".join(lines))


@admin_only
async def ban_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if ctx.args and ctx.args[0].lstrip("-").isdigit():
        ban = update.message.text.startswith("/ban")
        await storage.update_user(int(ctx.args[0]), banned=ban, **({} if ban else {"approved": True}))
        await _reply(update, "✅ Đã cập nhật.")


@admin_only
async def broadcast_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.partition(" ")[2].strip()
    if not text:
        await _reply(update, "Cú pháp: /broadcast nội dung")
        return
    n = 0
    for u in await storage.subscribers():
        if await service._send(ctx.bot, u["chat_id"], f"📢 {escape(text)}"):
            n += 1
        await asyncio.sleep(0.05)
    await _reply(update, f"Đã gửi {n} người.")


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Lỗi xử lý update: %s", ctx.error, exc_info=ctx.error)


def register(app: Application) -> None:
    private = filters.ChatType.PRIVATE  # lệnh cá nhân chỉ trong chat riêng; trong nhóm bot chỉ làm việc ở topic
    app.add_handler(CommandHandler(["start", "menu"], start, filters=private))
    app.add_handler(CommandHandler(["help", "huongdan"], help_cmd, filters=private))
    app.add_handler(CommandHandler("mode", mode_cmd, filters=private))
    app.add_handler(CommandHandler(["thongke", "stats"], stats, filters=private))
    app.add_handler(CommandHandler(["phantich", "analyze"], analyze_cmd, filters=private))
    app.add_handler(CommandHandler("scan", scan_cmd, filters=private))
    app.add_handler(CommandHandler("add", add_cmd, filters=private))
    app.add_handler(CommandHandler("remove", remove_cmd, filters=private))
    app.add_handler(CommandHandler("users", users_cmd, filters=private))
    app.add_handler(CommandHandler(["ban", "unban"], ban_cmd, filters=private))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd, filters=private))
    app.add_handler(CallbackQueryHandler(on_callback, pattern=r"^(mode|risk|style):"))
    extra.register(app)
    app.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
