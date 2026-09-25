"""Chiến lược swing ngắn hạn đa khung (1D xu hướng lớn / 4H xu hướng + vùng giá trị / 1H thời điểm).

Ý tưởng: chỉ đánh THUẬN xu hướng, vào lệnh ngay lúc setup vừa hình thành — trước khi giá chạy
tiếp — thay vì đuổi theo sau khi đã chạy. Có 2 kiểu setup:
  - PULLBACK: xu hướng 4H khỏe, giá hồi về vùng EMA20 4H và bắt đầu bật lại.
  - RETEST: vừa phá đỉnh/đáy 48 nến 1H với volume lớn, giá còn sát mốc vừa phá.
(Backtest cho thấy đặt limit chờ hồi sâu hơn cho kết quả TỆ hơn vì lệnh chỉ khớp khi giá đi ngược.)

Điểm 0-100 = tổng 6 nhóm dữ liệu độc lập:
  Xu hướng 30 | Động lượng 15 | Setup 20 | Dòng tiền (taker/CVD/volume) 15 |
  Phái sinh (funding/OI/long-short) 10 | Thị trường chung (BTC, Fear&Greed, thanh khoản, tin tức) 10

Hàm `score_frame` chạy trên toàn bộ DataFrame nên backtest và live dùng CHUNG một logic.
Các dữ liệu không có lịch sử (OI, L/S, tin tức, stablecoin) nhận điểm trung tính trong backtest
và được chấm thật khi chạy live bằng `apply_live_context`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app import indicators as ta
from app.strategy import custom
from app.strategy.tv_indicators import tv_features
from app.strategy.trade import BE_AT_R, TARGET_R

MIN_FLOW = 8      # điểm dòng tiền tối thiểu
FNG_PANIC = 13    # Fear & Greed <= mức này thì đứng ngoài
NEUTRAL_LIVE = {"oi": 2.0, "ls": 1.5, "liquidity": 0.5, "news": 1.0}


# ---------------------------------------------------------------- features
def _h4_features(h4: pd.DataFrame) -> pd.DataFrame:
    adx, pdi, mdi = ta.adx(h4)
    return pd.DataFrame({
        "avail": h4["close_time"],
        "h4_close": h4["close"],
        "h4_ema20": ta.ema(h4["close"], 20),
        "h4_ema50": ta.ema(h4["close"], 50),
        "h4_ema200": ta.ema(h4["close"], 200),
        "h4_rsi": ta.rsi(h4["close"]),
        "h4_atr": ta.atr(h4),
        "h4_adx": adx, "h4_pdi": pdi, "h4_mdi": mdi,
    })


def _d1_features(d1: pd.DataFrame) -> pd.DataFrame:
    e50 = ta.ema(d1["close"], 50)
    return pd.DataFrame({
        "avail": d1["close_time"],
        "d1_close": d1["close"],
        "d1_ema50": e50,
        "d1_ema50_slope": e50 - e50.shift(5),
        "d1_hh20": d1["high"].rolling(20).max(),
        "d1_ll20": d1["low"].rolling(20).min(),
    })


def _btc_trend(btc_h4: pd.DataFrame) -> pd.DataFrame:
    e20, e50 = ta.ema(btc_h4["close"], 20), ta.ema(btc_h4["close"], 50)
    trend = np.where((btc_h4["close"] > e50) & (e20 > e50), 1, np.where((btc_h4["close"] < e50) & (e20 < e50), -1, 0))
    return pd.DataFrame({"avail": btc_h4["close_time"], "btc_trend": trend})


def _asof(left: pd.DataFrame, right: pd.DataFrame) -> pd.DataFrame:
    """Ghép dữ liệu khung lớn vào khung 1H chỉ khi nến khung lớn ĐÃ ĐÓNG (tránh nhìn trước tương lai)."""
    right = right.dropna(subset=["avail"]).sort_values("avail")
    left, right = left.copy(), right.copy()
    left["avail"] = left["avail"].astype("datetime64[ns, UTC]")
    right["avail"] = right["avail"].astype("datetime64[ns, UTC]")
    return pd.merge_asof(left.sort_values("avail"), right, on="avail", direction="backward")


def build_features(h1: pd.DataFrame, h4: pd.DataFrame, d1: pd.DataFrame, *, btc_h4: pd.DataFrame | None = None,
                   fng: pd.Series | None = None, funding: pd.Series | None = None) -> pd.DataFrame:
    f = pd.DataFrame(index=h1.index)
    for c in ("open", "high", "low", "close", "volume", "taker_buy_vol"):
        f[c] = h1[c]
    f["avail"] = h1["close_time"]
    f["ema20"] = ta.ema(h1["close"], 20)
    f["rsi"] = ta.rsi(h1["close"])
    f["macd_hist"] = ta.macd_hist(h1["close"])
    f["vol_sma20"] = h1["volume"].rolling(20).mean()
    f["vol_ma3"] = h1["volume"].rolling(3).mean()
    buy_ratio = (h1["taker_buy_vol"] / h1["volume"].replace(0, np.nan)).fillna(0.5)
    f["buy_ratio3"] = buy_ratio.rolling(3).mean()
    delta = 2 * h1["taker_buy_vol"] - h1["volume"]
    f["cvd24"] = delta.rolling(24).sum() / h1["volume"].rolling(24).sum().replace(0, np.nan)
    f["hh48"] = h1["high"].rolling(48).max().shift(1)
    f["ll48"] = h1["low"].rolling(48).min().shift(1)
    f["hh12"] = h1["high"].rolling(12).max()
    f["ll12"] = h1["low"].rolling(12).min()
    f["swing_low24"] = h1["low"].rolling(24).min()
    f["swing_high24"] = h1["high"].rolling(24).max()

    idx = f.index
    f = _asof(f.reset_index(), _h4_features(h4))
    f = _asof(f, _d1_features(d1))
    if btc_h4 is not None:
        f = _asof(f, _btc_trend(btc_h4))
    else:  # chính BTC: dùng xu hướng 4H của nó
        f["btc_trend"] = np.where((f["h4_close"] > f["h4_ema50"]) & (f["h4_ema20"] > f["h4_ema50"]), 1,
                                  np.where((f["h4_close"] < f["h4_ema50"]) & (f["h4_ema20"] < f["h4_ema50"]), -1, 0))
    if fng is not None and len(fng):
        f = _asof(f, pd.DataFrame({"avail": fng.index + pd.Timedelta(days=1), "fng": fng.values}))
    else:
        f["fng"] = 50
    if funding is not None and len(funding):
        f = _asof(f, pd.DataFrame({"avail": funding.index, "funding": funding.values}))
    else:
        f["funding"] = 0.0
    f["fng"] = f["fng"].fillna(50)
    f["funding"] = f["funding"].fillna(0.0)
    f = f.set_index("open_time").reindex(idx)
    return f.join(tv_features(h1, h4, d1)) if custom.enabled() else f


# ---------------------------------------------------------------- scoring
def _pts(cond, pts: float) -> np.ndarray:
    return np.where(cond, pts, 0.0)


def _side_scores(f: pd.DataFrame, side: int) -> pd.DataFrame:
    """side=+1 LONG, -1 SHORT. Trả về điểm từng nhóm + kiểu setup + vùng vào lệnh/SL/TP."""
    s = side
    atr4 = f["h4_atr"]
    above = lambda a, b: (a - b) * s > 0  # noqa: E731  "a thuận hướng so với b"

    # --- Xu hướng (30)
    d1_up, d1_slope = above(f["d1_close"], f["d1_ema50"]), f["d1_ema50_slope"] * s > 0
    t_d1 = _pts(d1_up & d1_slope, 10) + _pts(d1_up ^ d1_slope, 5)
    h4_stack = above(f["h4_ema20"], f["h4_ema50"]) & above(f["h4_close"], f["h4_ema50"])
    t_h4 = _pts(h4_stack, 10) + _pts(~h4_stack & above(f["h4_close"], f["h4_ema50"]), 5)
    di_ok = above(f["h4_pdi"], f["h4_mdi"])
    t_adx = _pts(di_ok & (f["h4_adx"] >= 22), 10) + _pts(di_ok & (f["h4_adx"] >= 16) & (f["h4_adx"] < 22), 5)
    trend = t_d1 + t_h4 + t_adx

    # --- Động lượng (15): RSI 4H khỏe nhưng chưa quá mua/bán, MACD 1H quay đầu thuận hướng
    r = 50 + (f["h4_rsi"] - 50) * s  # quy về hướng long
    m_rsi = _pts((r >= 50) & (r <= 68), 8) + _pts(((r >= 45) & (r < 50)) | ((r > 68) & (r <= 75)), 4)
    mh = f["macd_hist"] * s
    m_macd = _pts((mh > 0) & (mh > f["macd_hist"].shift(1) * s), 7) + _pts((mh > 0) & ~(mh > f["macd_hist"].shift(1) * s), 3) \
        + _pts((mh <= 0) & (mh > f["macd_hist"].shift(1) * s), 3)  # đang hồi phục
    momentum = m_rsi + m_macd

    # --- Setup (20): PULLBACK về EMA20 4H hoặc RETEST mốc vừa phá
    dist = (f["close"] - f["h4_ema20"]) / atr4 * s
    retraced = ((f["hh12"] - f["close"]) if s > 0 else (f["close"] - f["ll12"])) >= 0.5 * atr4
    rsi1 = 50 + (f["rsi"] - 50) * s
    pullback = h4_stack & (dist >= -0.35) & (dist <= 1.2) & retraced & (rsi1 >= 38) & above(f["close"], f["h4_ema50"])

    lvl_src = f["hh48"] if s > 0 else f["ll48"]
    brk = above(f["close"], lvl_src) & (f["volume"] > 1.5 * f["vol_sma20"])
    brk_level = lvl_src.where(brk).ffill(limit=6)
    since_brk = brk.astype(float).rolling(6, min_periods=1).max() > 0
    ext = (f["close"] - brk_level) * s
    retest = ~pullback & since_brk & (ext >= 0) & (ext <= 1.2 * atr4) & (t_h4 > 0)
    setup = _pts(pullback, 20) + _pts(retest, 16)

    # --- Dòng tiền (15)
    br = 0.5 + (f["buy_ratio3"] - 0.5) * s
    fl_buy = _pts(br >= 0.53, 7) + _pts((br >= 0.50) & (br < 0.53), 4)
    fl_cvd = _pts(f["cvd24"] * s > 0.02, 4)
    fl_vol = _pts((pullback & (f["vol_ma3"] < f["vol_sma20"])) | retest, 4)  # hồi với volume cạn = lành mạnh
    flow = fl_buy + fl_cvd + fl_vol

    # --- Phái sinh (10): funding (có lịch sử) + OI & L/S (live, trung tính khi backtest)
    fund = f["funding"] * s  # >0 = phe cùng hướng đang trả phí (đông người)
    d_fund = _pts(fund < 0.0003, 3)
    deriv = d_fund + NEUTRAL_LIVE["oi"] + NEUTRAL_LIVE["ls"]

    # --- Thị trường chung (10)
    mk_btc = _pts(f["btc_trend"] * s > 0, 5) + _pts(f["btc_trend"] == 0, 2)
    fng_ok = (f["fng"] < 75) if s > 0 else (f["fng"] > 25)
    mk_fng = _pts(fng_ok, 2)
    market = mk_btc + mk_fng + NEUTRAL_LIVE["liquidity"] + NEUTRAL_LIVE["news"]

    extra = custom.score(f, s)  # chỗ gắn chỉ báo TradingView riêng của bạn (mặc định 0)

    total = trend + momentum + setup + flow + deriv + market + extra

    # --- Bộ lọc chặn cứng (đã kiểm chứng bằng backtest 1 năm, xem README)
    atr_pct = atr4 / f["close"]
    veto = (
        (setup == 0) | (t_h4 == 0)                     # không có setup / ngược xu hướng 4H
        | (flow < MIN_FLOW)                            # dòng tiền taker không ủng hộ
        | (f["fng"] <= FNG_PANIC)                      # hoảng loạn cực độ: thị trường giật 2 chiều
        | (fund > 0.0008)                              # funding quá nóng cùng phía
        | (atr_pct < 0.004) | (atr_pct > 0.06)          # thị trường chết hoặc quá hỗn loạn
        | f["h4_atr"].isna() | f["d1_ema50"].isna()
    )

    # --- Vào lệnh ngay khi setup hình thành (nến 1H vừa đóng), SL dưới/trên đáy/đỉnh 24 nến
    entry = f["close"]
    swing = f["swing_low24"] if s > 0 else f["swing_high24"]
    risk = np.clip((entry - (swing - s * 0.1 * atr4)) * s, 0.8 * atr4, 2.2 * atr4)
    sl = entry - s * risk

    # sát kháng cự/hỗ trợ ngày -> không đủ chỗ chạy (trừ setup retest vừa phá)
    wall = f["d1_hh20"] if s > 0 else f["d1_ll20"]
    room = (wall - entry) * s
    veto = veto | (pullback & (room > 0) & (room < 1.2 * risk))

    zone_a, zone_b = entry, entry - s * 0.15 * atr4  # vùng vào: giá hiện tại -> hồi nhẹ 0.15 ATR
    return pd.DataFrame({
        "score": np.where(veto, 0.0, total), "raw": total,
        "trend": trend, "momentum": momentum, "setup": setup, "flow": flow, "deriv": deriv, "market": market,
        "setup_type": np.where(pullback, "pullback", np.where(retest, "retest", "")),
        "zone_lo": np.minimum(zone_a, zone_b), "zone_hi": np.maximum(zone_a, zone_b),
        "entry": entry, "sl": sl, "risk": risk, "atr4": atr4,
        "tp1": entry + s * TARGET_R * risk, "tp2": entry + s * 3.0 * risk,  # mục tiêu tham khảo (không đặt lệnh chốt)
        "be": entry + s * BE_AT_R * risk,
        "fund_pts": d_fund, "btc_pts": mk_btc, "fng_pts": mk_fng,
    }, index=f.index)


def score_frame(f: pd.DataFrame) -> dict[int, pd.DataFrame]:
    return {1: _side_scores(f, 1), -1: _side_scores(f, -1)}


# ---------------------------------------------------------------- cổng chất lượng
GATE_OI = 0.05        # |thay đổi OI| tối thiểu (24h swing ngắn / 72h swing dài)
GATE_CROWD = 3.0      # đám đông nghiêng về phía NGƯỢC lệnh ít nhất 3:1


def quality_gate(side: int, setup: str, oi_chg: float | None, ls: float | None, style: str = "short") -> str | None:
    """Trả về lý do chặn (None = cho qua). Chọn theo backtest 2 năm / 40 coin (ổn định ở cả 2 nửa dữ liệu).

    - Cả 2 kiểu: bỏ Pullback LONG (kém ở mọi giai đoạn).
    - Swing ngắn: cần ít nhất 1 xác nhận — OI biến động mạnh (24h), hoặc đám đông ngược phía, hoặc setup Retest.
    - Swing dài: bắt buộc OI biến động mạnh (72h) — 2 năm gần nhất không có OI xác nhận thì setup 4H kém hẳn.
    """
    if setup == "pullback" and side > 0:
        return "Pullback LONG (backtest kém)"
    oi_ok = oi_chg is not None and abs(oi_chg) >= GATE_OI
    if style == "long":
        return None if oi_ok else "Swing dài cần OI biến động >= 5% (3 ngày)"
    contra = None if not ls else (ls if side < 0 else 1 / ls)
    crowd_ok = contra is not None and contra >= GATE_CROWD
    if not (oi_ok or crowd_ok or setup == "retest"):
        return "Chưa có xác nhận OI / đám đông"
    return None


# ---------------------------------------------------------------- Volume Profile: lọc phía POC
VP_BARS, VP_BINS = 150, 24


def poc(high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray, bins: int = VP_BINS) -> float | None:
    """POC (mức giá nhiều khối lượng nhất) — cùng công thức chỉ báo Volume Profile Pro (giá điển hình, 24 mức)."""
    lo, hi = float(np.min(low)), float(np.max(high))
    if not hi > lo:
        return None
    edges = np.linspace(lo, hi, bins + 1)
    idx = np.clip(np.searchsorted(edges, (high + low + close) / 3, side="right") - 1, 0, bins - 1)
    prof = np.bincount(idx, weights=volume, minlength=bins)
    k = int(prof.argmax())
    return float((edges[k] + edges[k + 1]) / 2)


def poc_veto(base: pd.DataFrame, side: int, entry: float, upto: int | None = None) -> str | None:
    """Chỉ vào lệnh khi giá ở phía thuận của POC 150 nến khung tín hiệu (LONG trên POC, SHORT dưới POC).
    Backtest 9 năm / 50 coin: lệnh phía nghịch POC gần như không có lời (còn ~85% lệnh). Dùng cho swing ngắn và
    chỉ báo; swing dài (đã lọc OI) thì không dùng — backtest 2 năm có giới hạn lệnh cho thấy làm kết quả kém đi."""
    end = len(base) if upto is None else upto + 1
    w = base.iloc[max(0, end - VP_BARS):end]
    if len(w) < 50:
        return None
    p = poc(w["high"].to_numpy(), w["low"].to_numpy(), w["close"].to_numpy(), w["volume"].to_numpy())
    if p is not None and (entry - p) * side <= 0:
        return f"Giá phía nghịch POC Volume Profile ({p:.6g})"
    return None


# ---------------------------------------------------------------- live
@dataclass
class Candidate:
    symbol: str
    side: int
    score: float
    row: dict
    reasons: list[str] = field(default_factory=list)
    vetoed: str | None = None

    @property
    def side_name(self) -> str:
        return "LONG" if self.side > 0 else "SHORT"


def best_candidate(symbol: str, scores: dict[int, pd.DataFrame]) -> Candidate | None:
    """Lấy điểm của nến 1H vừa đóng cho 2 phía, chọn phía cao hơn."""
    best = None
    for side, df in scores.items():
        row = df.iloc[-1].to_dict()
        if row["score"] > 0 and (best is None or row["score"] > best.score):
            best = Candidate(symbol, side, float(row["score"]), row)
    return best


def apply_live_context(c: Candidate, deriv: dict, *, coin_news: dict | None, market_news: float,
                       stable_7d: float | None, style: str = "short") -> Candidate:
    """Áp dữ liệu live: cổng chất lượng (OI, long/short), funding, tin tức, thanh khoản."""
    s, row = c.side, c.row
    adj = 0.0

    # OI & long/short KHÔNG cộng điểm nữa (backtest cho thấy cộng điểm làm chọn lệnh kém hơn);
    # chúng được dùng ở `quality_gate` — cùng cách với backtest.
    oi, ls = deriv.get("oi_chg"), deriv.get("ls")
    if oi is not None:
        c.reasons.append(f"OI {oi:+.1%}")
    if ls:
        c.reasons.append(f"Tỉ lệ long/short đám đông {ls:.2f}")
    fund = deriv.get("funding")
    if fund is not None:
        if fund * s > 0.0008:
            c.vetoed = f"Funding quá nóng ({fund:.3%})"
        c.reasons.append(f"Funding {fund:.4%}")

    if stable_7d is not None:
        pts = 1.0 if (stable_7d > 0) == (s > 0) else 0.0
        adj += pts - NEUTRAL_LIVE["liquidity"]

    news_pts = 1.0
    if coin_news:
        if s > 0 and coin_news["severe_negative"]:
            c.vetoed = f"Tin xấu: {coin_news['severe_negative'][0].title[:80]}"
        if s < 0 and coin_news["severe_positive"]:
            c.vetoed = f"Tin tốt mạnh: {coin_news['severe_positive'][0].title[:80]}"
        if coin_news["count"]:
            news_pts = 2.0 if coin_news["sentiment"] * s > 0.15 else 0.0 if coin_news["sentiment"] * s < -0.15 else 1.0
    if market_news * s < -0.3:
        news_pts = max(0.0, news_pts - 1)
    adj += news_pts - NEUTRAL_LIVE["news"]

    if not c.vetoed:
        c.vetoed = quality_gate(s, row["setup_type"], oi, ls, style)
    c.score = round(c.score + adj, 1)
    row["score"] = c.score
    return c


def describe(c: Candidate) -> list[str]:
    r = c.row
    out = []
    out.append("Setup hồi về EMA20 4H" if r["setup_type"] == "pullback" else "Retest mốc vừa phá (volume lớn)")
    out.append(f"Xu hướng {r['trend']:.0f}/30 · Động lượng {r['momentum']:.0f}/15 · Dòng tiền {r['flow']:.0f}/15")
    if r["btc_pts"] >= 5:
        out.append("BTC cùng xu hướng")
    return out + c.reasons
