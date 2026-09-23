"""Phát tín hiệu, theo dõi lệnh, báo cáo — nối chiến lược với Telegram."""
from __future__ import annotations

import asyncio
import logging
from html import escape
from datetime import datetime, timedelta, timezone

import pandas as pd
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import Forbidden, TelegramError

from app import chart, indicators as ta, storage
from app.bot import texts
from app.config import VN_TZ, settings
from app.data import binance, macro, news
from app.strategy.core import describe
from app.strategy.scanner import Found, bucket_stats, scan
from app.strategy.trade import Trade

log = logging.getLogger(__name__)
_scan_lock = asyncio.Lock()
CAPTION_LIMIT = 1024


def tv_url(sig: dict, mode: str) -> str:
    sym = f"BINANCE:{sig['spot_symbol']}" if mode == "spot" and sig.get("spot_symbol") else f"BINANCE:{sig['symbol']}.P"
    return f"https://www.tradingview.com/chart/?symbol={sym}&interval=60"


def receives(user: dict, sig: dict) -> bool:
    """Spot chỉ nhận lệnh MUA của coin có trên spot."""
    return user["mode"] == "futures" or (sig["side"] > 0 and bool(sig.get("spot_symbol")))


async def _send(bot: Bot, chat_id: int, text: str, *, photo: bytes | None = None, url: str | None = None,
                reply_to: int | None = None) -> int | None:
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("📈 Mở chart TradingView", url=url)]]) if url else None
    try:
        if photo is not None and len(text) <= CAPTION_LIMIT:
            m = await bot.send_photo(chat_id, photo, caption=text, parse_mode=ParseMode.HTML, reply_markup=markup)
        else:
            if photo is not None:
                m0 = await bot.send_photo(chat_id, photo)
                reply_to = m0.message_id
            m = await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=markup,
                                       reply_to_message_id=reply_to, disable_web_page_preview=True)
        return m.message_id
    except Forbidden:
        log.info("Người dùng %s đã chặn bot -> hủy đăng ký", chat_id)
        await storage.update_user(chat_id, subscribed=False)
    except TelegramError as exc:
        log.warning("Gửi tới %s lỗi: %s", chat_id, exc)
    return None


def _chart(h1: pd.DataFrame, sig: dict, mult: int) -> bytes:
    df = h1.copy()
    if mult != 1:
        df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]] / mult
    k = 1 / mult
    return chart.render(df, title=f"{sig['display']} · 1H · Binance {'Spot' if mult != 1 else 'Futures'}",
                        subtitle=f"Điểm {sig['score']:.0f}/100 · {sig['setup_text']} · {texts.vn_time(sig['created_at'])}",
                        side=sig["side"], entry=sig["entry"] * k, sl=sig["sl"] * k, tp1=sig["tp1"] * k,
                        tp2=sig["tp2"] * k, zone_lo=sig["zone_lo"] * k, zone_hi=sig["zone_hi"] * k)


async def publish(bot: Bot, found: Found) -> int:
    c, coin, row = found.candidate, found.coin, found.candidate.row
    created = storage.now()
    trade = Trade(c.side, row["entry"], row["sl"], created=created,
                  deadline=created + timedelta(hours=settings.max_hold_hours))
    reasons = describe(c)
    setup_text = reasons[0]
    values = dict(symbol=coin.symbol, display=coin.display, side=c.side, spot_symbol=coin.spot_symbol,
                  multiplier=coin.multiplier, score=c.score, setup=row["setup_type"], entry=row["entry"],
                  sl=row["sl"], tp1=row["tp1"], tp2=row["tp2"], zone_lo=row["zone_lo"], zone_hi=row["zone_hi"],
                  reasons=storage.dumps(reasons[1:]), status="ACTIVE", created_at=created,
                  state=storage.dumps({"trade": trade.to_dict(), "last_ts": created, "notified_stop": row["sl"]}))
    sig_id = await storage.insert_signal(**values)
    sig = {**values, "id": sig_id, "trend": row["trend"], "setup_text": setup_text, "reasons": reasons[1:]}
    stats = bucket_stats(c.score)

    photos: dict[int, bytes] = {}
    for user in await storage.subscribers():
        if not receives(user, sig):
            continue
        mult = coin.multiplier if user["mode"] == "spot" else 1
        if mult not in photos:
            photos[mult] = await asyncio.to_thread(_chart, found.h1, sig, mult)
        text = texts.signal_message(sig, mode=user["mode"], risk_pct=user["risk_pct"], stats=stats)
        mid = await _send(bot, user["chat_id"], text, photo=photos[mult], url=tv_url(sig, user["mode"]))
        if mid:
            await storage.add_message(sig_id, user["chat_id"], mid)
        await asyncio.sleep(0.05)
    log.info("Đã phát tín hiệu #%d %s %s điểm %.1f", sig_id, coin.symbol, c.side_name, c.score)
    return sig_id


async def run_scan(bot: Bot) -> str:
    if _scan_lock.locked():
        return "Đang quét, thử lại sau."
    async with _scan_lock:
        found, note = await scan()
        for f in found:
            await publish(bot, f)
        log.info("Quét xong: %s, phát %d tín hiệu", note, len(found))
        return f"{note}. Phát {len(found)} tín hiệu."


async def track(bot: Bot) -> None:
    """Cập nhật các lệnh đang mở bằng nến 5 phút; báo sự kiện vào đúng tin nhắn tín hiệu gốc."""
    for sig in await storage.open_signals():
        try:
            await _track_one(bot, sig)
        except Exception as exc:  # noqa: BLE001
            log.warning("Theo dõi #%s lỗi: %s", sig["id"], exc)


async def _track_one(bot: Bot, sig: dict) -> None:
    state = storage.loads(sig["state"])
    trade = Trade.from_dict(state["trade"])
    last_ts: datetime = state["last_ts"]
    bars = await binance.klines_since(sig["symbol"], "5m", int(last_ts.timestamp() * 1000) + 1)
    bars = bars[bars["close_time"] > last_ts] if len(bars) else bars
    if bars.empty:
        return
    atr = float(ta.atr(await binance.klines(sig["symbol"], "4h", 100)).iloc[-1])

    events = []
    for _, b in bars.iterrows():
        ct = b["close_time"].to_pydatetime()
        for ev, px in trade.step(ct, b["high"], b["low"], b["close"], atr, hour_close=ct.minute == 0):
            if ev == "TRAIL_MOVE":
                if abs(px - state["notified_stop"]) < 0.5 * trade.risk:
                    continue  # chỉ báo khi SL dời đáng kể (>= 0.5R)
            if ev in ("TRAIL_MOVE", "BE"):
                state["notified_stop"] = px
            events.append((ev, px))
        if trade.status != "ACTIVE":
            break
    state.update(trade=trade.to_dict(), last_ts=bars["close_time"].iloc[-1].to_pydatetime())
    values = {"state": storage.dumps(state)}
    if trade.status != "ACTIVE":
        values.update(status="CLOSED", result_r=round(trade.realized_r, 3), closed_at=trade.closed_at)
    await storage.update_signal(sig["id"], **values)
    if not events:
        return

    # gộp các lệnh TRAIL_MOVE liên tiếp trong cùng lần kiểm tra -> chỉ báo mức cuối
    # (bỏ hẳn nếu lệnh đã đóng trong lần kiểm tra này)
    trail = [e for e in events if e[0] == "TRAIL_MOVE"] if trade.status == "ACTIVE" else []
    events = [e for e in events if e[0] != "TRAIL_MOVE"] + trail[-1:]
    users = {u["chat_id"]: u for u in await storage.all_users()}
    for m in await storage.messages_for(sig["id"]):
        u = users.get(m["chat_id"])
        if not u or u["banned"]:
            continue
        for ev, px in events:
            r = trade.realized_r if ev in ("SL", "STOPPED", "TIMEOUT") else 0.0
            await _send(bot, m["chat_id"], texts.event_message(sig, ev, px, r, u["mode"]), reply_to=m["message_id"])


async def market_overview() -> str:
    btc = await binance.klines("BTCUSDT", "4h", 120)
    e20, e50 = ta.ema(btc["close"], 20).iloc[-1], ta.ema(btc["close"], 50).iloc[-1]
    px = btc["close"].iloc[-1]
    ch24 = px / btc["close"].iloc[-7] - 1
    trend = "🟢 Tăng" if px > e50 and e20 > e50 else "🔴 Giảm" if px < e50 and e20 < e50 else "⚪ Đi ngang"
    fg, dom, stable = await asyncio.gather(macro.fear_greed_now(), macro.btc_dominance(), macro.stablecoin_change_7d())
    events = [e for e in await macro.high_impact_events() if e["time"] >= datetime.now(timezone.utc)][:4]
    items = await news.headlines(12)
    sent = news.market_sentiment(items)
    lines = [f"🌍 <b>Tổng quan thị trường</b> · {texts.vn_time()}",
             f"₿ BTC: <b>{texts.price(px)}</b> ({ch24:+.1%} 24h) · Xu hướng 4H: {trend}"]
    if fg:
        lines.append(f"😱 Fear &amp; Greed: <b>{fg[0]}</b> ({fg[1]})")
    if dom:
        lines.append(f"👑 BTC Dominance: {dom:.1f}%")
    if stable is not None:
        lines.append(f"💵 Cung stablecoin 7 ngày: {stable:+.2%} ({'tiền đang vào' if stable > 0 else 'tiền đang rút'})")
    lines.append(f"📰 Sentiment tin tức 12h: {'🟢 tích cực' if sent > 0.15 else '🔴 tiêu cực' if sent < -0.15 else '⚪ trung tính'} ({sent:+.2f})")
    if events:
        lines.append("\n📅 <b>Tin vĩ mô Mỹ sắp tới</b> (bot tạm dừng 3h trước → 1h sau):")
        lines += [f"• {e['time'].astimezone(VN_TZ):%H:%M %d/%m} — {e['title']}" for e in events]
    if items:
        lines.append("\n🗞 <b>Tin mới</b>:")
        lines += [f"• <a href=\"{escape(h.link)}\">{escape(h.title[:90])}</a>" for h in items[:5]]
    return "\n".join(lines)


async def daily_report(bot: Bot) -> None:
    since = datetime.now(VN_TZ).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    today = await storage.signals_since(since)
    closed = [s for s in await storage.closed_signals(days=1)]
    opened = await storage.open_signals()
    text = (f"🗓 <b>Tổng kết ngày</b> {datetime.now(VN_TZ):%d/%m}\n"
            f"Tín hiệu mới: {len(today)} · Đang mở: {len(opened)}\n"
            + texts.stats_message(closed, "Lệnh đóng 24h qua").split("\n", 1)[1])
    for u in await storage.subscribers():
        await _send(bot, u["chat_id"], text)
        await asyncio.sleep(0.05)
