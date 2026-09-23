"""Backtest chiến lược trên dữ liệu lịch sử Binance Futures.

    python -m app.backtest --days 180 --top 30

- Dùng đúng `build_features` / `score_frame` / `Trade` như bot live.
- Mô phỏng chính sách phát tín hiệu: tối đa N tín hiệu/ngày, mỗi coin 1 lệnh, nghỉ 12h sau khi đóng.
- Thử nhiều ngưỡng điểm, in bảng kết quả và lưu bảng hiệu chỉnh (tỉ lệ thắng theo mức điểm)
  vào app/strategy/calibration.json để bot hiển thị cho người dùng.

Lưu ý trung thực: danh sách top coin lấy theo khối lượng HIỆN TẠI (có thiên lệch sống sót);
OI / long-short / tin tức không có lịch sử miễn phí nên được tính điểm trung tính.
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
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from app.config import settings
from app.data import binance, http, macro
from app.strategy.core import build_features, score_frame
from app.strategy.trade import PARTIALS, Trade

log = logging.getLogger("backtest")
CACHE = Path(".cache")
CALIBRATION = Path(__file__).parent / "strategy" / "calibration.json"
COOLDOWN = timedelta(hours=12)


async def _load(symbol: str, days: int) -> dict:
    CACHE.mkdir(exist_ok=True)
    path = CACHE / f"{symbol}_{days}.pkl"
    if path.exists() and time.time() - path.stat().st_mtime < 6 * 3600:
        return pickle.loads(path.read_bytes())
    now_ms = int(time.time() * 1000)
    start = now_ms - (days + 12) * 86_400_000  # +12 ngày làm nền cho EMA
    data = {
        "h1": await binance.klines_since(symbol, "1h", start),
        "h4": await binance.klines_since(symbol, "4h", start - 40 * 86_400_000),
        "d1": await binance.klines_since(symbol, "1d", start - 300 * 86_400_000),
        "funding": await binance.funding_history(symbol, start),
    }
    path.write_bytes(pickle.dumps(data))
    return data


async def prepare(days: int, top: int) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    coins = await binance.universe(top, settings.min_quote_volume)
    fng = await macro.fear_greed_history()
    btc = await _load("BTCUSDT", days)
    feats, scores = {}, {}
    for coin in coins:
        try:
            d = btc if coin.symbol == "BTCUSDT" else await _load(coin.symbol, days)
            if len(d["h1"]) < 500 or len(d["d1"]) < 60:
                continue
            f = build_features(d["h1"], d["h4"], d["d1"], btc_h4=None if coin.symbol == "BTCUSDT" else btc["h4"],
                               fng=fng, funding=d["funding"])
            f = f[f.index >= f.index[0] + pd.Timedelta(days=12)]
            feats[coin.symbol] = f
            scores[coin.symbol] = score_frame(f)
            log.info("Đã chuẩn bị %s (%d nến 1H)", coin.symbol, len(f))
        except Exception as exc:  # noqa: BLE001
            log.warning("Bỏ qua %s: %s", coin.symbol, exc)
    return feats, scores


def run_policy(feats: dict, scores: dict, threshold: float, *, per_day: int, per_scan: int,
               max_open: int, hold_h: int, partials: list[tuple[float, float]] = PARTIALS) -> list[dict]:
    # gom ứng viên theo giờ
    by_hour: dict[pd.Timestamp, list] = defaultdict(list)
    for sym, sides in scores.items():
        for side, df in sides.items():
            for ts, row in df[df["score"] >= threshold].iterrows():
                by_hour[ts].append((row["score"], sym, side, row))

    trades: list[dict] = []
    busy_until: dict[str, pd.Timestamp] = {}
    open_trades: list[tuple[pd.Timestamp, pd.Timestamp]] = []  # (bắt đầu, kết thúc)
    per_day_count: dict = defaultdict(int)
    never = pd.Timestamp("1970-01-01", tz="UTC")

    for ts in sorted(by_hour):
        day = (ts + pd.Timedelta(hours=7)).date()  # tính ngày theo giờ VN
        n_open = sum(1 for a, b in open_trades if a <= ts < b)
        sent = 0
        for score, sym, side, row in sorted(by_hour[ts], key=lambda x: -x[0]):
            if sent >= per_scan or per_day_count[day] >= per_day or n_open >= max_open:
                break
            if busy_until.get(sym, never) > ts:
                continue
            f = feats[sym]
            start = ts + pd.Timedelta(hours=1)  # tín hiệu gửi khi nến 1H đóng
            t = Trade(side, row["entry"], row["sl"], created=start,
                      deadline=start + pd.Timedelta(hours=hold_h), partials=list(partials))
            future = f.loc[f.index > ts]
            for bts, b in zip(future.index, future[["high", "low", "close", "h4_atr"]].to_numpy()):
                t.step(bts + pd.Timedelta(hours=1), *b)
                if t.status != "ACTIVE":
                    break
            end = t.closed_at or (future.index[-1] if len(future) else start)
            busy_until[sym] = end + COOLDOWN
            open_trades.append((start, end))
            per_day_count[day] += 1
            n_open += 1
            sent += 1
            trades.append({"symbol": sym, "side": side, "score": score, "time": start, "outcome": t.outcome,
                           "r": t.realized_r, "won": t.won, "setup": row["setup_type"],
                           "incomplete": t.status == "ACTIVE"})
    return trades


def summarize(trades: list[dict], days: int) -> dict:
    done = [t for t in trades if not t["incomplete"]]
    if not done:
        return {"signals": len(trades), "per_day": round(len(trades) / days, 2), "closed": 0}
    r = np.array([t["r"] for t in done])
    eq = np.cumsum(r)
    monthly = pd.Series(r, index=pd.DatetimeIndex([t["time"] for t in done]).tz_convert(None)).resample("ME").sum()
    return {
        "signals": len(trades),
        "per_day": round(len(trades) / days, 2),
        "closed": len(done),
        "win_rate": round(float(np.mean(r > 0)), 3),
        "sl_rate": round(float(np.mean([t["outcome"] == "SL" for t in done])), 3),
        "avg_r": round(float(r.mean()), 3),
        "total_r": round(float(r.sum()), 1),
        "max_dd_r": round(float(np.max(np.maximum.accumulate(eq) - eq)), 1),
        "profit_factor": round(float(r[r > 0].sum() / max(1e-9, -r[r < 0].sum())), 2),
        "losing_months": f"{int((monthly < 0).sum())}/{len(monthly)}",
    }


def calibration(trades: list[dict]) -> dict:
    done = [t for t in trades if not t["incomplete"]]
    out = {}
    for lo in range(50, 100, 5):
        b = [t for t in done if lo <= t["score"] < lo + 5]
        if len(b) >= 10:
            out[str(lo)] = {"n": len(b), "win_rate": round(float(np.mean([t["r"] > 0 for t in b])), 3),
                            "avg_r": round(float(np.mean([t["r"] for t in b])), 3)}
    return out


def _parse_partials(text: str) -> list[tuple[float, float]]:
    if text in ("", "none"):
        return []
    return [(float(a), float(b)) for a, b in (x.split(":") for x in text.split(","))]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--top", type=int, default=settings.top_n)
    ap.add_argument("--thresholds", default="60,65,70,75,80")
    ap.add_argument("--partials", default=",".join(f"{a}:{b}" for a, b in PARTIALS),
                    help="các mốc chốt một phần 'R:tỉ lệ', vd '2:0.3,3:0.3' hoặc 'none' (chỉ trailing)")
    ap.add_argument("--split", type=float, default=0.6, help="in thêm kết quả riêng phần dữ liệu sau mốc này")
    ap.add_argument("--choose", type=float, help="chốt ngưỡng lưu vào calibration thay vì ngưỡng tự đề xuất")
    ap.add_argument("--save", action="store_true", help="lưu calibration.json cho ngưỡng tốt nhất")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.stdout.reconfigure(encoding="utf-8")

    feats, scores = await prepare(args.days, args.top)
    await http.close()
    days = args.days
    print(f"\n{len(feats)} coin, {days} ngày, tối đa {settings.max_signals_per_day} tín hiệu/ngày\n")
    partials = _parse_partials(args.partials)
    results = {}
    for th in [float(x) for x in args.thresholds.split(",")]:
        trades = run_policy(feats, scores, th, per_day=settings.max_signals_per_day,
                            per_scan=settings.max_signals_per_scan, max_open=settings.max_open_signals,
                            hold_h=settings.max_hold_hours, partials=partials)
        results[th] = (summarize(trades, days), trades)
        print(f"Ngưỡng {th:>4}: {results[th][0]}")
        cut = min(t["time"] for t in trades) + (max(t["time"] for t in trades) - min(t["time"] for t in trades)) * args.split
        late = [t for t in trades if t["time"] >= cut]
        print(f"   {int((1 - args.split) * 100)}% dữ liệu gần nhất: {summarize(late, max(1, days * (1 - args.split)))}")
        by_setup = defaultdict(list)
        for t in trades:
            if not t["incomplete"]:
                by_setup[(t["setup"], t["side"])].append(t["r"])
        for k, v in sorted(by_setup.items()):
            print(f"        {k[0]:>8} {'LONG' if k[1] > 0 else 'SHORT':>5}: n={len(v):4d} avgR={np.mean(v):+.3f}")

    eligible = {th: v for th, v in results.items() if v[0].get("closed", 0) >= 30 and 1 <= v[0]["per_day"] <= 5}
    if eligible:
        best = max(eligible, key=lambda th: eligible[th][0]["avg_r"] * eligible[th][0]["closed"] ** 0.5)
        print(f"\n=> Ngưỡng đề xuất: {best} {eligible[best][0]}")
        if args.choose is not None:
            best = args.choose
            print(f"=> Dùng ngưỡng chọn tay: {best} {results[best][0]}")
        if args.save:
            all_trades = results[min(results)][1]  # ngưỡng thấp nhất để có đủ mẫu cho mọi mức điểm
            CALIBRATION.write_text(json.dumps({
                "threshold": best, "days": days, "coins": len(feats), "partials": partials,
                "summary": results[best][0], "buckets": calibration(all_trades),
            }, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"Đã lưu {CALIBRATION}")

if __name__ == "__main__":
    asyncio.run(main())
