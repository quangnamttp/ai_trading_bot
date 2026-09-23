# Chỉ báo TradingView

| File | Ghi chú |
|---|---|
| `swing_entry_pro_v3.pine` | Bản gốc của bạn |
| `swing_entry_pro_v4.pine` | **Đã sửa**: đa khung dùng nến đã đóng (hết repaint), dấu đỉnh/đáy vẽ đúng nến xác nhận, tín hiệu chỉ khi nến đóng |
| `volume_profile_pro.pine` | Bản gốc của bạn |
| `volume_profile_pro_v2.pine` | **Đã sửa**: tính POC/VAL/VAH tại từng nến có điều kiện, nên dấu VP★ hiện cả trên lịch sử để tự kiểm tra |

Bản Python dùng để backtest: [app/strategy/tv_indicators.py](../app/strategy/tv_indicators.py).
Cách bot dùng chỉ báo và kết quả backtest: [app/strategy/custom.py](../app/strategy/custom.py).

Tóm tắt backtest (1 năm, 30 coin, khung 1H):
- Dùng riêng với SL/TP gốc: **lỗ** ở mọi loại tín hiệu (thắng 33–39%, cần ≥ 38% mới hòa vốn).
- Làm xác nhận cho bot: **không cải thiện**, nên đang tắt.
- Nên dùng 2 chỉ báo để **quan sát** vùng S/R, POC, Value Area khi tự vào lệnh, không dùng làm tín hiệu độc lập.

TradingView webhook alert cần gói trả phí, vì vậy bot tự tính bằng Python để giữ chi phí 0đ.
