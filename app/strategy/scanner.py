"""Quét thị trường mỗi giờ (sau khi nến 1H đóng) và chọn tín hiệu tốt nhất theo chính sách."""
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
from app.data import binance, macro, news
from app.strategy.core import Candidate, apply_live_context, best_candidate, build_features, score_frame

log = logging.getLogger(__name__)
COOLDOWN = timedelta(hours=12)
CALIBRATION = Path(__file__).parent / "calibration.json"
LIVE_BONUS_MAX = 5  # điểm tối đa dữ liệu live có thể cộng thêm


@dataclass
class Found:
    candidate: Candidate
    coin: binance.Coin
    h1: pd.DataFrame


def calibration() -> dict:
    try:
        return json.loads(CALIBRATION.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def threshold() -> float:
    return float(calibration().get("threshold", settings.score_threshold))


def bucket_stats(score: float) -> dict | None:
    """Thống kê backtest của nhóm điểm chứa `score` (hoặc nhóm thấp hơn gần nhất)."""
    buckets = calibration().get("buckets", {})
    keys = sorted((int(k) for k in buckets), reverse=True)
    for k in keys:
        if score >= k:
            return buckets[str(k)]
    return None


async def _analyze(coin: binance.Coin, btc_h4: pd.DataFrame | None, fng: pd.Series) -> tuple[Candidate | None, pd.DataFrame, dict]:
    start = int((datetime.now(timezone.utc) - timedelta(days=20)).timestamp() * 1000)
    h1, h4, d1, funding = await asyncio.gather(
        binance.klines(coin.symbol, "1h", 400), binance.klines(coin.symbol, "4h", 300),
        binance.klines(coin.symbol, "1d", 200), binance.funding_history(coin.symbol, start),
    )
    f = build_features(h1, h4, d1, btc_h4=btc_h4, fng=fng, funding=funding)
    scores = score_frame(f)
    return best_candidate(coin.symbol, scores), h1, scores


async def analyze_symbol(symbol: str) -> dict:
    """Phân tích chi tiết 1 coin theo yêu cầu người dùng (kể cả khi không có tín hiệu)."""
    coins = {c.symbol: c for c in await binance.universe(500, 0)}
    coin = coins.get(symbol)
    if coin is None:
        raise ValueError(f"{symbol} không có trên Binance Futures")
    btc_h4 = None if symbol == "BTCUSDT" else await binance.klines("BTCUSDT", "4h", 300)
    fng = await macro.fear_greed_history()
    cand, h1, scores = await _analyze(coin, btc_h4, fng)
    rows = {side: df.iloc[-1].to_dict() for side, df in scores.items()}
    deriv = await binance.derivatives_snapshot(symbol)
    items = await news.headlines(24)
    cn = news.coin_news(coin.base, items)
    if cand is not None:
        cand = apply_live_context(cand, deriv, coin_news=cn, market_news=news.market_sentiment(items),
                                  stable_7d=await macro.stablecoin_change_7d())
    return {"coin": coin, "candidate": cand, "rows": rows, "deriv": deriv, "news": cn, "h1": h1,
            "threshold": threshold()}


async def scan() -> tuple[list[Found], str]:
    """Trả về (danh sách tín hiệu mới, ghi chú). Tôn trọng giới hạn ngày / mỗi lần quét / lệnh mở."""
    ev = await macro.event_blackout()
    if ev:
        return [], f"Tạm dừng: sắp có tin vĩ mô Mỹ «{ev['title']}» lúc {ev['time'].astimezone(VN_TZ):%H:%M %d/%m}"

    th = threshold()
    today_vn = datetime.now(VN_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    sent_today = len(await storage.signals_since(today_vn.astimezone(timezone.utc)))
    open_now = await storage.open_signals()
    room = min(settings.max_signals_per_scan, settings.max_signals_per_day - sent_today,
               settings.max_open_signals - len(open_now))
    if room <= 0:
        return [], f"Đã đủ giới hạn (hôm nay {sent_today}, đang mở {len(open_now)})"

    coins = await binance.universe(settings.top_n, settings.min_quote_volume, await storage.get_watchlist())
    busy = {s["symbol"] for s in open_now}
    btc_h4 = await binance.klines("BTCUSDT", "4h", 300)
    fng = await macro.fear_greed_history()

    async def one(coin: binance.Coin) -> Found | None:
        if coin.symbol in busy:
            return None
        last = await storage.last_signal_time(coin.symbol)
        if last and datetime.now(timezone.utc) - last < COOLDOWN:
            return None
        try:
            cand, h1, _ = await _analyze(coin, None if coin.symbol == "BTCUSDT" else btc_h4, fng)
        except Exception as exc:  # noqa: BLE001
            log.warning("Phân tích %s lỗi: %s", coin.symbol, exc)
            return None
        # nến 1H cuối phải là nến vừa đóng (tránh dữ liệu cũ khi API trễ)
        if cand is None or datetime.now(timezone.utc) - h1["close_time"].iloc[-1] > timedelta(minutes=65):
            return None
        return Found(cand, coin, h1) if cand.score >= th - LIVE_BONUS_MAX else None

    pre = [f for f in await asyncio.gather(*(one(c) for c in coins)) if f]
    if not pre:
        return [], f"Không có setup đạt chuẩn trong {len(coins)} coin"

    items = await news.headlines(24)
    mkt = news.market_sentiment(items)
    stable = await macro.stablecoin_change_7d()
    final = []
    for f in pre:
        deriv = await binance.derivatives_snapshot(f.coin.symbol)
        apply_live_context(f.candidate, deriv, coin_news=news.coin_news(f.coin.base, items), market_news=mkt, stable_7d=stable)
        if f.candidate.vetoed:
            log.info("Chặn %s: %s", f.coin.symbol, f.candidate.vetoed)
        elif f.candidate.score >= th:
            final.append(f)
    final.sort(key=lambda f: -f.candidate.score)
    return final[:room], f"{len(pre)} ứng viên, {len(final)} đạt ngưỡng {th:.0f}"
