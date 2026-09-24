"""Máy trạng thái của một tín hiệu — dùng CHUNG cho backtest và theo dõi lệnh live.

Hai cách quản lý phần lệnh sau khi có lãi (`exit_mode`):

- "pct" (mặc định, chọn theo backtest 2 năm / 40 coin): mô phỏng đúng lệnh đặt SẴN trên sàn —
    SL cố định · TP1 chốt 50% tại 2R (lệnh limit) · Trailing Stop của sàn cho toàn bộ vị thế:
    kích hoạt khi giá đi được +1R, sau đó bám giá cao nhất (LONG) / thấp nhất (SHORT) cách `callback` %.
    Người dùng đặt 1 lần rồi không cần theo dõi — bot chỉ báo khi có sự kiện.
- "atr" (cách cũ): +1R dời SL về entry, chốt 50% tại 2R, phần còn lại trailing = giá đóng cửa tốt nhất -/+ 2.5 x ATR.

Trong cùng một nến chạm cả SL và mục tiêu -> tính SL trước (giả định bất lợi, tránh backtest ảo).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

BE_AT_R = 1.0          # mốc kích hoạt (pct) / dời SL về entry (atr)
PARTIALS: list[tuple[float, float]] = [(2.0, 0.5)]  # (bội số R, tỉ lệ vị thế) — chốt 50% tại 2R
TRAIL_ATR = 2.5        # atr: khoảng trailing theo ATR khung xu hướng
CALLBACK_ATR = 3.0     # pct: callback = 3 x ATR(khung xu hướng) / giá vào lệnh (tốt nhất trong backtest)
MIN_CALLBACK, MAX_CALLBACK = 0.005, 0.10   # giới hạn callback của sàn (Binance Futures: 0.1% - 10%)
FEE_RATE = 0.001       # phí khứ hồi ~0.1% giá trị lệnh

OPEN_STATES = {"ACTIVE"}


def callback_rate(atr: float, entry: float) -> float:
    return min(MAX_CALLBACK, max(MIN_CALLBACK, CALLBACK_ATR * atr / entry))


@dataclass
class Trade:
    side: int
    entry: float
    sl: float
    created: datetime
    deadline: datetime
    partials: list[tuple[float, float]] = field(default_factory=lambda: list(PARTIALS))
    exit_mode: str = "atr"        # "pct" | "atr" (mặc định "atr" để đọc được lệnh cũ đã lưu)
    callback: float = 0.0         # pct: tỉ lệ callback của trailing stop sàn (vd 0.035 = 3.5%)
    status: str = "ACTIVE"        # ACTIVE / CLOSED
    stop: float = 0.0             # SL hiện hành
    extreme: float = 0.0          # atr: giá đóng cửa tốt nhất · pct: giá cao/thấp nhất sau khi kích hoạt
    be_done: bool = False         # atr: đã dời SL về entry · pct: trailing đã kích hoạt
    hit: list[int] = field(default_factory=list)  # chỉ số các mốc chốt đã đạt
    realized_r: float = 0.0
    remaining: float = 1.0
    closed_at: datetime | None = None
    exit_price: float | None = None
    outcome: str = ""             # SL / BE / TRAIL / TP / TIMEOUT
    max_r: float = 0.0

    def __post_init__(self) -> None:
        self.stop = self.stop or self.sl
        self.extreme = self.extreme or self.entry

    @property
    def risk(self) -> float:
        return abs(self.entry - self.sl)

    @property
    def activation(self) -> float:
        return self.entry + self.side * BE_AT_R * self.risk

    def target(self, i: int) -> float:
        return self.entry + self.side * self.partials[i][0] * self.risk

    def r_at(self, price: float) -> float:
        return (price - self.entry) * self.side / self.risk

    def trailing_stop(self) -> float | None:
        """pct: mức dừng hiện tại của trailing stop sàn (None nếu chưa kích hoạt)."""
        if self.exit_mode != "pct" or not self.be_done:
            return None
        return self.extreme * (1 - self.callback) if self.side > 0 else self.extreme * (1 + self.callback)

    def effective_stop(self) -> float:
        t = self.trailing_stop()
        if t is None:
            return self.stop
        return max(self.stop, t) if self.side > 0 else min(self.stop, t)

    def _close(self, price: float, ts: datetime, outcome: str) -> None:
        self.realized_r += self.remaining * self.r_at(price) - FEE_RATE * self.entry / self.risk
        self.remaining, self.status, self.closed_at, self.exit_price, self.outcome = 0.0, "CLOSED", ts, price, outcome

    def step(self, ts: datetime, high: float, low: float, close: float, atr: float,
             hour_close: bool = True) -> list[tuple[str, float]]:
        """Xử lý một nến. Trả về sự kiện mới: (BE|ARMED|TP1|TRAIL_MOVE|SL|STOPPED|TIMEOUT, giá).

        `hour_close=False` khi theo dõi bằng nến 5 phút ở chế độ atr: vẫn bắt SL/TP ngay, nhưng trailing chỉ
        cập nhật theo giá đóng cửa 1H (giống backtest). Chế độ pct bám theo high/low như lệnh của sàn.
        """
        if self.status != "ACTIVE":
            return []
        s, ev = self.side, []
        fav, adv = (high, low) if s > 0 else (low, high)
        beyond = lambda p, lvl: (p - lvl) * s >= 0  # noqa: E731  p vượt lvl theo hướng lệnh

        stop = self.effective_stop()
        if beyond(stop, adv):  # chạm SL / trailing (kiểm tra trước — bảo thủ)
            if self.exit_mode == "pct":
                outcome = "SL" if (stop == self.stop and not self.hit) else "TRAIL"
            else:
                outcome = "SL" if not self.be_done else "BE" if abs(self.stop - self.entry) < 1e-12 else "TRAIL"
            self._close(stop, ts, outcome)
            return [("SL" if outcome == "SL" else "STOPPED", stop)]

        self.max_r = max(self.max_r, self.r_at(fav))
        for i, (_, w) in enumerate(self.partials):
            if i not in self.hit and beyond(fav, self.target(i)):
                self.hit.append(i)
                self.realized_r += w * self.r_at(self.target(i))
                self.remaining = round(self.remaining - w, 6)
                ev.append((f"TP{i + 1}", self.target(i)))

        if self.exit_mode == "pct":
            if not self.be_done and beyond(fav, self.activation):
                self.be_done = True
                self.extreme = fav
                ev.append(("ARMED", self.activation))
            elif self.be_done:
                self.extreme = max(self.extreme, fav) if s > 0 else min(self.extreme, fav)
        else:
            new_stop = self.stop
            if not self.be_done and beyond(fav, self.activation):
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
