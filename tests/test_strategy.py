import numpy as np
import pandas as pd
import pytest

from app import indicators as ta
from app.strategy.core import build_features, score_frame

INTERVALS = {"1h": pd.Timedelta(hours=1), "4h": pd.Timedelta(hours=4), "1d": pd.Timedelta(days=1)}


def candles(n: int, interval: str, drift: float = 0.001, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    step = INTERVALS[interval]
    idx = pd.date_range("2026-01-01", periods=n, freq=step, tz="UTC")
    close = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.01, n)))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * 1.004
    low = np.minimum(open_, close) * 0.996
    vol = rng.uniform(900, 1100, n)
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol,
                       "quote_vol": vol * close, "taker_buy_vol": vol * 0.55}, index=idx)
    df.index.name = "open_time"
    df["close_time"] = df.index + step
    return df


def test_rsi_bounds_and_atr_positive():
    df = candles(300, "1h")
    r = ta.rsi(df["close"]).dropna()
    assert ((r >= 0) & (r <= 100)).all()
    assert (ta.atr(df).dropna() > 0).all()


def test_higher_timeframe_uses_only_closed_candles():
    h1 = candles(24 * 30, "1h")
    h4 = candles(6 * 60, "4h")
    h4.index = h4.index - pd.Timedelta(days=30)  # phủ cả giai đoạn trước
    h4["close_time"] = h4.index + INTERVALS["4h"]
    d1 = candles(120, "1d")
    d1.index = d1.index - pd.Timedelta(days=90)
    d1["close_time"] = d1.index + INTERVALS["1d"]

    f = build_features(h1, h4, d1)
    # nến 1H 02:00-03:00 ngày 10 chỉ được thấy nến 4H 20:00-24:00 ngày 9 (đóng lúc 00:00), không phải nến 00:00-04:00
    row = f.loc[pd.Timestamp("2026-01-10 02:00", tz="UTC")]
    expected = h4.loc[pd.Timestamp("2026-01-09 20:00", tz="UTC"), "close"]
    assert row["h4_close"] == pytest.approx(expected)
    # nến 1H 03:00-04:00 đóng cùng lúc nến 4H 00:00-04:00 -> được thấy nến đó
    row = f.loc[pd.Timestamp("2026-01-10 03:00", tz="UTC")]
    assert row["h4_close"] == pytest.approx(h4.loc[pd.Timestamp("2026-01-10 00:00", tz="UTC"), "close"])


def test_score_frame_levels_consistent():
    h1 = candles(24 * 60, "1h", drift=0.0015)
    h4 = candles(6 * 90, "4h", drift=0.004)
    h4.index = h4.index - pd.Timedelta(days=30)
    h4["close_time"] = h4.index + INTERVALS["4h"]
    d1 = candles(200, "1d", drift=0.01)
    d1.index = d1.index - pd.Timedelta(days=140)
    d1["close_time"] = d1.index + INTERVALS["1d"]
    scores = score_frame(build_features(h1, h4, d1))
    for side, df in scores.items():
        ok = df[df["score"] > 0]
        assert (ok["score"] <= 105).all()
        # SL phía dưới entry với LONG, phía trên với SHORT; TP ngược lại
        assert ((ok["entry"] - ok["sl"]) * side > 0).all()
        assert ((ok["tp1"] - ok["entry"]) * side > 0).all()
        assert (ok["zone_lo"] <= ok["zone_hi"]).all()
