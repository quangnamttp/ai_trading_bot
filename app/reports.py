"""Báo cáo định kỳ và cảnh báo.

Tin tức chung (thị trường, lịch sự kiện, nhắc tin vĩ mô, biến động mạnh, funding) -> topic 📰 của nhóm (nếu đã /set_news)
+ chat riêng của người bật "nhận tin tức ở chat riêng". Nội dung cá nhân (tổng kết lời lỗ, coin đang giữ, tin xấu về lệnh
đang mở) -> chỉ chat riêng.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from html import escape

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError

from app import events, indicators as ta, storage
from app.bot import texts
from app.config import VN_TZ, settings
from app.data import binance, macro, news

log = logging.getLogger(__name__)


def vn_now() -> datetime:
    return datetime.now(VN_TZ)


def is_quiet(dt: datetime | None = None) -> bool:
    h = (dt or vn_now()).astimezone(VN_TZ).hour
    s, e = settings.quiet_start, settings.quiet_end
    return (h >= s or h < e) if s > e else (s <= h < e)


def vn_midnight_utc(days_ago: int = 0) -> datetime:
    d = vn_now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
    return d.astimezone(timezone.utc)


async def broadcast(bot: Bot, text: str) -> None:
    from app.service import _send  # tránh vòng import
    for u in await storage.subscribers():
        await _send(bot, u["chat_id"], text)
        await asyncio.sleep(0.05)


async def group_target(kind: str) -> tuple[int, int | None] | None:
    """Nơi gửi trong nhóm: kind = 'news' | 'ai' (đặt bằng /set_news, /set_ai)."""
    raw = await storage.kv_get(f"{kind}_target")
    if not raw:
        return None
    chat, _, thread = raw.partition(":")
    return int(chat), int(thread) if thread and thread != "None" else None


async def broadcast_news(bot: Bot, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    """Tin tức chung: topic 📰 của nhóm + chat riêng của người bật nhận tin tức."""
    target = await group_target("news")
    if target:
        try:
            await bot.send_message(target[0], text, parse_mode=ParseMode.HTML, message_thread_id=target[1],
                                   reply_markup=markup, disable_web_page_preview=True)
        except TelegramError as exc:
            log.warning("Gửi topic tin tức lỗi: %s", exc)
    for u in await storage.subscribers():
        if u.get("news_dm", True):
            try:
                await bot.send_message(u["chat_id"], text, parse_mode=ParseMode.HTML, reply_markup=markup,
                                       disable_web_page_preview=True)
            except TelegramError as exc:
                log.warning("Gửi tin tức tới %s lỗi: %s", u["chat_id"], exc)
            await asyncio.sleep(0.05)


WEEKDAYS = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]


def event_key(e: dict) -> str:
    return f"{events.classify(e['title'])[0]}:{e['time']:%Y%m%d%H%M}"


def calendar_message(evs: list[dict], title: str) -> tuple[str, InlineKeyboardMarkup | None]:
    """Danh sách tin + nút xem chi tiết (tối đa 8 nút, ưu tiên tin tác động mạnh)."""
    if not evs:
        return f"{title}\nKhông có tin kinh tế Mỹ đáng chú ý.", None
    lines, buttons, last_day = [title], [], None
    for e in evs:
        t = e["time"].astimezone(VN_TZ)
        if t.date() != last_day:
            last_day = t.date()
            lines.append(f"\n<b>{WEEKDAYS[t.weekday()]} {t:%d/%m}</b>")
        icon = "🔴" if e.get("impact") == "High" else "🟠"
        fc = f" · dự báo {escape(str(e['forecast']))}" if e.get("forecast") else ""
        lines.append(f"{icon} {t:%H:%M} {escape(e['title'])}{fc}")
        if len(buttons) < 8 and (e.get("impact") == "High" or len(evs) <= 8):
            buttons.append([InlineKeyboardButton(f"ℹ️ {t:%d/%m} {e['title'][:40]}", callback_data=f"ev:{event_key(e)}")])
    lines.append("\n🔴 tác động mạnh (bot tạm dừng tín hiệu 3h trước → 1h sau) · 🟠 tác động vừa\n"
                 "Bấm nút bên dưới để xem giải thích và thống kê.")
    return "\n".join(lines), InlineKeyboardMarkup(buttons) if buttons else None


async def find_event(key: str) -> dict | None:
    for e in await events.week_events():
        if event_key(e) == key:
            return e
    return None


async def week_calendar(bot: Bot) -> None:
    evs = [e for e in await events.week_events() if e["time"] >= datetime.now(timezone.utc) - timedelta(hours=2)]
    text, markup = calendar_message(evs, f"📅 <b>Lịch sự kiện tuần này</b> ({vn_now():%d/%m})")
    await broadcast_news(bot, text, markup)


async def today_calendar(bot: Bot) -> None:
    start, end = vn_midnight_utc(), vn_midnight_utc() + timedelta(days=1)
    evs = [e for e in await events.week_events() if start <= e["time"] < end]
    text, markup = calendar_message(evs, f"🗓 <b>Tin kinh tế hôm nay</b> {vn_now():%d/%m}")
    await broadcast_news(bot, text, markup)


# ---------------------------------------------------------------- 07:00
async def morning_text() -> str:
    from app.strategy import scanner
    coins = await binance.universe(settings.top_n, settings.min_quote_volume)
    tick = await binance.tickers_24h()
    fund = await binance.all_funding()
    lines = [f"🌅 <b>Thị trường 24 giờ qua</b> · {vn_now():%d/%m}"]

    for sym, name in (("BTCUSDT", "₿ BTC"), ("ETHUSDT", "Ξ ETH")):
        t = tick.get(sym)
        if t:
            ch = float(t["priceChangePercent"])
            lines.append(f"{name}: <b>{texts.price(float(t['lastPrice']))}</b> ({'🟢' if ch >= 0 else '🔴'} {ch:+.2f}%)")

    moves = sorted(((c.display, float(tick[c.symbol]["priceChangePercent"])) for c in coins if c.symbol in tick),
                   key=lambda x: -x[1])
    if moves:
        up = " · ".join(f"{d.split('/')[0]} {v:+.1f}%" for d, v in moves[:5] if v > 0) or "không có coin tăng"
        down = " · ".join(f"{d.split('/')[0]} {v:+.1f}%" for d, v in moves[::-1][:5] if v < 0) or "không có coin giảm"
        breadth = sum(1 for _, v in moves if v > 0)
        lines += ["", f"📈 <b>Tăng mạnh nhất</b>: {up}", f"📉 <b>Giảm mạnh nhất</b>: {down}",
                  f"Độ rộng: {breadth}/{len(moves)} coin tăng"]

    lines.append("")
    try:
        fng = await macro.fear_greed_history()
        today, yday = int(fng.iloc[-1]), int(fng.iloc[-2])
        lines.append(f"😱 Fear &amp; Greed: <b>{today}</b> (hôm qua {yday}, {today - yday:+d})")
    except Exception:  # noqa: BLE001
        pass
    oi = [x for x in await asyncio.gather(*(binance.oi_change_24h(c.symbol) for c in coins[:10])) if x]
    if oi:
        tot_now = sum(v for v, _ in oi)
        tot_prev = sum(v / (1 + ch) for v, ch in oi)
        ch = tot_now / tot_prev - 1
        lines.append(f"💼 Tổng OI top 10: {ch:+.1%} 24h ({'tiền mới vào' if ch > 0.02 else 'tiền rút ra' if ch < -0.02 else 'ổn định'})")
    fr = [fund[c.symbol] for c in coins if c.symbol in fund]
    if fr:
        avg = sum(fr) / len(fr)
        hot = sum(1 for x in fr if abs(x) >= 0.0005)
        lines.append(f"💸 Funding TB: {avg:.4%} ({'phe long đông' if avg > 0.0002 else 'phe short đông' if avg < -0.0001 else 'cân bằng'})"
                     + (f" · {hot} coin funding nóng" if hot else ""))
    stable = await macro.stablecoin_change_7d()
    if stable is not None:
        lines.append(f"💵 Cung stablecoin 7 ngày: {stable:+.2%} ({'tiền đang vào' if stable > 0 else 'tiền đang rút'})")

    start, end = vn_midnight_utc(), vn_midnight_utc() + timedelta(days=1)
    events = [e for e in await macro.high_impact_events() if start <= e["time"] < end]
    lines.append("")
    if events:
        lines.append("📅 <b>Tin vĩ mô Mỹ hôm nay</b> (bot tạm dừng 3h trước → 1h sau):")
        lines += [f"• {e['time'].astimezone(VN_TZ):%H:%M} — {escape(e['title'])}" for e in events]
    else:
        lines.append("📅 Hôm nay không có tin vĩ mô Mỹ quan trọng.")

    items = await news.headlines(24)
    if items:
        top = sorted(items, key=lambda h: -abs(h.score))[:3]
        lines += ["", "🗞 <b>Tin đáng chú ý</b>:"]
        lines += [f"• <a href=\"{escape(h.link)}\">{escape(h.title[:100])}</a>" for h in top]

    watch = await scanner.watch_candidates(5)
    if watch:
        lines += ["", "👀 <b>Đang theo dõi</b> (chưa phải tín hiệu):"]
        lines += [f"• {w}" for w in watch]
    return "\n".join(lines)


async def morning(bot: Bot) -> None:
    await broadcast_news(bot, await morning_text())
    if vn_now().weekday() == 0:
        await week_calendar(bot)
    else:
        await today_calendar(bot)


# ---------------------------------------------------------------- 15:00
async def afternoon_watch(bot: Bot) -> None:
    """Chưa có tín hiệu nào trong ngày -> gửi danh sách coin đang hình thành setup để bot không 'im lặng'."""
    from app.strategy import scanner
    if await storage.signals_since(vn_midnight_utc()):
        return
    watch = await scanner.watch_candidates(5)
    text = (f"🕒 <b>{vn_now():%H:%M}</b> — hôm nay chưa có setup đạt chuẩn. Bot vẫn đang quét mỗi giờ.\n")
    if watch:
        text += "\n👀 <b>Đang theo dõi</b> (chưa phải tín hiệu, KHÔNG vào lệnh):\n" + "\n".join(f"• {w}" for w in watch)
    else:
        text += "Thị trường chưa có coin nào gần đạt chuẩn — đứng ngoài cũng là một quyết định tốt."
    await broadcast_news(bot, text)


# ---------------------------------------------------------------- 22:00
def _pct(r: float, risk_pct: float) -> str:
    return f"{r * risk_pct:+.2f}% vốn"


async def evening(bot: Bot) -> None:
    from app.service import _send
    today = await storage.signals_since(vn_midnight_utc())
    closed_today = [s for s in await storage.closed_signals(days=2) if s["closed_at"] and s["closed_at"] >= vn_midnight_utc()]
    opened = await storage.open_signals()
    week = await storage.closed_signals(days=7)
    month = await storage.closed_signals(days=30)
    upcoming = [e for e in await macro.high_impact_events()
                if vn_midnight_utc() + timedelta(hours=22) <= e["time"] < vn_midnight_utc(-1) + timedelta(hours=6)]

    def summary(rows: list[dict]) -> str:
        if not rows:
            return "chưa có lệnh đóng"
        r = [x["result_r"] or 0 for x in rows]
        return f"{len(r)} lệnh · {sum(v > 0 for v in r) / len(r):.0%} có lời · tổng <b>{sum(r):+.2f}R</b>"

    for u in await storage.subscribers():
        mine = lambda rows: [s for s in rows if (u["mode"] == "futures" or s["side"] > 0)  # noqa: E731
                             and u.get("style", "both") in ("both", s.get("style", "short"))]
        mult = lambda s: s["multiplier"] if u["mode"] == "spot" else 1  # noqa: E731
        lines = [f"🌙 <b>Tổng kết ngày {vn_now():%d/%m}</b>", ""]
        t = mine(today)
        lines.append(f"📨 Tín hiệu hôm nay: <b>{len(t)}</b>" + (": " + ", ".join(
            f"{'🟢' if s['side'] > 0 else '🔴'}{s['display'].split('/')[0]}" for s in t) if t else ""))
        c = mine(closed_today)
        if c:
            lines.append("\n✅ <b>Lệnh đóng hôm nay</b>:")
            for s in c:
                r = s["result_r"] or 0
                lines.append(f"• {escape(s['display'])} {'LONG' if s['side'] > 0 else 'SHORT'}: <b>{r:+.2f}R</b> "
                             f"({_pct(r, u['risk_pct'])})")
        o = mine(opened)
        if o:
            lines.append("\n🌃 <b>Lệnh giữ qua đêm</b> — kiểm tra đã đặt SL trên sàn:")
            for s in o:
                st = storage.loads(s["state"])["trade"]
                lines.append(f"• {escape(s['display'])} {'LONG' if s['side'] > 0 else 'SHORT'} · entry "
                             f"{texts.price(s['entry'] / mult(s))} · <b>SL {texts.price(st['stop'] / mult(s))}</b>")
        if upcoming:
            lines.append("\n⚠️ Đêm nay có tin vĩ mô: " + ", ".join(
                f"{escape(e['title'])} lúc {e['time'].astimezone(VN_TZ):%H:%M}" for e in upcoming))
        lines += ["", f"📊 7 ngày: {summary(mine(week))}", f"📊 30 ngày: {summary(mine(month))}",
                  f"\n<i>Bot tạm ngừng gửi tín hiệu mới tới {settings.quiet_end}h sáng, vẫn báo SL/TP lệnh đang chạy.</i>"]
        await _send(bot, u["chat_id"], "\n".join(lines))
        await asyncio.sleep(0.05)


# ---------------------------------------------------------------- cảnh báo
def _key(*parts: object) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:40]


async def news_alerts(bot: Bot) -> None:
    """Tin cực xấu (với lệnh LONG) / cực tốt (với lệnh SHORT) về coin đang có lệnh mở -> nhắn ngay dưới tín hiệu."""
    from app.service import _send
    opened = await storage.open_signals()
    if not opened:
        return
    items = await news.headlines(3)
    users = {u["chat_id"]: u for u in await storage.all_users()}
    for s in opened:
        base = s["display"].split("/")[0]
        cn = news.coin_news(base, items)
        bad = cn["severe_negative"] if s["side"] > 0 else cn["severe_positive"]
        for h in bad:
            key = "news:" + _key(s["id"], h.title)
            if await storage.kv_get(key):
                continue
            await storage.kv_set(key, "1")
            text = (f"⚠️ <b>{escape(s['display'])}</b>: có tin có thể đi NGƯỢC lệnh "
                    f"{'LONG' if s['side'] > 0 else 'SHORT'} của bạn:\n<a href=\"{escape(h.link)}\">{escape(h.title)}</a>\n"
                    "Cân nhắc giảm vị thế hoặc dời SL sát hơn.")
            for m in await storage.messages_for(s["id"]):
                if m["chat_id"] in users and not users[m["chat_id"]]["banned"]:
                    await _send(bot, m["chat_id"], text, reply_to=m["message_id"])


async def macro_reminders(bot: Bot) -> None:
    """Nhắc trước ~1 giờ khi có tin vĩ mô Mỹ quan trọng (ngoài giờ yên lặng)."""
    now = datetime.now(timezone.utc)
    for e in await macro.high_impact_events():
        if timedelta(minutes=45) <= e["time"] - now <= timedelta(minutes=75) and not is_quiet():
            key = "macro:" + _key(e["title"], e["time"].isoformat())
            if await storage.kv_get(key):
                continue
            await storage.kv_set(key, "1")
            await broadcast_news(bot, f"⏰ <b>Sắp có tin vĩ mô Mỹ</b>: {escape(e['title'])} lúc "
                                      f"<b>{e['time'].astimezone(VN_TZ):%H:%M}</b>.\nGiá có thể biến động mạnh 2 chiều — "
                                      "bot tạm dừng tín hiệu mới tới 1 giờ sau tin. Lệnh đang mở nên có SL trên sàn.",
                                 InlineKeyboardMarkup([[InlineKeyboardButton(
                                     "ℹ️ Tin này ảnh hưởng thế nào?", callback_data=f"ev:{event_key(e)}")]]))


async def health_check(bot: Bot) -> None:
    """Quá N giờ không quét được thị trường (ngoài giờ yên lặng) -> báo admin."""
    last = await storage.kv_get("last_scan_ok")
    if is_quiet() or not last:
        return
    age = datetime.now(timezone.utc) - datetime.fromisoformat(last)
    if age < timedelta(hours=settings.health_alert_hours):
        return
    now = datetime.now(timezone.utc)
    key = f"health:{now:%Y%m%d}:{now.hour // 6}"  # tối đa 1 cảnh báo mỗi 6 giờ
    if await storage.kv_get(key):
        return
    await storage.kv_set(key, "1")
    for admin in settings.admin_ids:
        try:
            await bot.send_message(admin, f"🚨 Bot chưa quét được thị trường {age.total_seconds() / 3600:.1f} giờ. "
                                          "Kiểm tra Logs trên Render (có thể Binance lỗi hoặc bị chặn).")
        except Exception:  # noqa: BLE001
            log.warning("Không gửi được cảnh báo sức khỏe cho %s", admin)


# ---------------------------------------------------------------- cảnh báo thị trường
async def market_alerts(bot: Bot) -> None:
    """BTC chạy mạnh trong 1 giờ; funding cực đoan ở coin lớn (đám đông quá đông 1 phía -> dễ bị quét ngược)."""
    try:
        k = await binance.klines("BTCUSDT", "5m", 13)
        move = k["close"].iloc[-1] / k["open"].iloc[-12] - 1
        if abs(move) >= settings.btc_move_alert_pct / 100:
            key = f"btcmove:{datetime.now(timezone.utc):%Y%m%d%H}"
            if not await storage.kv_get(key):
                await storage.kv_set(key, "1")
                await broadcast_news(bot, f"🚨 <b>BTC {'tăng' if move > 0 else 'giảm'} mạnh {move:+.1%} trong 1 giờ</b> "
                                          f"(giá {texts.price(float(k['close'].iloc[-1]))}).\n"
                                          "Biến động mạnh dễ quét SL 2 chiều — kiểm tra lệnh đang mở, tránh đuổi giá.")
    except Exception as exc:  # noqa: BLE001
        log.warning("Cảnh báo BTC lỗi: %s", exc)
    try:
        coins = await binance.universe(settings.top_n, settings.min_quote_volume)
        fund = await binance.all_funding()
        fresh = []
        for c in coins:
            f = fund.get(c.symbol)
            if f is None or abs(f) < settings.funding_alert:
                continue
            key = f"funding:{c.symbol}:{vn_now():%Y%m%d}:{f > 0}"
            if not await storage.kv_get(key):
                await storage.kv_set(key, "1")
                fresh.append((c, f))
        if fresh:
            lines = [f"🔥 <b>Funding cực đoan</b> (≥{settings.funding_alert:.1%}/8h):"]
            for c, f in fresh:
                side = "LONG đang quá đông → dễ bị quét xuống" if f > 0 else "SHORT đang quá đông → dễ bị ép tăng"
                lines.append(f"• {escape(c.display)}: {f:+.3%} — {side}")
            await broadcast_news(bot, "\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        log.warning("Cảnh báo funding lỗi: %s", exc)


# ---------------------------------------------------------------- coin 📌 đang giữ
async def holdings_watch(bot: Bot) -> None:
    """Theo dõi coin người dùng đang giữ: xu hướng 4H đổi chiều, thủng/vượt vùng quan trọng, OI, funding, tin xấu."""
    from app.service import _send
    from app.strategy.scanner import live_derivs
    holders: dict[str, list[int]] = {}
    for r in await storage.all_user_coins():
        if r["holding"]:
            holders.setdefault(r["symbol"], []).append(r["chat_id"])
    if not holders:
        return
    items = await news.headlines(6)
    day = vn_now().strftime("%Y%m%d")
    for sym, chats in holders.items():
        alerts = []
        try:
            h4 = await binance.klines(sym, "4h", 120)
            d1 = await binance.klines(sym, "1d", 80)
            c = h4["close"]
            e20, e50 = ta.ema(c, 20).iloc[-1], ta.ema(c, 50).iloc[-1]
            px = float(c.iloc[-1])
            state = "up" if px > e50 and e20 > e50 else "down" if px < e50 and e20 < e50 else "flat"
            prev = await storage.kv_get(f"hold:{sym}:trend")
            await storage.kv_set(f"hold:{sym}:trend", state)
            if prev and prev != state:
                alerts.append({"up": "✅ Xu hướng 4H chuyển sang TĂNG", "down": "⚠️ Xu hướng 4H chuyển sang GIẢM",
                               "flat": "⚪ Xu hướng 4H mất đà, chuyển sang đi ngang"}[state])
            low20 = float(d1["low"].iloc[-21:-1].min())
            if px < low20 and not await storage.kv_get(f"hold:{sym}:low20:{day}"):
                await storage.kv_set(f"hold:{sym}:low20:{day}", "1")
                alerts.append(f"🔻 Giá thủng đáy 20 ngày ({texts.price(low20)}) — cân nhắc bảo vệ vốn")
            above = "1" if px > ta.ema(d1["close"], 50).iloc[-1] else "0"
            prev_above = await storage.kv_get(f"hold:{sym}:above_e50")
            await storage.kv_set(f"hold:{sym}:above_e50", above)
            if prev_above is not None and prev_above != above:
                alerts.append("📈 Giá vượt lên trên EMA50 ngày" if above == "1" else "📉 Giá rơi xuống dưới EMA50 ngày")
            d = await live_derivs(sym, 24)
            oi = d.get("oi_chg")
            if oi is not None and abs(oi) >= 0.10 and not await storage.kv_get(f"hold:{sym}:oi:{day}"):
                await storage.kv_set(f"hold:{sym}:oi:{day}", "1")
                alerts.append(f"💼 OI 24h {oi:+.0%} — dòng tiền phái sinh biến động mạnh")
            f = d.get("funding")
            if f is not None and abs(f) >= settings.funding_alert and not await storage.kv_get(f"hold:{sym}:fund:{day}"):
                await storage.kv_set(f"hold:{sym}:fund:{day}", "1")
                alerts.append(f"🔥 Funding {f:+.3%} — đám đông {'LONG' if f > 0 else 'SHORT'} quá đông")
            base = binance.split_symbol(sym)[0]
            for h in news.coin_news(base, items)["severe_negative"]:
                k = "hold:news:" + _key(sym, h.title)
                if not await storage.kv_get(k):
                    await storage.kv_set(k, "1")
                    alerts.append(f"📰 Tin xấu: <a href=\"{escape(h.link)}\">{escape(h.title[:100])}</a>")
        except Exception as exc:  # noqa: BLE001
            log.warning("Theo dõi coin giữ %s lỗi: %s", sym, exc)
            continue
        if alerts:
            text = (f"📌 <b>{escape(binance.split_symbol(sym)[0])}</b> (coin bạn đang giữ) · giá {texts.price(px)}\n"
                    + "\n".join(f"• {a}" for a in alerts))
            for chat in chats:
                await _send(bot, chat, text)


# ---------------------------------------------------------------- báo cáo tuần (tối chủ nhật)
async def weekly_report(bot: Bot) -> None:
    from app.service import _send
    from app.strategy.scanner import calibration
    week = await storage.closed_signals(days=7)
    short = calibration().get("styles", {}).get("short", {}).get("summary", {})
    for u in await storage.subscribers():
        mine = []
        for s in week:
            if any(m["chat_id"] == u["chat_id"] for m in await storage.messages_for(s["id"])):
                mine.append(s)
        lines = [f"📅 <b>Tổng kết tuần</b> (7 ngày tới {vn_now():%d/%m})"]
        if mine:
            r = [s["result_r"] or 0 for s in mine]
            wins = sum(v > 0 for v in r)
            lines.append(f"Lệnh đã đóng: <b>{len(r)}</b> · có lời {wins} ({wins / len(r):.0%})")
            lines.append(f"Tổng: <b>{sum(r):+.2f}R</b> = <b>{sum(r) * u['risk_pct']:+.2f}% vốn</b> "
                         f"(rủi ro {u['risk_pct']:g}%/lệnh)")
            best = max(mine, key=lambda s: s["result_r"] or 0)
            lines.append(f"Lệnh tốt nhất: {escape(best['display'])} {best['result_r']:+.2f}R")
        else:
            lines.append("Tuần này bạn chưa có lệnh nào đóng.")
        if short.get("avgR") is not None:
            lines.append(f"\n🧪 So sánh backtest swing ngắn: TB {short['avgR']:+.2f}R/lệnh, khoảng "
                         f"{short['per_day'] * 7:.0f} lệnh/tuần. Tuần lỗ là bình thường — đánh giá sau vài tuần mới có ý nghĩa.")
        await _send(bot, u["chat_id"], "\n".join(lines))
        await asyncio.sleep(0.05)
