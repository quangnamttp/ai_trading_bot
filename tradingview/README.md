# Chỉ báo TradingView

Gồm 2 chỉ báo, dùng chung trên một chart (gói TradingView miễn phí cho gắn tối đa 2 chỉ báo mỗi chart):

| File code | Hướng dẫn sử dụng | Vai trò |
|---|---|---|
| `swing_entry_pro.pine` (v6.1) | [HUONG_DAN_SWING_ENTRY_PRO.md](HUONG_DAN_SWING_ENTRY_PRO.md) | **Khi nào vào lệnh**: điểm vào, SL, trailing stop, hỗ trợ/kháng cự, bảng thống kê |
| `volume_profile_pro.pine` (v3.3) | [HUONG_DAN_VOLUME_PROFILE_PRO.md](HUONG_DAN_VOLUME_PROFILE_PRO.md) | **Vùng giá quan trọng**: POC, Value Area (VAH/VAL), mốc tuần/tháng trước, POC chưa bị chạm |

Cả 2 chỉ báo chạy 24/24 và **không repaint**: tín hiệu chỉ xuất hiện khi nến đóng, đã hiện thì không mất.

Cập nhật bản mới: Pine Editor → mở script cũ → xóa hết → dán nội dung file mới → **Save**. Cảnh báo (alert) đã tạo
trước đó phải **xóa và tạo lại**, vì cảnh báo cũ vẫn chạy theo code cũ.

## Backtest nghiệm thu (25/09/2026)

Mô phỏng đúng luật của `swing_entry_pro.pine` v6.1 trên 53 coin (nến Binance, 08/2017 → 09/2026). Mỗi thời điểm chỉ
tính 20 coin thanh khoản cao nhất lúc đó (tránh chỉ chọn coin còn sống tới nay), mỗi coin 1 lệnh 1 lúc, vào lệnh bằng
giá đóng nến tín hiệu, đã trừ phí 0.1% khứ hồi, chưa tính trượt giá. Code: [`backtest/`](backtest/).

| Khung | Số lệnh | Có lời | Lời TB / lệnh | 2 năm gần nhất | Sụt giảm tối đa* | Năm lỗ | Chuỗi thua dài nhất |
|---|---|---|---|---|---|---|---|
| **4H** | 1.179 | 48% | **+0.29R** | +0.21R | 30R | 1/10 (2022: −0.03R) | 13 lệnh |
| 1H | 8.674 | 41% | +0.10R | +0.07R | 143R | 2/10 (2023, 2024) | 43 lệnh |

\* Tính khi vào **mọi** tín hiệu của cả 20 coin. R = số tiền chấp nhận mất nếu chạm SL.

Kết luận: **dùng khung 4H**. Khung 1H từ 2021 tới nay chỉ khoảng +0.03R/lệnh (gần hòa vốn sau phí) → chỉ tham khảo.

Kiểm tra các bộ lọc (cùng dữ liệu):
- Lọc POC ở 4H: +0.25R → **+0.29R**/lệnh, sụt giảm 35R → **30R** → giữ.
- Ở 1H, bỏ lọc POC hay bỏ lọc OI đều không khác biệt đáng kể → giữ nguyên luật, không chỉnh thêm để tránh "tối ưu
  theo quá khứ".
- Lệnh có kháng cự cách dưới 1R **không** kém hơn các lệnh khác (4H: +0.35R/lệnh) → vùng hỗ trợ/kháng cự chỉ để nhìn,
  không dùng để bỏ lệnh.
- Hạng A không tốt hơn hạng B → hạng chỉ để tham khảo.

Chạy lại: `python tradingview/backtest/download_data.py` (tải dữ liệu, ~30 phút) →
`python tradingview/backtest/bt_swing.py` → `python tradingview/backtest/bt_report.py`.
Dữ liệu OI trong backtest lấy từ Bybit (từ 2021); chỉ báo trên TradingView lấy OI Binance.

## Lịch sử nghiên cứu

- v6 (09/2026, nghiên cứu 9 năm / 50 coin): bỏ chốt 50% cố định, để Trailing Stop chốt cả lệnh (kích hoạt +1R,
  callback 2.5 × ATR khung xu hướng); thêm lọc POC; lọc OI chỉ ở 1H; 4H ngưỡng 70.
- Đã thử và **không** giữ: chốt sớm ở 1R + dời SL hòa vốn (tỉ lệ thắng 53% nhưng lời TB giảm ~30%), tránh nến quá lớn,
  tránh giá cách EMA20 xa, điểm ≥ 80/85, chỉ Retest, giữ lệnh lâu gấp đôi. Scalping 15m: lỗ sau phí ở mọi cách → bỏ.
- Dấu VP★ của Volume Profile dùng riêng: lỗ (−0.06 … −0.23R/lệnh) → mặc định TẮT.
- Kiểm chứng: bản Python của chỉ báo (`app/strategy/indicator.py`) tái hiện đúng tín hiệu trên chart PEPE 1H 18–22/09.

## Vì sao không dùng alert webhook của TradingView cho bot?

Webhook alert cần gói TradingView trả phí. Bot tự tính cùng công thức bằng Python nên giữ chi phí 0đ.
