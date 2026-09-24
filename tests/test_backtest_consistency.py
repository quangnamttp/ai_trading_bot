"""Backtest dùng bản mô phỏng nhanh — phải cho kết quả GIỐNG HỆT máy trạng thái lệnh của bot live."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.backtest import simulate
from app.strategy.trade import Trade, callback_rate

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize("seed", range(300))
def test_simulate_matches_trade_state_machine(seed):
    rng = np.random.default_rng(seed)
    n = 120
    side = 1 if seed % 2 else -1
    close = 100 * np.exp(np.cumsum(rng.normal(0.001 * side, 0.02, n)))
    open_ = np.r_[100.0, close[:-1]]
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.015, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.015, n))
    atr = np.full(n, rng.uniform(1.0, 5.0))
    entry = close[0]
    sl = entry - side * rng.uniform(1.5, 6.0)
    hold = 100

    R, bars, out = simulate(high, low, close, atr, 0, side, entry, sl, hold)

    t = Trade(side, entry, sl, created=T0, deadline=T0 + timedelta(hours=hold), exit_mode="pct",
              callback=callback_rate(atr[0], entry))
    for j in range(1, n):
        t.step(T0 + timedelta(hours=j), high[j], low[j], close[j], atr[j])
        if t.status != "ACTIVE":
            break
    assert t.status == "CLOSED"
    assert R == pytest.approx(t.realized_r, abs=1e-9)
    assert out == t.outcome
