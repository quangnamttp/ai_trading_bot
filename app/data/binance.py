"""Dữ liệu công khai Binance (miễn phí, không cần API key), dự phòng bằng Bybit.

Server phải đặt ngoài Mỹ (Binance trả HTTP 451 cho IP Mỹ) -> Render region Frankfurt/Singapore.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import pandas as pd

from app.data.http import get_json

log = logging.getLogger(__name__)

FAPI = ["https://fapi.binance.com"]
SPOT = ["https://api.binance.com", "https://data-api.binance.vision", "https://api1.binance.com"]
BYBIT = "https://api.bybit.com"

INTERVAL_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000, "5m": 300_000, "15m": 900_000}
BYBIT_INTERVAL = {"1h": "60", "4h": "240", "1d": "D", "5m": "5", "15m": "15"}
STABLES = {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "USDE", "PYUSD", "RLUSD", "USD1", "XUSD", "BFUSD"}
_MULT_RE = re.compile(r"^(1000000|100000|10000|1000|1M)(.+)$")


@dataclass(frozen=True)
class Coin:
    symbol: str          # mã futures, vd 1000PEPEUSDT
    base: str            # PEPE
    multiplier: int      # 1000 với 1000PEPEUSDT (giá spot = giá futures / 1000)
    quote_volume: float  # USD 24h
    spot_symbol: str | None  # PEPEUSDT nếu có trên spot

    @property
    def display(self) -> str:
        return f"{self.base}/USDT"


def split_symbol(symbol: str) -> tuple[str, int]:
    base = symbol.removesuffix("USDT")
    m = _MULT_RE.match(base)
    if m:
        mult = 1_000_000 if m.group(1) == "1M" else int(m.group(1))
        return m.group(2), mult
    return base, 1


async def perpetual_symbols() -> set[str]:
    info = await get_json(f"{FAPI[0]}/fapi/v1/exchangeInfo", ttl=6 * 3600)
    return {
        s["symbol"] for s in info["symbols"]
        if s["status"] == "TRADING" and s["contractType"] == "PERPETUAL"
        and s["quoteAsset"] == "USDT" and s.get("underlyingType") == "COIN"
    }


async def spot_symbols() -> set[str]:
    data = await get_json([f"{h}/api/v3/ticker/price" for h in SPOT], ttl=6 * 3600)
    return {d["symbol"] for d in data if d["symbol"].endswith("USDT")}


async def universe(top_n: int, min_quote_volume: float, extra: list[str] | None = None) -> list[Coin]:
    """Top coin theo khối lượng futures 24h + các coin admin thêm vào."""
    perps = await perpetual_symbols()
    spots = await spot_symbols()
    tickers = await get_json(f"{FAPI[0]}/fapi/v1/ticker/24hr", ttl=600)
    vol = {t["symbol"]: float(t["quoteVolume"]) for t in tickers}

    def make(sym: str) -> Coin:
        base, mult = split_symbol(sym)
        spot = f"{base}USDT"
        return Coin(sym, base, mult, vol.get(sym, 0.0), spot if spot in spots else None)

    ranked = sorted(
        (s for s in perps if split_symbol(s)[0] not in STABLES and vol.get(s, 0) >= min_quote_volume),
        key=lambda s: -vol[s],
    )
    chosen = ranked[:top_n]
    for sym in extra or []:
        if sym in perps and sym not in chosen:
            chosen.append(sym)
    return [make(s) for s in chosen]


def _frame(rows: list[list], interval: str) -> pd.DataFrame:
    df = pd.DataFrame(rows).iloc[:, :11]
    df.columns = ["open_time", "open", "high", "low", "close", "volume", "close_time",
                  "quote_vol", "trades", "taker_buy_vol", "taker_buy_quote"]
    df = df.drop(columns=["close_time", "trades", "taker_buy_quote"]).astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
    df["close_time"] = df["open_time"] + pd.Timedelta(milliseconds=INTERVAL_MS[interval])
    return df.set_index("open_time")


def _drop_open_candle(df: pd.DataFrame) -> pd.DataFrame:
    now = pd.Timestamp.now(tz="UTC")
    return df[df["close_time"] <= now]


async def klines(symbol: str, interval: str, limit: int = 500, *, closed_only: bool = True) -> pd.DataFrame:
    """`limit` nến futures mới nhất (tự phân trang khi > 1500). Mặc định chỉ trả nến đã đóng."""
    try:
        frames: list[pd.DataFrame] = []
        remaining, end = limit, None
        while remaining > 0:
            params = {"symbol": symbol, "interval": interval, "limit": min(remaining, 1500)}
            if end:
                params["endTime"] = end
            rows = await get_json(f"{FAPI[0]}/fapi/v1/klines", params, ttl=50)
            if not rows:
                break
            frames.append(_frame(rows, interval))
            remaining -= len(rows)
            if len(rows) < params["limit"]:
                break
            end = int(rows[0][0]) - 1
        df = pd.concat(frames).sort_index()
        df = df[~df.index.duplicated()]
    except Exception as exc:  # noqa: BLE001
        log.warning("Binance klines %s %s lỗi (%s) -> thử Bybit", symbol, interval, exc)
        df = await _bybit_klines(symbol, interval, min(limit, 1000))
    return _drop_open_candle(df) if closed_only else df


async def klines_since(symbol: str, interval: str, start_ms: int) -> pd.DataFrame:
    """Toàn bộ nến đã đóng từ `start_ms` tới nay (dùng cho backtest và theo dõi lệnh)."""
    frames: list[pd.DataFrame] = []
    start = start_ms
    while True:
        rows = await get_json(f"{FAPI[0]}/fapi/v1/klines",
                              {"symbol": symbol, "interval": interval, "limit": 1500, "startTime": start}, ttl=50)
        if not rows:
            break
        frames.append(_frame(rows, interval))
        if len(rows) < 1500:
            break
        start = int(rows[-1][0]) + 1
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames).sort_index()
    return _drop_open_candle(df[~df.index.duplicated()])


async def _bybit_klines(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    data = await get_json(f"{BYBIT}/v5/market/kline",
                          {"category": "linear", "symbol": symbol, "interval": BYBIT_INTERVAL[interval], "limit": limit})
    rows = data["result"]["list"][::-1]  # Bybit trả mới nhất trước
    df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume", "quote_vol"]).astype(float)
    df["taker_buy_vol"] = df["volume"] * 0.5  # Bybit không có -> trung tính
    df["open_time"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
    df["close_time"] = df["open_time"] + pd.Timedelta(milliseconds=INTERVAL_MS[interval])
    return df.set_index("open_time")


async def last_price(symbol: str) -> float:
    d = await get_json(f"{FAPI[0]}/fapi/v1/ticker/price", {"symbol": symbol}, ttl=5)
    return float(d["price"])


async def funding_history(symbol: str, start_ms: int | None = None) -> pd.Series:
    params = {"symbol": symbol, "limit": 1000}
    if start_ms:
        params["startTime"] = start_ms
    rows = await get_json(f"{FAPI[0]}/fapi/v1/fundingRate", params, ttl=1800)
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series([float(r["fundingRate"]) for r in rows],
                  index=pd.to_datetime([int(r["fundingTime"]) for r in rows], unit="ms", utc=True))
    return s.sort_index()


async def derivatives_snapshot(symbol: str) -> dict:
    """Dòng tiền phái sinh hiện tại: funding, OI 24h, tỉ lệ L/S, taker buy/sell."""
    out: dict = {}
    try:
        prem = await get_json(f"{FAPI[0]}/fapi/v1/premiumIndex", {"symbol": symbol}, ttl=300)
        out["funding"] = float(prem["lastFundingRate"])
    except Exception as exc:  # noqa: BLE001
        log.debug("funding %s: %s", symbol, exc)
    try:
        oi = await get_json(f"{FAPI[0]}/futures/data/openInterestHist",
                            {"symbol": symbol, "period": "1h", "limit": 25}, ttl=600)
        if len(oi) >= 2:
            first, last = float(oi[0]["sumOpenInterestValue"]), float(oi[-1]["sumOpenInterestValue"])
            out["oi_change_24h"] = (last - first) / first if first else 0.0
    except Exception as exc:  # noqa: BLE001
        log.debug("OI %s: %s", symbol, exc)
    try:
        ls = await get_json(f"{FAPI[0]}/futures/data/globalLongShortAccountRatio",
                            {"symbol": symbol, "period": "1h", "limit": 1}, ttl=600)
        out["global_ls"] = float(ls[-1]["longShortRatio"])
        top = await get_json(f"{FAPI[0]}/futures/data/topLongShortPositionRatio",
                             {"symbol": symbol, "period": "1h", "limit": 1}, ttl=600)
        out["top_ls"] = float(top[-1]["longShortRatio"])
    except Exception as exc:  # noqa: BLE001
        log.debug("L/S %s: %s", symbol, exc)
    return out
