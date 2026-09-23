"""Máy trạng thái của một tín hiệu — dùng CHUNG cho backtest và theo dõi lệnh live.

Cách quản lý lệnh (chọn theo backtest 1 năm, 30 coin):
  - Vào lệnh ngay khi setup hình thành (giá vùng entry).
  - Giá đi được +1R  -> dời SL về entry (hòa vốn).
  - Chốt 50% tại TP1 (2R) theo `PARTIALS`.
  - Phần còn lại chạy theo trailing stop = giá đóng cửa tốt nhất -/+ 2.5 x ATR(4H).
  - Quá thời gian giữ tối đa -> đóng theo giá thị trường.
Trong cùng một nến chạm cả SL và mục tiêu -> tính SL trước (giả định bất lợi, tránh backtest ảo).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

BE_AT_R = 1.0
PARTIALS: list[tuple[float, float]] = [(2.0, 0.5)]  # (bội số R, tỉ lệ vị thế) — chốt 50% tại 2R
TRAIL_ATR = 2.5
FEE_RATE = 0.001  # phí khứ hồi ~0.1% giá trị lệnh

OPEN_STATES = {"ACTIVE"}


@dataclass
class Trade:
    side: int
    entry: float
    sl: float
    created: datetime
    deadline: datetime
    partials: list[tuple[float, float]] = field(default_factory=lambda: list(PARTIALS))
    status: str = "ACTIVE"        # ACTIVE / CLOSED
    stop: float = 0.0             # SL hiện hành
    extreme: float = 0.0          # giá đóng cửa tốt nhất từ khi vào lệnh
    be_done: bool = False
    hit: list[int] = field(default_factory=list)  # chỉ số các mốc chốt đã đạt
    realized_r: float = 0.0
    remaining: float = 1.0
    closed_at: datetime | None = None
    exit_price: float | None = None
    outcome: str = ""             # SL / BE / TRAIL / TIMEOUT
    max_r: float = 0.0

    def __post_init__(self) -> None:
        self.stop = self.stop or self.sl
        self.extreme = self.extreme or self.entry

    @property
    def risk(self) -> float:
        return abs(self.entry - self.sl)

    def target(self, i: int) -> float:
        return self.entry + self.side * self.partials[i][0] * self.risk

    def r_at(self, price: float) -> float:
        return (price - self.entry) * self.side / self.risk

    def _close(self, price: float, ts: datetime, outcome: str) -> None:
        self.realized_r += self.remaining * self.r_at(price) - FEE_RATE * self.entry / self.risk
        self.remaining, self.status, self.closed_at, self.exit_price, self.outcome = 0.0, "CLOSED", ts, price, outcome

    def step(self, ts: datetime, high: float, low: float, close: float, atr: float,
             hour_close: bool = True) -> list[tuple[str, float]]:
        """Xử lý một nến. Trả về sự kiện mới: (BE|TP1|TRAIL_MOVE|SL|STOPPED|TIMEOUT, giá).

        `hour_close=False` khi theo dõi bằng nến 5 phút: vẫn bắt SL/TP ngay, nhưng trailing chỉ
        cập nhật theo giá đóng cửa 1H (giống backtest).
        """
        if self.status != "ACTIVE":
            return []
        s, ev = self.side, []
        fav, adv = (high, low) if s > 0 else (low, high)
        beyond = lambda p, lvl: (p - lvl) * s >= 0  # noqa: E731  p vượt lvl theo hướng lệnh

        if beyond(self.stop, adv):  # chạm SL hiện hành (kiểm tra trước — bảo thủ)
            outcome = "SL" if not self.be_done else "BE" if abs(self.stop - self.entry) < 1e-12 else "TRAIL"
            self._close(self.stop, ts, outcome)
            return [("SL" if outcome == "SL" else "STOPPED", self.stop)]

        self.max_r = max(self.max_r, self.r_at(fav))
        for i, (_, w) in enumerate(self.partials):
            if i not in self.hit and beyond(fav, self.target(i)):
                self.hit.append(i)
                self.realized_r += w * self.r_at(self.target(i))
                self.remaining = round(self.remaining - w, 6)
                ev.append((f"TP{i + 1}", self.target(i)))

        new_stop = self.stop
        if not self.be_done and beyond(fav, self.entry + s * BE_AT_R * self.risk):
            self.be_done, new_stop = True, self.entry
            ev.append(("BE", self.entry))
        if hour_close:
            self.extreme = max(self.extreme, close) if s > 0 else min(self.extreme, close)
        if self.be_done and hour_close:
            trail = self.extreme - s * TRAIL_ATR * atr
            if beyond(trail, new_stop):
                new_stop = trail
        if new_stop != self.stop:
            if self.be_done and new_stop != self.entry:
                ev.append(("TRAIL_MOVE", new_stop))
            self.stop = new_stop

        if self.remaining <= 1e-9:
            self._close(close, ts, "TP")
        elif ts >= self.deadline and hour_close:
            self._close(close, ts, "TIMEOUT")
            ev.append(("TIMEOUT", close))
        return ev

    @property
    def won(self) -> bool:
        return self.realized_r > 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Trade":
        d = dict(d)
        d["partials"] = [tuple(p) for p in d.get("partials", PARTIALS)]
        return cls(**d)
