"""Quét thị trường và chọn tín hiệu tốt nhất theo chính sách, cho 2 kiểu giao dịch:

- Swing ngắn (short): nến 1H (setup) / 4H (xu hướng) / 1D (bối cảnh), quét mỗi giờ, giữ lệnh tối đa 7 ngày.
- Swing dài  (long) : nến 4H / 1D / 1W, quét mỗi 4 giờ khi nến 4H đóng, giữ lệnh tối đa 30 ngày.

Hai kiểu dùng CÙNG chiến lược (core.py), chỉ khác khung thời gian — đã backtest riêng từng kiểu.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from app import storage
from app.config import VN_TZ, settings
from app.data import binance, bybit, macro, news
from app.strategy.core import Candidate, apply_live_context, best_candidate, build_features, score_frame

log = logging.getLogger(__name__)
CALIBRATION = Path(__file__).parent / "calibration.json"
LIVE_BONUS_MAX = 2  # điểm tối đa dữ liệu live (tin tức, thanh khoản) có thể cộng thêm
MAX_USER_SIGNALS_PER_SCAN = 3
MAX_SCAN_COINS = 60  # giới hạn tổng số coin quét (Render gói miễn phí), ưu tiên coin nhiều người theo dõi
TIER_B = 70         # hạng B (swing ngắn): chỉ dùng sau WATCH_REPORT_HOUR nếu cả ngày chưa có tín hiệu


@dataclass(frozen=True)
class Style:
    key: str
    label: str
    tfs: tuple[str, str, str]      # (setup, xu hướng, bối cảnh)
    bars: tuple[int, int, int]
    cooldown: timedelta
    hold_hours: int
    oi_hours: int                  # cửa sổ tính thay đổi OI
    default_threshold: float
    night_silent: bool             # giờ yên lặng: True = vẫn gửi nhưng không chuông, False = không gửi


# Thông số chọn theo backtest 2 năm / 40 coin (xem README):
STYLES = {
    "short": Style("short", "⚡ Swing ngắn", ("1h", "4h", "1d"), (400, 300, 200), timedelta(hours=12),
                   settings.max_hold_hours, 24, 75, night_silent=False),
    # nến 4H đóng lúc 23h/3h sáng cho tín hiệu tốt; setup 4H kéo dài nhiều giờ nên gửi im lặng để sáng xem
    "long": Style("long", "🌙 Swing dài", ("4h", "1d", "1w"), (400, 300, 160), timedelta(hours=72),
                  settings.long_max_hold_hours, 72, 70, night_silent=True),
}


@dataclass
class Found:
    candidate: Candidate
    coin: binance.Coin
    h1: pd.DataFrame           # nến khung setup (để vẽ biểu đồ)
    style: Style
    tier: str = "A"
    silent: bool = False       # gửi không chuông (swing dài ban đêm)
    source: str = "top"        # top = Top 20 (đã backtest) · user = coin tự chọn của người dùng


def calibration() -> dict:
    try:
        return json.loads(CALIBRATION.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def threshold(style: str = "short") -> float:
    cal = calibration().get("styles", {}).get(style, {})
    return float(cal.get("threshold", STYLES[style].default_threshold))


def bucket_stats(score: float, style: str = "short") -> dict | None:
    """Thống kê backtest của nhóm điểm chứa `score` (hoặc nhóm thấp hơn gần nhất)."""
    cal = calibration()
    buckets = cal.get("styles", {}).get(style, {}).get("buckets") or cal.get("buckets", {})
    for k in sorted((int(k) for k in buckets), reverse=True):
        if score >= k:
            return buckets[str(k)]
    return None


def is_quiet(now: datetime | None = None) -> bool:
    h = (now or datetime.now(VN_TZ)).astimezone(VN_TZ).hour
    s, e = settings.quiet_start, settings.quiet_end
    return (h >= s or h < e) if s > e else (s <= h < e)


async def live_derivs(symbol: str, oi_hours: int) -> dict:
    """Funding (Binance) + thay đổi OI & tỉ lệ long/short (Bybit — cùng nguồn với backtest)."""
    out = await binance.derivatives_snapshot(symbol)
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    start = now - (oi_hours + 12) * 3_600_000
    oi, ls = await asyncio.gather(bybit.open_interest(symbol, start, now), bybit.long_short(symbol, start, now))
    if len(oi) >= 2:
        ref = oi[oi.index <= oi.index[-1] - pd.Timedelta(hours=oi_hours)]
        if len(ref):
            out["oi_chg"] = float(oi.iloc[-1] / ref.iloc[-1] - 1)
    if len(ls):
        out["ls"] = float(ls.iloc[-1])
    return out


async def _analyze(coin: binance.Coin, style: Style, btc_mid: pd.DataFrame | None,
                   fng: pd.Series) -> tuple[Candidate | None, pd.DataFrame, dict]:
    b, m, h = style.tfs
    start = int((datetime.now(timezone.utc) - timedelta(days=30)).timestamp() * 1000)
    base, mid, high, funding = await asyncio.gather(
        binance.klines(coin.symbol, b, style.bars[0]), binance.klines(coin.symbol, m, style.bars[1]),
        binance.klines(coin.symbol, h, style.bars[2]), binance.funding_history(coin.symbol, start),
    )
    # tính toán nặng (pandas) chạy ở luồng riêng để bot vẫn trả lời tin nhắn / health check trong lúc quét
    scores = await asyncio.to_thread(
        lambda: score_frame(build_features(base, mid, high, btc_h4=btc_mid, fng=fng, funding=funding)))
    return best_candidate(coin.symbol, scores), base, scores


async def _eligible_coins(with_user: bool = False) -> tuple[list[binance.Coin], set[str]]:
    """(danh sách coin cần quét, tập mã Top N). Top N bỏ coin niêm yết < 90 ngày; coin người dùng tự chọn thì giữ
    nguyên (họ chủ động chọn). Tổng số coin giới hạn MAX_SCAN_COINS, ưu tiên coin nhiều người theo dõi."""
    coins = await binance.universe(settings.top_n, settings.min_quote_volume, await storage.get_watchlist())
    listed = await binance.listing_dates()
    now = pd.Timestamp.now(tz="UTC")
    min_age = pd.Timedelta(days=settings.min_listing_days)
    top = [c for c in coins if c.symbol not in listed or now - listed[c.symbol] >= min_age]
    top_syms = {c.symbol for c in top}
    if not with_user:
        return top, top_syms
    counts: dict[str, int] = {}
    for r in await storage.all_user_coins():
        counts[r["symbol"]] = counts.get(r["symbol"], 0) + 1
    extra = sorted((s for s in counts if s not in top_syms), key=lambda s: -counts[s])
    extra = extra[:max(0, MAX_SCAN_COINS - len(top))]
    if extra:
        allc = {c.symbol: c for c in await binance.universe(1000, 0)}
        top += [allc[s] for s in extra if s in allc]
    return top, top_syms


async def analyze_symbol(symbol: str, style_key: str = "short") -> dict:
    """Phân tích chi tiết 1 coin theo yêu cầu người dùng (kể cả khi không có tín hiệu)."""
    style = STYLES[style_key]
    coins = {c.symbol: c for c in await binance.universe(1000, 0)}
    coin = coins.get(symbol)
    if coin is None:
        raise ValueError(f"{symbol} không có trên Binance Futures")
    btc_mid = None if symbol == "BTCUSDT" else await binance.klines("BTCUSDT", style.tfs[1], style.bars[1])
    fng = await macro.fear_greed_history()
    cand, base, scores = await _analyze(coin, style, btc_mid, fng)
    rows = {side: df.iloc[-1].to_dict() for side, df in scores.items()}
    deriv = await live_derivs(symbol, style.oi_hours)
    items = await news.headlines(24)
    cn = news.coin_news(coin.base, items)
    if cand is not None:
        cand = apply_live_context(cand, deriv, coin_news=cn, market_news=news.market_sentiment(items),
                                  stable_7d=await macro.stablecoin_change_7d(), style=style_key)
    return {"coin": coin, "candidate": cand, "rows": rows, "deriv": deriv, "news": cn, "h1": base,
            "threshold": threshold(style_key), "style": style}


async def _open_state() -> tuple[list[dict], dict[int, int]]:
    open_now = await storage.open_signals()
    by_side: dict[int, int] = {1: 0, -1: 0}
    for s in open_now:
        by_side[s["side"]] = by_side.get(s["side"], 0) + 1
    return open_now, by_side


async def scan(style_key: str = "short", *, force: bool = False) -> tuple[list[Found], str]:
    """Trả về (tín hiệu mới, ghi chú). `force=True` (admin /scan) bỏ qua giờ yên lặng."""
    style = STYLES[style_key]
    quiet = is_quiet() and not force
    if quiet and not style.night_silent:
        return [], f"{style.label}: giờ yên lặng — không phát tín hiệu mới"
    ev = await macro.event_blackout()
    if ev:
        return [], f"{style.label}: tạm dừng, sắp có tin vĩ mô Mỹ «{ev['title']}» lúc {ev['time'].astimezone(VN_TZ):%H:%M %d/%m}"

    th = threshold(style_key)
    th_min = th
    if style_key == "short":
        since = datetime.now(VN_TZ).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        cap = settings.max_signals_per_day
    else:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        cap = settings.long_max_per_week
    sent = [s for s in await storage.signals_since(since) if s.get("style", "short") == style_key]
    open_now, by_side = await _open_state()
    sent = [s for s in sent if s.get("source", "top") == "top"]
    room = max(0, min(settings.max_signals_per_scan, cap - len(sent), settings.max_open_signals - len(open_now)))
    # hạng B: swing ngắn, sau giờ WATCH_REPORT_HOUR mà cả ngày chưa có tín hiệu -> hạ ngưỡng (đã backtest: vẫn có lời)
    tier_b = style_key == "short" and not sent and datetime.now(VN_TZ).hour >= settings.watch_report_hour
    if tier_b:
        th_min = min(th, TIER_B)

    coins, top_syms = await _eligible_coins(with_user=True)
    busy = {s["symbol"] for s in open_now}
    btc_mid = await binance.klines("BTCUSDT", style.tfs[1], style.bars[1])
    fng = await macro.fear_greed_history()
    bar = pd.Timedelta(milliseconds=binance.INTERVAL_MS[style.tfs[0]])

    async def one(coin: binance.Coin) -> Found | None:
        if coin.symbol in busy:
            return None
        last = await storage.last_signal_time(coin.symbol)
        if last and datetime.now(timezone.utc) - last < style.cooldown:
            return None
        try:
            cand, base, _ = await _analyze(coin, style, None if coin.symbol == "BTCUSDT" else btc_mid, fng)
        except Exception as exc:  # noqa: BLE001
            log.warning("Phân tích %s lỗi: %s", coin.symbol, exc)
            return None
        # nến setup cuối phải là nến vừa đóng (tránh dữ liệu cũ khi API trễ)
        if cand is None or pd.Timestamp.now(tz="UTC") - base["close_time"].iloc[-1] > bar + pd.Timedelta(minutes=5):
            return None
        return Found(cand, coin, base, style, silent=quiet) if cand.score >= th_min - LIVE_BONUS_MAX else None

    pre = [f for f in await asyncio.gather(*(one(c) for c in coins)) if f]
    await storage.kv_set("last_scan_ok", datetime.now(timezone.utc).isoformat())
    if not pre:
        return [], f"{style.label}: không có setup đạt chuẩn trong {len(coins)} coin"

    items = await news.headlines(24)
    mkt = news.market_sentiment(items)
    stable = await macro.stablecoin_change_7d()
    final = []
    for f in pre:
        deriv = await live_derivs(f.coin.symbol, style.oi_hours)
        apply_live_context(f.candidate, deriv, coin_news=news.coin_news(f.coin.base, items), market_news=mkt,
                           stable_7d=stable, style=style_key)
        if f.candidate.vetoed:
            log.info("Chặn %s: %s", f.coin.symbol, f.candidate.vetoed)
            if f.candidate.vetoed.startswith("Tin"):
                await storage.log_news_block(f.coin.symbol, f.candidate.side, float(f.candidate.row["entry"]),
                                             f.candidate.vetoed)
        elif f.candidate.score >= th_min:
            f.tier = "A" if f.candidate.score >= th else "B"
            final.append(f)
    final.sort(key=lambda f: -f.candidate.score)
    if tier_b and any(f.tier == "A" for f in final):
        final = [f for f in final if f.tier == "A"]

    chosen = []
    for f in final:
        if f.coin.symbol not in top_syms:
            continue
        if len(chosen) >= room:
            break
        if by_side.get(f.candidate.side, 0) >= settings.max_same_direction:
            continue  # đã đủ lệnh cùng chiều -> tránh dồn rủi ro khi cả thị trường đảo chiều
        by_side[f.candidate.side] = by_side.get(f.candidate.side, 0) + 1
        chosen.append(f)
    # coin tự chọn: không chiếm giới hạn của Top N (chính sách đã backtest); mỗi người tự giới hạn số tín hiệu nhận
    user_found = [f for f in final if f.coin.symbol not in top_syms][:MAX_USER_SIGNALS_PER_SCAN]
    for f in user_found:
        f.source = "user"
    chosen += user_found
    return chosen, f"{style.label}: {len(pre)} ứng viên, {len(final)} đạt ngưỡng {th_min:.0f}"


async def watch_candidates(limit: int = 5, style_key: str = "short") -> list[str]:
    """Coin đang hình thành setup nhưng CHƯA đủ điểm — để người dùng chủ động theo dõi (không phải tín hiệu)."""
    style = STYLES[style_key]
    th = threshold(style_key)
    coins, _ = await _eligible_coins()
    btc_mid = await binance.klines("BTCUSDT", style.tfs[1], style.bars[1])
    fng = await macro.fear_greed_history()
    out = []

    async def one(coin: binance.Coin) -> None:
        try:
            _, _, scores = await _analyze(coin, style, None if coin.symbol == "BTCUSDT" else btc_mid, fng)
        except Exception:  # noqa: BLE001
            return
        for side, df in scores.items():
            r = df.iloc[-1]
            # có setup + đúng xu hướng, điểm thô gần ngưỡng
            if r["setup"] > 0 and r["trend"] >= 15 and th - 12 <= r["raw"] < th + LIVE_BONUS_MAX:
                out.append((r["raw"], coin.display, side, r))

    await asyncio.gather(*(one(c) for c in coins))
    out.sort(key=lambda x: -x[0])
    return [f"{'🟢' if side > 0 else '🔴'} {name} {'LONG' if side > 0 else 'SHORT'} · điểm {raw:.0f}/{th:.0f} "
            f"· giá {r['entry']:.6g}" for raw, name, side, r in out[:limit]]
