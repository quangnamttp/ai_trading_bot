"""Backtest nghiệm thu Swing Entry Pro v6.1 — mô phỏng ĐÚNG luật của file Pine (không dùng ứng viên cũ).

- Dữ liệu: 53 coin Binance, 2017-08 -> 2026-09, khung 1H và 4H (khung giữa / lớn / BTC như chỉ báo).
- Tín hiệu: điểm >= ngưỡng (1H 75, 4H 70), bỏ Pullback LONG, lọc OI 24h >= 5% ở 1H (khi có dữ liệu OI),
  lọc POC 150 nến (LONG trên POC, SHORT dưới POC).
- Mỗi coin 1 lệnh 1 lúc; vào = giá đóng nến tín hiệu; lệnh bắt đầu quản lý từ nến kế tiếp.
- Thoát: SL kiểm tra trước; trailing kích hoạt khi giá đạt +1R, callback = 2.5 x ATR khung giữa (0.5%–10%);
  giữ tối đa 168 nến; phí khứ hồi 0.1%.
- Ghi thêm: kháng cự / hỗ trợ gần nhất lúc vào lệnh (cách tính của chỉ báo: 12 đỉnh/đáy xoay chiều 5 nến +
  đỉnh/đáy ngày & tuần trước) để kiểm tra lời khuyên "vùng cản < 1R".
"""
import os
import pickle
import sys
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # thư mục gốc repo

import numpy as np
import pandas as pd

sys.path.insert(0, str(ROOT))
from app.strategy.core import build_features, poc_veto, score_frame  # noqa: E402

LONG = ROOT / ".cache" / "long"
FEE = 0.001
CFG = {"1h": ("1h", "4h", "1d", 75.0, True, 6), "4h": ("4h", "1d", "1w", 70.0, False, 18)}  # ..., OI 24h = 6 nến 4h
HOLD, ACT, CBK, SR_LEN = 168, 1.0, 2.5, 5
NO_POC = os.environ.get("NO_POC") == "1"
NO_OI = os.environ.get("NO_OI") == "1"


def ohlc_flow(df):
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    d = df.copy()
    d["taker_buy_vol"] = (df["volume"] * (df["close"] - df["low"]) / rng).fillna(df["volume"] / 2)
    return d


def asof(times, series, lag):
    if series is None or not len(series):
        return np.full(len(times), np.nan)
    r = pd.DataFrame({"t": (series.index + lag).astype("datetime64[ns, UTC]"), "v": series.to_numpy()}).sort_values("t")
    lt = pd.DataFrame({"t": pd.DatetimeIndex(times).astype("datetime64[ns, UTC]")})
    return pd.merge_asof(lt, r, on="t", direction="backward")["v"].to_numpy()


def pivots(x, n, high):
    """Chỉ số nến là đỉnh (high=True) / đáy xoay chiều n nến mỗi bên; chỉ biết được sau n nến."""
    s = pd.Series(x)
    w = s.rolling(2 * n + 1, center=True)
    m = (w.max() if high else w.min()).to_numpy()
    return np.flatnonzero(x == m)


def simulate(H, L, C, i, side, entry, sl, atr_mid):
    risk = abs(entry - sl)
    fee = FEE * entry / risk
    cb = min(max(CBK * atr_mid / entry, 0.005), 0.10)
    armed, peak, mfe = False, entry, 0.0
    n = len(H)
    for j in range(i + 1, n):
        adv, fav = (L[j], H[j]) if side > 0 else (H[j], L[j])
        eff = sl
        if armed:
            t = peak * (1 - cb) if side > 0 else peak * (1 + cb)
            eff = max(sl, t) if side > 0 else min(sl, t)
        if (eff - adv) * side >= 0:
            return (eff - entry) * side / risk - fee, j, mfe
        r_fav = (fav - entry) * side / risk
        mfe = max(mfe, r_fav)
        if not armed and r_fav >= ACT:
            armed, peak = True, fav
        elif armed:
            peak = max(peak, fav) if side > 0 else min(peak, fav)
        if j - i >= HOLD:
            return (C[j] - entry) * side / risk - fee, j, mfe
    return None, n, mfe  # lệnh chưa đóng ở cuối dữ liệu -> bỏ


def work(args):
    base, tf = args
    d = pickle.loads((LONG / f"{base}.pkl").read_bytes())
    btc = pickle.loads((LONG / "BTC.pkl").read_bytes())
    b, m, h, th, use_oi, oi_n = CFG[tf]
    raw = d[b]
    f = build_features(ohlc_flow(raw), d[m], d[h], btc_h4=None if base == "BTC" else btc[m])
    sc = score_frame(f)
    times = f.index
    oi = d["oi"]
    oi_v = asof(times + pd.Timedelta(tf), oi / oi.shift(oi_n) - 1 if len(oi) else None, pd.Timedelta(0))
    qv = asof(times, d["1d"]["quote_vol"].rolling(30).sum(), pd.Timedelta(days=1))
    H, L, C = (f[k].to_numpy() for k in ("high", "low", "close"))
    atr_mid = f["h4_atr"].to_numpy()
    base_df = raw.reindex(f.index)
    # hỗ trợ / kháng cự như chỉ báo
    ph_idx, pl_idx = pivots(H, SR_LEN, True), pivots(L, SR_LEN, False)
    dH = asof(times, d["1d"]["high"], pd.Timedelta(days=1))
    dL = asof(times, d["1d"]["low"], pd.Timedelta(days=1))
    wH = asof(times, d["1w"]["high"], pd.Timedelta(days=7))
    wL = asof(times, d["1w"]["low"], pd.Timedelta(days=7))
    s_long, s_short = sc[1], sc[-1]
    scL, scS = s_long["score"].to_numpy(), s_short["score"].to_numpy()
    rows, busy_until = [], -1
    for i in range(300, len(H) - 1):
        if i <= busy_until or np.isnan(atr_mid[i]):
            continue
        o = oi_v[i]
        if use_oi and not NO_OI and not np.isnan(o) and abs(o) < 0.05:
            continue
        best = None
        for side, s, arr in ((1, s_long, scL), (-1, s_short, scS)):
            if arr[i] < th:
                continue
            r = s.iloc[i]
            if side > 0 and r["setup_type"] == "pullback":
                continue
            if not NO_POC and poc_veto(base_df, side, float(r["entry"]), upto=i):
                continue
            if best is None or r["score"] > best[1]["score"]:
                best = (side, r)
        if best is None:
            continue
        side, r = best
        entry, sl = float(r["entry"]), float(r["sl"])
        if abs(entry - sl) <= 0:
            continue
        R, j, mfe = simulate(H, L, C, i, side, entry, sl, atr_mid[i])
        if R is None:
            break
        busy_until = j
        risk = abs(entry - sl)
        # kháng cự phía trước lệnh / hỗ trợ phía sau (đỉnh-đáy đã xác nhận trước nến i)
        ahead_src = H[ph_idx[ph_idx + SR_LEN <= i][-12:]] if side > 0 else L[pl_idx[pl_idx + SR_LEN <= i][-12:]]
        cands = list(ahead_src) + ([dH[i], wH[i]] if side > 0 else [dL[i], wL[i]])
        cands = [v for v in cands if not np.isnan(v) and (v - entry) * side > 0]
        ahead = min(cands, key=lambda v: abs(v - entry)) if cands else np.nan
        rows.append({"base": base, "tf": tf, "t": times[i], "side": side, "score": float(r["score"]),
                     "setup": r["setup_type"], "R": R, "mfe": mfe, "oi": o, "qv30": qv[i], "exit_t": times[j],
                     "res_r": abs(ahead - entry) / risk if not np.isnan(ahead) else np.nan,
                     "grade": "A" if r["score"] >= 85 or (not np.isnan(o) and abs(o) >= 0.10) else "B"})
    return pd.DataFrame(rows)


def stats(g, name):
    g = g.sort_values("t")
    if not len(g):
        print(f"  {name}: không có lệnh")
        return
    eq = g["R"].cumsum()
    dd = (eq.cummax() - eq).max()
    mon = g.groupby(g["t"].dt.to_period("M"))["R"].sum()
    yr = g.groupby(g["t"].dt.year)["R"].sum()
    print(f"  {name:34s} {len(g):5d} lệnh · có lời {(g['R'] > 0).mean():4.0%} · TB {g['R'].mean():+.3f}R · "
          f"tổng {g['R'].sum():+7.1f}R · sụt giảm tối đa {dd:5.1f}R · tháng lỗ {(mon < 0).mean():3.0%} · "
          f"năm lỗ {(yr < 0).sum()}/{len(yr)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    bases = sorted(p.stem for p in LONG.glob("*.pkl") if not p.stem.startswith("_"))
    jobs = [(b, tf) for b in bases for tf in ("1h", "4h")]
    with Pool(8) as p:
        parts = [x for x in p.imap_unordered(work, jobs) if x is not None and len(x)]
    df = pd.concat(parts, ignore_index=True)
    df.to_pickle(Path(__file__).with_name(os.environ.get("OUT", "bt_swing.pkl")))
    print(f"Tổng {len(df)} lệnh, {df['t'].min():%Y-%m} -> {df['t'].max():%Y-%m}")
