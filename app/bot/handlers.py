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

from app import service, storage
from app.bot import texts
from app.config import settings
from app.strategy.core import describe
from app.strategy.scanner import analyze_symbol, bucket_stats, calibration

log = logging.getLogger(__name__)

BTN_OPEN = "📊 Lệnh đang chạy"
BTN_ANALYZE = "🔍 Phân tích coin"
BTN_MODE = "⚙️ Chế độ & rủi ro"
BTN_STATS = "📈 Thống kê"
BTN_MARKET = "🌍 Thị trường"
BTN_WATCH = "📋 Danh sách coin"
BTN_HELP = "ℹ️ Hướng dẫn"
BTN_SUB = "🔔 Bật/Tắt tín hiệu"


def is_admin(chat_id: int) -> bool:
    return chat_id in settings.admin_ids


def menu() -> ReplyKeyboardMarkup:
    rows = [[BTN_OPEN, BTN_ANALYZE], [BTN_MODE, BTN_STATS], [BTN_MARKET, BTN_WATCH], [BTN_HELP, BTN_SUB]]
    return ReplyKeyboardMarkup([[KeyboardButton(t) for t in r] for r in rows], resize_keyboard=True)


async def _reply(update: Update, text: str, **kw) -> None:
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True, **kw)


async def _user(update: Update) -> dict | None:
    chat = update.effective_chat
    user = await storage.upsert_user(chat.id, update.effective_user.username if update.effective_user else None)
    if user["banned"]:
        return None
    return user


def normalize_symbol(text: str) -> str:
    s = re.sub(r"[^A-Z0-9]", "", text.upper())
    s = s.removesuffix("USDT").removesuffix("PERP")
    return f"{s}USDT"


# ---------------------------------------------------------------- commands
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _user(update)
    if not user:
        return
    await _reply(update,
                 "👋 <b>Chào mừng đến bot tín hiệu swing crypto!</b>\n\n"
                 "Bot quét top coin mỗi giờ và gửi <b>1–5 tín hiệu/ngày</b> có vùng vào lệnh, SL, TP, "
                 "biểu đồ và theo dõi lệnh tới khi đóng.\n\n"
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
    ])


def mode_text(user: dict) -> str:
    mode = "Spot (chỉ MUA)" if user["mode"] == "spot" else "Futures (LONG &amp; SHORT)"
    return ("⚙️ <b>Chế độ giao dịch &amp; rủi ro mỗi lệnh</b>\n\n"
            f"Đang chọn: <b>{mode}</b> · rủi ro <b>{user['risk_pct']:g}%</b>/lệnh\n\n"
            "Rủi ro = % vốn mất nếu lệnh chạm SL. Người mới nên dùng <b>0.25–0.5%</b>.\n"
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
    if cal.get("summary"):
        s = cal["summary"]
        parts.append(f"🧪 <b>Backtest</b> {cal['days']} ngày, {cal['coins']} coin: {s['closed']} lệnh, "
                     f"{s['win_rate']:.0%} có lời, TB {s['avg_r']:+.2f}R/lệnh, sụt giảm tối đa {s['max_dd_r']}R, "
                     f"tháng lỗ {s['losing_months']}")
    await _reply(update, "\n\n".join(parts))


async def market(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if await _user(update):
        msg = await update.effective_message.reply_text("⏳ Đang tổng hợp dữ liệu...")
        await msg.edit_text(await service.market_overview(), parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def watch_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _user(update)
    if not user:
        return
    extra = await storage.get_watchlist()
    text = (f"📋 <b>Danh sách quét</b>\n• Tự động: top {settings.top_n} coin theo khối lượng Binance Futures\n"
            f"• Thêm thủ công: {', '.join(extra) if extra else '(chưa có)'}")
    if is_admin(user["chat_id"]):
        text += "\n\nAdmin: /add SOL · /remove SOL"
    await _reply(update, text)


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
            f"OI 24h {d['oi_change_24h']:+.1%}" if "oi_change_24h" in d else "",
            f"L/S đám đông {d['global_ls']:.2f}" if "global_ls" in d else "",
            f"top trader {d['top_ls']:.2f}" if "top_ls" in d else "",
        ])))
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
    routes = {BTN_OPEN: open_signals, BTN_MODE: mode_cmd, BTN_STATS: stats, BTN_MARKET: market,
              BTN_WATCH: watch_list, BTN_HELP: help_cmd, BTN_SUB: toggle_sub}
    if text in routes:
        ctx.user_data.pop("await_symbol", None)
        await routes[text](update, ctx)
    elif text == BTN_ANALYZE:
        await analyze(update, ctx)
    elif ctx.user_data.pop("await_symbol", False):
        await analyze(update, ctx, text)
    else:
        await _reply(update, "Chọn chức năng trong menu bên dưới 👇", reply_markup=menu())


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
    await _reply(update, escape(await service.run_scan(ctx.bot)))


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
    lines = [f"👥 <b>{len(us)} người dùng</b>"]
    for u in us[-40:]:
        flag = "⛔" if u["banned"] else "🔔" if u["subscribed"] else "🔕"
        lines.append(f"{flag} <code>{u['chat_id']}</code> @{escape(u['username'] or '-')} · {u['mode']} · {u['risk_pct']:g}%")
    await _reply(update, "\n".join(lines))


@admin_only
async def ban_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if ctx.args and ctx.args[0].lstrip("-").isdigit():
        await storage.update_user(int(ctx.args[0]), banned=update.message.text.startswith("/ban"))
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
    app.add_handler(CommandHandler(["start", "menu"], start))
    app.add_handler(CommandHandler(["help", "huongdan"], help_cmd))
    app.add_handler(CommandHandler("mode", mode_cmd))
    app.add_handler(CommandHandler(["thongke", "stats"], stats))
    app.add_handler(CommandHandler(["phantich", "analyze"], analyze_cmd))
    app.add_handler(CommandHandler("scan", scan_cmd))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("remove", remove_cmd))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler(["ban", "unban"], ban_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CallbackQueryHandler(on_callback, pattern=r"^(mode|risk):"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
