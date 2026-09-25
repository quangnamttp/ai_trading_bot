# Chỉ báo TradingView

Gồm 2 chỉ báo, dùng chung trên một chart (gói TradingView miễn phí cho gắn tối đa 2 chỉ báo mỗi chart):

| File | Vai trò |
|---|---|
| `swing_entry_pro_v5.pine` (v5.3) | **Khi nào vào lệnh**: điểm vào, SL, TP1, TP2, trailing stop, hạng tín hiệu, cảnh báo "Chuẩn bị", bảng thống kê |
| `volume_profile_pro_v3.pine` (v3.2) | **Vùng giá quan trọng**: POC, Value Area (VAH/VAL), POC chưa bị chạm, vùng thanh khoản mỏng |

Cả 2 chỉ báo chạy 24/24, không lọc giờ, và **không repaint**: tín hiệu chỉ xuất hiện khi nến đóng, đã hiện thì không bao giờ mất.

### Cập nhật v5.3
- Mỗi nến tín hiệu chỉ quyết định **1 lần, khi OI của đúng nến đó đã có**. TradingView đôi khi cập nhật OI trễ vài phút:
  bản cũ có thể tính bằng OI cũ rồi sau đó tín hiệu "mọc ra" trong lịch sử (vd PEPE 18/09 OI +6.4%, sát ngưỡng 5%).
  Giờ bảng hiện "Đang chờ OI…" trong lúc chờ (tối đa 20 phút), tín hiệu đã hiện/không hiện thì giữ nguyên.
- Kiểm tra lại PEPE 1H 18–22/09 bằng bản Python: 2 lệnh MUA 18/09 22:00 (+1.39R) và 21/09 23:00 (−0.25R) trùng với
  chart, không phụ thuộc lịch sử chart bắt đầu từ đâu.

### Cập nhật v5.2 / v3.2
- **Swing v5.2 — OI luôn lấy từ Binance**, kể cả khi mở chart MEXC, OKX, cặp USDC... (vd chart `MEXC:PEPEUSDC` tự lấy
  OI của `BINANCE:1000PEPEUSDT.P`). Bảng ghi rõ OI lấy từ mã nào. Không tìm thấy thì nhập tay ở Cài đặt → "Mã OI tự nhập".
- **Vì sao bản cũ hay vào lệnh ngược sóng?** Đã kiểm tra dứt điểm trên 2 năm / 20 coin: nguyên nhân chính là **thiếu dữ
  liệu OI** (chart MEXC không có OI → bộ lọc OI bị bỏ qua). Tín hiệu có OI biến động ≥ 5% dương rõ ở cả nửa đầu và nửa sau
  dữ liệu (4H: +0.36R / +0.14R); tín hiệu OI < 2% gần như hòa vốn. Các bộ lọc xu hướng khác (tuổi xu hướng, khoảng cách
  EMA, xu hướng ngày, ADX, BTC) **không ổn định** giữa 2 nửa → không thêm để tránh "đẹp trên quá khứ".
- Bảng "Đánh giá khung" chuyển màu cam khi không có OI.
- **Volume Profile v3.2**: thêm POC / VAH / VAL **tuần trước** (xanh dương) và **tháng trước** (tím), đường VAH/VAL cuộn,
  chế độ **"Chỉ vẽ đường"** (ẩn histogram cho chart gọn), và **cảnh báo khi giá chạm** POC / VAH / VAL / POC trinh / mốc
  tuần-tháng: bấm đồng hồ báo thức → Condition "Volume Profile Pro v3.2" → **Any alert() function call**.

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

- **Khung nên dùng**: chart **4H** (tốt nhất) hoặc **1H**, và bảng phải hiện "Dữ liệu OI" có số. Mở chart 15m vẫn được: chỉ báo tự lấy tín hiệu từ khung 1H,
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
