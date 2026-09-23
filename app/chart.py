"""Vẽ biểu đồ tín hiệu phong cách TradingView (nền tối, hộp vị thế Long/Short, nhãn giá bên phải)."""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from app import indicators as ta  # noqa: E402
from app.config import VN_TZ  # noqa: E402

BG, GRID, TEXT, MUTED = "#131722", "#1e222d", "#d1d4dc", "#787b86"
UP, DOWN, EMA_FAST, EMA_SLOW = "#26a69a", "#ef5350", "#2962ff", "#ff9800"
TP_FILL, SL_FILL = (0.15, 0.65, 0.6, 0.18), (0.94, 0.33, 0.31, 0.18)


def _fmt(p: float) -> str:
    if p >= 1000:
        return f"{p:,.1f}"
    if p >= 1:
        return f"{p:,.4f}".rstrip("0").rstrip(".")
    return f"{p:.8f}".rstrip("0")


def _tag(ax, y: float, text: str, color: str) -> None:
    ax.annotate(text, xy=(1.0, y), xycoords=("axes fraction", "data"), xytext=(4, 0), textcoords="offset points",
                va="center", ha="left", fontsize=8.5, color="white", fontweight="bold",
                bbox=dict(boxstyle="square,pad=0.25", fc=color, ec=color))


def render(h1: pd.DataFrame, *, title: str, side: int, entry: float, sl: float, tp1: float, tp2: float,
           zone_lo: float, zone_hi: float, subtitle: str = "", bars: int = 110) -> bytes:
    df = h1.tail(bars + 60).copy()
    df["ema20"], df["ema50"] = ta.ema(df["close"], 20), ta.ema(df["close"], 50)
    df = df.tail(bars)
    x = mdates.date2num(df.index.tz_convert(VN_TZ).tz_localize(None).to_pydatetime())
    w = (x[1] - x[0]) * 0.7 if len(x) > 1 else 0.02
    step = x[1] - x[0] if len(x) > 1 else 1 / 24
    future = 28  # số nến trống bên phải để vẽ hộp vị thế

    fig = plt.figure(figsize=(10, 6), dpi=110, facecolor=BG)
    gs = fig.add_gridspec(2, 1, height_ratios=[4, 1], hspace=0.03, left=0.02, right=0.88, top=0.9, bottom=0.07)
    ax, axv = fig.add_subplot(gs[0]), fig.add_subplot(gs[1])
    for a in (ax, axv):
        a.set_facecolor(BG)
        a.grid(color=GRID, linewidth=0.8)
        a.tick_params(colors=MUTED, labelsize=8, length=0)
        a.yaxis.tick_right()
        for sp in a.spines.values():
            sp.set_visible(False)

    colors = [UP if c >= o else DOWN for o, c in zip(df["open"], df["close"])]
    ax.vlines(x, df["low"], df["high"], colors=colors, linewidth=0.9)
    ax.bar(x, (df["close"] - df["open"]).abs().clip(lower=(df["high"] - df["low"]).max() * 0.002),
           bottom=df[["open", "close"]].min(axis=1), width=w, color=colors, linewidth=0)
    ax.plot(x, df["ema20"], color=EMA_FAST, linewidth=1.2, label="EMA 20")
    ax.plot(x, df["ema50"], color=EMA_SLOW, linewidth=1.2, label="EMA 50")

    # Hộp vị thế kiểu TradingView
    x0, x1 = x[-1] + step * 0.5, x[-1] + step * future
    ax.add_patch(Rectangle((x0, min(entry, tp1)), x1 - x0, abs(tp1 - entry), fc=TP_FILL, ec="none"))
    ax.add_patch(Rectangle((x0, min(entry, sl)), x1 - x0, abs(sl - entry), fc=SL_FILL, ec="none"))
    ax.add_patch(Rectangle((x[-12], zone_lo), x1 - x[-12], max(zone_hi - zone_lo, entry * 1e-4),
                           fc=(0.16, 0.38, 1, 0.22), ec="none"))
    for y, c, ls in ((entry, TEXT, "-"), (sl, DOWN, "-"), (tp1, UP, "-"), (tp2, UP, "--")):
        ax.hlines(y, x0, x1, colors=c, linewidth=1.1, linestyles=ls)
    _tag(ax, tp2, f"TP2 {_fmt(tp2)}", "#1b7f75")
    _tag(ax, tp1, f"TP1 {_fmt(tp1)}", UP)
    _tag(ax, entry, f"ENTRY {_fmt(entry)}", "#2962ff")
    _tag(ax, sl, f"SL {_fmt(sl)}", DOWN)
    ax.plot([x0 - step * 0.5], [df["close"].iloc[-1]], marker="o", color="white", markersize=4)

    lo = min(df["low"].min(), sl, tp2)
    hi = max(df["high"].max(), sl, tp2)
    pad = (hi - lo) * 0.05
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_xlim(x[0] - step, x1 + step)
    ax.set_xticklabels([])
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _fmt(v)))
    ax.legend(loc="upper left", fontsize=8, facecolor=BG, edgecolor=GRID, labelcolor=TEXT)

    axv.bar(x, df["volume"], width=w, color=[(*matplotlib.colors.to_rgb(c), 0.55) for c in colors])
    axv.set_xlim(ax.get_xlim())
    axv.set_yticklabels([])
    axv.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m %H:%M"))
    axv.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=7))

    color = UP if side > 0 else DOWN
    fig.text(0.02, 0.955, title, color=TEXT, fontsize=13, fontweight="bold", va="center")
    fig.text(0.02, 0.92, subtitle, color=MUTED, fontsize=9, va="center")
    fig.text(0.88, 0.955, "LONG" if side > 0 else "SHORT", color="white", fontsize=11, fontweight="bold",
             ha="right", va="center", bbox=dict(boxstyle="round,pad=0.35", fc=color, ec=color))

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()
