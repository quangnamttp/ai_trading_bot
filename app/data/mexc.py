"""Dữ liệu công khai MEXC Futures (miễn phí) — nguồn dự phòng thứ 3 (sau Binance, Bybit) + giá cho người giao dịch MEXC.

MEXC không có lịch sử OI / long-short, không có khối lượng mua chủ động -> chỉ dùng cho giá / nến / funding.
Mã: Binance "SOLUSDT" -> MEXC "SOL_USDT"; coin kiểu 1000PEPE trên MEXC tính theo 1 coin -> nhân hệ số để khớp Binance.
"""
from __future__ import annotations

import logging

import pandas as pd

from app.data.http import get_json

log = logging.getLogger(__name__)

BASE = "https://contract.mexc.com/api/v1/contract"
INTERVAL = {"5m": "Min5", "15m": "Min15", "1h": "Min60", "4h": "Hour4", "1d": "Day1", "1w": "Week1"}
MS = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000, "1w": 604_800_000}


def to_mexc(symbol: str) -> tuple[str, int]:
    """(mã MEXC, hệ số): 1000PEPEUSDT -> ('PEPE_USDT', 1000)."""
    from app.data.binance import split_symbol
    base, mult = split_symbol(symbol)
    return f"{base}_USDT", mult


async def klines(symbol: str, interval: str, limit: int = 500, start_ms: int | None = None) -> pd.DataFrame:
    """Nến theo định dạng giống Binance (giá đã nhân hệ số, volume tính theo đơn vị coin của Binance)."""
    sym, mult = to_mexc(symbol)
    step = MS[interval]
    now_s = int(pd.Timestamp.now(tz="UTC").timestamp())
    start_s = start_ms // 1000 if start_ms else now_s - (limit + 2) * step // 1000
    data = (await get_json(f"{BASE}/kline/{sym}", {"interval": INTERVAL[interval], "start": start_s, "end": now_s},
                           ttl=50))["data"]
    if not data or not data.get("time"):
        return pd.DataFrame()
    df = pd.DataFrame({"open_time": data["time"], "open": data["open"], "high": data["high"], "low": data["low"],
                       "close": data["close"], "quote_vol": data["amount"]}).astype(float)
    for k in ("open", "high", "low", "close"):
        df[k] *= mult
    df["volume"] = df["quote_vol"] / df["close"].where(df["close"] > 0)
    df["taker_buy_vol"] = df["volume"] * 0.5  # MEXC không có -> trung tính
    df["open_time"] = pd.to_datetime(df["open_time"].astype("int64"), unit="s", utc=True)
    df["close_time"] = df["open_time"] + pd.Timedelta(milliseconds=step)
    return df.set_index("open_time").iloc[-limit:]


async def tickers() -> dict[str, dict]:
    """{mã Binance: ticker định dạng Binance} cho các hợp đồng USDT của MEXC."""
    rows = (await get_json(f"{BASE}/ticker", ttl=60))["data"]
    out = {}
    for t in rows:
        s = t.get("symbol", "")
        if not s.endswith("_USDT"):
            continue
        base = s[:-5]
        price = float(t.get("lastPrice") or 0)
        row = {"lastPrice": str(price), "priceChangePercent": str(float(t.get("riseFallRate") or 0) * 100),
               "quoteVolume": str(t.get("amount24") or 0), "fundingRate": float(t.get("fundingRate") or 0),
               "mexc_price": price}
        out[f"{base}USDT"] = {**row, "symbol": f"{base}USDT"}
        # coin kiểu 1000PEPE: Binance tính theo 1000 coin
        out[f"1000{base}USDT"] = {**row, "symbol": f"1000{base}USDT", "lastPrice": str(price * 1000)}
    return out


async def price(symbol: str) -> float | None:
    """Giá 1 coin thật trên MEXC Futures (không nhân hệ số) — hiển thị cho người giao dịch MEXC."""
    try:
        sym, _ = to_mexc(symbol)
        d = (await get_json(f"{BASE}/ticker", {"symbol": sym}, ttl=15, retries=1))["data"]
        return float(d["lastPrice"])
    except Exception as exc:  # noqa: BLE001
        log.debug("Giá MEXC %s: %s", symbol, exc)
        return None
