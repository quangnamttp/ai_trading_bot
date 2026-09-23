"""Chuyển 2 chỉ báo TradingView của bạn (thư mục tradingview/) sang Python để backtest.

- `swing_entry_pro`  : Swing Entry Pro v3 (EMA 9/21, đa khung D/H4/H1, S/R theo pivot, phân kỳ RSI, nến đảo chiều).
- `volume_profile_at`: Volume Profile Pro (POC / VAH / VAL cuộn 150 nến + phiên Á), cùng cách chia volume thân/bóng nến.
- `fvg_zones`        : Fair Value Gap (khoảng trống giá 3 nến) — bổ sung mới để thử nghiệm.

Khác bản Pine: dữ liệu khung lớn chỉ dùng nến ĐÃ ĐÓNG (bản Pine dùng lookahead_off nên bị repaint khi chạy live).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app import indicators as ta


# ---------------------------------------------------------------- Swing Entry Pro v3
def _trend(close: pd.Series) -> tuple[pd.Series, pd.Series]:
    ef, es = ta.ema(close, 9), ta.ema(close, 21)
    return ef > es, ef < es  # swingMode = true (mặc định)


def _htf_votes(h1: pd.DataFrame, htf: pd.DataFrame) -> pd.DataFrame:
    bull, bear = _trend(htf["close"])
    r = pd.DataFrame({"avail": htf["close_time"].astype("datetime64[ns, UTC]"), "bull": bull.values, "bear": bear.values})
    left = pd.DataFrame({"avail": h1["close_time"].astype("datetime64[ns, UTC]")})
    m = pd.merge_asof(left, r.sort_values("avail"), on="avail", direction="backward")
    return m[["bull", "bear"]].fillna(False).astype(bool).set_index(h1.index)


def candles(df: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body, rng = (c - o).abs(), h - l
    bull_engulf = (c > o) & (c.shift() < o.shift()) & (c >= o.shift()) & (o <= c.shift())
    bear_engulf = (c < o) & (c.shift() > o.shift()) & (c <= o.shift()) & (o >= c.shift())
    hammer = (rng > 0) & ((h - np.maximum(c, o)) < body * 0.4) & ((np.minimum(c, o) - l) > body * 1.8)
    star = (rng > 0) & ((np.minimum(c, o) - l) < body * 0.4) & ((h - np.maximum(c, o)) > body * 1.8)
    return pd.DataFrame({"bull_candle": bull_engulf | hammer, "bear_candle": bear_engulf | star})


def swing_entry_pro(h1: pd.DataFrame, h4: pd.DataFrame, d1: pd.DataFrame, *, pivot: int = 5, merge_pct: float = 0.15,
                    touch_pct: float = 0.25, vol_mult: float = 1.4, require_vote: int = 2, warn_bars: int = 4) -> pd.DataFrame:
    close, high, low = h1["close"], h1["high"], h1["low"]
    bull, bear = _trend(close)
    d, f4 = _htf_votes(h1, d1), _htf_votes(h1, h4)
    bull_votes = d["bull"].astype(int) + f4["bull"].astype(int) + bull.astype(int)  # H1 = khung biểu đồ
    bear_votes = d["bear"].astype(int) + f4["bear"].astype(int) + bear.astype(int)

    # pivot xác nhận sau `pivot` nến bên phải (giống ta.pivothigh/low)
    win = 2 * pivot + 1
    ph = (high.shift(pivot) == high.rolling(win).max()) & high.shift(pivot).notna()
    pl = (low.shift(pivot) == low.rolling(win).min()) & low.shift(pivot).notna()
    rsi = ta.rsi(close)

    n = len(h1)
    near_sup = np.zeros(n, bool)
    near_res = np.zeros(n, bool)
    sup_level = np.full(n, np.nan)
    res_level = np.full(n, np.nan)
    bull_div = np.zeros(n, bool)
    bear_div = np.zeros(n, bool)
    res, sup = [], []
    last_pl = prev_pl = last_ph = prev_ph = None
    hv, lv, cv, rv, phv, plv = high.values, low.values, close.values, rsi.values, ph.values, pl.values

    def add(levels: list, lvl: float) -> None:
        merged = False
        for i, x in enumerate(levels):
            if abs(lvl - x) / x * 100 < merge_pct:
                levels[i] = (x + lvl) / 2
                merged = True
        if not merged:
            levels.append(lvl)
        if len(levels) > 25:
            levels.pop(0)

    for t in range(n):
        if phv[t]:
            add(res, hv[t - pivot])
            prev_ph, last_ph = last_ph, (hv[t - pivot], rv[t - pivot])
            bear_div[t] = prev_ph is not None and last_ph[0] > prev_ph[0] and last_ph[1] < prev_ph[1]
        if plv[t]:
            add(sup, lv[t - pivot])
            prev_pl, last_pl = last_pl, (lv[t - pivot], rv[t - pivot])
            bull_div[t] = prev_pl is not None and last_pl[0] < prev_pl[0] and last_pl[1] > prev_pl[1]
        c = cv[t]
        above = [x for x in res if x > c]
        below = [x for x in sup if x < c]
        if above:
            res_level[t] = min(above)
            near_res[t] = (res_level[t] - c) / c * 100 <= touch_pct
        if below:
            sup_level[t] = max(below)
            near_sup[t] = (c - sup_level[t]) / c * 100 <= touch_pct

    cd = candles(h1)
    vol_spike = h1["volume"] > h1["volume"].rolling(20).mean() * vol_mult
    ef, es = ta.ema(close, 9), ta.ema(close, 21)
    cross_up = (ef > es) & (ef.shift() <= es.shift())
    cross_dn = (ef < es) & (ef.shift() >= es.shift())
    near_sup_s, near_res_s = pd.Series(near_sup, h1.index), pd.Series(near_res, h1.index)

    warn_bull = near_sup_s & (pd.Series(bull_div, h1.index) | cd["bull_candle"])
    warn_bear = near_res_s & (pd.Series(bear_div, h1.index) | cd["bear_candle"])
    recent = lambda s: s.astype(float).rolling(warn_bars + 1, min_periods=1).max() > 0  # noqa: E731

    buy_raw = (cross_up | (cd["bull_candle"] & near_sup_s)) & vol_spike & bull & (bull_votes >= require_vote)
    sell_raw = (cross_dn | (cd["bear_candle"] & near_res_s)) & vol_spike & bear & (bear_votes >= require_vote)
    buy = buy_raw & ~buy_raw.shift(fill_value=False)
    sell = sell_raw & ~sell_raw.shift(fill_value=False)
    return pd.DataFrame({
        "sep_buy": buy, "sep_sell": sell,
        "sep_buy_best": buy & recent(warn_bull), "sep_sell_best": sell & recent(warn_bear),
        "sep_near_sup": near_sup_s, "sep_near_res": near_res_s,
        "sep_sup": sup_level, "sep_res": res_level,
        "sep_bull_votes": bull_votes, "sep_bear_votes": bear_votes,
    }, index=h1.index)


# ---------------------------------------------------------------- Volume Profile Pro
def _profile(o, h, l, c, v, bins: int) -> tuple[np.ndarray, float, float]:
    """Chia volume từng nến vào các mức giá: thân trọng số 1, bóng nến trọng số 2 (giống bản Pine)."""
    hi, lo = h.max(), l.min()
    if hi <= lo:
        return np.zeros(bins), lo, 0.0
    step = (hi - lo) / bins
    edges = lo + step * np.arange(bins + 1)
    bt, bb = np.maximum(o, c), np.minimum(o, c)
    tw, bw, body = h - bt, bb - l, bt - bb
    tr = 2 * tw + 2 * bw + body
    tr = np.where(tr > 0, tr, np.nan)

    def spread(seg_lo, seg_hi, seg_vol):
        length = seg_hi - seg_lo
        ov = np.clip(np.minimum(seg_hi[:, None], edges[None, 1:]) - np.maximum(seg_lo[:, None], edges[None, :-1]), 0, None)
        dens = np.where(length > 0, seg_vol / np.where(length > 0, length, 1), 0.0)
        return np.nan_to_num(ov * dens[:, None]).sum(axis=0)

    prof = spread(bb, bt, body * v / tr) + spread(bt, h, 2 * tw * v / tr) + spread(l, bb, 2 * bw * v / tr)
    return prof, lo, step


def _poc_va(prof: np.ndarray, lo: float, step: float, va_pct: float = 70) -> tuple[float, float, float]:
    poc = int(np.argmax(prof))
    lo_i = hi_i = poc
    va, target = prof[poc], prof.sum() * va_pct / 100
    while va < target and (lo_i > 0 or hi_i < len(prof) - 1):
        below = prof[lo_i - 1] if lo_i > 0 else -1
        above = prof[hi_i + 1] if hi_i < len(prof) - 1 else -1
        if above >= below:
            hi_i += 1
            va += prof[hi_i]
        else:
            lo_i -= 1
            va += prof[lo_i]
    return lo + (poc + 0.5) * step, lo + (hi_i + 1) * step, lo + lo_i * step


def volume_profile_at(h1: pd.DataFrame, positions: np.ndarray, *, lookback: int = 150, bins: int = 24,
                      session_hours: tuple[int, int] = (0, 8)) -> pd.DataFrame:
    """POC/VAH/VAL cuộn và theo phiên Á, tính tại các vị trí nến `positions` (chỉ dùng dữ liệu tới nến đó)."""
    o, h, l, c, v = (h1[k].to_numpy() for k in ("open", "high", "low", "close", "volume"))
    hours = h1.index.hour.to_numpy()
    in_sess = (hours >= session_hours[0]) & (hours < session_hours[1])
    out = []
    for t in positions:
        a = max(0, t - lookback + 1)
        poc, vah, val = _poc_va(*_profile(o[a:t + 1], h[a:t + 1], l[a:t + 1], c[a:t + 1], v[a:t + 1], bins))
        # phiên Á gần nhất tính tới nến t
        j = t
        while j >= 0 and not in_sess[j]:
            j -= 1
        k = j
        while k >= 0 and in_sess[k]:
            k -= 1
        if j >= 0 and j - k >= 2:
            s = slice(k + 1, j + 1)
            spoc, svah, sval = _poc_va(*_profile(o[s], h[s], l[s], c[s], v[s], bins))
        else:
            spoc = svah = sval = np.nan
        out.append((poc, vah, val, spoc, svah, sval))
    return pd.DataFrame(out, columns=["poc", "vah", "val", "s_poc", "s_vah", "s_val"], index=h1.index[positions])


def volume_profile_signals(h1: pd.DataFrame, *, touch_pct: float = 0.3, vol_mult: float = 1.3) -> pd.DataFrame:
    """Tín hiệu VP★ của bản Pine: chạm POC/VAL (mua) hoặc POC/VAH (bán) + nến đảo chiều + volume + EMA50."""
    cd = candles(h1)
    spike = h1["volume"] > h1["volume"].rolling(20).mean() * vol_mult
    ema50 = ta.ema(h1["close"], 50)
    pre_b = cd["bull_candle"] & spike & (h1["close"] > ema50)
    pre_s = cd["bear_candle"] & spike & (h1["close"] < ema50)
    pos = np.flatnonzero((pre_b | pre_s).to_numpy())
    pos = pos[pos >= 150]
    vp = volume_profile_at(h1, pos)
    c = h1["close"].iloc[pos]
    near = lambda lvl: ((c - vp[lvl]).abs() / c * 100 <= touch_pct).fillna(False)  # noqa: E731
    buy_raw = pd.Series(False, h1.index)
    sell_raw = pd.Series(False, h1.index)
    buy_raw.loc[vp.index] = (near("val") | near("poc") | near("s_val") | near("s_poc")) & pre_b.iloc[pos]
    sell_raw.loc[vp.index] = (near("vah") | near("poc") | near("s_vah") | near("s_poc")) & pre_s.iloc[pos]
    return pd.DataFrame({"vp_buy": buy_raw & ~buy_raw.shift(fill_value=False),
                         "vp_sell": sell_raw & ~sell_raw.shift(fill_value=False)}, index=h1.index)


# ---------------------------------------------------------------- FVG
def fvg_zones(df: pd.DataFrame, *, max_age: int = 48, min_atr: float = 0.2) -> pd.DataFrame:
    """Fair Value Gap chưa bị lấp.

    FVG tăng: low[t] > high[t-2] (khoảng trống giữa nến 1 và nến 3). Còn hiệu lực tới khi giá đóng cửa
    dưới đáy vùng hoặc quá `max_age` nến. Trả về cờ 'giá đang chạm vùng FVG thuận hướng' cho mỗi nến.
    """
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    atr = ta.atr(df).to_numpy()
    n = len(df)
    in_bull, in_bear = np.zeros(n, bool), np.zeros(n, bool)
    bulls: list[list] = []  # [bottom, top, t_created]
    bears: list[list] = []
    for t in range(2, n):
        bulls = [z for z in bulls if c[t] >= z[0] and t - z[2] <= max_age]
        bears = [z for z in bears if c[t] <= z[1] and t - z[2] <= max_age]
        in_bull[t] = any(l[t] <= z[1] for z in bulls if z[2] < t)
        in_bear[t] = any(h[t] >= z[0] for z in bears if z[2] < t)
        gap = atr[t] * min_atr if not np.isnan(atr[t]) else 0
        if l[t] - h[t - 2] > gap:
            bulls.append([h[t - 2], l[t], t])
        if l[t - 2] - h[t] > gap:
            bears.append([h[t], l[t - 2], t])
    return pd.DataFrame({"fvg_bull_touch": in_bull, "fvg_bear_touch": in_bear}, index=df.index)


# ---------------------------------------------------------------- gộp cho chiến lược
def tv_features(h1: pd.DataFrame, h4: pd.DataFrame, d1: pd.DataFrame, recent: int = 4) -> pd.DataFrame:
    """Các xác nhận từ 2 chỉ báo TradingView + FVG 4H, theo từng nến 1H (chỉ dùng nến đã đóng)."""
    sep = swing_entry_pro(h1, h4, d1)
    vp = volume_profile_signals(h1)
    f4 = fvg_zones(h4).assign(avail=h4["close_time"].astype("datetime64[ns, UTC]"))
    f4 = pd.merge_asof(pd.DataFrame({"avail": h1["close_time"].astype("datetime64[ns, UTC]")}), f4.sort_values("avail"),
                       on="avail", direction="backward").set_index(h1.index).fillna(False)
    win = lambda s: s.astype(float).rolling(recent, min_periods=1).max() > 0  # noqa: E731  xuất hiện trong N nến gần nhất
    return pd.DataFrame({
        "tv_sep_buy": win(sep["sep_buy"]), "tv_sep_sell": win(sep["sep_sell"]),
        "tv_vp_buy": win(vp["vp_buy"]), "tv_vp_sell": win(vp["vp_sell"]),
        "tv_votes_bull": sep["sep_bull_votes"], "tv_votes_bear": sep["sep_bear_votes"],
        "tv_fvg4_bull": win(f4["fvg_bull_touch"].astype(bool)), "tv_fvg4_bear": win(f4["fvg_bear_touch"].astype(bool)),
    }, index=h1.index)
