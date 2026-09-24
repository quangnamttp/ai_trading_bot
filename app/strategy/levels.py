"""Vùng giá quan trọng + kế hoạch DCA / vùng vào lệnh tham khảo cho 1 coin.

Mọi con số do bot tính từ dữ liệu Binance (AI chỉ trình bày lại, không tự nghĩ ra giá):
- Volume Profile 90 ngày (nến 4H): POC, VAH, VAL.
- Đáy / đỉnh 20, 60, 180 ngày; EMA50 / EMA200 khung ngày; ATR ngày.
Đây là kế hoạch tham khảo, KHÔNG phải tín hiệu đã được backtest như tín hiệu của bot.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app import indicators as ta
from app.data import binance


def volume_profile(df: pd.DataFrame, bins: int = 48, va: float = 0.70) -> tuple[float, float, float]:
    """(POC, VAH, VAL): mức giá nhiều khối lượng nhất và vùng chứa 70% khối lượng."""
    lo, hi = float(df["low"].min()), float(df["high"].max())
    if hi <= lo:
        return lo, hi, lo
    edges = np.linspace(lo, hi, bins + 1)
    typical = ((df["high"] + df["low"] + df["close"]) / 3).to_numpy()
    idx = np.clip(np.searchsorted(edges, typical, side="right") - 1, 0, bins - 1)
    vol = np.bincount(idx, weights=df["volume"].to_numpy(), minlength=bins)
    poc = int(vol.argmax())
    a = b = poc
    total, acc = vol.sum(), vol[poc]
    while acc < va * total and (a > 0 or b < bins - 1):
        down = vol[a - 1] if a > 0 else -1
        up = vol[b + 1] if b < bins - 1 else -1
        if up >= down:
            b += 1
            acc += vol[b]
        else:
            a -= 1
            acc += vol[a]
    mid = (edges[:-1] + edges[1:]) / 2
    return float(mid[poc]), float(edges[b + 1]), float(edges[a])


def _merge(levels: list[tuple[float, str]], tol: float) -> list[tuple[float, str]]:
    """Gộp các mức gần nhau (trong tol %) thành 1 vùng, giữ tên của các mức."""
    out: list[tuple[float, str]] = []
    for p, name in sorted(levels, key=lambda x: x[0]):
        if out and abs(p / out[-1][0] - 1) <= tol:
            q, n = out[-1]
            out[-1] = ((q + p) / 2, f"{n} + {name}")
        else:
            out.append((p, name))
    return out


def build_plan(d1: pd.DataFrame, h4: pd.DataFrame) -> dict:
    close = d1["close"]
    px = float(h4["close"].iloc[-1])
    e50, e200 = float(ta.ema(close, 50).iloc[-1]), float(ta.ema(close, 200).iloc[-1])
    atr = float(ta.atr(d1, 14).iloc[-1])
    poc, vah, val = volume_profile(h4.iloc[-540:])
    lv = [(poc, "POC 90 ngày"), (vah, "VAH 90 ngày"), (val, "VAL 90 ngày"), (e50, "EMA50 ngày")]
    if len(close) >= 200:
        lv.append((e200, "EMA200 ngày"))
    for n in (20, 60, 180):
        if len(d1) > n:
            lv += [(float(d1["low"].iloc[-n:].min()), f"đáy {n} ngày"), (float(d1["high"].iloc[-n:].max()), f"đỉnh {n} ngày")]
    zones = _merge(lv, 0.025)
    supports = [z for z in reversed(zones) if z[0] < px * 0.995][:3]
    resistances = [z for z in zones if z[0] > px * 1.005][:3]
    if px > e50 > e200 or (len(close) < 200 and px > e50):
        trend = "TĂNG (giá trên EMA50 ngày" + (", EMA50 trên EMA200)" if len(close) >= 200 else ")")
    elif px < e50 < e200 or (len(close) < 200 and px < e50):
        trend = "GIẢM (giá dưới EMA50 ngày" + (", EMA50 dưới EMA200)" if len(close) >= 200 else ")")
    else:
        trend = "ĐI NGANG / chưa rõ (giá và các đường EMA ngày đan xen)"
    dca = []
    if supports:
        weights = [0.3, 0.3, 0.4][:len(supports)]
        weights = [w / sum(weights) for w in weights]
        dca = [(p, name, w) for (p, name), w in zip(supports, weights)]
    stop = (supports[-1][0] if supports else px) - atr
    return {"price": px, "trend": trend, "atr": atr, "atr_pct": atr / px, "poc": poc, "vah": vah, "val": val,
            "supports": supports, "resistances": resistances, "dca": dca, "stop": stop,
            "chg7": px / float(close.iloc[-8]) - 1 if len(close) > 8 else None,
            "chg30": px / float(close.iloc[-31]) - 1 if len(close) > 31 else None}


async def coin_plan(symbol: str) -> dict:
    d1 = await binance.klines(symbol, "1d", 400)
    h4 = await binance.klines(symbol, "4h", 540, closed_only=False)  # giá hiện tại khớp giá sàn
    plan = build_plan(d1, h4)
    plan["symbol"] = symbol
    plan["display"] = binance.split_symbol(symbol)[0]
    return plan


def plan_context(p: dict, fmt=lambda x: f"{x:.6g}") -> str:
    """Kế hoạch dạng chữ để đưa vào ngữ cảnh AI (và làm câu trả lời dự phòng khi AI lỗi)."""
    lines = [f"KẾ HOẠCH DO BOT TÍNH cho {p['display']} (giá hiện tại {fmt(p['price'])}):",
             f"- Xu hướng khung ngày: {p['trend']}"]
    if p.get("chg7") is not None:
        lines.append(f"- Thay đổi 7 ngày {p['chg7']:+.1%}, 30 ngày {p['chg30']:+.1%}" if p.get("chg30") is not None
                     else f"- Thay đổi 7 ngày {p['chg7']:+.1%}")
    lines.append(f"- Biến động TB 1 ngày (ATR): {fmt(p['atr'])} ({p['atr_pct']:.1%})")
    lines.append("- Hỗ trợ gần nhất: " + ("; ".join(f"{fmt(x)} ({n})" for x, n in p["supports"]) or "không có (giá ở đáy vùng)"))
    lines.append("- Kháng cự gần nhất: " + ("; ".join(f"{fmt(x)} ({n})" for x, n in p["resistances"]) or "không có (giá ở đỉnh vùng)"))
    if p["dca"]:
        lines.append("- DCA tham khảo (Spot, chia vốn): " + "; ".join(f"{w:.0%} vốn tại {fmt(x)}" for x, _, w in p["dca"]))
        lines.append(f"- Dừng DCA / xem lại nếu nến ngày đóng dưới {fmt(p['stop'])} (hỗ trợ cuối − 1 ATR)")
    lines.append("- Vùng vào LONG tham khảo: gần các mức hỗ trợ trên; vùng SHORT tham khảo: gần các mức kháng cự. "
                 "Chỉ vào khi có tín hiệu xác nhận (tín hiệu của bot / nến đảo chiều), SL ngoài vùng khoảng 1 ATR.")
    return "\n".join(lines)
