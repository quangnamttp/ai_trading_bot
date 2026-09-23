from datetime import datetime, timedelta, timezone

import pytest

from app.strategy.trade import FEE_RATE, Trade

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
H = timedelta(hours=1)


def long_trade(**kw) -> Trade:
    # entry 100, SL 90 -> 1R = 10; TP1 (2R) = 120
    return Trade(1, 100.0, 90.0, created=T0, deadline=T0 + 100 * H, **kw)


def fee(t: Trade) -> float:
    return FEE_RATE * t.entry / t.risk


def test_stop_loss_is_minus_one_r():
    t = long_trade()
    assert t.step(T0 + H, 101, 89, 95, atr=5) == [("SL", 90.0)]
    assert t.status == "CLOSED" and t.outcome == "SL"
    assert t.realized_r == pytest.approx(-1 - fee(t))


def test_sl_checked_before_target_in_same_candle():
    t = long_trade()
    t.step(T0 + H, 130, 85, 100, atr=5)  # nến quét cả TP1 lẫn SL -> tính SL (bảo thủ)
    assert t.outcome == "SL"


def test_breakeven_after_one_r_then_stopped_at_entry():
    t = long_trade()
    ev = t.step(T0 + H, 111, 99.5, 108, atr=100)  # ATR lớn -> trailing chưa vượt entry
    assert ("BE", 100.0) in ev and t.stop == 100.0
    t.step(T0 + 2 * H, 105, 99, 100, atr=100)
    assert t.outcome == "BE"
    assert t.realized_r == pytest.approx(-fee(t))


def test_tp1_takes_half_then_trailing_stop():
    t = long_trade()
    ev = t.step(T0 + H, 121, 100.5, 120, atr=2)  # chạm TP1 = 120
    assert ("TP1", 120.0) in ev
    assert t.remaining == pytest.approx(0.5)
    # trailing = giá đóng tốt nhất 120 - 2.5*2 = 115
    assert t.stop == pytest.approx(115.0)
    t.step(T0 + 2 * H, 118, 114, 116, atr=2)
    assert t.status == "CLOSED" and t.outcome == "TRAIL"
    # 0.5 * 2R + 0.5 * 1.5R
    assert t.realized_r == pytest.approx(0.5 * 2 + 0.5 * 1.5 - fee(t))


def test_trailing_only_updates_on_hour_close():
    t = long_trade()
    t.step(T0 + H, 112, 100.5, 111, atr=2, hour_close=False)
    assert t.be_done and t.stop == 100.0  # BE áp dụng ngay
    t.step(T0 + H, 115, 110, 114, atr=2, hour_close=False)
    assert t.stop == 100.0  # chưa tới giờ đóng nến 1H -> chưa trailing
    t.step(T0 + H, 115, 110, 114, atr=2, hour_close=True)
    assert t.stop == pytest.approx(114 - 5)


def test_short_mirror():
    t = Trade(-1, 100.0, 110.0, created=T0, deadline=T0 + 100 * H)
    ev = t.step(T0 + H, 99, 79, 80, atr=2)  # TP1 short = 80
    assert ("TP1", 80.0) in ev and t.be_done
    assert t.stop == pytest.approx(85.0)  # 80 + 2.5*2


def test_timeout_closes_at_market():
    t = Trade(1, 100.0, 90.0, created=T0, deadline=T0 + 2 * H)
    t.step(T0 + H, 103, 99, 102, atr=5)
    t.step(T0 + 2 * H, 104, 101, 103, atr=5)
    assert t.outcome == "TIMEOUT"
    assert t.realized_r == pytest.approx(0.3 - fee(t))


def test_roundtrip_dict():
    t = long_trade()
    t.step(T0 + H, 121, 100.5, 120, atr=2)
    t2 = Trade.from_dict(t.to_dict())
    assert t2 == t
