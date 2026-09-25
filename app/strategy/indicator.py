"""🎯 Tín hiệu chỉ báo Swing Entry Pro (bản Python giống hệt Pine) cho coin người dùng tự chọn.

Khác tín hiệu chính của bot: dòng tiền ước lượng từ nến (như TradingView), không dùng funding / Fear & Greed /
long-short; lọc OI Binance >= 5% (24h với khung 1H, 72h với khung 4H); bỏ Pullback LONG; ngưỡng 75 điểm.
Đã đối chiếu PEPE 1H 18–22/09: trùng với chart TradingView.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.data import binance
from app.data.http import get_json
from app.strategy.core import build_features, poc_veto, score_frame

log = logging.getLogger(__name__)

THRESHOLD = 75.0
OI_MIN = 0.05
TFS = {"1h": ("1h", "4h", "1d", 24), "4h": ("4h", "1d", "1w", 72)}  # (khung tín hiệu, giữa, lớn, giờ tính OI)
# v6 (backtest 9 năm / 50 coin): 1H cần OI >= 5% (tốt hơn 6/6 năm); 4H ngưỡng 70, không lọc OI (OI không ổn định ở 4H)
RULES = {"1h": (75.0, True), "4h": (70.0, False)}  # khung -> (ngưỡng điểm, có lọc OI)
HOLD_BARS = 168  # giữ lệnh tối đa 168 nến khung tín hiệu (như chỉ báo)


def ohlc_flow(df: pd.DataFrame) -> pd.DataFrame:
    """Ước lượng volume mua chủ động từ vị trí giá đóng trong nến (cách chỉ báo TradingView làm)."""
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    d = df.copy()
    d["taker_buy_vol"] = (df["volume"] * (df["close"] - df["low"]) / rng).fillna(df["volume"] / 2)
    return d


async def oi_change(symbol: str, hours: int) -> float | None:
    """Thay đổi OI Binance trong `hours` giờ (cùng nguồn OI mà chỉ báo lấy trên TradingView)."""
    try:
        rows = await get_json(f"{binance.FAPI[0]}/futures/data/openInterestHist",
                              {"symbol": symbol, "period": "1h", "limit": hours + 1}, ttl=600)
        first, last = float(rows[0]["sumOpenInterest"]), float(rows[-1]["sumOpenInterest"])
        return last / first - 1 if first else None
    except Exception as exc:  # noqa: BLE001
        log.debug("OI chỉ báo %s: %s", symbol, exc)
        return None


@dataclass
class IndSignal:
    symbol: str
    tf: str
    side: int
    score: float
    grade: str
    row: dict
    oi: float | None
    base: pd.DataFrame


def pick(scores: dict[int, pd.DataFrame], oi: float | None, threshold: float = THRESHOLD,
         use_oi: bool = True) -> tuple[int, dict] | None:
    """Nến vừa đóng có tín hiệu không (điều kiện giống chỉ báo). Trả (phía, dòng điểm) hoặc None."""
    if use_oi and oi is not None and abs(oi) < OI_MIN:
        return None
    best = None
    for side, df in scores.items():
        row = df.iloc[-1].to_dict()
        if row["score"] < threshold or (side > 0 and row["setup_type"] == "pullback"):
            continue
        if best is None or row["score"] > best[1]["score"]:
            best = (side, row)
    return best


async def check(symbol: str, tf: str, btc_mid: pd.DataFrame | None) -> IndSignal | None:
    b, m, h, oi_hours = TFS[tf]
    base = await binance.klines(symbol, b, 500)
    mid = await binance.klines(symbol, m, 300)
    high = await binance.klines(symbol, h, 200)
    bar = pd.Timedelta(milliseconds=binance.INTERVAL_MS[b])
    if not len(base) or pd.Timestamp.now(tz="UTC") - base["close_time"].iloc[-1] > bar + pd.Timedelta(minutes=10):
        return None  # dữ liệu chưa có nến vừa đóng
    f = build_features(ohlc_flow(base), mid, high, btc_h4=None if symbol == "BTCUSDT" else btc_mid)
    oi = await oi_change(symbol, oi_hours)
    th, use_oi = RULES[tf]
    got = pick(score_frame(f), oi, th, use_oi)
    if not got:
        return None
    side, row = got
    if poc_veto(base, side, float(row["entry"])):
        return None
    grade = "A" if row["score"] >= 85 or (oi is not None and abs(oi) >= 0.10) else "B"
    return IndSignal(symbol, tf, side, float(row["score"]), grade, row, oi, base)
