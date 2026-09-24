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
from app.strategy.scanner import STYLES, Found, bucket_stats, scan
from app.strategy.trade import Trade, callback_rate

log = logging.getLogger(__name__)
_scan_lock = asyncio.Lock()
CAPTION_LIMIT = 1024


def tv_url(sig: dict, mode: str) -> str:
    sym = f"BINANCE:{sig['spot_symbol']}" if mode == "spot" and sig.get("spot_symbol") else f"BINANCE:{sig['symbol']}.P"
    return f"https://www.tradingview.com/chart/?symbol={sym}&interval=60"


def receives(user: dict, sig: dict) -> bool:
    """Spot chỉ nhận lệnh MUA của coin có trên spot; mỗi người chỉ nhận kiểu swing đã chọn.
    Spot không nhận Swing dài: backtest 2 năm cho kết quả lỗ ở nửa dữ liệu gần đây."""
    style = sig.get("style", "short")
    if user.get("style", "both") not in ("both", style):
        return False
    if user["mode"] == "spot" and style == "long":
        return False
    return user["mode"] == "futures" or (sig["side"] > 0 and bool(sig.get("spot_symbol")))


async def _send(bot: Bot, chat_id: int, text: str, *, photo: bytes | None = None, url: str | None = None,
                reply_to: int | None = None, silent: bool = False) -> int | None:
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("📈 Mở chart TradingView", url=url)]]) if url else None
    try:
        if photo is not None and len(text) <= CAPTION_LIMIT:
            m = await bot.send_photo(chat_id, photo, caption=text, parse_mode=ParseMode.HTML, reply_markup=markup,
                                     disable_notification=silent)
        else:
            if photo is not None:
                m0 = await bot.send_photo(chat_id, photo, disable_notification=silent)
                reply_to = m0.message_id
            m = await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=markup,
                                       reply_to_message_id=reply_to, disable_web_page_preview=True,
                                       disable_notification=silent)
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
    tf = STYLES[sig.get("style", "short")].tfs[0].upper()
    return chart.render(df, title=f"{sig['display']} · {tf} · Binance {'Spot' if mult != 1 else 'Futures'}",
                        subtitle=f"Điểm {sig['score']:.0f}/100 · Hạng {sig.get('tier', 'A')} · {sig['setup_text']} · "
                                 f"{texts.vn_time(sig['created_at'])}",
                        side=sig["side"], entry=sig["entry"] * k, sl=sig["sl"] * k, tp1=sig["tp1"] * k,
                        tp2=(sig["entry"] + sig["side"] * abs(sig["entry"] - sig["sl"])) * k,
                        zone_lo=sig["zone_lo"] * k, zone_hi=sig["zone_hi"] * k, tp2_label="TRAIL")


async def publish(bot: Bot, found: Found) -> int:
    c, coin, row, style = found.candidate, found.coin, found.candidate.row, found.style
    created = storage.now()
    cb = callback_rate(float(row["atr4"]), float(row["entry"]))
    trade = Trade(c.side, row["entry"], row["sl"], created=created,
                  deadline=created + timedelta(hours=style.hold_hours), exit_mode="pct", callback=cb)
    reasons = describe(c)
    setup_text = reasons[0]
    values = dict(symbol=coin.symbol, display=coin.display, side=c.side, spot_symbol=coin.spot_symbol,
                  multiplier=coin.multiplier, score=c.score, setup=row["setup_type"], style=style.key, tier=found.tier,
                  entry=row["entry"], sl=row["sl"], tp1=row["tp1"], tp2=row["tp2"], zone_lo=row["zone_lo"],
                  zone_hi=row["zone_hi"], reasons=storage.dumps(reasons[1:]), status="ACTIVE", created_at=created,
                  state=storage.dumps({"trade": trade.to_dict(), "last_ts": created, "notified_stop": row["sl"]}))
    sig_id = await storage.insert_signal(**values)
    sig = {**values, "id": sig_id, "trend": row["trend"], "setup_text": setup_text, "reasons": reasons[1:],
           "exit_mode": "pct", "callback": cb}
    stats = bucket_stats(c.score, style.key)

    photos: dict[int, bytes] = {}
    for user in await storage.subscribers():
        if not receives(user, sig):
            continue
        mult = coin.multiplier if user["mode"] == "spot" else 1
        if mult not in photos:
            photos[mult] = await asyncio.to_thread(_chart, found.h1, sig, mult)
        text = texts.signal_message(sig, mode=user["mode"], risk_pct=user["risk_pct"], stats=stats)
        if found.silent:
            text = "🌙 <i>Tín hiệu ban đêm (gửi không chuông) — sáng ra kiểm tra giá chưa vượt mức \"Không vào\" rồi hãy vào.</i>\n" + text
        mid = await _send(bot, user["chat_id"], text, photo=photos[mult], url=tv_url(sig, user["mode"]),
                          silent=found.silent)
        if mid:
            await storage.add_message(sig_id, user["chat_id"], mid)
        await asyncio.sleep(0.05)
    log.info("Đã phát tín hiệu #%d %s %s %s hạng %s điểm %.1f", sig_id, style.key, coin.symbol, c.side_name,
             found.tier, c.score)
    return sig_id


async def run_scan(bot: Bot, styles: tuple[str, ...] = ("short",), *, force: bool = False) -> str:
    if _scan_lock.locked():
        return "Đang quét, thử lại sau."
    notes = []
    async with _scan_lock:
        for key in styles:
            found, note = await scan(key, force=force)
            for f in found:
                await publish(bot, f)
            log.info("Quét xong: %s, phát %d tín hiệu", note, len(found))
            notes.append(f"{note}. Phát {len(found)} tín hiệu.")
    return "\n".join(notes)


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
