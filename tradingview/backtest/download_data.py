"""Tải dữ liệu dài hạn cho nghiên cứu Swing: nến SPOT Binance 1h/4h/1d/1w từ 2017 (có taker buy volume),
funding futures (từ 2019), OI + long/short Bybit 4h (từ 2021). Lưu .cache/long/{BASE}.pkl"""
import asyncio
import pickle
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # thư mục gốc repo

import httpx
import pandas as pd

sys.path.insert(0, str(ROOT))
from app.data import bybit  # noqa: E402

OUT = ROOT / ".cache" / "long"
SPOT = "https://data-api.binance.vision/api/v3/klines"
START = int(pd.Timestamp("2017-08-01", tz="UTC").timestamp() * 1000)
MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000, "1w": 604_800_000}
COINS = ["BTC", "ETH", "BNB", "XRP", "ADA", "SOL", "DOGE", "DOT", "LINK", "LTC", "TRX", "AVAX", "ATOM", "ETC", "XLM",
         "BCH", "UNI", "AAVE", "FIL", "NEAR", "ALGO", "VET", "ICP", "APT", "ARB", "OP", "SUI", "INJ", "HBAR", "SHIB",
         "PEPE", "TON", "EOS", "NEO", "THETA", "SAND", "MANA", "AXS", "CRV", "RUNE", "FET", "GRT", "LDO", "SEI", "WLD",
         "ENA", "TIA", "ONDO", "ZEC", "DASH"]
FUT = {"PEPE": "1000PEPEUSDT", "SHIB": "1000SHIBUSDT"}


def frame(rows, tf):
    df = pd.DataFrame(rows).iloc[:, :11]
    df.columns = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_vol", "trades",
                  "taker_buy_vol", "taker_buy_quote"]
    df = df.drop(columns=["close_time", "trades", "taker_buy_quote"]).astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
    df["close_time"] = df["open_time"] + pd.Timedelta(milliseconds=MS[tf])
    return df.set_index("open_time")


async def klines(c, sym, tf):
    out, t = [], START
    while True:
        for attempt in range(5):
            try:
                r = await c.get(SPOT, params={"symbol": sym, "interval": tf, "startTime": t, "limit": 1000})
                if r.status_code == 429:
                    await asyncio.sleep(30)
                    continue
                r.raise_for_status()
                rows = r.json()
                break
            except httpx.HTTPError:
                await asyncio.sleep(3)
        else:
            raise RuntimeError(f"{sym} {tf} lỗi")
        if not rows:
            break
        out += rows
        if len(rows) < 1000:
            break
        t = int(rows[-1][0]) + 1
    df = frame(out, tf)
    now = pd.Timestamp.now(tz="UTC")
    return df[df["close_time"] <= now]


async def funding(c, sym):
    out, t = [], int(pd.Timestamp("2019-09-01", tz="UTC").timestamp() * 1000)
    while True:
        r = await c.get("https://fapi.binance.com/fapi/v1/fundingRate", params={"symbol": sym, "limit": 1000, "startTime": t})
        if r.status_code != 200:
            break
        rows = r.json()
        out += rows
        if len(rows) < 1000:
            break
        t = int(rows[-1]["fundingTime"]) + 1
    if not out:
        return pd.Series(dtype=float)
    s = pd.Series({pd.Timestamp(int(x["fundingTime"]), unit="ms", tz="UTC"): float(x["fundingRate"]) for x in out})
    return s[~s.index.duplicated()].sort_index()


async def one(c, base):
    p = OUT / f"{base}.pkl"
    if p.exists():
        return base, "đã có"
    sym = f"{base}USDT"
    try:
        d = {tf: await klines(c, sym, tf) for tf in ("1h", "4h", "1d", "1w")}
    except Exception as exc:  # noqa: BLE001
        return base, f"lỗi {exc}"
    fut = FUT.get(base, sym)
    d["funding"] = await funding(c, fut)
    a = int(pd.Timestamp("2021-01-01", tz="UTC").timestamp() * 1000)
    now = int(time.time() * 1000)
    d["oi"] = await bybit.open_interest(fut, a, now)
    d["ls"] = await bybit.long_short(fut, a, now)
    d["futures_symbol"] = fut
    p.write_bytes(pickle.dumps(d))
    return base, f"{len(d['1h'])} nến 1h từ {d['1h'].index[0]:%Y-%m-%d}, OI {len(d['oi'])}"


async def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=30) as c:
        sem = asyncio.Semaphore(4)

        async def guarded(b):
            async with sem:
                return await one(c, b)
        for fut in asyncio.as_completed([guarded(b) for b in COINS]):
            b, msg = await fut
            print(b, msg, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
