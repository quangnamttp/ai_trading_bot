"""Báo cáo định kỳ và cảnh báo.

Tin tức chung (thị trường, lịch sự kiện, tin vĩ mô, biến động mạnh, funding) -> 📰 Bot Tin tức (chat riêng từng
người, mỗi người tự bật/tắt từng loại). Chưa cấu hình Bot Tin tức -> gửi qua Bot Tín hiệu.
Nội dung về tín hiệu (tổng kết lời lỗ, danh mục Spot, tin xấu về lệnh đang mở, 15h đang theo dõi) -> Bot Tín hiệu.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from html import escape

import pandas as pd
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


# 📰 Bot Tin tức (main.py gán khi có NEWS_BOT_TOKEN) + username 2 bot để tạo nút liên kết
NEWS_BOT: Bot | None = None
SIGNAL_BOT: Bot | None = None  # gửi yêu cầu duyệt + nhật ký (bot tín hiệu có trong nhóm, là nơi quản lý chung)
SIGNAL_USERNAME = ""
NEWS_USERNAME = ""

NEWS_CATS = {"morning": "🌅 Thị trường 7h sáng", "calendar": "📅 Lịch tin kinh tế",
             "macro": "⏰ Tin vĩ mô Mỹ (trước / sau khi ra)", "breaking": "⚡ Tin nóng ảnh hưởng xu hướng",
             "money": "💰 Tiền lớn vào / ra (stablecoin)", "listing": "🆕 Coin niêm yết sàn lớn",
             "early": "🚀 Dấu hiệu gom hàng / ép short", "moves": "📈 Coin chạy mạnh (Top 20)",
             "weekly": "📊 Tổng kết thị trường tuần"}


def news_off(u: dict) -> set[str]:
    try:
        return set(storage.loads(u["news_prefs"])) if u.get("news_prefs") else set()
    except Exception:  # noqa: BLE001
        return set()


def analyze_url(base: str) -> str | None:
    """Link mở 🔍 Phân tích coin ở Bot Tín hiệu (deep link /start an_SOL)."""
    return f"https://t.me/{SIGNAL_USERNAME}?start=an_{base}" if SIGNAL_USERNAME else None


async def broadcast_news(bot: Bot, text: str, markup: InlineKeyboardMarkup | None = None, *,
                         category: str = "general", silent: bool | None = None, photo: bytes | None = None) -> None:
    """Tin tức chung -> 📰 Bot Tin tức (người đã mở bot đó, không tắt loại tin này).
    Chưa có Bot Tin tức -> gửi qua Bot Tín hiệu cho mọi người. Giờ yên lặng -> gửi không chuông."""
    silent = is_quiet() if silent is None else silent
    sender = NEWS_BOT or bot
    users = await storage.news_users() if NEWS_BOT else await storage.subscribers()
    for u in users:
        if category in news_off(u):
            continue
        try:
            if photo is not None and len(text) <= 1024:
                await sender.send_photo(u["chat_id"], photo, caption=text, parse_mode=ParseMode.HTML, reply_markup=markup,
                                        disable_notification=silent)
            else:
                await sender.send_message(u["chat_id"], text, parse_mode=ParseMode.HTML, reply_markup=markup,
                                          disable_web_page_preview=True, disable_notification=silent)
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
        lines.append(f"{icon} {t:%H:%M} {escape(events.vi_title(e['title']))}{fc}")
        if len(buttons) < 8 and (e.get("impact") == "High" or len(evs) <= 8):
            buttons.append([InlineKeyboardButton(f"ℹ️ {t:%d/%m} {events.vi_title(e['title'])[:40]}", callback_data=f"ev:{event_key(e)}")])
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
    await broadcast_news(bot, text, markup, category="calendar")


async def pinned_calendar(bot: Bot, *, new: bool = False) -> bool:
    """Tin ghim "📅 Lịch tuần" đầu chat 📰 Bot Tin tức của từng người: thứ 2 gửi mới + ghim, các ngày khác sửa lại
    (bỏ tin đã qua). Trả False nếu chưa có Bot Tin tức."""
    if not NEWS_BOT:
        return False
    evs = [e for e in await events.week_events() if e["time"] >= datetime.now(timezone.utc) - timedelta(hours=2)]
    text, markup = calendar_message(evs, f"📅 <b>Lịch sự kiện tuần này</b> · cập nhật {vn_now():%H:%M %d/%m}")
    for u in await storage.news_users():
        if "calendar" in news_off(u):
            continue
        chat, key = u["chat_id"], f"cal_pin:{u['chat_id']}"
        old = await storage.kv_get(key)
        if old and not new:
            try:
                await NEWS_BOT.edit_message_text(text, chat_id=chat, message_id=int(old), parse_mode=ParseMode.HTML,
                                                 reply_markup=markup, disable_web_page_preview=True)
                continue
            except TelegramError as exc:
                if "not modified" in str(exc).lower():
                    continue
        try:
            m = await NEWS_BOT.send_message(chat, text, parse_mode=ParseMode.HTML, reply_markup=markup,
                                            disable_web_page_preview=True, disable_notification=True)
            if old:
                try:
                    await NEWS_BOT.unpin_chat_message(chat, int(old))
                except TelegramError:
                    pass
            await NEWS_BOT.pin_chat_message(chat, m.message_id, disable_notification=True)
            await storage.kv_set(key, str(m.message_id))
        except TelegramError as exc:
            log.info("Lịch ghim cho %s lỗi: %s", chat, exc)
        await asyncio.sleep(0.05)
    return True


async def today_calendar(bot: Bot) -> None:
    start, end = vn_midnight_utc(), vn_midnight_utc() + timedelta(days=1)
    evs = [e for e in await events.week_events() if start <= e["time"] < end]
    text, markup = calendar_message(evs, f"🗓 <b>Tin kinh tế hôm nay</b> {vn_now():%d/%m}")
    await broadcast_news(bot, text, markup, category="calendar")


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
        extreme = [(c.base, fund[c.symbol]) for c in coins if abs(fund.get(c.symbol, 0)) >= settings.funding_alert]
        if extreme:
            lines.append("🔥 Funding cực đoan: " + " · ".join(f"{b} {f:+.3%}" for b, f in extreme[:5])
                         + " (đám đông quá đông 1 phía, dễ bị quét ngược)")
    stable = await macro.stablecoin_change_7d()
    if stable is not None:
        lines.append(f"💵 Cung stablecoin 7 ngày: {stable:+.2%} ({'tiền đang vào' if stable > 0 else 'tiền đang rút'})")

    start, end = vn_midnight_utc(), vn_midnight_utc() + timedelta(days=1)
    events = [e for e in await macro.high_impact_events() if start <= e["time"] < end]
    lines.append("")
    if events:
        lines.append("📅 <b>Tin vĩ mô Mỹ hôm nay</b> (bot tạm dừng 3h trước → 1h sau):")
        lines += [f"• {e['time'].astimezone(VN_TZ):%H:%M} — {escape(events.vi_title(e['title']))}" for e in events]
    else:
        lines.append("📅 Hôm nay không có tin vĩ mô Mỹ quan trọng.")

    items = await news.headlines(24)
    if items:
        from app.assistant import vi_titles
        top = sorted(items, key=lambda h: -abs(h.score))[:3]
        vi = await vi_titles([h.title for h in top])
        lines += ["", "🗞 <b>Tin đáng chú ý</b>:"]
        lines += [f"• <a href=\"{escape(h.link)}\">{escape(t[:120])}</a>" for h, t in zip(top, vi)]

    watch = await scanner.watch_candidates(5)
    if watch:
        lines += ["", "👀 <b>Đang theo dõi</b> (chưa phải tín hiệu):"]
        lines += [f"• {w}" for w in watch]
    return "\n".join(lines)


async def morning(bot: Bot) -> None:
    await broadcast_news(bot, await morning_text(), category="morning")
    if vn_now().weekday() == 0:
        if not await pinned_calendar(bot, new=True):
            await week_calendar(bot)
    else:
        start, end = vn_midnight_utc(), vn_midnight_utc() + timedelta(days=1)
        if any(start <= e["time"] < end for e in await macro.high_impact_events()):
            await today_calendar(bot)  # chỉ nhắn lịch trong ngày khi hôm đó có tin tác động mạnh
        await pinned_calendar(bot)


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
    await broadcast(bot, text)


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
        got = {s["id"] for s in await storage.user_signals(u["chat_id"], 31)}
        mine = lambda rows: [s for s in rows if s["id"] in got]  # noqa: E731  chỉ lệnh bot đã gửi cho người này
        mult = lambda s: texts.disp_mult(s, u["mode"], u.get("exchange"))  # noqa: E731
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
                f"{escape(events.vi_title(e['title']))} lúc {e['time'].astimezone(VN_TZ):%H:%M}" for e in upcoming))
        if u["mode"] == "spot":
            from app import portfolio as pf
            line = await pf.summary_line(u["chat_id"], u.get("currency", "USDT"))
            if line:
                lines += ["", line]
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
            from app.assistant import vi_titles
            vi = (await vi_titles([h.title]))[0]
            text = (f"⚠️ <b>{escape(s['display'])}</b>: có tin có thể đi NGƯỢC lệnh "
                    f"{'LONG' if s['side'] > 0 else 'SHORT'} của bạn:\n<a href=\"{escape(h.link)}\">{escape(vi)}</a>\n"
                    "Cân nhắc giảm vị thế hoặc dời SL sát hơn.")
            for m in await storage.messages_for(s["id"]):
                if m["chat_id"] in users and not users[m["chat_id"]]["banned"]:
                    await _send(bot, m["chat_id"], text, reply_to=m["message_id"])


FF_URL = "https://www.forexfactory.com/calendar?day=today"
NEWS_STAGES = (("pre", timedelta(minutes=-75), timedelta(minutes=-45)),   # trước 1 giờ
               ("r60", timedelta(minutes=60), timedelta(minutes=90)))    # 1 giờ sau: phản ứng thật + tóm tắt


def _groups(evs: list[dict]) -> dict[datetime, list[dict]]:
    """Gộp các tin ra cùng giờ (vd CPI + Core CPI) thành 1 tin nhắn."""
    out: dict[datetime, list[dict]] = {}
    for e in evs:
        out.setdefault(e["time"], []).append(e)
    return out


async def _reaction(t: datetime) -> dict[str, dict]:
    """BTC/ETH từ lúc tin ra tới giờ: giá lúc ra tin, giá hiện tại, cao/thấp nhất."""
    out = {}
    for sym in ("BTCUSDT", "ETHUSDT"):
        k = await binance.klines(sym, "5m", 40, closed_only=False)
        after = k[k.index >= pd.Timestamp(t)]
        if not len(after):
            continue
        p0 = float(after["open"].iloc[0])
        out[sym[:3]] = {"p0": p0, "now": float(after["close"].iloc[-1]), "hi": float(after["high"].max()),
                        "lo": float(after["low"].min()), "chg": float(after["close"].iloc[-1]) / p0 - 1}
    return out


def _mood(chg: float) -> str:
    if abs(chg) < 0.003:
        return "⚪ Thị trường chưa chọn hướng rõ (BTC chạy dưới 0.3%)"
    return "🟢 Thị trường đang hiểu tin là TỐT (BTC tăng)" if chg > 0 else "🔴 Thị trường đang hiểu tin là XẤU (BTC giảm)"


def _scenario(r: dict) -> str:
    p = texts.price
    if abs(r["chg"]) < 0.003:
        return f"👉 Chờ BTC vượt {p(r['hi'])} hoặc thủng {p(r['lo'])} để rõ hướng — đừng đoán trước."
    if r["chg"] > 0:
        return (f"👉 Nếu BTC giữ trên {p(r['p0'])} (giá lúc ra tin) → đà tăng thường còn tiếp; "
                f"rơi lại dưới {p(r['p0'])} → dễ là bẫy tăng, cẩn thận LONG đuổi.")
    return (f"👉 Nếu BTC nằm dưới {p(r['p0'])} (giá lúc ra tin) → áp lực bán thường còn tiếp; "
            f"lấy lại {p(r['p0'])} → dễ là bẫy giảm, cẩn thận SHORT đuổi.")


async def news_message(stage: str, t: datetime, group: list[dict]) -> tuple[str, InlineKeyboardMarkup | None]:
    """Tin nhắn ngắn (~5 dòng) cho từng mốc: trước 1 giờ, lúc ra tin, +15 phút, +1 giờ."""
    main = group[0]
    kind, explain = events.classify(main["title"])
    titles = escape(", ".join(dict.fromkeys(events.vi_title(e["title"]) for e in group)))
    hhmm = t.astimezone(VN_TZ).strftime("%H:%M")
    if stage == "pre":
        what, rule = events.brief(kind, explain)
        st = await events.reaction_stats(kind)
        lines = [f"⏰ <b>{hhmm} — {titles}</b> (còn khoảng 1 giờ)", f"📌 {escape(what)}", f"⚖️ {escape(rule)}"]
        if st:
            lines.append(f"📊 BTC 24h sau {st['n']} lần gần đây: TB ±{st['avg_abs']:.1%} (ngày thường ±{st['normal_abs']:.1%}), "
                         f"tăng {st['up']} · giảm {st['down']}")
        lines.append(f"⏸ Bot dừng tín hiệu mới tới {(t + timedelta(hours=1)).astimezone(VN_TZ):%H:%M}. "
                     "Lệnh đang mở nên có SL trên sàn.")
        button = InlineKeyboardMarkup([[InlineKeyboardButton("ℹ️ Chi tiết + thống kê",
                                                             callback_data=f"ev:{event_key(main)}")]])
        return "\n".join(lines), button
    if stage == "release":
        fc = " · ".join(f"{escape(events.vi_title(e['title']))}: dự báo <b>{escape(str(e['forecast']))}</b>, kỳ trước "
                        f"{escape(str(e.get('previous') or '?'))}" for e in group if e.get("forecast"))
        _, rule = events.brief(kind, explain)
        r = (await _reaction(t)).get("BTC")
        lines = [f"🔔 <b>{titles} vừa ra</b> ({hhmm})"]
        if fc:
            lines.append(fc)
        lines += [f"⚖️ {escape(rule)}", f"🔎 Số thực tế: <a href=\"{FF_URL}\">ForexFactory</a> (cột Actual)"]
        if r:
            lines.append(f"₿ BTC lúc ra tin: {texts.price(r['p0'])} — bot báo phản ứng sau 15 phút.")
        return "\n".join(lines), None
    react = await _reaction(t)
    r = react.get("BTC")
    if not r:
        return "", None
    moves = " · ".join(f"{k} {v['chg']:+.2%}" for k, v in react.items())
    if stage == "r15":
        lines = [f"📈 <b>15 phút sau {titles}</b>",
                 f"{moves} (biên độ BTC {texts.price(r['lo'])} – {texts.price(r['hi'])})", _mood(r["chg"]), _scenario(r)]
        return "\n".join(lines), None
    lines = [f"🕐 <b>1 giờ sau {titles}</b>: {moves} so với lúc ra tin", _mood(r["chg"])]
    items = await news.headlines(3)
    if items:
        from app import assistant
        ctx = (f"Tin kinh tế Mỹ vừa ra: {', '.join(e['title'] for e in group)} lúc {hhmm} giờ VN. "
               f"Phản ứng 1 giờ: {moves}.\nTiêu đề tin crypto 3 giờ gần nhất:\n"
               + "\n".join(f"- {h.title}" for h in items[:12]))
        summary = await assistant.news_summary(
            "Tóm tắt thị trường đang phản ứng thế nào với tin này (tối đa 3 gạch đầu dòng, chỉ dựa vào dữ liệu).", ctx)
        if summary:
            lines.append("🤖 " + escape(summary))
    lines.append("▶️ Bot mở lại tín hiệu mới. Tránh vào lệnh đuổi theo cây nến tin.")
    return "\n".join(lines), None


async def macro_reminders(bot: Bot) -> None:
    """Tin vĩ mô Mỹ tác động mạnh -> topic 📰: trước 1 giờ, lúc ra tin, +15 phút, +1 giờ (mỗi mốc 1 lần)."""
    now = datetime.now(timezone.utc)
    for t, group in _groups(await macro.high_impact_events()).items():
        for stage, lo, hi in NEWS_STAGES:
            if not (lo <= now - t < hi):
                continue
            key = f"macro:{stage}:{t:%Y%m%d%H%M}"
            if await storage.kv_get(key):
                continue
            await storage.kv_set(key, "1")
            try:
                text, markup = await news_message(stage, t, group)
            except Exception as exc:  # noqa: BLE001
                log.warning("Tin vĩ mô %s lỗi: %s", stage, exc)
                continue
            if text:
                await broadcast_news(bot, text, markup, category="macro")


# ---------------------------------------------------------------- tổng kết thị trường tuần (topic 📰, chủ nhật)
async def weekly_market_text() -> str:
    coins = await binance.universe(settings.top_n, settings.min_quote_volume)
    now = datetime.now(timezone.utc)
    lines = [f"📊 <b>Tổng kết thị trường tuần</b> ({(vn_now() - timedelta(days=7)):%d/%m} – {vn_now():%d/%m})"]

    async def week_chg(sym: str) -> float | None:
        try:
            d = await binance.klines(sym, "1d", 9, closed_only=False)
            return float(d["close"].iloc[-1] / d["close"].iloc[-8] - 1)
        except Exception:  # noqa: BLE001
            return None

    syms = list(dict.fromkeys(["BTCUSDT", "ETHUSDT"] + [c.symbol for c in coins]))
    chg = dict(zip(syms, await asyncio.gather(*(week_chg(s) for s in syms))))
    for sym, name in (("BTCUSDT", "₿ BTC"), ("ETHUSDT", "Ξ ETH")):
        if chg.get(sym) is not None:
            lines.append(f"{name}: {'🟢' if chg[sym] >= 0 else '🔴'} {chg[sym]:+.1%} trong tuần")
    ranked = sorted(((c.display.split("/")[0], chg[c.symbol]) for c in coins if chg.get(c.symbol) is not None),
                    key=lambda x: -x[1])
    if ranked:
        lines.append("📈 Mạnh nhất: " + " · ".join(f"{d} {v:+.0%}" for d, v in ranked[:3]))
        lines.append("📉 Yếu nhất: " + " · ".join(f"{d} {v:+.0%}" for d, v in ranked[::-1][:3]))

    past = await events.recent_events(7)
    if past:
        btc = await binance.klines("BTCUSDT", "1h", 200)
        lines += ["", "📅 <b>Tin lớn tuần qua</b> → BTC 24h sau tin:"]
        for t, group in _groups(past).items():
            before = btc[btc.index <= pd.Timestamp(t)]
            after = btc[btc.index <= pd.Timestamp(t + timedelta(hours=24))]
            move = (f"{after['close'].iloc[-1] / before['close'].iloc[-1] - 1:+.1%}"
                    if len(before) and len(after) and after.index[-1] > before.index[-1] else "chưa đủ 24h")
            lines.append(f"• {WEEKDAYS[t.astimezone(VN_TZ).weekday()]} {escape(events.vi_title(group[0]['title'])[:50])}: {move}")

    lines.append("")
    try:
        fng = await macro.fear_greed_history()
        lines.append(f"😱 Fear &amp; Greed: <b>{int(fng.iloc[-1])}</b> (tuần trước {int(fng.iloc[-8])})")
    except Exception:  # noqa: BLE001
        pass
    oi = await binance.oi_change("BTCUSDT", "1d", 7)
    if oi is not None:
        lines.append(f"💼 OI BTC 7 ngày: {oi:+.1%} "
                     f"({'đòn bẩy tăng' if oi > 0.03 else 'đòn bẩy giảm' if oi < -0.03 else 'ổn định'})")
    fund = await binance.all_funding()
    fr = [fund[c.symbol] for c in coins if c.symbol in fund]
    if fr:
        lines.append(f"💸 Funding TB top {len(fr)}: {sum(fr) / len(fr):.4%}/8h")
    stable = await macro.stablecoin_change_7d()
    if stable is not None:
        lines.append(f"💵 Stablecoin 7 ngày: {stable:+.2%} ({'tiền đang vào' if stable > 0 else 'tiền đang rút'})")

    upcoming = [e for e in await events.week_events()
                if now < e["time"] < now + timedelta(days=8) and e.get("impact") == "High"]
    lines += ["", "🔭 <b>Tuần tới cần chú ý</b>:"]
    if upcoming:
        for t, group in _groups(upcoming).items():
            lines.append(f"• {WEEKDAYS[t.astimezone(VN_TZ).weekday()]} {t.astimezone(VN_TZ):%d/%m %H:%M} "
                         f"{escape(', '.join(dict.fromkeys(events.vi_title(e['title']) for e in group))[:80])}")
    else:
        lines.append("Lịch chi tiết gửi lúc 7h sáng thứ 2 (nguồn lịch chưa cập nhật tuần mới).")
    lines.append("\n<i>Số liệu thật từ Binance / alternative.me / DefiLlama — không phải dự đoán.</i>")
    return "\n".join(lines)


async def weekly_market(bot: Bot) -> None:
    await broadcast_news(bot, await weekly_market_text(), category="weekly")


async def health_check(bot: Bot) -> None:
    """Sàn vừa giới hạn tần suất -> báo admin (bot đã tự chuyển nguồn). Quá N giờ không quét được -> báo admin."""
    import time
    from app.data import http
    from app.service import notify_admins
    recent = [h for h, t in http.last_block.items() if time.time() - t < 1800]
    if recent:
        await notify_admins(bot, f"ℹ️ Sàn giới hạn tần suất: {', '.join(recent)} — bot đang tạm lấy dữ liệu từ Bybit, "
                                 "vẫn quét và báo tín hiệu bình thường.", key="rate_limit", every_minutes=360)
    await _stale_scan_check(bot)


async def _stale_scan_check(bot: Bot) -> None:
    last = await storage.kv_get("last_scan_ok")
    if is_quiet() or not last:
        return
    age = datetime.now(timezone.utc) - datetime.fromisoformat(last)
    if age < timedelta(hours=settings.health_alert_hours):
        return
    from app.service import notify_admins
    await notify_admins(bot, f"🚨 Bot chưa quét được thị trường {age.total_seconds() / 3600:.1f} giờ "
                             "(cả Binance, Bybit, MEXC đều lỗi?). Bot sẽ tự khởi động lại nếu còn kẹt.",
                        key="stale_scan", every_minutes=360)


# ---------------------------------------------------------------- cảnh báo thị trường
async def market_alerts(bot: Bot) -> None:
    """BTC chạy mạnh trong 1 giờ (funding cực đoan đã gộp vào bản tin 7h cho đỡ loãng tin)."""
    try:
        k = await binance.klines("BTCUSDT", "5m", 13)
        move = k["close"].iloc[-1] / k["open"].iloc[-12] - 1
        if abs(move) >= settings.btc_move_alert_pct / 100:
            key = f"btcmove:{datetime.now(timezone.utc):%Y%m%d%H}"
            if not await storage.kv_get(key):
                await storage.kv_set(key, "1")
                await broadcast_news(bot, f"🚨 <b>BTC {'tăng' if move > 0 else 'giảm'} mạnh {move:+.1%} trong 1 giờ</b> "
                                          f"(giá {texts.price(float(k['close'].iloc[-1]))}).\n"
                                          "Biến động mạnh dễ quét SL 2 chiều — kiểm tra lệnh đang mở, tránh đuổi giá.",
                                     category="moves")
    except Exception as exc:  # noqa: BLE001
        log.warning("Cảnh báo BTC lỗi: %s", exc)


async def big_moves(bot: Bot) -> None:
    """📈 Coin Top 20 (trừ BTC) chạy mạnh trong ~1 giờ / ~4 giờ kèm volume tăng đột biến — tối đa 1 tin / 4 giờ."""
    from app.strategy.scanner import live_derivs
    slot = f"moves_slot:{datetime.now(timezone.utc):%Y%m%d}{datetime.now(timezone.utc).hour // 4}"
    if await storage.kv_get(slot):
        return
    coins = [c for c in await binance.universe(settings.top_n, settings.min_quote_volume) if c.symbol != "BTCUSDT"]
    items = await news.headlines(6)
    found = []
    for c in coins:
        try:
            k = await binance.klines(c.symbol, "1h", 30, closed_only=False)
        except Exception:  # noqa: BLE001
            continue
        if len(k) < 27:
            continue
        px = float(k["close"].iloc[-1])
        ch1, ch4 = px / float(k["close"].iloc[-2]) - 1, px / float(k["close"].iloc[-5]) - 1
        vol_x = max(float(k["volume"].iloc[-1]), float(k["volume"].iloc[-2])) / max(1e-9, float(k["volume"].iloc[-26:-2].mean()))
        hit = abs(ch1) >= settings.move_1h_pct / 100 or abs(ch4) >= settings.move_4h_pct / 100
        if not hit or vol_x < settings.move_vol_x:
            continue
        up = (ch1 if abs(ch1) >= settings.move_1h_pct / 100 else ch4) > 0
        key = f"move:{c.symbol}:{up}:{datetime.now(timezone.utc):%Y%m%d}{datetime.now(timezone.utc).hour // 4}"
        if await storage.kv_get(key):
            continue
        await storage.kv_set(key, "1")
        found.append((c, px, ch1, ch4, vol_x, up))
    if not found:
        return
    await storage.kv_set(slot, "1")
    lines, buttons = ["📈 <b>Coin chạy mạnh</b>"], []
    for c, px, ch1, ch4, vol_x, up in found[:5]:
        d = await live_derivs(c.symbol, 24)
        extra = " · ".join(filter(None, [f"OI 24h {d['oi_chg']:+.0%}" if "oi_chg" in d else "",
                                         f"funding {d['funding']:.3%}" if "funding" in d else ""]))
        lines.append(f"\n{'🟢' if up else '🔴'} <b>{escape(c.base)}</b> {ch1:+.1%} (1 giờ) · {ch4:+.1%} (4 giờ) · "
                     f"volume x{vol_x:.1f}\nGiá {texts.price(px / c.multiplier)}" + (f" · {extra}" if extra else ""))
        cn = news.coin_news(c.base, items)
        heads = (cn.get("severe_negative") or []) + (cn.get("severe_positive") or [])
        if heads:
            from app.assistant import vi_titles
            lines.append("📰 " + escape((await vi_titles([heads[0].title]))[0][:110]))
        url = analyze_url(c.base)
        if url:
            buttons.append(InlineKeyboardButton(f"🔍 {c.base}", url=url))
    markup = InlineKeyboardMarkup([buttons[i:i + 3] for i in range(0, len(buttons), 3)]) if buttons else None
    await broadcast_news(bot, "\n".join(lines), markup, category="moves")


async def latest_news_text(limit: int = 8) -> str:
    from app.alerts import rate_headlines
    from app.assistant import vi_titles
    all_items = await news.headlines(24)
    if not all_items:
        return "📰 Chưa lấy được tin mới, thử lại sau ít phút."
    rated = await rate_headlines(all_items[:40])
    items = sorted(all_items[:40], key=lambda h: (rated.get(h.title, 1), h.time), reverse=True)[:limit]
    items.sort(key=lambda h: h.time, reverse=True)
    vi = await vi_titles([h.title for h in items])
    lines = [f"📰 <b>{limit} tin quan trọng nhất 24h</b> · cập nhật {vn_now():%H:%M %d/%m} (tin mới nhất lúc "
             f"{all_items[0].time.astimezone(VN_TZ):%H:%M})"]
    for h, t in zip(items, vi):
        icon = "🟢" if h.score > 0.2 else "🔴" if h.score < -0.2 else "⚪"
        lines.append(f"{icon} {h.time.astimezone(VN_TZ):%H:%M} <a href=\"{escape(h.link)}\">{escape(t[:120])}</a>")
    return "\n".join(lines)


async def hot_coins_text() -> str:
    from app.strategy import scanner
    coins = await binance.universe(50, settings.min_quote_volume)
    tick = await binance.tickers_24h()
    moves = sorted(((c.base, float(tick[c.symbol]["priceChangePercent"])) for c in coins if c.symbol in tick),
                   key=lambda x: -x[1])
    lines = [f"🔥 <b>Coin đáng chú ý</b> · {vn_now():%H:%M %d/%m}"]
    if moves:
        lines.append("📈 Tăng mạnh 24h: " + " · ".join(f"{b} {v:+.1f}%" for b, v in moves[:5]))
        lines.append("📉 Giảm mạnh 24h: " + " · ".join(f"{b} {v:+.1f}%" for b, v in moves[::-1][:5]))
    oi = [(c.base, x[1]) for c, x in zip(coins[:20], await asyncio.gather(*(binance.oi_change_24h(c.symbol)
                                                                           for c in coins[:20]))) if x]
    if oi:
        top = sorted(oi, key=lambda x: -abs(x[1]))[:5]
        lines.append("💼 OI biến động mạnh 24h: " + " · ".join(f"{b} {v:+.0%}" for b, v in top))
    watch = await scanner.watch_candidates(5)
    if watch:
        lines += ["", "👀 <b>Gần đủ điều kiện vào lệnh</b> (bot đang theo dõi):"] + [f"• {w}" for w in watch]
    return "\n".join(lines)


# ---------------------------------------------------------------- coin 📌 đang giữ
async def holdings_watch(bot: Bot) -> None:
    """Theo dõi coin trong 💼 Danh mục Spot: xu hướng 4H đổi chiều, thủng/vượt vùng quan trọng, OI, funding, tin xấu."""
    from app.service import _send
    from app.strategy.scanner import live_derivs
    holders: dict[str, list[int]] = {}
    for r in await storage.all_positions():
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
                alerts.append(f"🔻 Giá thủng đáy 20 ngày ({texts.price(low20 / binance.split_symbol(sym)[1])}) — cân nhắc bảo vệ vốn")
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
                    from app.assistant import vi_titles
                    vi = (await vi_titles([h.title]))[0]
                    alerts.append(f"📰 Tin xấu: <a href=\"{escape(h.link)}\">{escape(vi[:120])}</a>")
        except Exception as exc:  # noqa: BLE001
            log.warning("Theo dõi coin giữ %s lỗi: %s", sym, exc)
            continue
        if alerts:
            text = (f"📌 <b>{escape(binance.split_symbol(sym)[0])}</b> (trong 💼 danh mục của bạn) · giá {texts.price(px / binance.split_symbol(sym)[1])}\n"
                    + "\n".join(f"• {a}" for a in alerts))
            for chat in chats:
                await _send(bot, chat, text)


# ---------------------------------------------------------------- sao lưu dữ liệu (tối chủ nhật + nút của admin)
async def send_backup(bot: Bot, chat_id: int | None = None) -> None:
    """File JSON dữ liệu người dùng -> topic nhật ký (nhóm chỉ có admin + 2 bot); nút 📦 thì gửi vào chat đang bấm."""
    import io
    from app.service import log_target
    data = storage.dumps(await storage.export_data()).encode()
    name = f"backup_{vn_now():%Y%m%d_%H%M}.json"
    target = None if chat_id else await log_target()
    if target:
        try:
            await (SIGNAL_BOT or bot).send_document(target[0], io.BytesIO(data), filename=name, message_thread_id=target[1],
                                                    caption="📦 Sao lưu dữ liệu người dùng hằng tuần. Cần khôi phục: "
                                                            "gửi file này vào chat riêng với Bot Tín hiệu.")
            return
        except TelegramError as exc:
            log.warning("Gửi sao lưu vào topic lỗi: %s", exc)
    for admin in [chat_id] if chat_id else settings.admin_ids:
        try:
            await bot.send_document(admin, io.BytesIO(data), filename=name,
                                    caption="📦 Sao lưu dữ liệu người dùng (cài đặt, coin theo dõi, danh mục, lịch sử "
                                            "mua bán). Cần khôi phục: gửi lại file này cho bot.")
        except TelegramError as exc:
            log.warning("Gửi sao lưu cho %s lỗi: %s", admin, exc)


# ---------------------------------------------------------------- 23:00 tóm tắt sức khỏe bot (topic nhật ký)
async def daily_health(bot: Bot) -> None:
    import time
    from app.data import http
    from app.service import notify_admins
    today = vn_midnight_utc()
    sigs = await storage.signals_since(today)
    closed = [s for s in await storage.closed_signals(days=2) if s["closed_at"] and s["closed_at"] >= today]
    last = await storage.kv_get("last_scan_ok")
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 60 if last else None
    blocked = [h for h, t in http.last_block.items() if time.time() - t < 86400]
    errs = int(await storage.kv_get(f"errors:{vn_now():%Y%m%d}") or 0)
    ok = age is not None and age < 90 and errs == 0
    await notify_admins(bot, "\n".join([
        f"{'🟢' if ok else '🟠'} <b>Sức khỏe bot {vn_now():%d/%m}</b>",
        f"Quét gần nhất: {f'{age:.0f} phút trước' if age is not None else 'chưa có'} · lỗi xử lý hôm nay: {errs}",
        f"Tín hiệu hôm nay: {len([s for s in sigs if s.get('source') != 'ind'])} bot · "
        f"{len([s for s in sigs if s.get('source') == 'ind'])} 🎯 · lệnh đóng: {len(closed)}",
        f"Nguồn dữ liệu bị giới hạn trong ngày: {', '.join(blocked) if blocked else 'không'}",
        f"Người dùng: {len(await storage.subscribers())} nhận tín hiệu · {len(await storage.news_users())} dùng Bot Tin tức",
    ]))


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
