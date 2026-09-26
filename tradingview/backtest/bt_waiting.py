"""Backtest 📋 Kịch bản chờ (app/strategy/waiting.py) — đúng như bot nói với khách khi kết luận CHƯA NÊN VÀO.

- 53 coin (nến Binance), 09/2023 -> 09/2026. Cứ mỗi 4 giờ, coin chưa đủ điều kiện vào lệnh (điểm < 75) và chưa có
  kịch bản / lệnh đang chạy -> tạo kịch bản chờ bằng đúng hàm của bot (EMA20 4H, vùng hỗ trợ/kháng cự ngày).
- Cách A (bot đang hướng dẫn): giá chạm vùng + nến 1H đóng đúng hướng (xanh khi LONG, đỏ khi SHORT) -> vào giá đóng.
- Cách B (lệnh chờ Limit): giá chạm giữa vùng -> khớp ở giữa vùng.
- Hủy: nến 4H đóng qua mức SL trước khi vào, hoặc 48 giờ chưa vào.
- Thoát: SL; trailing kích hoạt +1R, callback 2.5 x ATR 4H (0.5%–10%); giữ tối đa 168 giờ; phí khứ hồi 0.1%.
Kết quả: tradingview/backtest/bt_waiting.pkl -> xem bằng bt_waiting.py --report
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
from app.strategy import levels  # noqa: E402
import waiting_plan as waiting  # noqa: E402  (kịch bản chờ đã gỡ khỏi bot vì backtest ~0R)
from app.strategy.core import build_features, score_frame  # noqa: E402

LONG = ROOT / ".cache" / "long"
OUT = Path(__file__).with_name("bt_waiting.pkl")
START = pd.Timestamp("2023-09-26", tz="UTC")
FEE, HOLD, EXPIRE, CBK, TH = 0.001, 168, 48, 2.5, 75.0


def simulate(H, L, C, i, side, entry, sl, atr4):
    risk = abs(entry - sl)
    fee = FEE * entry / risk
    cb = min(max(CBK * atr4 / entry, 0.005), 0.10)
    armed, peak = False, entry
    for j in range(i + 1, len(H)):
        adv, fav = (L[j], H[j]) if side > 0 else (H[j], L[j])
        eff = sl
        if armed:
            t = peak * (1 - cb) if side > 0 else peak * (1 + cb)
            eff = max(sl, t) if side > 0 else min(sl, t)
        if (eff - adv) * side >= 0:
            return (eff - entry) * side / risk - fee, j
        if not armed and (fav - entry) * side / risk >= 1.0:
            armed, peak = True, fav
        elif armed:
            peak = max(peak, fav) if side > 0 else min(peak, fav)
        if j - i >= HOLD:
            return (C[j] - entry) * side / risk - fee, j
    return None, len(H)


def work(base):
    d = pickle.loads((LONG / f"{base}.pkl").read_bytes())
    btc = pickle.loads((LONG / "BTC.pkl").read_bytes())
    h1, h4, d1 = d["1h"], d["4h"], d["1d"]
    f = build_features(h1, h4, d1, btc_h4=None if base == "BTC" else btc["4h"])
    sc = score_frame(f)
    t = f.index
    O, H, L, C = (h1["open"].reindex(t).to_numpy(), f["high"].to_numpy(), f["low"].to_numpy(), f["close"].to_numpy())
    ema = f["h4_ema20"].to_numpy()
    s_l, s_s = sc[1], sc[-1]
    cols = ["trend", "entry", "atr4", "score"]
    L_, S_ = s_l[cols].to_numpy(), s_s[cols].to_numpy()
    qv = d1["quote_vol"].rolling(30).sum()
    zones_by_day: dict = {}
    rows, busy = [], -1
    first = int(np.searchsorted(t, START))
    for i in range(max(first, 300), len(t) - 2):
        if i <= busy or t[i].hour % 4 != 3:  # nến 1H cuối của mỗi nến 4H (vừa đóng 4H)
            continue
        if np.isnan(ema[i]) or np.isnan(L_[i, 2]) or max(L_[i, 3], S_[i, 3]) >= TH:
            continue  # đủ điều kiện -> bot gửi tín hiệu thật, không phải kịch bản chờ
        day = t[i].floor("D")
        if day not in zones_by_day:
            try:
                p = levels.build_plan(d1[d1.index < day].iloc[-400:], h4[h4.index < t[i]].iloc[-540:])
                zones_by_day[day] = [x for x, _ in p["supports"] + p["resistances"]]
            except Exception:  # noqa: BLE001
                zones_by_day[day] = []
        zones = zones_by_day[day]
        r = {1: dict(zip(cols, L_[i])), -1: dict(zip(cols, S_[i]))}
        w = waiting.plan(r, float(ema[i]), zones, zones)
        if w.side == 0:
            continue
        s, atr4 = w.side, float(r[w.side]["atr4"])
        mid = (w.lo + w.hi) / 2
        got = {}
        for j in range(i + 1, min(i + 1 + EXPIRE, len(t) - 1)):
            if t[j].hour % 4 == 3 and (C[j] - w.sl) * s <= 0:
                break  # nến 4H đóng qua mức hủy
            touched = L[j] <= w.hi and H[j] >= w.lo
            if "B" not in got and L[j] <= mid <= H[j]:
                got["B"] = (j, mid)
            if "A" not in got and touched and (C[j] - O[j]) * s > 0 and (C[j] - w.sl) * s > 0:
                got["A"] = (j, C[j])
            if len(got) == 2:
                break
        end = i + EXPIRE
        for kind, (j, entry) in got.items():
            if (entry - w.sl) * s <= 0:
                continue
            R, k = simulate(H, L, C, j, s, entry, w.sl, atr4)
            if R is None:
                continue
            rows.append({"base": base, "t": t[j], "made": t[i], "side": s, "how": kind, "zone": w.kind, "R": R,
                         "risk_pct": abs(entry - w.sl) / entry, "hold_h": k - j,
                         "qv30": float(qv[qv.index < t[i].floor("D")].iloc[-1]) if (qv.index < t[i].floor("D")).any() else np.nan})
            if kind == "A":
                end = max(end, k)
        busy = end if got else i + EXPIRE  # 1 kịch bản / coin tại 1 thời điểm
    return pd.DataFrame(rows)


def report():
    df = pd.read_pickle(OUT)
    vols = {p.stem: pickle.loads(p.read_bytes())["1d"]["quote_vol"].rolling(30).sum()
            for p in LONG.glob("*.pkl") if not p.stem.startswith("_")}
    rank = pd.DataFrame(vols).rank(axis=1, ascending=False)
    rank.index = pd.to_datetime(rank.index, utc=True) + pd.Timedelta(days=1)
    rk = rank.stack().rename("rank").reset_index()
    rk.columns = ["day", "base", "rank"]
    df["day"] = df["made"].dt.floor("D")
    df = df.merge(rk, on=["day", "base"], how="left")
    two = pd.Timestamp("2024-09-26", tz="UTC")
    for name, g0 in (("TOP 20 thanh khoản", df[df["rank"] <= 20]), ("cả 53 coin", df)):
        print(f"\n===== {name}")
        for how, label in (("A", "A · chạm vùng + nến 1H xác nhận (bot đang hướng dẫn)"), ("B", "B · lệnh chờ Limit giữa vùng")):
            g = g0[g0["how"] == how].sort_values("t")
            if not len(g):
                continue
            eq = g["R"].cumsum()
            mon = g.groupby(g["t"].dt.strftime("%Y-%m"))["R"].sum()
            print(f"  {label}\n    {len(g)} lệnh · có lời {(g['R'] > 0).mean():.0%} · TB {g['R'].mean():+.3f}R · "
                  f"2 năm gần {g[g['t'] >= two]['R'].mean():+.3f}R · sụt giảm tối đa {(eq.cummax() - eq).max():.0f}R · "
                  f"tháng lỗ {(mon < 0).mean():.0%} · SL TB {g['risk_pct'].mean():.1%}")
            print("    theo năm: " + " · ".join(f"{y}: {x['R'].mean():+.2f}R ({len(x)})" for y, x in g.groupby(g['t'].dt.year)))
            print("    LONG " + f"{g[g['side'] > 0]['R'].mean():+.3f}R ({(g['side'] > 0).sum()}) · SHORT "
                  f"{g[g['side'] < 0]['R'].mean():+.3f}R ({(g['side'] < 0).sum()})")
            print("    theo loại vùng: " + " · ".join(f"{z}: {x['R'].mean():+.3f}R ({len(x)})" for z, x in g.groupby("zone")))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if "--report" not in sys.argv:
        bases = sorted(p.stem for p in LONG.glob("*.pkl") if not p.stem.startswith("_"))
        with Pool(8) as pool:
            parts = [x for x in pool.imap_unordered(work, bases) if x is not None and len(x)]
        pd.concat(parts, ignore_index=True).to_pickle(OUT)
    report()
