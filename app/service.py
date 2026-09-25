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


def receives(user: dict, sig: dict, my_coins: set[str] | None = None) -> bool:
    """Ai nhận tín hiệu nào — mỗi người theo cài đặt riêng, không ảnh hưởng người khác:
    - kiểu swing đã chọn; Spot chỉ nhận lệnh MUA của coin có trên spot, không nhận Swing dài (backtest yếu);
    - coin: 'top' = Top 20 · 'mine' = chỉ coin tự chọn · 'both' = cả hai."""
    style = sig.get("style", "short")
    if user.get("style", "both") not in ("both", style):
        return False
    if user["mode"] == "spot" and style == "long":
        return False
    if not (user["mode"] == "futures" or (sig["side"] > 0 and bool(sig.get("spot_symbol")))):
        return False
    mine = sig["symbol"] in (my_coins or set())
    top = sig.get("source", "top") == "top"
    return {"top": top, "mine": mine, "both": top or mine}.get(user.get("coin_mode", "top"), top)


async def _send(bot: Bot, chat_id: int, text: str, *, photo: bytes | None = None, url: str | None = None,
                reply_to: int | None = None, silent: bool = False, why_id: int | None = None,
                markup: InlineKeyboardMarkup | None = None) -> int | None:
    rows = list(markup.inline_keyboard) if markup else []
    if url:
        rows.append([InlineKeyboardButton("📈 Mở chart TradingView", url=url)])
    if why_id:
        rows.append([InlineKeyboardButton("🧠 Vì sao có tín hiệu này?", callback_data=f"why:{why_id}")])
    markup = InlineKeyboardMarkup(rows) if rows else None
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
    style = sig.get("style", "short")
    tf = STYLES[style].tfs[0].upper() if style in STYLES else style.removeprefix("ind").upper()
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
                  source=found.source,
                  entry=row["entry"], sl=row["sl"], tp1=row["tp1"], tp2=row["tp2"], zone_lo=row["zone_lo"],
                  zone_hi=row["zone_hi"], reasons=storage.dumps(reasons[1:]), status="ACTIVE", created_at=created,
                  state=storage.dumps({"trade": trade.to_dict(), "last_ts": created, "notified_stop": row["sl"]}))
    sig_id = await storage.insert_signal(**values)
    sig = {**values, "id": sig_id, "trend": row["trend"], "setup_text": setup_text, "reasons": reasons[1:],
           "exit_mode": "pct", "callback": cb}
    stats = bucket_stats(c.score, style.key)

    photos: dict[int, bytes] = {}
    coins_by_user: dict[int, set[str]] = {}
    for r in await storage.all_user_coins():
        coins_by_user.setdefault(r["chat_id"], set()).add(r["symbol"])
    today = datetime.now(VN_TZ).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    for user in await storage.subscribers():
        if not receives(user, sig, coins_by_user.get(user["chat_id"])):
            continue
        if style.key == "short":  # mỗi người tối đa N tín hiệu swing ngắn/ngày (kể cả coin tự chọn)
            got = [m for m in await storage.messages_since(user["chat_id"], today) if m["style"] == "short"]
            if len(got) >= settings.max_signals_per_day:
                continue
        mult = coin.multiplier if user["mode"] == "spot" else 1
        if mult not in photos:
            photos[mult] = await asyncio.to_thread(_chart, found.h1, sig, mult)
        text = texts.signal_message(sig, mode=user["mode"], risk_pct=user["risk_pct"], stats=stats)
        if found.source == "user":
            text = "🪙 <i>Coin bạn chọn</i>\n" + text
        if found.silent:
            text = "🌙 <i>Tín hiệu ban đêm (gửi không chuông) — sáng ra kiểm tra giá chưa vượt mức \"Không vào\" rồi hãy vào.</i>\n" + text
        mid = await _send(bot, user["chat_id"], text, photo=photos[mult], url=tv_url(sig, user["mode"]),
                          silent=found.silent, why_id=sig_id)
        if mid:
            await storage.add_message(sig_id, user["chat_id"], mid)
        await asyncio.sleep(0.05)
    log.info("Đã phát tín hiệu #%d %s %s %s hạng %s điểm %.1f", sig_id, style.key, coin.symbol, c.side_name,
             found.tier, c.score)
    return sig_id


SCAN_TIMEOUT = 180  # giây — quá thì dừng lần quét này, lần sau vẫn chạy bình thường


async def notify_admins(bot: Bot, text: str, *, key: str | None = None, every_minutes: int = 60) -> None:
    """Nhắn admin (tối đa 1 lần / `every_minutes` cho cùng `key` để không dội tin)."""
    if key:
        k = f"admin_note:{key}:{int(datetime.now(timezone.utc).timestamp() // (every_minutes * 60))}"
        if await storage.kv_get(k):
            return
        await storage.kv_set(k, "1")
    for admin in settings.admin_ids:
        try:
            await bot.send_message(admin, text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except TelegramError as exc:
            log.warning("Không nhắn được admin %s: %s", admin, exc)


async def run_scan(bot: Bot, styles: tuple[str, ...] = ("short",), *, force: bool = False) -> str:
    if _scan_lock.locked():
        return "Đang quét, thử lại sau."
    notes = []
    async with _scan_lock:
        for key in styles:
            t0 = datetime.now(timezone.utc)
            try:
                found, note = await asyncio.wait_for(scan(key, force=force), SCAN_TIMEOUT)
            except asyncio.TimeoutError:
                log.error("Quét %s quá %ss -> dừng lần này", key, SCAN_TIMEOUT)
                await notify_admins(bot, f"⚠️ Quét {key} quá {SCAN_TIMEOUT // 60} phút nên đã dừng lần này "
                                         "(nguồn dữ liệu chậm / bị giới hạn). Lần quét sau vẫn chạy.", key="scan_timeout")
                notes.append(f"{key}: quá thời gian, bỏ qua lần này.")
                continue
            for f in found:
                await publish(bot, f)
            secs = (datetime.now(timezone.utc) - t0).total_seconds()
            log.info("Quét xong trong %.0fs: %s, phát %d tín hiệu", secs, note, len(found))
            notes.append(f"{note}. Phát {len(found)} tín hiệu ({secs:.0f}s).")
    return "\n".join(notes)


# ---------------------------------------------------------------- 🎯 tín hiệu chỉ báo Swing (coin tự chọn)
_ind_lock = asyncio.Lock()


async def _ind_recipients(tf: str) -> dict[str, list[dict]]:
    """{symbol: [người dùng]} — người bật 🎯 đúng khung `tf`, coin nằm trong danh sách tự chọn theo chế độ của họ."""
    users = {u["chat_id"]: u for u in await storage.subscribers() if u.get("ind_tf") == tf}
    out: dict[str, list[dict]] = {}
    for r in await storage.all_user_coins():
        if r["chat_id"] in users:
            out.setdefault(r["symbol"], []).append(users[r["chat_id"]])
    return out


async def run_indicator(bot: Bot, tf: str) -> str:
    """Nến khung `tf` vừa đóng -> tính chỉ báo trên các coin có người bật 🎯, đủ điều kiện thì gửi."""
    from app.strategy import indicator
    if _ind_lock.locked():
        return "đang chạy"
    async with _ind_lock:
        targets = await _ind_recipients(tf)
        if not targets:
            return "không có ai bật 🎯"
        style = f"ind{tf}"
        busy = {s["symbol"] for s in await storage.open_signals() if s.get("style") == style}
        btc_mid = await binance.klines("BTCUSDT", indicator.TFS[tf][1], 300)
        coins = {c.symbol: c for c in await binance.universe(1000, 0)}
        sent = 0
        for sym, users in targets.items():
            if sym in busy or sym not in coins:
                continue  # đang có lệnh 🎯 cùng khung trên coin này (chỉ báo cũng chỉ mở 1 lệnh 1 lúc)
            try:
                s = await asyncio.wait_for(indicator.check(sym, tf, btc_mid), 60)
            except Exception as exc:  # noqa: BLE001
                log.info("Chỉ báo %s %s lỗi: %s", sym, tf, exc)
                continue
            if s:
                sent += await publish_indicator(bot, s, coins[sym], users)
        return f"🎯 {tf}: {len(targets)} coin, gửi {sent} tin"


async def publish_indicator(bot: Bot, s, coin: binance.Coin, users: list[dict]) -> int:
    from app.strategy import indicator
    row, created = s.row, storage.now()
    style = f"ind{s.tf}"
    hours = indicator.HOLD_BARS * (1 if s.tf == "1h" else 4)
    cb = callback_rate(float(row["atr4"]), float(row["entry"]))
    trade = Trade(s.side, row["entry"], row["sl"], created=created, deadline=created + timedelta(hours=hours),
                  exit_mode="pct", callback=cb)
    setup_text = "Setup hồi về EMA20" if row["setup_type"] == "pullback" else "Retest mốc vừa phá (volume lớn)"
    reasons = [f"Xu hướng {row['trend']:.0f}/30 · Động lượng {row['momentum']:.0f}/15 · Dòng tiền {row['flow']:.0f}/15"]
    if s.oi is not None:
        reasons.append(f"OI Binance {'24h' if s.tf == '1h' else '72h'} {s.oi:+.1%}")
    values = dict(symbol=coin.symbol, display=coin.display, side=s.side, spot_symbol=coin.spot_symbol,
                  multiplier=coin.multiplier, score=s.score, setup=row["setup_type"] or "retest", style=style,
                  tier=s.grade, source="ind", entry=row["entry"], sl=row["sl"], tp1=row["tp1"], tp2=row["tp2"],
                  zone_lo=row["zone_lo"], zone_hi=row["zone_hi"], reasons=storage.dumps(reasons), status="ACTIVE",
                  created_at=created,
                  state=storage.dumps({"trade": trade.to_dict(), "last_ts": created, "notified_stop": row["sl"]}))
    today = datetime.now(VN_TZ).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    bot_open = {(x["symbol"], x["side"]) for x in await storage.open_signals() if x.get("source") != "ind"}
    receivers = []
    for u in users:
        if u["mode"] == "spot" and (s.side < 0 or not coin.spot_symbol):
            continue  # Spot chỉ MUA coin có trên sàn spot
        got = [m for m in await storage.messages_since(u["chat_id"], today) if str(m.get("style", "")).startswith("ind")]
        if len(got) >= (u.get("ind_max") or 3):
            continue
        if (coin.symbol, s.side) in bot_open:
            continue  # bot đã có lệnh cùng coin cùng chiều -> không gửi trùng
        receivers.append(u)
    if not receivers:
        return 0
    sig_id = await storage.insert_signal(**values)
    sig = {**values, "id": sig_id, "trend": row["trend"], "setup_text": setup_text, "reasons": reasons,
           "exit_mode": "pct", "callback": cb}
    photos: dict[int, bytes] = {}
    for u in receivers:
        mult = coin.multiplier if u["mode"] == "spot" else 1
        if mult not in photos:
            photos[mult] = await asyncio.to_thread(_chart, s.base, sig, mult)
        text = texts.signal_message(sig, mode=u["mode"], risk_pct=u["risk_pct"], stats=None)
        url = tv_url(sig, u["mode"]).replace("interval=60", f"interval={'60' if s.tf == '1h' else '240'}")
        mid = await _send(bot, u["chat_id"], text, photo=photos[mult], url=url,
                          silent=bool(u.get("ind_silent")) or is_quiet_now(), why_id=sig_id)
        if mid:
            await storage.add_message(sig_id, u["chat_id"], mid)
        await asyncio.sleep(0.05)
    log.info("🎯 Chỉ báo %s %s %s điểm %.0f -> %d người", s.tf, coin.symbol, "LONG" if s.side > 0 else "SHORT",
             s.score, len(receivers))
    return len(receivers)


def is_quiet_now() -> bool:
    from app.reports import is_quiet
    return is_quiet()


async def track(bot: Bot) -> None:
    """Cập nhật các lệnh đang mở bằng nến 5 phút; báo sự kiện vào đúng tin nhắn tín hiệu gốc."""
    for sig in await storage.open_signals():
        try:
            await _track_one(bot, sig)
        except Exception as exc:  # noqa: BLE001
            log.warning("Theo dõi #%s lỗi: %s", sig["id"], exc)


_btc_cache: dict[int, float | None] = {}


async def _close_summary(sig: dict, trade: Trade, risk_pct: float) -> str:
    created = sig["created_at"]
    hours = ((trade.closed_at or storage.now()) - created).total_seconds() / 3600
    if sig["id"] not in _btc_cache:
        btc = None
        if sig["symbol"] != "BTCUSDT":
            try:
                k = await binance.klines_since("BTCUSDT", "1h", int(created.timestamp() * 1000))
                btc = float(k["close"].iloc[-1] / k["open"].iloc[0] - 1) if len(k) else None
            except Exception:  # noqa: BLE001
                btc = None
        _btc_cache[sig["id"]] = btc
    return texts.close_summary(sig, trade, risk_pct=risk_pct, hours=hours, btc_chg=_btc_cache[sig["id"]])


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
        if trade.status != "ACTIVE":
            summary = await _close_summary(sig, trade, u["risk_pct"])
            await _send(bot, m["chat_id"], summary, reply_to=m["message_id"])
