# Chỉ báo TradingView

Gồm 2 chỉ báo, dùng chung trên một chart (gói TradingView miễn phí cho gắn tối đa 2 chỉ báo mỗi chart):

| File | Vai trò |
|---|---|
| `swing_entry_pro_v5.pine` (v5.1) | **Khi nào vào lệnh**: điểm vào, SL, TP1, TP2, trailing stop, hạng tín hiệu, cảnh báo "Chuẩn bị", bảng thống kê |
| `volume_profile_pro_v3.pine` (v3.1) | **Vùng giá quan trọng**: POC, Value Area (VAH/VAL), POC chưa bị chạm, vùng thanh khoản mỏng |

Cả 2 chỉ báo chạy 24/24, không lọc giờ, và **không repaint**: tín hiệu chỉ xuất hiện khi nến đóng, đã hiện thì không bao giờ mất.

### Cập nhật v5.1 / v3.1
- Ẩn thông số khỏi dòng trạng thái → hết chữ đè lên bảng.
- Chọn **vị trí bảng** (4 góc) và **cỡ chữ** trong Cài đặt → Hiển thị.
- Swing: khi chart không có dữ liệu OI (vd sàn MEXC) bảng nhắc mở mã `BINANCE:...USDT.P`.
- Volume Profile: trên khung ≥ 4H, POC trinh tính **theo tuần** (bản cũ báo 0 trên khung 1D) và tự ẩn Profile theo phiên.

Cập nhật: mở Pine Editor → mở script cũ → xóa hết → dán nội dung file mới → **Save**. Chart tự cập nhật.

## Cài lên TradingView

1. Mở TradingView → mở chart một coin, ví dụ `BINANCE:BTCUSDT.P`.
2. Dưới đáy màn hình bấm **Pine Editor**.
3. Xóa hết nội dung mẫu, dán toàn bộ nội dung file `swing_entry_pro_v5.pine`.
4. Bấm **Save** (đặt tên tùy ý), rồi bấm **Add to chart**.
5. Làm lại các bước 2–4 với file `volume_profile_pro_v3.pine`.

Nếu Pine Editor báo lỗi (dòng chữ đỏ ở dưới), chụp màn hình gửi lại để sửa.

## Dùng Swing Entry Pro v5

- **Khung nên dùng**: chart **4H** (tốt nhất) hoặc **1H**. Mở chart 15m vẫn được: chỉ báo tự lấy tín hiệu từ khung 1H,
  anh/chị dùng 15m để canh giá vào đẹp hơn.
- **Nhãn MUA/BÁN**: rê chuột vào nhãn để xem đủ: giá vào, SL, TP1 (chốt 50%), TP2 tham khảo (theo Volume Profile),
  mức kích hoạt và callback của trailing stop, giá "không vào nếu đã vượt".
- **Hạng A**: điểm ≥ 85 hoặc OI biến động ≥ 10%. **Hạng B**: đạt ngưỡng.
- **Hình thoi vàng "Chuẩn bị"**: setup đang hình thành, gần đạt chuẩn. **Chưa phải tín hiệu**, chỉ để theo dõi.
- **Đường vàng**: trailing stop, xuất hiện sau khi giá đi được +1R.
- **Bảng góc phải**: kết quả lịch sử của chính chỉ báo trên coin và khung đang xem (số lệnh, % có lời, TB R, sụt giảm).
  Dùng bảng này để tự kiểm tra trước khi tin tín hiệu trên một coin.
- **Chỉ giao dịch Spot**: vào Cài đặt → tắt "Cho phép tín hiệu BÁN/SHORT".
- **Cảnh báo (alert)**: bấm nút đồng hồ → Condition chọn "Swing Pro v5" → **Any alert() function call**.
  Nội dung alert có sẵn giá vào / SL / TP1 / trailing.

## Kết quả backtest (Python, cùng logic, 2 năm, 20 coin lớn)

| Khung | Không lọc OI | **Có lọc OI ≥ 5%** (mặc định) |
|---|---|---|
| 15m | lỗ (−0.03R/lệnh) | — (nên dùng tín hiệu từ 1H) |
| 1H | +0.05R/lệnh | **+0.08R/lệnh** (nửa đầu +0.09 / nửa sau +0.07) |
| 4H | +0.09R, nửa đầu lỗ | **+0.31R/lệnh** (nửa đầu +0.22 / nửa sau +0.39), sụt giảm tối đa 11R |
| 1D | quá ít tín hiệu để kết luận | — |

TradingView không có dữ liệu taker, funding và tỉ lệ long/short như bot. Dòng tiền trong chỉ báo được **ước lượng từ nến**,
nên kết quả kém hơn bot Telegram. Bot vẫn là nguồn tín hiệu chính. Chỉ báo dùng để xem chart và học.

Bản Python dùng để backtest nằm trong [app/strategy/core.py](../app/strategy/core.py). Logic của Swing v5 được chuyển
từ file này. Kết quả trên chart TradingView có thể lệch nhẹ so với số liệu trên, vì nguồn nến và dữ liệu OI khác nhau.

## Vì sao không dùng alert webhook của TradingView cho bot?

Webhook alert cần gói TradingView trả phí. Bot tự tính toán bằng Python nên giữ được chi phí 0đ.
