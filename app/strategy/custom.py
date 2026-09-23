"""Điểm xác nhận từ 2 chỉ báo TradingView của bạn (tradingview/*.pine) + FVG.

Logic chỉ báo được chuyển sang Python trong `tv_indicators.py`. Kết quả backtest 1 năm / 30 coin (09/2026):
  - Dùng RIÊNG với SL 1.2 / TP 2.0 ATR gốc: cả 6 loại tín hiệu đều lỗ (-0.06 .. -0.23R/lệnh).
  - Làm XÁC NHẬN (cộng 3-5 điểm): kết quả chính sách thật đều KÉM hơn không cộng
    (+0.19R -> +0.10..0.16R/lệnh, sụt giảm tăng từ 41R lên 43-57R).
=> Mặc định tắt (0). Muốn thử lại: sửa `WEIGHTS` rồi chạy `python -m app.backtest --days 365 --top 30`.
"""
from __future__ import annotations

import pandas as pd

WEIGHTS = {
    "votes3": 0.0,  # Swing Entry Pro: cả 3 khung D1/H4/H1 cùng xu hướng (EMA 9/21)
    "fvg4": 0.0,    # giá chạm vùng FVG 4H thuận hướng trong 4 nến gần nhất
    "sep": 0.0,     # có tín hiệu MUA/BÁN của Swing Entry Pro trong 4 nến gần nhất
    "vp": 0.0,      # có tín hiệu VP★ của Volume Profile Pro trong 4 nến gần nhất
}


def score(f: pd.DataFrame, side: int) -> pd.Series:
    if "tv_votes_bull" not in f:
        return pd.Series(0.0, index=f.index)
    up = side > 0
    votes = f["tv_votes_bull"] if up else f["tv_votes_bear"]
    parts = [
        WEIGHTS["votes3"] * (votes == 3),
        WEIGHTS["fvg4"] * f["tv_fvg4_bull" if up else "tv_fvg4_bear"],
        WEIGHTS["sep"] * f["tv_sep_buy" if up else "tv_sep_sell"],
        WEIGHTS["vp"] * f["tv_vp_buy" if up else "tv_vp_sell"],
    ]
    return sum(p.astype(float) for p in parts)
