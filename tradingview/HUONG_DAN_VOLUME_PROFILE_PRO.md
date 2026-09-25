# Hướng dẫn sử dụng Volume Profile Pro v3.3

Chỉ báo vẽ **bản đồ vùng giá**: ở mức giá nào thị trường đã mua bán nhiều nhất (POC, Value Area), mốc của tuần và
tháng trước, và các POC chưa bị giá quay lại chạm. Đây là **công cụ xem vùng giá**, không phải công cụ báo điểm vào
lệnh. Điểm vào lệnh dùng Swing Entry Pro (xem [HUONG_DAN_SWING_ENTRY_PRO.md](HUONG_DAN_SWING_ENTRY_PRO.md)).

---

## 1. Cài đặt lần đầu

1. Mở chart coin trên [tradingview.com](https://www.tradingview.com), ví dụ `BINANCE:BTCUSDT.P`.
2. Dưới đáy màn hình bấm **Pine Editor**, xóa hết code mẫu.
3. Mở file [`volume_profile_pro.pine`](volume_profile_pro.pine), copy **toàn bộ**, dán vào Pine Editor.
4. Bấm **Save** (đặt tên, ví dụ "Volume Profile"), rồi **Add to chart**.
5. Trên chart xuất hiện chữ **Volume Profile v3.3**. Không có dấu **!** đỏ là đã chạy đúng.

Tài khoản TradingView miễn phí cho gắn 2 chỉ báo mỗi chart: vừa đủ cho Swing Entry Pro + Volume Profile Pro.

## 2. Thiết lập khuyên dùng

| Việc | Chọn | Lý do |
|---|---|---|
| Khung chart | **4h** (cùng khung với Swing Entry Pro) | Mốc POC 150 nến khớp với bộ lọc POC của Swing |
| Chart quá rối | Cài đặt → **"Chỉ vẽ đường"** | Ẩn các thanh histogram, chỉ giữ đường POC / VAH / VAL |
| Dấu VP★ | **Giữ tắt** (mặc định) | Backtest 2 năm / 20 coin: dùng riêng bị lỗ (−0.06 … −0.23R/lệnh) |
| Còn lại | Mặc định | |

Mở Cài đặt: rê chuột vào chữ **Volume Profile v3.3** trên chart → bánh răng **⚙️** → tab **Inputs**.

## 3. Các khái niệm cần biết

- **Volume Profile**: thay vì đếm khối lượng theo thời gian (cột volume dưới chart), đếm khối lượng theo **mức giá**.
  Mức giá nào có thanh ngang dài = ở đó đã giao dịch nhiều.
- **POC** (Point of Control): mức giá giao dịch nhiều nhất. Giá hay bị "hút" về POC hoặc dừng lại ở POC.
- **Value Area** (vùng giá trị): khoảng giá chứa 70% khối lượng, từ **VAL** (đáy vùng) đến **VAH** (đỉnh vùng).
  Giá trong vùng này = thị trường đang "chấp nhận" mức giá; giá ra ngoài vùng = đang tìm mặt bằng giá mới.
- **POC trinh** (naked POC): POC của một ngày cũ mà giá **chưa quay lại chạm**. Là mốc giá thường được nhắm tới.
- **LVN** (khoảng trống thanh khoản): khoảng giá rất ít giao dịch. Giá thường đi **nhanh** qua các khoảng này.

## 4. Đọc chart

| Bạn thấy | Ý nghĩa |
|---|---|
| Các thanh ngang xanh dương / cam ở bên trái vùng 150 nến gần nhất | Volume Profile cuộn 150 nến. Xanh = phần mua, cam = phần bán. Màu đậm = nằm trong Value Area |
| Đường **đỏ dày** + nhãn **POC** | POC của 150 nến gần nhất |
| Đường xanh dương đứt + nhãn **VAH** | Đỉnh vùng giá trị |
| Đường cam đứt + nhãn **VAL** | Đáy vùng giá trị |
| Thanh ngang xanh ngọc / tím + đường vàng **POC Phiên** | Profile của phiên giao dịch (mặc định phiên Á), chỉ hiện ở khung nhỏ hơn 4H |
| Đường **xanh dương đậm** + nhãn **POC tuần trước**, chấm "VAH tuần", "VAL tuần" | Mốc của tuần trước |
| Đường **tím** + nhãn **POC tháng trước**, chấm "VAH tháng", "VAL tháng" | Mốc của tháng trước |
| Đường đỏ ngắn + nhãn **POC trinh** | POC của ngày cũ chưa bị chạm (khung ≥ 4H: tính theo tuần) |
| Nhãn **⚠** bên trái | Khoảng trống thanh khoản (LVN) |
| Đường trắng mờ | EMA 50 (xu hướng) |
| Bảng góc dưới phải | Giá POC, Value Area (cuộn và phiên), số POC trinh còn lại, mốc tuần / tháng trước |

## 5. Dùng cùng Swing Entry Pro

Volume Profile giúp **hiểu bối cảnh** của tín hiệu Swing, không thay thế tín hiệu:

1. **Bộ lọc POC có sẵn trong Swing**: Swing chỉ cho tín hiệu MUA khi giá **trên** POC 150 nến và BÁN khi giá **dưới**
   POC. Backtest 9 năm khung 4H: bộ lọc này nâng lời trung bình từ +0.25R lên **+0.29R**/lệnh và giảm sụt giảm tối đa
   từ 35R xuống **30R**. Nhìn đường POC đỏ là biết vì sao có hoặc không có tín hiệu.
2. **Mục tiêu xa**: nhãn MUA/BÁN của Swing dùng VAH / VAL / POC làm "mục tiêu xa". Lệnh vẫn để trailing chốt; mục tiêu
   xa chỉ giúp hình dung giá có thể chạy tới đâu.
3. **Hiểu lệnh đang chạy**: giá tới gần VAH / POC tuần / POC trinh phía trên thì thường chững lại. Không cần đóng lệnh
   sớm; trailing stop sẽ lo phần chốt lời.

Không nên:
- Vào lệnh chỉ vì giá chạm POC / VAH / VAL. Chạm mốc **không phải** tín hiệu.
- Bật dấu VP★ và vào lệnh theo nó: đã backtest và bị lỗ.

## 6. Cài cảnh báo khi giá chạm mốc

1. Mở chart coin (đã có Volume Profile v3.3), bấm **đồng hồ báo thức ⏰** hoặc phím **Alt + A**.
2. Ô **Condition**: chọn **Volume Profile v3.3**, ô dưới chọn **Any alert() function call**.
3. Tab **Notifications**: tích **Notify in app** (cài app TradingView trên điện thoại để nhận).
4. Bấm **Create**.

Cảnh báo khi **nến đóng** mà giá vừa chạm: POC / VAH / VAL cuộn, mốc tuần trước, mốc tháng trước, POC trinh.
Bật / tắt từng loại trong Cài đặt → "Cảnh báo khi giá chạm …". Khi nhận cảnh báo: mở chart, xem có tín hiệu Swing
không. **Không vào lệnh chỉ vì cảnh báo chạm mốc.**

Sau khi dán bản chỉ báo mới: **xóa cảnh báo cũ và tạo lại**.

## 7. Toàn bộ cài đặt

**Chế độ hiển thị**

| Cài đặt | Mặc định | Ghi chú |
|---|---|---|
| Hiện Volume Profile Cuộn | Bật | 150 nến gần nhất |
| Hiện Volume Profile Theo Phiên | Bật | Tự ẩn ở khung 4H trở lên |
| Vị trí / cỡ chữ bảng | Dưới phải / Nhỏ | |
| Chỉ vẽ đường | Tắt | Bật cho chart gọn |
| Hiện POC / VAH / VAL tuần trước, tháng trước | Bật | |
| Cảnh báo chạm mốc cuộn / tuần–tháng / POC trinh | Bật | |

**Volume Profile Cuộn / Theo Phiên**

| Cài đặt | Mặc định | Ghi chú |
|---|---|---|
| Số nến nhìn lại | 150 | Giữ 150 để khớp bộ lọc POC của Swing |
| Số mức giá (bins) | 24 | Nhiều hơn = chi tiết hơn |
| Chọn phiên | Á (Asia) | Á 00–08h UTC (7–15h giờ VN), Âu 07–16h UTC, Mỹ 13–21h UTC, hoặc tự nhập |
| Xem lại bao nhiêu phiên | 1 | |

**Value Area & VP★**

| Cài đặt | Mặc định | Ghi chú |
|---|---|---|
| Value Area (%) | 70 | Chuẩn thông dụng |
| Đánh dấu VP★ | Tắt | Chỉ để tham khảo; dùng riêng bị lỗ |
| Khoảng cách coi là "chạm" (%) | 0.3 | Dùng cho VP★ |
| Chu kỳ MA / hệ số volume | 20 / 1.3 | Dùng cho VP★ |
| Chỉ vào lệnh thuận xu hướng | Bật | Dùng cho VP★ |
| Độ dài EMA xu hướng / hiện EMA | 50 / Bật | Tắt EMA nếu chart rối |
| SL / TP gợi ý cho VP★ | Bật, 1.2 / 2.0 ATR | Chỉ hiện khi bật VP★ |

**Khác**

| Cài đặt | Mặc định | Ghi chú |
|---|---|---|
| Ưu tiên nến gần đây | 0 (tắt) | 0.8 = profile nghiêng về giao dịch gần đây |
| Đánh dấu khoảng trống thanh khoản / ngưỡng | Bật / 15% | Mức giá có volume < 15% POC |
| Hiện POC trinh / số lượng tối đa | Bật / 10 | |
| Màu sắc | | Đổi tùy ý |

## 8. Câu hỏi thường gặp

**Dấu ! đỏ cạnh tên chỉ báo?**
Bấm vào dấu !, chụp màn hình dòng báo lỗi gửi người hỗ trợ. Bản v3.3 đã giữ sẵn 2000 nến lịch sử để không lỗi trên
khung nhỏ (15m, 5m).

**Vì sao POC / VAH / VAL thay đổi khi giá chạy?**
Profile cuộn luôn tính trên 150 nến gần nhất, nên khi có nến mới, mốc cũ nhất bị bỏ ra và các mức có thể dịch. Mốc
tuần trước / tháng trước thì cố định cho tới khi sang tuần / tháng mới.

**Chart chậm hoặc rối?**
Bật "Chỉ vẽ đường", tắt Profile Theo Phiên, hoặc giảm "Số mức giá" xuống 20.

**Không thấy Profile Theo Phiên?**
Ở khung 4H trở lên, phiên tự ẩn vì một nến đã dài gần bằng cả phiên. Xem ở khung 1H hoặc nhỏ hơn.
