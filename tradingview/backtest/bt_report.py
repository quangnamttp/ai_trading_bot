"""Báo cáo backtest nghiệm thu Swing Entry Pro v6.1 (chạy sau bt_swing.py)."""
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))
from bt_swing import LONG, stats  # noqa: E402

df = pd.read_pickle(Path(__file__).with_name("bt_swing.pkl"))
vols = {p.stem: pickle.loads(p.read_bytes())["1d"]["quote_vol"].rolling(30).sum()
        for p in LONG.glob("*.pkl") if not p.stem.startswith("_")}
rank = pd.DataFrame(vols).rank(axis=1, ascending=False)
rank.index = pd.to_datetime(rank.index, utc=True) + pd.Timedelta(days=1)
rk = rank.stack().rename("rank").reset_index()
rk.columns = ["day", "base", "rank"]
df["day"] = df["t"].dt.floor("D")
df = df.merge(rk, on=["day", "base"], how="left")
top = df[df["rank"] <= 20]
recent = pd.Timestamp("2024-09-25", tz="UTC")

for tf in ("1h", "4h"):
    g = top[top["tf"] == tf]
    print(f"\n===== Swing Entry Pro v6.1 — khung {tf.upper()} (top 20 coin thanh khoản tại thời điểm tín hiệu)")
    stats(g, "9 năm (2017-2026)")
    stats(g[g["t"] >= pd.Timestamp("2021-07-01", tz="UTC")], "từ 07/2021 (có dữ liệu OI)")
    stats(g[g["t"] >= recent], "2 năm gần nhất")
    stats(g[g["t"] >= pd.Timestamp("2025-09-25", tz="UTC")], "12 tháng gần nhất")
    stats(g[g["side"] > 0], "chỉ MUA (Spot dùng được)")
    stats(g[g["side"] < 0], "chỉ BÁN")
    stats(g[g["grade"] == "A"], "hạng A")
    stats(g[g["grade"] == "B"], "hạng B")
    stats(df[df["tf"] == tf], "cả 53 coin (không lọc thanh khoản)")
    print("  Theo năm:", " · ".join(f"{y}: {x['R'].mean():+.2f}R ({len(x)})" for y, x in g.groupby(g["t"].dt.year)))
    per_mon = len(g[g["t"] >= recent]) / 24
    print(f"  Số lệnh TB / tháng (2 năm gần, top 20): {per_mon:.0f} — tức ~{per_mon / 20:.1f} lệnh / coin / tháng")
    print(f"  Giữ lệnh TB: {((g['exit_t'] - g['t']).dt.total_seconds() / 3600).median():.0f} giờ (trung vị)")
    print("  Phân bố R: lỗ đủ 1R " f"{(g['R'] <= -0.95).mean():.0%} · lời >= 2R {(g['R'] >= 2).mean():.0%} · "
          f"lời >= 5R {(g['R'] >= 5).mean():.0%} · chuỗi thua dài nhất "
          f"{max((len(list(x)) for k, x in __import__('itertools').groupby(g.sort_values('t')['R'] <= 0) if k), default=0)}")
    # lời khuyên dòng 🧱: kháng cự phía trước gần (< 1R) có làm lệnh kém đi không
    for lo, hi, name in ((0, 1, "< 1R"), (1, 2, "1–2R"), (2, 99, ">= 2R")):
        m = (g["res_r"] >= lo) & (g["res_r"] < hi)
        x = g[m]
        print(f"  Vùng cản phía trước {name:6s}: {len(x):5d} lệnh · TB {x['R'].mean():+.3f}R · có lời {(x['R'] > 0).mean():.0%}"
              f" · 2 năm gần {x[x['t'] >= recent]['R'].mean():+.3f}R")
    x = g[g["res_r"].isna()]
    print(f"  Không có vùng cản phía trước: {len(x)} lệnh · TB {x['R'].mean():+.3f}R")
