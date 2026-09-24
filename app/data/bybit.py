"""Lịch sử Open Interest và tỉ lệ long/short từ Bybit (miễn phí, có dữ liệu nhiều năm).

Binance chỉ lưu OI/long-short 30 ngày nên không backtest được; Bybit là thị trường phái sinh lớn thứ 2,
dòng tiền tương quan cao với Binance. Bot live và backtest dùng CÙNG nguồn này để kết quả khớp nhau.
"""
from __future__ import annotations

import logging

import pandas as pd

from app.data.http import get_json

log = logging.getLogger(__name__)
BASE = "https://api.bybit.com/v5/market"
STEP_MS = {"1h": 3_600_000, "4h": 14_400_000}


async def _paged(path: str, params: dict, start_ms: int, end_ms: int, step_ms: int, limit: int) -> list[dict]:
    rows: list[dict] = []
    t = start_ms
    while t < end_ms:
        chunk_end = min(end_ms, t + step_ms * limit)
        data = await get_json(f"{BASE}/{path}", {**params, "startTime": t, "endTime": chunk_end, "limit": limit}, ttl=300)
        rows += data.get("result", {}).get("list", [])
        t = chunk_end + 1
    return rows


async def open_interest(symbol: str, start_ms: int, end_ms: int, interval: str = "4h") -> pd.Series:
    """Giá trị OI (số coin) theo thời gian."""
    try:
        rows = await _paged("open-interest", {"category": "linear", "symbol": symbol, "intervalTime": interval},
                            start_ms, end_ms, STEP_MS[interval], 200)
    except Exception as exc:  # noqa: BLE001
        log.debug("Bybit OI %s: %s", symbol, exc)
        return pd.Series(dtype=float)
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series({pd.Timestamp(int(r["timestamp"]), unit="ms", tz="UTC"): float(r["openInterest"]) for r in rows})
    return s[~s.index.duplicated()].sort_index()


async def long_short(symbol: str, start_ms: int, end_ms: int, interval: str = "4h") -> pd.Series:
    """Tỉ lệ tài khoản long / short."""
    try:
        rows = await _paged("account-ratio", {"category": "linear", "symbol": symbol, "period": interval},
                            start_ms, end_ms, STEP_MS[interval], 500)
    except Exception as exc:  # noqa: BLE001
        log.debug("Bybit L/S %s: %s", symbol, exc)
        return pd.Series(dtype=float)
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series({pd.Timestamp(int(r["timestamp"]), unit="ms", tz="UTC"):
                   float(r["buyRatio"]) / max(1e-9, float(r["sellRatio"])) for r in rows})
    return s[~s.index.duplicated()].sort_index()
