"""Dữ liệu công khai Binance (miễn phí, không cần API key), dự phòng bằng Bybit.

Khi Binance giới hạn tần suất (Render dùng chung IP) -> lấy ngay từ Bybit, Bybit lỗi -> MEXC, không đứng chờ.
Nến được giữ trong bộ nhớ: lần sau chỉ tải thêm nến mới (vài nến) thay vì tải lại 500 nến -> ít request hơn nhiều.

Server phải đặt ngoài Mỹ (Binance trả HTTP 451 cho IP Mỹ) -> Render region Frankfurt/Singapore.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import pandas as pd

from app.data.http import get_json

_kcache: dict[tuple[str, str], pd.DataFrame] = {}
_last_perps: set[str] = set()
KCACHE_MAX = 1600

log = logging.getLogger(__name__)

FAPI = ["https://fapi.binance.com"]
SPOT = ["https://api.binance.com", "https://data-api.binance.vision", "https://api1.binance.com"]
BYBIT = "https://api.bybit.com"

INTERVAL_MS = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000, "1w": 604_800_000}
BYBIT_INTERVAL = {"5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D", "1w": "W"}
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


async def _bybit_instruments() -> list[dict]:
    data = await get_json(f"{BYBIT}/v5/market/instruments-info", {"category": "linear", "limit": 1000}, ttl=6 * 3600)
    return [i for i in data["result"]["list"]
            if i.get("status") == "Trading" and i.get("contractType") == "LinearPerpetual" and i.get("quoteCoin") == "USDT"]


async def perpetual_symbols() -> set[str]:
    global _last_perps
    try:
        info = await get_json(f"{FAPI[0]}/fapi/v1/exchangeInfo", ttl=6 * 3600)
    except Exception as exc:  # noqa: BLE001
        log.info("Binance exchangeInfo lỗi (%s) -> dùng Bybit", exc)
        bybit = {i["symbol"] for i in await _bybit_instruments()}
        return (bybit & _last_perps) or bybit  # Bybit có cả mã cổ phiếu -> ưu tiên danh sách Binance đã biết
    _last_perps = {
        s["symbol"] for s in info["symbols"]
        if s["status"] == "TRADING" and s["contractType"] == "PERPETUAL"
        and s["quoteAsset"] == "USDT" and s.get("underlyingType") == "COIN"
    }
    return _last_perps


async def spot_symbols() -> set[str]:
    data = await get_json([f"{h}/api/v3/ticker/price" for h in SPOT], ttl=6 * 3600)
    return {d["symbol"] for d in data if d["symbol"].endswith("USDT")}


async def universe(top_n: int, min_quote_volume: float, extra: list[str] | None = None) -> list[Coin]:
    """Top coin theo khối lượng futures 24h + các coin admin thêm vào."""
    perps = await perpetual_symbols()
    spots = await spot_symbols()
    vol = {sym: float(t["quoteVolume"]) for sym, t in (await tickers_24h()).items()}

    def make(sym: str) -> Coin:
        base, mult = split_symbol(sym)
        spot = f"{base}USDT"
        return Coin(sym, base, mult, vol.get(sym, 0.0), spot if spot in spots else None)

    ranked = sorted(
        (s for s in perps if split_symbol(s)[0] not in STABLES and split_symbol(s)[0].isascii()
         and split_symbol(s)[0].isalnum() and vol.get(s, 0) >= min_quote_volume),
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


async def _binance_klines(symbol: str, interval: str, limit: int) -> pd.DataFrame:
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
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames).sort_index()
    return df[~df.index.duplicated(keep="last")]


async def _fetch(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    """Binance -> Bybit -> MEXC (nguồn nào trả được trước dùng nguồn đó)."""
    try:
        df = await _binance_klines(symbol, interval, limit)
        if len(df):
            return df
    except Exception as exc:  # noqa: BLE001
        log.info("Binance klines %s %s lỗi (%s) -> dùng Bybit", symbol, interval, exc)
    try:
        df = await _bybit_klines(symbol, interval, min(limit, 1000))
        if len(df):
            return df
    except Exception as exc:  # noqa: BLE001
        log.info("Bybit klines %s %s lỗi (%s) -> dùng MEXC", symbol, interval, exc)
    from app.data import mexc
    return await mexc.klines(symbol, interval, min(limit, 1500))


async def klines(symbol: str, interval: str, limit: int = 500, *, closed_only: bool = True) -> pd.DataFrame:
    """`limit` nến futures mới nhất. Mặc định chỉ trả nến đã đóng.
    Có sẵn trong bộ nhớ thì chỉ tải thêm phần nến mới (thường 2–3 nến)."""
    key = (symbol, interval)
    cached = _kcache.get(key)
    step = pd.Timedelta(milliseconds=INTERVAL_MS[interval])
    df = None
    if cached is not None and len(cached) >= limit:
        missing = int((pd.Timestamp.now(tz="UTC") - cached.index[-1]) / step) + 2
        if missing <= 900:
            new = await _fetch(symbol, interval, missing)
            if len(new):
                df = pd.concat([cached, new])
                df = df[~df.index.duplicated(keep="last")].sort_index()
    if df is None:
        df = await _fetch(symbol, interval, limit)
    if len(df):
        _kcache[key] = df.iloc[-max(limit, min(len(df), KCACHE_MAX)):]
    out = df.iloc[-limit - 1:] if closed_only else df.iloc[-limit:]
    return _drop_open_candle(out).iloc[-limit:] if closed_only else out


async def klines_since(symbol: str, interval: str, start_ms: int) -> pd.DataFrame:
    """Toàn bộ nến đã đóng từ `start_ms` tới nay (dùng cho backtest và theo dõi lệnh). Binance lỗi -> Bybit."""
    frames: list[pd.DataFrame] = []
    start = start_ms
    try:
        while True:
            rows = await get_json(f"{FAPI[0]}/fapi/v1/klines",
                                  {"symbol": symbol, "interval": interval, "limit": 1500, "startTime": start}, ttl=50)
            if not rows:
                break
            frames.append(_frame(rows, interval))
            if len(rows) < 1500:
                break
            start = int(rows[-1][0]) + 1
    except Exception as exc:  # noqa: BLE001
        log.info("Binance klines_since %s lỗi (%s) -> dùng Bybit", symbol, exc)
        try:
            frames = [await _bybit_klines(symbol, interval, 1000, start_ms=start_ms)]
        except Exception as exc2:  # noqa: BLE001
            log.info("Bybit klines_since %s lỗi (%s) -> dùng MEXC", symbol, exc2)
            from app.data import mexc
            frames = [await mexc.klines(symbol, interval, 2000, start_ms=start_ms)]
    frames = [f for f in frames if len(f)]
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames).sort_index()
    return _drop_open_candle(df[~df.index.duplicated()])


async def _bybit_klines(symbol: str, interval: str, limit: int, start_ms: int | None = None) -> pd.DataFrame:
    params = {"category": "linear", "symbol": symbol, "interval": BYBIT_INTERVAL[interval], "limit": limit}
    if start_ms:
        params["start"] = start_ms
    data = await get_json(f"{BYBIT}/v5/market/kline", params, ttl=50)
    rows = data["result"]["list"][::-1]  # Bybit trả mới nhất trước
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume", "quote_vol"]).astype(float)
    df["taker_buy_vol"] = df["volume"] * 0.5  # Bybit không có -> trung tính
    df["open_time"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
    df["close_time"] = df["open_time"] + pd.Timedelta(milliseconds=INTERVAL_MS[interval])
    return df.set_index("open_time")


async def _bybit_tickers() -> dict[str, dict]:
    data = await get_json(f"{BYBIT}/v5/market/tickers", {"category": "linear"}, ttl=120)
    return {t["symbol"]: t for t in data["result"]["list"]}


async def last_price(symbol: str) -> float:
    try:
        d = await get_json(f"{FAPI[0]}/fapi/v1/ticker/price", {"symbol": symbol}, ttl=5)
        return float(d["price"])
    except Exception:  # noqa: BLE001
        try:
            return float((await _bybit_tickers())[symbol]["lastPrice"])
        except Exception:  # noqa: BLE001
            from app.data import mexc
            return float((await mexc.tickers())[symbol]["lastPrice"])


async def funding_history(symbol: str, start_ms: int | None = None) -> pd.Series:
    params = {"symbol": symbol, "limit": 1000}
    if start_ms:
        params["startTime"] = start_ms
    try:
        rows = await get_json(f"{FAPI[0]}/fapi/v1/fundingRate", params, ttl=1800)
        times = [int(r["fundingTime"]) for r in rows]
    except Exception:  # noqa: BLE001
        bp = {"category": "linear", "symbol": symbol, "limit": 200}
        if start_ms:  # Bybit cần cả startTime và endTime
            bp["startTime"], bp["endTime"] = start_ms, int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
        try:
            rows = (await get_json(f"{BYBIT}/v5/market/funding/history", bp, ttl=1800))["result"]["list"]
        except Exception as exc:  # noqa: BLE001
            log.info("Funding %s lỗi cả 2 sàn: %s", symbol, exc)
            return pd.Series(dtype=float)
        times = [int(r["fundingRateTimestamp"]) for r in rows]
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series([float(r["fundingRate"]) for r in rows], index=pd.to_datetime(times, unit="ms", utc=True))
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


async def listing_dates() -> dict[str, pd.Timestamp]:
    """Ngày niêm yết hợp đồng (để bỏ qua coin mới niêm yết)."""
    try:
        info = await get_json(f"{FAPI[0]}/fapi/v1/exchangeInfo", ttl=6 * 3600)
        return {s["symbol"]: pd.Timestamp(s["onboardDate"], unit="ms", tz="UTC") for s in info["symbols"]}
    except Exception:  # noqa: BLE001
        return {i["symbol"]: pd.Timestamp(int(i["launchTime"]), unit="ms", tz="UTC") for i in await _bybit_instruments()}


async def tickers_24h() -> dict[str, dict]:
    """Giá + thay đổi 24h + khối lượng (định dạng Binance). Binance lỗi -> Bybit (đổi sang cùng định dạng)."""
    try:
        rows = await get_json(f"{FAPI[0]}/fapi/v1/ticker/24hr", ttl=120)
        return {r["symbol"]: r for r in rows}
    except Exception as exc:  # noqa: BLE001
        log.info("Binance tickers lỗi (%s) -> dùng Bybit", exc)
    try:
        return {s: {"symbol": s, "lastPrice": t["lastPrice"], "quoteVolume": t.get("turnover24h", "0"),
                    "priceChangePercent": str(float(t.get("price24hPcnt") or 0) * 100)}
                for s, t in (await _bybit_tickers()).items()}
    except Exception as exc:  # noqa: BLE001
        log.info("Bybit tickers lỗi (%s) -> dùng MEXC", exc)
    from app.data import mexc
    return await mexc.tickers()


async def all_funding() -> dict[str, float]:
    try:
        rows = await get_json(f"{FAPI[0]}/fapi/v1/premiumIndex", ttl=300)
        return {r["symbol"]: float(r["lastFundingRate"]) for r in rows if r.get("lastFundingRate") not in (None, "")}
    except Exception as exc:  # noqa: BLE001
        log.info("Binance funding lỗi (%s) -> dùng Bybit", exc)
    try:
        return {s: float(t["fundingRate"]) for s, t in (await _bybit_tickers()).items() if t.get("fundingRate")}
    except Exception as exc:  # noqa: BLE001
        log.info("Bybit funding lỗi (%s) -> dùng MEXC", exc)
    from app.data import mexc
    return {s: float(t["fundingRate"]) for s, t in (await mexc.tickers()).items()}


async def oi_change_24h(symbol: str) -> tuple[float, float] | None:
    """(giá trị OI hiện tại USD, % thay đổi 24h) từ Binance."""
    try:
        rows = await get_json(f"{FAPI[0]}/futures/data/openInterestHist",
                              {"symbol": symbol, "period": "1h", "limit": 25}, ttl=600)
        first, last = float(rows[0]["sumOpenInterestValue"]), float(rows[-1]["sumOpenInterestValue"])
        return last, (last - first) / first if first else 0.0
    except Exception as exc:  # noqa: BLE001
        log.debug("OI %s: %s", symbol, exc)
        return None


async def oi_change(symbol: str, period: str = "1d", bars: int = 7) -> float | None:
    """% thay đổi OI (giá trị USD) sau `bars` kỳ `period` (Binance giữ tối đa 30 ngày)."""
    try:
        rows = await get_json(f"{FAPI[0]}/futures/data/openInterestHist",
                              {"symbol": symbol, "period": period, "limit": bars + 1}, ttl=1800)
        first, last = float(rows[0]["sumOpenInterestValue"]), float(rows[-1]["sumOpenInterestValue"])
        return (last - first) / first if first else None
    except Exception as exc:  # noqa: BLE001
        log.debug("OI %s: %s", symbol, exc)
        return None
