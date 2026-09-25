# Chỉ báo TradingView

Gồm 2 chỉ báo, dùng chung trên một chart (gói TradingView miễn phí cho gắn tối đa 2 chỉ báo mỗi chart):

| File | Vai trò |
|---|---|
| `swing_entry_pro.pine` (v6) | **Khi nào vào lệnh**: điểm vào, SL, trailing stop, mục tiêu tham khảo, hạng tín hiệu, "Chuẩn bị", bảng thống kê |
| `volume_profile_pro.pine` (v3.2) | **Vùng giá quan trọng**: POC, Value Area (VAH/VAL), mốc tuần/tháng trước, POC chưa bị chạm |

Cả 2 chỉ báo chạy 24/24, không lọc giờ, và **không repaint**: tín hiệu chỉ xuất hiện khi nến đóng, đã hiện thì không mất.

Cập nhật: mở Pine Editor → mở script cũ → xóa hết → dán nội dung file mới → **Save**. Chart tự cập nhật.

## Swing Entry Pro v6 — nghiên cứu 9 năm (2017–2026, 50 coin, luôn chọn 20 coin thanh khoản nhất ở từng thời điểm)

Vấn đề cần giải quyết: nhiều lệnh đi đúng hướng nhưng không chạm TP rồi quay đầu. Đã thử 11 cách thoát lệnh và
nhiều bộ lọc; chỉ giữ thay đổi **tốt hơn ở phần lớn các năm và ở cả 2 giai đoạn 2018–2021 / 2022–2026**.

**1. Thoát lệnh: bỏ chốt 50% cố định, để Trailing Stop chốt cả lệnh** (kích hoạt +1R, callback 2.5 × ATR khung xu hướng)
- Chốt sớm ở 1R + dời SL về hòa vốn: tỉ lệ thắng lên 53% nhưng **lời trung bình giảm ~30%** (giá hay quét SL hòa vốn
  rồi mới chạy) → không dùng.
- Trailing cho cả lệnh: lời/lệnh cao hơn ở gần như mọi năm; với callback 2.5 ATR thì sụt giảm tối đa còn thấp hơn cách cũ.

**2. Lọc Volume Profile: chỉ vào lệnh phía thuận POC** (LONG khi giá trên POC 150 nến, SHORT khi dưới) — bỏ ~15% lệnh;
nhóm bị bỏ gần như không có lời (+0.05R 1H, −0.01R 4H) → tốt hơn 7–8/10 năm.

**3. Lọc OI chỉ dùng ở khung 1H** (tốt hơn 6/6 năm). Ở 4H, 9 năm dữ liệu cho thấy lọc OI không ổn định → bỏ, ngưỡng 70.

| Khung (chỉ báo) | Trước (v5) | **v6** | Sụt giảm tối đa | Năm lỗ |
|---|---|---|---|---|
| 1H (lọc OI) | +0.12R/lệnh, thắng 41% | **+0.17R/lệnh, thắng 42%** | giảm ~46% | 2 → **0**/10 |
| 4H | +0.21R/lệnh, thắng 45% | **+0.31R/lệnh, thắng 47%** | giảm ~5% | 0 → 1/10 |

Đã thử và **không** giữ (không ổn định qua các năm): tránh nến quá lớn, tránh giá cách EMA20 xa, điểm ≥ 80/85,
chỉ Retest, dời SL hòa vốn ở 1R/1.5R/2R, giữ lệnh lâu gấp đôi. Scalping 15m: lỗ sau phí ở mọi cách → bỏ.

Kiểm chứng: bản Python của chỉ báo (`app/strategy/indicator.py`) tái hiện đúng tín hiệu trên chart PEPE 1H 18–22/09.

## Cài lên TradingView

1. Mở TradingView → mở chart một coin, ví dụ `BINANCE:BTCUSDT.P` hoặc `MEXC:BTCUSDT.P`.
2. Dưới đáy màn hình bấm **Pine Editor**.
3. Xóa hết nội dung mẫu, dán toàn bộ nội dung file `swing_entry_pro.pine`.
4. Bấm **Save** (đặt tên tùy ý), rồi bấm **Add to chart**.
5. Làm lại các bước 2–4 với file `volume_profile_pro.pine`.

Nếu Pine Editor báo lỗi (dòng chữ đỏ ở dưới), chụp màn hình gửi lại để sửa.

## Dùng Swing Entry Pro v6

- **Khung nên dùng**: **4H** (tốt nhất) hoặc **1H** (bảng phải hiện "Dữ liệu OI" có số). Chart 15m vẫn được: chỉ báo lấy
  tín hiệu từ 1H, dùng 15m để canh giá vào.
- **OI luôn lấy từ Binance**, kể cả khi mở chart MEXC/OKX/cặp USDC. Không tìm thấy thì nhập tay ở "Mã OI tự nhập".
- **Nhãn MUA/BÁN**: rê chuột để xem giá vào, SL, mục tiêu tham khảo 2R, mục tiêu xa theo Volume Profile, POC, mức kích
  hoạt và callback trailing, giá "không vào nếu đã vượt".
- **Cách đặt lệnh**: SL + **Trailing Stop cho cả lệnh** (giá kích hoạt + callback % trong nhãn). Mục tiêu 2R chỉ để tham
  khảo, không đặt lệnh chốt. Muốn chốt bớt một phần: Cài đặt → "Chốt từng phần tại mục tiêu (%)".
- **Hạng A**: điểm ≥ 85 hoặc OI biến động ≥ 10%. **Hạng B**: đạt ngưỡng.
- **Hình thoi vàng "Chuẩn bị"**: setup gần đạt chuẩn, chưa phải tín hiệu.
- **Đường vàng**: trailing stop, xuất hiện khi giá đi được +1R.
- **Bảng góc phải**: kết quả lịch sử của chỉ báo trên coin và khung đang xem.
- **Chỉ giao dịch Spot**: Cài đặt → tắt "Cho phép tín hiệu BÁN/SHORT".
- **Cảnh báo**: đồng hồ báo thức → Condition "Swing Pro v6" → **Any alert() function call**.
- Mỗi nến tín hiệu chỉ quyết định 1 lần khi OI của nến đó đã có (tối đa chờ 20 phút) → không có tín hiệu "mọc ra sau".
- Bot Telegram gửi cùng tín hiệu này cho coin bạn tự chọn: 🪙 Coin theo dõi / 💼 Danh mục → 🎯 Tín hiệu chỉ báo Swing.

## Volume Profile Pro v3.2

- POC / VAH / VAL cuộn 150 nến, theo phiên (khung < 4H), **tuần trước** (xanh dương), **tháng trước** (tím), POC chưa bị chạm.
- **"Chỉ vẽ đường"** để chart gọn; **cảnh báo khi giá chạm** POC / VAH / VAL / POC trinh / mốc tuần–tháng
  (Condition "Volume Profile Pro v3.2" → Any alert() function call).
- Nghiên cứu 9 năm: vị trí giá so với POC rất có ích làm **bộ lọc** (đã đưa vào Swing v6 và bot). Dấu VP★ dùng riêng
  vẫn lỗ → giữ mặc định TẮT.

## Vì sao không dùng alert webhook của TradingView cho bot?

Webhook alert cần gói TradingView trả phí. Bot tự tính cùng công thức bằng Python nên giữ chi phí 0đ.
