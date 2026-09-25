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
from app.bot import extra, portfolio_ui, texts
from app.config import settings
from app.strategy.core import describe
from app.strategy.scanner import analyze_symbol, bucket_stats, calibration

log = logging.getLogger(__name__)

BTN_OPEN = "📊 Lệnh đang chạy"
BTN_SPOT_SIG = "📊 Tín hiệu Spot"
BTN_ANALYZE = "🔍 Phân tích coin"
BTN_SETTINGS = "⚙️ Cài đặt"
BTN_STATS = "📈 Thống kê"
BTN_WATCH = "🪙 Coin theo dõi"
BTN_PORTFOLIO = "💼 Danh mục của tôi"
BTN_AI = "🤖 Hỏi AI"
BTN_HELP = "ℹ️ Hướng dẫn"
BTN_ADMIN = "👥 Quản lý"
# nút của bàn phím cũ (người dùng chưa bấm /start lại vẫn bấm được)
OLD_BUTTONS = {"⚙️ Chế độ & rủi ro": BTN_SETTINGS, "🪙 Coin của tôi": BTN_WATCH, "🔔 Bật/Tắt tín hiệu": BTN_SETTINGS,
               "🌍 Thị trường": "market", "📅 Lịch sự kiện": "calendar"}


def is_admin(chat_id: int) -> bool:
    return chat_id in settings.admin_ids


def menu(user: dict | None = None) -> ReplyKeyboardMarkup:
    """Menu theo chế độ (Spot: danh mục · Futures: lệnh & coin theo dõi) và vai trò (admin thêm 👥 Quản lý).
    Tin tức, lịch sự kiện, thị trường chung nằm ở topic 📰 của nhóm nên không lặp lại ở đây."""
    if user and user.get("mode") == "spot":
        rows = [[BTN_PORTFOLIO, BTN_ANALYZE], [BTN_AI, BTN_SPOT_SIG], [BTN_SETTINGS, BTN_STATS], [BTN_HELP]]
    else:
        rows = [[BTN_OPEN, BTN_ANALYZE], [BTN_AI, BTN_WATCH], [BTN_SETTINGS, BTN_STATS], [BTN_HELP]]
    if user and is_admin(user["chat_id"]):
        rows[-1].append(BTN_ADMIN)
    # is_persistent: bàn phím luôn hiện, không bị thu lại sau khi bấm
    return ReplyKeyboardMarkup([[KeyboardButton(t) for t in r] for r in rows], resize_keyboard=True, is_persistent=True)


# Đổi số này mỗi khi bố cục menu thay đổi -> lần khởi động sau bot tự gửi bàn phím mới cho mọi người
MENU_VERSION = "2026-09-24-2"


async def refresh_menus(bot) -> int:
    """Gửi bàn phím mới cho mọi người dùng đã duyệt (1 lần cho mỗi phiên bản menu, không chuông)."""
    if await storage.kv_get("menu_version") == MENU_VERSION:
        return 0
    await storage.kv_set("menu_version", MENU_VERSION)
    n = 0
    for u in await storage.all_users():
        if u["banned"] or not (u.get("approved", True) or is_admin(u["chat_id"])):
            continue
        try:
            await bot.send_message(u["chat_id"], "🔄 Menu đã cập nhật — các chức năng nằm ở bàn phím nút bên dưới 👇",
                                   reply_markup=menu(u), disable_notification=True)
            n += 1
        except Exception as exc:  # noqa: BLE001
            log.info("Không gửi được menu mới cho %s: %s", u["chat_id"], exc)
        await asyncio.sleep(0.05)
    log.info("Đã gửi menu mới cho %d người", n)
    return n


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
        if await extra.auto_approve_member(ctx.bot, user["chat_id"]):
            user = await storage.get_user(user["chat_id"])
        else:
            await extra.request_approval(update, ctx, user)
            return
    if ctx.args and ctx.args[0].startswith("an_"):  # nút 🔍 từ Bot Tin tức
        await analyze(update, ctx, ctx.args[0][3:])
        return
    await _reply(update,
                 "👋 <b>Chào mừng đến bot tín hiệu swing crypto!</b>\n\n"
                 "Bot quét Top 20 coin (và coin bạn tự chọn) mỗi giờ, gửi tín hiệu có điểm vào, SL, TP, trailing stop, "
                 "biểu đồ và theo dõi lệnh tới khi đóng.\n\n"
                 + ("• 💼 Danh mục: ghi mua/bán, giá vốn, kế hoạch DCA theo số tiền, bot nhắc khi giá chạm vùng DCA\n"
                    "• 🤖 Hỏi AI về coin trong danh mục của bạn\n" if user["mode"] == "spot" else
                    "• 🪙 Coin theo dõi: thêm coin muốn nhận tín hiệu ngoài Top 20\n"
                    "• 🤖 Hỏi AI về tín hiệu bot đã gửi cho bạn\n")
                 + (f"• 📰 Tin tức, lịch sự kiện, hỏi AI thị trường: @{reports.NEWS_USERNAME}\n\n" if reports.NEWS_USERNAME
                    else "\n")
                 + f"Chế độ hiện tại: <b>{user['mode'].upper()}</b> · rủi ro {user['risk_pct']:g}%/lệnh\n"
                 "Đổi ở ⚙️ Cài đặt. Đọc ℹ️ Hướng dẫn trước khi giao dịch.",
                 reply_markup=menu(user))


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _user(update)
    if user:
        await _reply(update, texts.HELP, reply_markup=menu(user))


def mode_keyboard(user: dict) -> InlineKeyboardMarkup:
    """Chữ ngắn, rủi ro 2 hàng x 2 nút để Telegram không cắt bớt trên màn hình hẹp.
    Spot không có Swing dài (backtest yếu) -> ẩn hàng kiểu swing."""
    mark = lambda cond: "✅ " if cond else ""  # noqa: E731
    risk = lambda r: InlineKeyboardButton(f"{mark(user['risk_pct'] == r)}{r:g}%", callback_data=f"risk:{r}")  # noqa: E731
    spot = user["mode"] == "spot"
    rows = [
        [InlineKeyboardButton(f"{mark(spot)}Spot — chỉ MUA", callback_data="mode:spot")],
        [InlineKeyboardButton(f"{mark(not spot)}Futures — LONG & SHORT", callback_data="mode:futures")],
        [risk(0.25), risk(0.5)],
        [risk(1.0), risk(2.0)],
    ]
    if not spot:
        rows.append([InlineKeyboardButton(f"{mark(user.get('style', 'both') == k)}{t}", callback_data=f"style:{k}")
                     for k, t in (("short", "⚡ Ngắn"), ("long", "🌙 Dài"), ("both", "Cả hai"))])
    rows.append([InlineKeyboardButton("⏸ Tín hiệu: admin đang tạm dừng" if user.get("admin_muted") else
                                      f"🔔 Nhận tín hiệu: {'BẬT' if user['subscribed'] else 'TẮT'}",
                                      callback_data="sub:toggle")])
    rows.append([InlineKeyboardButton(f"💱 Đơn vị tiền: {'VNĐ' if user.get('currency') == 'VND' else 'USDT'}",
                                      callback_data="cur:toggle"),
                 InlineKeyboardButton(f"🏦 Sàn: {user.get('exchange') or 'Binance'}", callback_data="exch:toggle")])
    return InlineKeyboardMarkup(rows)


STYLE_TEXT = {"short": "⚡ Swing ngắn", "long": "🌙 Swing dài", "both": "⚡ Ngắn + 🌙 Dài"}


def mode_text(user: dict) -> str:
    spot = user["mode"] == "spot"
    mode = "Spot (chỉ MUA)" if spot else "Futures (LONG &amp; SHORT)"
    style = "⚡ Swing ngắn" if spot else STYLE_TEXT.get(user.get("style", "both"), "")
    lines = ["⚙️ <b>Cài đặt</b>", "",
             f"Đang chọn: <b>{mode}</b> · rủi ro <b>{user['risk_pct']:g}%</b>/lệnh · <b>{style}</b>", "",
             "• Rủi ro = % vốn mất nếu lệnh chạm SL. Người mới nên dùng <b>0.25–0.5%</b>."]
    if spot:
        lines.append("• Spot chỉ nhận tín hiệu MUA swing ngắn (swing dài trên Spot backtest yếu nên không gửi).")
    else:
        lines += ["• ⚡ Swing ngắn: 1–3 tín hiệu/ngày (6h–22h), giữ vài giờ → vài ngày.",
                  "• 🌙 Swing dài: khoảng 1 tín hiệu/tuần, giữ vài ngày → vài tuần."]
    lines.append("Bấm nút bên dưới để đổi:")
    return "\n".join(lines)


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
    changed_mode = kind == "mode" and value in ("spot", "futures") and value != user["mode"]
    if kind == "mode" and value in ("spot", "futures"):
        await storage.update_user(user["chat_id"], mode=value)
    elif kind == "sub":
        if user.get("admin_muted"):
            await q.answer("Admin đang tạm dừng tín hiệu của bạn — liên hệ admin để mở lại.", show_alert=True)
            return
        await storage.update_user(user["chat_id"], subscribed=not user["subscribed"])
    elif kind == "exch":
        await storage.update_user(user["chat_id"], exchange="Binance" if user.get("exchange") == "MEXC" else "MEXC")
    elif kind == "cur":
        await storage.update_user(user["chat_id"], currency="USDT" if user.get("currency") == "VND" else "VND")
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
    if changed_mode:  # đổi chế độ -> báo rõ + đổi bàn phím menu cho đúng chế độ
        await q.message.reply_text(
            "✅ Đã chuyển sang <b>SPOT</b>: chỉ nhận tín hiệu MUA; menu có 💼 Danh mục của tôi." if user["mode"] == "spot"
            else "✅ Đã chuyển sang <b>FUTURES</b>: nhận LONG &amp; SHORT; menu có 🪙 Coin theo dõi.",
            parse_mode=ParseMode.HTML, reply_markup=menu(user))


async def open_signals(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _user(update)
    if not user:
        return
    got = {s["id"] for s in await storage.user_signals(user["chat_id"], 45)}
    sigs = [s for s in await storage.open_signals()
            if (s.get("source") != "ind" and service.receives(user, s)) or s["id"] in got]
    if not sigs:
        await _reply(update, "📊 Hiện không có lệnh nào đang chạy.")
        return
    lines = ["📊 <b>Lệnh đang chạy</b>"]
    for s in sigs:
        st = storage.loads(s["state"])["trade"]
        mult = texts.disp_mult(s, user["mode"], user.get("exchange"))
        emoji = ("🎯" if s.get("source") == "ind" else "") + ("🟢" if s["side"] > 0 else "🔴")
        flags = " · đã về hòa vốn" if st["be_done"] else ""
        flags += " · đã TP1" if st["hit"] else ""
        lines.append(f"{emoji} <b>{escape(s['display'])}</b> entry {texts.price(s['entry'] / mult)} · "
                     f"SL hiện tại {texts.price(st['stop'] / mult)}{flags} · lãi tối đa {st['max_r']:+.1f}R")
    await _reply(update, "\n".join(lines))


async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _user(update):
        return
    parts = []
    for d, t in ((7, "7 ngày"), (30, "30 ngày"), (None, "Từ đầu")):
        rows = await storage.closed_signals(days=d)
        parts.append(texts.stats_message([r for r in rows if r.get("source") != "ind"], f"Tín hiệu bot · {t}"))
    ind = [r for r in await storage.closed_signals(days=None) if r.get("source") == "ind"]
    if ind:
        parts.append(texts.stats_message(ind, "🎯 Tín hiệu chỉ báo · từ đầu"))
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


async def portfolio_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _user(update)
    if user:
        await portfolio_ui.show_list(update, ctx, user)


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
    return "\n".join(lines)


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.effective_message.text or "").strip()
    user = await _user(update, allow_pending=True)
    if not user:
        return
    if not user.get("approved", True) and not is_admin(user["chat_id"]):
        if not await extra.auto_approve_member(ctx.bot, user["chat_id"]):
            await _reply(update, "⏳ Bạn đang chờ admin duyệt. Khi được duyệt, bot sẽ nhắn cho bạn.")
            return
        user = await storage.get_user(user["chat_id"])
    text = OLD_BUTTONS.get(text, text)
    routes = {BTN_OPEN: open_signals, BTN_SPOT_SIG: open_signals, BTN_SETTINGS: mode_cmd, BTN_STATS: stats,
              BTN_WATCH: watch_list, BTN_PORTFOLIO: portfolio_menu, BTN_HELP: help_cmd, BTN_AI: extra.ai_prompt,
              "market": market, "calendar": extra.calendar_cmd}
    if text == BTN_ADMIN and is_admin(user["chat_id"]):
        await admin_panel(update, ctx)
        return
    if text in routes:
        for k in ("await_symbol", "await_coin", "await_ai", "await_pf"):
            ctx.user_data.pop(k, None)
        await routes[text](update, ctx)
    elif text == BTN_ANALYZE:
        await analyze(update, ctx)
    elif ctx.user_data.pop("await_symbol", False):
        await analyze(update, ctx, text)
    elif ctx.user_data.pop("await_coin", False):
        await extra.add_coin_text(update, ctx, user, text)
    elif await portfolio_ui.handle_text(update, ctx, user, text):
        pass
    elif (reply := update.effective_message.reply_to_message) and (
            sig := await storage.signal_by_message(user["chat_id"], reply.message_id)):
        await extra.ai_answer(update, ctx, text, user=user, signal=sig)
    elif extra.assistant.ai.enabled():
        await extra.ai_answer(update, ctx, text, user=user, kind=ctx.user_data.pop("await_ai", None) or "personal")
    else:
        await _reply(update, "Chọn chức năng trong menu bên dưới 👇", reply_markup=menu(user))


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
    await _reply(update, "⏳ Đang quét thị trường, có kết quả bot sẽ báo...")
    _bg(_scan_in_background(ctx.bot, update.effective_chat.id))


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
        flag = _flag(u)
        n = len(await storage.user_coins_of(u["chat_id"]))
        name = escape(u.get("full_name") or u["username"] or "-")
        lines.append(f"{flag} <code>{u['chat_id']}</code> {name} · {u['mode']} · {u['risk_pct']:g}% · "
                     f"{u.get('coin_mode', 'top')} ({n} coin)")
    lines.append("\nDuyệt: /allow ID · Chặn: /ban ID · Mở: /unban ID")
    await _reply(update, "\n".join(lines))


async def admin_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    us = await storage.all_users()
    pending = [u for u in us if not u.get("approved", True) and not u["banned"]]
    await _reply(update, f"👥 <b>Quản lý</b> · {len(us)} người dùng · {len(pending)} chờ duyệt", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⏳ Chờ duyệt ({len(pending)})", callback_data="adm:pending"),
         InlineKeyboardButton("👥 Danh sách", callback_data="adm:users")],
        [InlineKeyboardButton("🔍 Quét ngay", callback_data="adm:scan"),
         InlineKeyboardButton("🤖 Kiểm tra AI", callback_data="adm:ai")],
        [InlineKeyboardButton("🩺 Trạng thái bot", callback_data="adm:status"),
         InlineKeyboardButton("📦 Sao lưu dữ liệu", callback_data="adm:backup")],
    ] + ([] if reports.NEWS_BOT else [[InlineKeyboardButton("🌍 Thị trường", callback_data="adm:market"),
                                         InlineKeyboardButton("📅 Lịch tuần", callback_data="adm:cal")]])))


def _flag(u: dict) -> str:
    return ("⛔" if u["banned"] else "⏳" if not u.get("approved", True) else "⏸" if u.get("admin_muted")
            else "🔔" if u["subscribed"] else "🔕")


async def _user_card(q, u: dict, *, edit: bool = False) -> None:
    """Thẻ 1 người dùng + 3 nút: tạm dừng tín hiệu · xóa · chặn."""
    uid = u["chat_id"]
    status = ("⛔ đang bị chặn" if u["banned"] else "⏸ admin đang tạm dừng tín hiệu" if u.get("admin_muted")
              else "🔔 đang nhận tín hiệu" if u["subscribed"] else "🔕 tự tắt tín hiệu")
    text = (f"👤 <b>{escape(u.get('full_name') or u['username'] or '-')}</b> · <code>{uid}</code>\n"
            f"{u['mode']} · rủi ro {u['risk_pct']:g}% · {status}")
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔔 Mở lại tín hiệu" if u.get("admin_muted") else "🔕 Tắt tín hiệu",
                              callback_data=f"adm:mute:{uid}")],
        [InlineKeyboardButton("🗑 Xóa", callback_data=f"adm:del:{uid}"),
         InlineKeyboardButton("✅ Bỏ chặn" if u["banned"] else "⛔ Chặn", callback_data=f"adm:ban:{uid}")]])
    if edit:
        try:
            await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
            return
        except BadRequest:
            pass
    await q.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def on_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("Chỉ admin")
        return
    await q.answer()
    parts = q.data.split(":")
    op = parts[1]
    if op == "pending":
        pend = [u for u in await storage.all_users() if not u.get("approved", True) and not u["banned"]]
        if not pend:
            await q.message.reply_text("Không có ai chờ duyệt.")
        for u in pend[:15]:
            name = escape(u.get("full_name") or u["username"] or "-")
            await q.message.reply_text(
                f"🙋 {name} · <code>{u['chat_id']}</code>", parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Duyệt", callback_data=f"appr:{u['chat_id']}:1"),
                                                    InlineKeyboardButton("❌ Từ chối", callback_data=f"appr:{u['chat_id']}:0")]]))
    elif op == "users":
        us = [u for u in await storage.all_users() if not is_admin(u["chat_id"])]
        lines = [f"👥 <b>{len(us)} người dùng</b> (🔔 nhận tín hiệu · 🔕 tự tắt · ⏸ admin tạm dừng · ⛔ chặn · ⏳ chờ duyệt)",
                 "Bấm tên để 🔕 tạm dừng tín hiệu / 🗑 xóa / ⛔ chặn."]
        rows = []
        for u in us[-30:]:
            flag = _flag(u)
            name = u.get("full_name") or u["username"] or str(u["chat_id"])
            lines.append(f"{flag} {escape(name)} · {u['mode']} · {u['risk_pct']:g}%")
            rows.append([InlineKeyboardButton(f"{flag} {name[:20]}", callback_data=f"adm:u:{u['chat_id']}")])
        await q.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML,
                                   reply_markup=InlineKeyboardMarkup(rows) if rows else None)
    elif op == "u":
        u = await storage.get_user(int(parts[2]))
        if u:
            await _user_card(q, u)
        else:
            await q.message.reply_text("Người này không còn trong danh sách.")
    elif op in ("ban", "mute"):
        u = await storage.get_user(int(parts[2]))
        if not u:
            return
        if op == "ban":
            await storage.update_user(u["chat_id"], banned=not u["banned"], **({"approved": True} if u["banned"] else {}))
            note = "✅ Đã bỏ chặn." if u["banned"] else "⛔ Đã chặn — người này không dùng được bot nữa."
        else:
            await storage.update_user(u["chat_id"], admin_muted=not u.get("admin_muted"))
            note = "🔔 Đã mở lại tín hiệu." if u.get("admin_muted") else "🔕 Đã tạm dừng tín hiệu của người này."
            try:
                await ctx.bot.send_message(u["chat_id"], "🔔 Admin đã mở lại tín hiệu cho bạn." if u.get("admin_muted")
                                           else "⏸ Admin đã tạm dừng tín hiệu của bạn. Bạn vẫn dùng được danh mục, "
                                                "hỏi AI và thống kê.")
            except Exception:  # noqa: BLE001
                pass
        await q.message.reply_text(note)
        await _user_card(q, await storage.get_user(u["chat_id"]), edit=True)
    elif op == "del":
        u = await storage.get_user(int(parts[2]))
        if u:
            name = escape(u.get("full_name") or u["username"] or str(u["chat_id"]))
            await q.message.reply_text(
                f"🗑 Chắc chắn xóa <b>{name}</b>?\nCài đặt, danh mục, coin theo dõi của họ bị xóa hết. Nếu họ bấm Start "
                "lại sẽ phải chờ admin duyệt (kể cả khi còn trong nhóm).", parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗑 Xóa", callback_data=f"adm:delok:{u['chat_id']}"),
                                                    InlineKeyboardButton("Không", callback_data=f"adm:u:{u['chat_id']}")]]))
    elif op == "delok":
        uid = int(parts[2])
        if await storage.get_user(uid):
            await storage.delete_user(uid)
            try:
                await ctx.bot.send_message(uid, "Tài khoản của bạn đã được admin gỡ khỏi bot tín hiệu.")
            except Exception:  # noqa: BLE001
                pass
        await q.edit_message_text("🗑 Đã xóa người dùng khỏi danh sách nhận tín hiệu.")
    elif op == "scan":
        await q.message.reply_text("⏳ Đang quét thị trường, có kết quả bot sẽ báo (thường dưới 1 phút)...")
        _bg(_scan_in_background(ctx.bot, q.message.chat_id))
    elif op == "ai":
        await q.message.reply_text(await extra.assistant.ping(), parse_mode=ParseMode.HTML)
    elif op == "backup":
        await reports.send_backup(ctx.bot, q.message.chat_id)
    elif op == "status":
        await q.message.reply_text(await status_text(), parse_mode=ParseMode.HTML)
    elif op == "restore":
        data = ctx.user_data.pop("restore_data", None)
        if not data:
            await q.message.reply_text("Hết hạn, gửi lại file sao lưu.")
            return
        added = await storage.import_data(data)
        await q.message.reply_text("✅ Đã khôi phục (chỉ thêm dữ liệu còn thiếu): "
                                   + ", ".join(f"{k} +{v}" for k, v in added.items()))
    elif op == "market":
        await q.message.reply_text(await reports.morning_text(), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    elif op == "cal":
        await extra.calendar_cmd(update, ctx)


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
    """Có lỗi -> người dùng luôn nhận được phản hồi (không im lặng), admin nhận chi tiết lỗi."""
    log.error("Lỗi xử lý update: %s", ctx.error, exc_info=ctx.error)
    if isinstance(update, Update):
        try:
            if update.callback_query:
                await update.callback_query.answer("⚠️ Có lỗi, thử lại sau ít phút.", show_alert=True)
            elif update.effective_message and update.effective_chat and update.effective_chat.type == "private":
                await update.effective_message.reply_text("⚠️ Có lỗi, thử lại sau ít phút.")
        except Exception:  # noqa: BLE001
            pass
    what = update.callback_query.data if isinstance(update, Update) and update.callback_query else (
        update.effective_message.text if isinstance(update, Update) and update.effective_message else "")
    await service.notify_admins(ctx.bot, f"🐞 Lỗi khi xử lý «{escape(str(what)[:60])}»: "
                                         f"<code>{escape(type(ctx.error).__name__)}: {escape(str(ctx.error)[:300])}</code>",
                                key=f"err:{type(ctx.error).__name__}", every_minutes=30)


_tasks: set[asyncio.Task] = set()


def _bg(coro) -> None:
    """Chạy nền, giữ tham chiếu để task không bị dọn giữa chừng."""
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


async def status_text() -> str:
    """🩺 Trạng thái: lần quét gần nhất, nguồn dữ liệu đang bị giới hạn, lệnh mở, người dùng, AI, Bot Tin tức."""
    import time as _t
    from datetime import datetime, timezone
    from app.data import http
    last = await storage.kv_get("last_scan_ok")
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 60 if last else None
    blocked = [h for h, t in http._blocked_until.items() if t > _t.time()]
    opened = await storage.open_signals()
    users = await storage.all_users()
    return "\n".join([
        "🩺 <b>Trạng thái bot</b>",
        f"Lần quét có dữ liệu gần nhất: {f'{age:.0f} phút trước' if age is not None else 'chưa có'}",
        f"Nguồn dữ liệu đang tạm nghỉ: {', '.join(blocked) if blocked else 'không (Binance bình thường)'}",
        f"Lệnh đang mở: {len([s for s in opened if s.get('source') != 'ind'])} tín hiệu bot · "
        f"{len([s for s in opened if s.get('source') == 'ind'])} 🎯 chỉ báo",
        f"Người dùng: {len(users)} · Bot Tin tức: {len(await storage.news_users())} người"
        + (f" (@{reports.NEWS_USERNAME})" if reports.NEWS_USERNAME else " (chưa cấu hình NEWS_BOT_TOKEN)"),
        f"AI: {'đã có key' if extra.assistant.ai.enabled() else 'chưa có key'}",
    ])


async def on_backup_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin gửi file sao lưu .json -> hỏi xác nhận rồi khôi phục (chỉ thêm dữ liệu còn thiếu)."""
    if not is_admin(update.effective_user.id):
        return
    doc = update.effective_message.document
    try:
        raw = await (await doc.get_file()).download_as_bytearray()
        data = storage.loads(bytes(raw).decode())
        assert isinstance(data, dict) and "users" in data
    except Exception:  # noqa: BLE001
        await _reply(update, "❌ File không phải bản sao lưu của bot.")
        return
    ctx.user_data["restore_data"] = data
    await _reply(update, f"📦 Bản sao lưu có {len(data.get('users', []))} người dùng, "
                         f"{len(data.get('portfolio_tx', []))} lệnh mua/bán. Khôi phục (chỉ thêm phần còn thiếu)?",
                 reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Khôi phục", callback_data="adm:restore")]]))


async def _scan_in_background(bot, chat_id: int) -> None:
    """Quét ngay chạy nền: bot vẫn trả lời người khác trong lúc quét, xong thì báo kết quả."""
    try:
        note = await service.run_scan(bot, ("short", "long"), force=True)
    except Exception as exc:  # noqa: BLE001
        note = f"Lỗi khi quét: {exc}"
    await bot.send_message(chat_id, "🔍 " + escape(note), parse_mode=ParseMode.HTML)


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
    app.add_handler(CallbackQueryHandler(on_callback, pattern=r"^(mode|risk|style|sub|cur|exch):"))
    app.add_handler(CallbackQueryHandler(on_admin, pattern=r"^adm:"))
    app.add_handler(MessageHandler(private & filters.Document.FileExtension("json"), on_backup_file))
    extra.register(app)
    portfolio_ui.register(app)
    app.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
