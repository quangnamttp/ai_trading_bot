"""Backtest 2 năm cho cả 2 kiểu swing — cùng chiến lược, cùng cổng chất lượng, cùng cách thoát lệnh như bot live.

    python -m app.backtest --download          # tải/cập nhật dữ liệu (lần đầu ~15 phút)
    python -m app.backtest --save              # chạy backtest + lưu app/strategy/calibration.json

Quy trình (chống "học vẹt" quá khứ):
- Dữ liệu Binance (nến, funding) + Bybit (lịch sử OI, tỉ lệ long/short), top 40 coin hiện tại.
- Mỗi ngày xếp hạng lại top N theo khối lượng 30 ngày trước đó (như bot live), bỏ coin niêm yết < 90 ngày.
- Chính sách y như bot: giới hạn tín hiệu/ngày, tối đa 2 lệnh cùng chiều, giờ yên lặng, hạng B, cooldown.
- In kết quả riêng 60% dữ liệu đầu / 40% dữ liệu sau — cấu hình chỉ được chọn nếu tốt ở CẢ HAI phần.

Hạn chế: danh sách coin lấy theo hiện tại (thiên lệch sống sót); tin tức không có lịch sử nên không backtest được.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import pickle
import sys
import time
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

from app.data import binance, bybit, macro
from app.data.http import get_json
from app.strategy.core import build_features, quality_gate, score_frame
from app.strategy.trade import BE_AT_R, CALLBACK_ATR, FEE_RATE, MAX_CALLBACK, MIN_CALLBACK, PARTIALS

log = logging.getLogger("backtest")
CACHE = Path(".cache/hist")
CALIBRATION = Path(__file__).parent / "strategy" / "calibration.json"
DAYS = 730
VN = pd.Timedelta(hours=7)

# kiểu giao dịch -> (khung setup, xu hướng, bối cảnh), cửa sổ OI (giờ), giữ tối đa (nến), cooldown (giờ)
STYLES = {
    "short": dict(tfs=("1h", "4h", "1d"), oi_hours=24, hold=24 * 7, cooldown=12, threshold=75, tier_b=70,
                  per_day=3, hours=(6, 22), top=20),
    "long": dict(tfs=("4h", "1d", "1w"), oi_hours=72, hold=6 * 30, cooldown=72, threshold=70, tier_b=None,
                 per_day=1, hours=None, top=20),
}
BAR_H = {"1h": 1, "4h": 4, "1d": 24, "1w": 168}


# ---------------------------------------------------------------- dữ liệu
async def _funding_all(symbol: str, start_ms: int) -> pd.Series:
    out, t = [], start_ms
    while True:
        rows = await get_json(f"{binance.FAPI[0]}/fapi/v1/fundingRate", {"symbol": symbol, "limit": 1000, "startTime": t})
        out += rows
        if len(rows) < 1000:
            break
        t = int(rows[-1]["fundingTime"]) + 1
    s = pd.Series({pd.Timestamp(int(r["fundingTime"]), unit="ms", tz="UTC"): float(r["fundingRate"]) for r in out})
    return s[~s.index.duplicated()].sort_index()


async def download(top: int = 40) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    listed = await binance.listing_dates()
    coins = await binance.universe(top, 20_000_000)
    (CACHE / "universe.pkl").write_bytes(pickle.dumps([(c, listed.get(c.symbol)) for c in coins]))
    (CACHE / "fng.pkl").write_bytes(pickle.dumps(await macro.fear_greed_history()))
    now = int(time.time() * 1000)
    start = now - DAYS * 86_400_000
    for c in coins:
        p = CACHE / f"{c.symbol}.pkl"
        if p.exists() and time.time() - p.stat().st_mtime < 20 * 3600:
            continue
        for attempt in range(5):
            try:
                d = {
                    "1h": await binance.klines_since(c.symbol, "1h", start - 20 * 86_400_000),
                    "4h": await binance.klines_since(c.symbol, "4h", start - 80 * 86_400_000),
                    "1d": await binance.klines_since(c.symbol, "1d", start - 400 * 86_400_000),
                    "1w": await binance.klines_since(c.symbol, "1w", start - 1200 * 86_400_000),
                    "funding": await _funding_all(c.symbol, start - 30 * 86_400_000),
                    "oi": await bybit.open_interest(c.symbol, start - 10 * 86_400_000, now),
                    "ls": await bybit.long_short(c.symbol, start - 10 * 86_400_000, now),
                }
                p.write_bytes(pickle.dumps(d))
                print(f"  tải xong {c.symbol}", flush=True)
                break
            except Exception as exc:  # noqa: BLE001
                print(f"  {c.symbol} lỗi {exc}, thử lại sau 60s", flush=True)
                await asyncio.sleep(60)
        await asyncio.sleep(2)


def _load(sym: str) -> dict:
    return pickle.loads((CACHE / f"{sym}.pkl").read_bytes())


def _universe() -> list:
    return pickle.loads((CACHE / "universe.pkl").read_bytes())


# ---------------------------------------------------------------- mô phỏng lệnh (bản nhanh của Trade, có test đối chiếu)
def simulate(H, L, C, A, i: int, side: int, entry: float, sl: float, hold: int) -> tuple[float, int, str]:
    """Như Trade(exit_mode="pct"): SL cố định, chốt 50% tại 2R, trailing stop sàn kích hoạt ở +1R với callback
    = CALLBACK_ATR x ATR(khung xu hướng) / giá vào (giới hạn như sàn). SL kiểm tra trước trong mỗi nến.
    Trả (R, số nến giữ, kết quả)."""
    s, risk = side, abs(entry - sl)
    fee = FEE_RATE * entry / risk
    cb = min(MAX_CALLBACK, max(MIN_CALLBACK, CALLBACK_ATR * A[i] / entry))
    tp_r, part = PARTIALS[0]
    stop, rem, R, hit, armed, peak = sl, 1.0, 0.0, False, False, entry
    end = min(i + 1 + hold, len(H))
    for j in range(i + 1, end):
        adv, fav = (L[j], H[j]) if s > 0 else (H[j], L[j])
        eff = stop
        if armed:
            t = peak * (1 - cb) if s > 0 else peak * (1 + cb)
            eff = max(stop, t) if s > 0 else min(stop, t)
        if (eff - adv) * s >= 0:
            R += rem * (eff - entry) * s / risk
            return R - fee, j - i, "SL" if (eff == stop and not hit) else "TRAIL"
        r_fav = (fav - entry) * s / risk
        if not hit and r_fav >= tp_r:
            R += part * tp_r
            rem -= part
            hit = True
        if not armed and r_fav >= BE_AT_R:
            armed, peak = True, fav
        elif armed:
            peak = max(peak, fav) if s > 0 else min(peak, fav)
    j = end - 1
    return R + rem * (C[j] - entry) * s / risk - fee, j - i, "TIMEOUT"


def _asof(index_avail: pd.Series, s: pd.Series, lag_h: int = 4) -> np.ndarray:
    """Giá trị chuỗi (OI/LS 4h Bybit) tại thời điểm tín hiệu — chỉ dùng mốc đã kết thúc."""
    if s is None or not len(s):
        return np.full(len(index_avail), np.nan)
    left = pd.DataFrame({"avail": index_avail.astype("datetime64[ns, UTC]").reset_index(drop=True)})
    r = pd.DataFrame({"avail": (s.index + pd.Timedelta(hours=lag_h)).astype("datetime64[ns, UTC]"), "v": s.values})
    return pd.merge_asof(left, r.sort_values("avail"), on="avail", direction="backward")["v"].to_numpy()


def candidates_for(args: tuple) -> pd.DataFrame | None:
    sym, style = args
    cfg = STYLES[style]
    try:
        d, btc = _load(sym), _load("BTCUSDT")
        fng = pickle.loads((CACHE / "fng.pkl").read_bytes())
        b, m, h = cfg["tfs"]
        f = build_features(d[b], d[m], d[h], btc_h4=None if sym == "BTCUSDT" else btc[m], fng=fng, funding=d["funding"])
        sc = score_frame(f)
    except Exception as exc:  # noqa: BLE001
        log.warning("bỏ qua %s: %s", sym, exc)
        return None
    oi = _asof(f["avail"], d["oi"])
    ls = _asof(f["avail"], d["ls"])
    lag = int(cfg["oi_hours"] / BAR_H[b])
    oi_chg = oi / np.roll(oi, lag) - 1
    oi_chg[:lag] = np.nan
    H, L, C, A = (f[k].to_numpy() for k in ("high", "low", "close", "h4_atr"))
    rows = []
    min_th = min(cfg["threshold"], cfg["tier_b"] or 999)
    for side, df in sc.items():
        for i in np.flatnonzero(df["score"].to_numpy() >= min_th):
            if i >= len(H) - 2 or np.isnan(A[i]):
                continue
            r = df.iloc[i]
            gate = quality_gate(side, r["setup_type"], None if np.isnan(oi_chg[i]) else float(oi_chg[i] * side),
                                None if np.isnan(ls[i]) else float(ls[i]), style)
            if gate:
                continue
            R, bars, out = simulate(H, L, C, A, i, side, r["entry"], r["sl"], cfg["hold"])
            rows.append({"sym": sym, "ts": f.index[i], "side": side, "score": r["score"], "setup": r["setup_type"],
                         "R": R, "bars": bars, "outcome": out})
    return pd.DataFrame(rows)


def build_candidates(style: str) -> pd.DataFrame:
    syms = [c.symbol for c, _ in _universe()]
    with Pool(8) as pool:
        parts = [p for p in pool.imap_unordered(candidates_for, [(s, style) for s in syms]) if p is not None and len(p)]
    return pd.concat(parts, ignore_index=True)


# ---------------------------------------------------------------- chính sách phát tín hiệu
def daily_rank() -> pd.DataFrame:
    vols = {c.symbol: _load(c.symbol)["1d"]["quote_vol"].rolling(30, min_periods=10).mean().shift(1)
            for c, _ in _universe()}
    r = pd.DataFrame(vols).rank(axis=1, ascending=False)
    r.index = r.index.tz_convert(None).normalize()
    return r


def run_policy(c: pd.DataFrame, style: str, *, spot: bool = False, min_age_days: int = 90, **over) -> pd.DataFrame:
    cfg = {**STYLES[style], **over}
    bar = pd.Timedelta(hours=BAR_H[cfg["tfs"][0]])
    x = c.copy()
    x["t"] = x["ts"] + bar
    rk = daily_rank().stack().rename("rank").reset_index()
    rk.columns = ["day", "sym", "rank"]
    x["day"] = x["t"].dt.tz_convert(None).dt.normalize()
    x = x.merge(rk, on=["day", "sym"], how="left")
    listed = {c.symbol: ob for c, ob in _universe()}
    x["age"] = (x["t"] - x["sym"].map(listed)).dt.days.fillna(9999)
    x = x[(x["rank"] <= cfg["top"]) & (x["age"] >= min_age_days)]
    if spot:
        x = x[x.side > 0]
    if cfg["hours"]:
        h = (x["t"] + VN).dt.hour
        x = x[(h >= cfg["hours"][0]) & (h < cfg["hours"][1])]
    x = x.sort_values(["t", "score"], ascending=[True, False])
    th, tb = cfg["threshold"], cfg["tier_b"]
    trades, busy, opened, per_day = [], {}, [], defaultdict(int)
    never = pd.Timestamp("1970-01-01", tz="UTC")
    for t, g in x.groupby("t", sort=True):
        d, hour = (t + VN).date(), (t + VN).hour
        opened = [(sd, e) for sd, e in opened if e > t]
        sent = 0
        for r in g.itertuples(index=False):
            if sent >= 2 or per_day[d] >= cfg["per_day"] or len(opened) >= 6:
                break
            if r.score < th and (not tb or per_day[d] > 0 or hour < 15):
                continue
            if busy.get(r.sym, never) > t or sum(1 for sd, _ in opened if sd == r.side) >= 2:
                continue
            end = t + bar * (r.bars + 1)
            busy[r.sym] = end + pd.Timedelta(hours=cfg["cooldown"])
            opened.append((r.side, end))
            per_day[d] += 1
            sent += 1
            trades.append({"t": t, "sym": r.sym, "side": r.side, "score": r.score, "R": r.R, "outcome": r.outcome})
    return pd.DataFrame(trades)


def stats(tr: pd.DataFrame, days: float) -> dict:
    if not len(tr):
        return {"n": 0}
    r = tr["R"].to_numpy()
    eq = np.cumsum(r)
    m = pd.Series(r, index=tr["t"].dt.tz_convert(None)).resample("ME").sum()
    return {"n": len(r), "per_day": round(len(r) / days, 2), "win": round(float((r > 0).mean()), 3),
            "avgR": round(float(r.mean()), 3), "totR": round(float(r.sum()), 1),
            "PF": round(float(r[r > 0].sum() / max(1e-9, -r[r < 0].sum())), 2),
            "DD": round(float((np.maximum.accumulate(eq) - eq).max()), 1), "lose_m": f"{int((m < 0).sum())}/{len(m)}"}


def report(tr: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    cut = start + (end - start) * 0.6
    s = stats(tr, (end - start).days)
    s["first_half_avgR"] = stats(tr[tr.t < cut], (cut - start).days).get("avgR")
    s["second_half_avgR"] = stats(tr[tr.t >= cut], (end - cut).days).get("avgR")
    return s


def buckets(tr: pd.DataFrame) -> dict:
    out = {}
    for lo in range(70, 100, 5):
        b = tr[(tr.score >= lo) & (tr.score < lo + 5)]
        if len(b) >= 20:
            out[str(lo)] = {"n": int(len(b)), "win_rate": round(float((b.R > 0).mean()), 3),
                            "avg_r": round(float(b.R.mean()), 3)}
    if not out and len(tr):
        out["70"] = {"n": int(len(tr)), "win_rate": round(float((tr.R > 0).mean()), 3), "avg_r": round(float(tr.R.mean()), 3)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true", help="tải/cập nhật dữ liệu lịch sử")
    ap.add_argument("--styles", default="short,long")
    ap.add_argument("--save", action="store_true", help="lưu calibration.json")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    sys.stdout.reconfigure(encoding="utf-8")
    if args.download or not (CACHE / "universe.pkl").exists():
        print("Đang tải dữ liệu lịch sử...")
        asyncio.run(download())

    out = {"generated": pd.Timestamp.now(tz="UTC").isoformat(), "data": f"Binance/Bybit {DAYS} ngày, top 40 coin",
           "styles": {}}
    for style in args.styles.split(","):
        c = build_candidates(style)
        bar = pd.Timedelta(hours=BAR_H[STYLES[style]["tfs"][0]])
        start, end = (c.ts + bar).min(), (c.ts + bar).max()
        print(f"\n===== {style}: {len(c)} ứng viên qua cổng chất lượng ({start.date()} -> {end.date()})")
        for label, kw in (("Futures", {}), ("Spot (chỉ LONG)", {"spot": True})):
            tr = run_policy(c, style, **kw)
            rep = report(tr, start, end)
            print(f"  {label:16s} {rep}")
            if not kw:
                out["styles"][style] = {"threshold": STYLES[style]["threshold"], "tier_b": STYLES[style]["tier_b"],
                                        "summary": rep, "buckets": buckets(tr)}
            else:
                out["styles"][style]["spot_summary"] = rep
    if args.save:
        CALIBRATION.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"\nĐã lưu {CALIBRATION}")


if __name__ == "__main__":
    main()
