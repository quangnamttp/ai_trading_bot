# Hướng dẫn sử dụng Swing Entry Pro v6.1

Chỉ báo cho biết **khi nào vào lệnh**: giá vào, cắt lỗ (SL), cách để Trailing Stop tự chốt lời, và các vùng hỗ trợ /
kháng cự gần giá. Dùng cho coin có hợp đồng futures trên Binance (đa số coin lớn), giao dịch được cả Spot (chỉ MUA)
và Futures (MUA / BÁN).

> Chỉ báo không đảm bảo thắng. Trong 9 năm backtest, khoảng **một nửa số lệnh bị lỗ**; lợi nhuận đến từ số ít lệnh
> chạy xa. Luôn đặt SL và chỉ mất một phần nhỏ vốn mỗi lệnh (xem mục 6).

---

## 1. Cài đặt lần đầu (khoảng 5 phút)

1. Đăng nhập [tradingview.com](https://www.tradingview.com) (tài khoản miễn phí là đủ).
2. Mở chart một coin: gõ tên vào ô tìm kiếm góc trên bên trái, ví dụ `BTCUSDT.P` rồi chọn dòng **BINANCE**.
   - Giao dịch Futures: dùng mã có đuôi **`.P`** (hợp đồng vĩnh cửu), ví dụ `BINANCE:SOLUSDT.P`.
   - Giao dịch Spot: dùng mã thường, ví dụ `BINANCE:SOLUSDT`.
   - Mở chart của MEXC, OKX… vẫn được: chỉ báo tự lấy dữ liệu OI của Binance.
3. Dưới đáy màn hình bấm **Pine Editor** (trên điện thoại không có, phải dùng máy tính).
4. Xóa hết đoạn code mẫu trong Pine Editor.
5. Mở file [`swing_entry_pro.pine`](swing_entry_pro.pine), copy **toàn bộ** nội dung, dán vào Pine Editor.
6. Bấm **Save** (đặt tên, ví dụ "Swing Pro"), rồi bấm **Add to chart**.
7. Trên chart xuất hiện chữ **Swing Pro v6.1** ở góc trên bên trái. Không có dấu **!** đỏ bên cạnh là đã chạy đúng.

Muốn dùng trên coin khác: chỉ cần đổi mã coin trên chart, chỉ báo đi theo. Muốn chỉ báo có sẵn ở mọi chart: rê chuột
vào tên chỉ báo → **⋯** → **Add to favorites**, lần sau mở danh sách **Indicators → Favorites** để thêm nhanh.

## 2. Thiết lập khuyên dùng

| Việc cần chỉnh | Chọn | Lý do |
|---|---|---|
| Khung thời gian của chart | **4h** (bấm nút khung giờ trên thanh công cụ) | 9 năm backtest: 4H lời +0.29R/lệnh; 1H chỉ +0.03R/lệnh từ 2021 |
| Cài đặt → "Cho phép tín hiệu BÁN/SHORT" | **Tắt** nếu chỉ chơi Spot | Spot không bán khống được |
| Cài đặt → "Lọc Open Interest" và "Lọc Volume Profile" | **Giữ bật** | Đã kiểm chứng trong backtest |
| Các ô còn lại | Để mặc định | Các con số trong hướng dẫn này tính với mặc định |

Mở Cài đặt: rê chuột vào chữ **Swing Pro v6.1** trên chart → bấm biểu tượng **bánh răng ⚙️** → tab **Inputs**.

## 3. Đọc chart

| Bạn thấy | Ý nghĩa |
|---|---|
| Nhãn xanh **MUA A · 86đ** / nhãn đỏ **BÁN B · 72đ** | Tín hiệu vào lệnh. Chữ A/B là hạng, số là điểm (0–100). Backtest cho thấy hạng A **không** tốt hơn hạng B → coi như nhau |
| Rê chuột vào nhãn MUA/BÁN | Hiện đầy đủ: giá vào, SL, mục tiêu tham khảo, mục tiêu xa, mức kích hoạt + callback trailing, giá "không vào nếu đã vượt", kháng cự / hỗ trợ gần nhất |
| Hộp xanh nhạt / đỏ nhạt sau nhãn | Vùng lời tới mục tiêu tham khảo 2R / vùng lỗ tới SL |
| Đường đỏ mảnh | SL của lệnh đang chạy |
| Đường trắng mảnh | Giá vào |
| **Đường vàng** | Trailing stop, xuất hiện khi lệnh lời được +1R và dời theo giá |
| Nhãn **Đóng +2.35R** / **Đóng −1.01R** | Lệnh trước đó đã đóng, lời/lỗ bao nhiêu R |
| Hình thoi vàng nhỏ | "Chuẩn bị": setup gần đạt chuẩn. **Chưa phải tín hiệu**, chỉ để để ý coin |
| Khung đỏ **KC1, KC2** phía trên giá | Kháng cự gần nhất (vùng giá dễ bị bán ra) |
| Khung xanh **HT1, HT2** phía dưới giá | Hỗ trợ gần nhất (vùng giá dễ được mua vào) |
| Chữ **(mạnh)**, viền dày | Vùng có từ 3 mốc giá trùng nhau trở lên |

Vùng hỗ trợ / kháng cự **chỉ để nhìn**, không phải điều kiện vào lệnh. Backtest cho thấy lệnh có kháng cự ở gần
không bị kém hơn, nên **không bỏ tín hiệu chỉ vì có vùng cản gần**.

### Bảng thống kê (góc trên bên phải)

| Dòng | Ý nghĩa |
|---|---|
| Khung tín hiệu | Khung đang dùng để tính tín hiệu |
| Đánh giá khung | Xanh lá "Khuyên dùng" ở 4H; màu cam ở khung khác |
| Lệnh trên chart này / Có lời / TB / Tổng / Sụt giảm tối đa | Kết quả nếu đã vào **mọi** tín hiệu trên đúng coin và khung đang xem (chỉ tính phần lịch sử đang tải trên chart) |
| Dữ liệu OI | Thay đổi OI Binance. Ở 4H ghi "Không dùng" là đúng |
| Lệnh hiện tại | Có lệnh đang chạy không, "trailing ON" = đã kích hoạt |

Kết quả trong bảng chỉ của 1 coin trong vài tháng nên dao động mạnh. Đừng kết luận chỉ báo hỏng hay tốt từ vài lệnh.

## 4. Vào lệnh từng bước

Khi có nhãn **MUA** hoặc **BÁN** (nến 4H vừa đóng):

1. **Rê chuột vào nhãn** để xem các con số.
2. **Kiểm tra giá hiện tại**: nếu giá đã vượt mức "Không vào nếu giá đã vượt" thì **bỏ qua**, không đuổi theo.
3. **Tính khối lượng** sao cho chạm SL chỉ mất 0.5–1% vốn (xem ví dụ mục 6).
4. **Vào lệnh bằng giá thị trường** (Market).
5. **Đặt SL ngay** tại mức SL trong nhãn.
6. **Đặt Trailing Stop cho cả lệnh**:
   - Giá kích hoạt (Activation price) = mức "kích hoạt" trong nhãn.
   - Tỉ lệ callback = % "callback" trong nhãn.
   - Trên MEXC / Binance Futures: chọn loại lệnh **Trailing Stop** (lệnh dừng di động), chiều ngược với lệnh đang
     mở, tích **Reduce-Only** (chỉ giảm vị thế), khối lượng bằng toàn bộ vị thế, rồi nhập 2 số trên. Giao diện sàn
     hay thay đổi; không tìm thấy thì tìm "trailing stop" trong mục hỗ trợ của sàn.
   - Sàn không có Trailing Stop (hoặc Spot): khi giá chạm mức kích hoạt, tự dời SL về giá vào, sau đó cứ mỗi nến
     4H đóng thì dời SL theo đường vàng trên chart.
7. **Không đặt lệnh chốt lời cố định**. Mục tiêu 2R chỉ để tham khảo; trailing tự chốt khi giá quay đầu.
   Backtest 9 năm: để trailing chốt cả lệnh lời hơn chốt 50% cố định.
8. Để lệnh tự chạy. Lệnh 4H thường giữ khoảng **6–7 ngày** (trung vị 156 giờ). Chỉ báo tự đóng lệnh sau 168 nến
   (4H ≈ 28 ngày) nếu chưa chạm SL/trailing, lúc đó đóng tay theo giá thị trường.

Chỉ báo **chỉ mở 1 lệnh 1 lúc** trên mỗi chart: khi đang có lệnh thì không hiện tín hiệu mới của coin đó.

## 5. Cài cảnh báo về điện thoại

1. Cài app **TradingView** trên điện thoại, đăng nhập cùng tài khoản.
2. Trên máy tính, mở chart coin (khung 4h, đã có Swing Pro v6.1).
3. Bấm nút **đồng hồ báo thức ⏰ (Alert)** trên thanh công cụ, hoặc phím **Alt + A**.
4. Ô **Condition**: chọn **Swing Pro v6.1**, ô bên dưới chọn **Any alert() function call**.
5. Tab **Notifications**: tích **Notify in app**.
6. Bấm **Create**.

Cảnh báo sẽ báo: tín hiệu **MUA/BÁN** (kèm giá vào, SL, trailing), và nến đóng **phá kháng cự** / **thủng hỗ trợ**.
Muốn nhận thêm "Chuẩn bị": tạo thêm 1 cảnh báo, ô dưới chọn **Chuẩn bị**.

- Mỗi cảnh báo chỉ theo dõi **1 coin, 1 khung giờ**. Coin khác phải tạo thêm.
- Tài khoản miễn phí chỉ giữ được ít cảnh báo cùng lúc, nên chọn vài coin chính.
- Sau khi dán bản chỉ báo mới: **xóa cảnh báo cũ và tạo lại**.
- Không muốn tự canh nhiều coin: Bot Tín hiệu Telegram gửi cùng tín hiệu này cho coin bạn chọn
  (🪙 Coin theo dõi hoặc 💼 Danh mục → 🎯 Tín hiệu chỉ báo Swing → chọn **4H**).

## 6. Quản lý vốn (quan trọng nhất)

**R** = số tiền bạn chấp nhận mất nếu lệnh chạm SL. Mọi kết quả đều tính theo R.

Ví dụ: vốn 1.000 USDT, rủi ro 1% mỗi lệnh → 1R = 10 USDT. Nhãn MUA cho SL cách giá vào 4%:
- Khối lượng lệnh = 10 ÷ 4% = **250 USDT** (giá trị vị thế).
- Futures đòn bẩy x5: ký quỹ 50 USDT. Đòn bẩy chỉ đổi số tiền ký quỹ, **không** đổi số tiền mất khi chạm SL.
- Chạm SL: mất khoảng 10 USDT (+ phí). Lệnh chạy +3R: lời khoảng 30 USDT.

Dựa trên backtest 4H:
- Rủi ro **0.5–1% vốn / lệnh**. Chuỗi thua dài nhất 9 năm là **13 lệnh liên tiếp** → với 1%/lệnh là mất khoảng 13% vốn.
- Không tăng khối lượng để "gỡ" sau vài lệnh thua.
- Không dời SL ra xa hơn mức trong nhãn.
- Đánh giá sau ít nhất 30–50 lệnh, không phải sau 5 lệnh.

## 7. Kết quả backtest (để biết kỳ vọng thực tế)

53 coin, 08/2017 → 09/2026, mỗi thời điểm chỉ tính 20 coin thanh khoản cao nhất, đã trừ phí 0.1%, chưa tính trượt giá.

| | **4H (khuyên dùng)** | 1H (tham khảo) |
|---|---|---|
| Số lệnh 9 năm | 1.179 | 8.674 |
| Tỉ lệ lệnh có lời | 48% | 41% |
| Lời trung bình / lệnh | **+0.29R** | +0.10R (từ 2021: +0.03R) |
| 2 năm gần nhất | +0.21R / lệnh | +0.07R / lệnh |
| 12 tháng gần nhất | +0.29R / lệnh | +0.13R / lệnh |
| Chỉ lệnh MUA (dùng cho Spot) | +0.34R / lệnh | +0.08R / lệnh |
| Năm bị lỗ | 1/10 (2022: −0.03R) | 2/10 (2023, 2024) |
| Chuỗi thua dài nhất | 13 lệnh | 43 lệnh |
| Tỉ lệ lệnh lời ≥ 2R | 13% | 10% |
| Thời gian giữ lệnh (trung vị) | 156 giờ (~6.5 ngày) | 39 giờ |
| Số tín hiệu | ~0.7 lệnh / coin / tháng | ~3 lệnh / coin / tháng |

Cách hiểu: với 4H, trung bình mỗi lệnh lời 0.29R. Với rủi ro 1% vốn/lệnh, 100 lệnh kỳ vọng khoảng +29% vốn, nhưng có
những giai đoạn thua liên tiếp và khoảng một nửa số tháng có thể lỗ. Kết quả quá khứ không đảm bảo tương lai.

## 8. Toàn bộ cài đặt

**Tín hiệu**

| Cài đặt | Mặc định | Ghi chú |
|---|---|---|
| Khung tín hiệu | trống (= khung chart) | Chart nhỏ hơn 1H (vd 15m) thì tự lấy tín hiệu 1H |
| Ngưỡng điểm khung 1H / 4H | 75 / 70 | Tăng lên = ít tín hiệu hơn; backtest không thấy tốt hơn |
| Lọc Open Interest ở khung 1H | Bật | Chỉ có tác dụng ở 1H |
| Lọc Volume Profile (POC) | Bật | LONG khi giá trên POC, SHORT khi dưới |
| OI biến động tối thiểu | 5% | |
| Mã OI tự nhập | trống | Chỉ nhập khi bảng báo không tìm thấy OI, vd `BINANCE:1000PEPEUSDT.P_OI` |
| Cho phép tín hiệu BÁN/SHORT | Bật | Tắt nếu chỉ chơi Spot |
| Hiện cảnh báo "Chuẩn bị" | Bật | |
| Mã BTC tham chiếu | `BINANCE:BTCUSDT.P` | Dùng để xem xu hướng chung |

**Quản lý lệnh**

| Cài đặt | Mặc định | Ghi chú |
|---|---|---|
| Mục tiêu tham khảo (R) | 2 | Chỉ để vẽ, không phải lệnh chốt |
| Chốt từng phần tại mục tiêu (%) | 0 | 0 = để trailing chốt cả lệnh (tốt nhất trong backtest) |
| Kích hoạt trailing tại (R) | 1 | |
| Callback trailing (x ATR) | 2.5 | |
| Callback tối đa (%) | 10 | Giới hạn của sàn |
| Giữ lệnh tối đa (nến) | 168 | |
| Phí khứ hồi (%) | 0.1 | Chỉ dùng để tính bảng thống kê |

**Hiển thị**

| Cài đặt | Mặc định | Ghi chú |
|---|---|---|
| Hiện bảng thống kê / vị trí / cỡ chữ | Bật / Trên phải / Nhỏ | |
| Vẽ hộp vị thế | Bật | |
| Vẽ hỗ trợ / kháng cự | Bật | 2 kháng cự + 2 hỗ trợ gần giá nhất |
| Độ rõ đỉnh/đáy xoay chiều | 5 | Tăng lên = chỉ lấy đỉnh/đáy lớn hơn |
| Gộp các mốc cách nhau dưới (x ATR) | 0.5 | Tăng lên = vùng rộng hơn, ít vùng hơn |
| Viền khung hỗ trợ / kháng cự màu trắng | Tắt | Bật nếu thích viền trắng |
| Kéo dài khung sang phải | 25 nến | |
| Số nến / số mức giá Volume Profile | 150 / 24 | Khớp với Volume Profile Pro |

## 9. Câu hỏi thường gặp

**Dấu ! đỏ cạnh tên chỉ báo, chart không hiện gì?**
Chỉ báo bị lỗi. Bấm vào dấu !, chụp màn hình dòng báo lỗi gửi người hỗ trợ. Thường do dán thiếu code: copy lại
toàn bộ file và dán lại.

**Tín hiệu có bị mất / mọc ra sau không?**
Không. Tín hiệu chỉ quyết định 1 lần khi nến khung tín hiệu đã đóng. Ở 1H, chỉ báo chờ dữ liệu OI của nến đó (tối
đa 20 phút) rồi mới quyết định, nên có thể xuất hiện trễ vài phút sau khi nến đóng.

**Vì sao lâu rồi không có tín hiệu?**
Khung 4H trung bình chỉ khoảng 0.7 tín hiệu mỗi coin mỗi tháng. Theo dõi 10–20 coin hoặc dùng Bot Tín hiệu Telegram
để không bỏ lỡ.

**Bảng ghi "Không tìm thấy OI Binance"?**
Chỉ ảnh hưởng khung 1H. Vào Cài đặt, nhập mã OI theo gợi ý trong bảng. Coin không có futures trên Binance thì
chỉ báo vẫn chạy nhưng bỏ lọc OI.

**Giá trên MEXC hơi khác giá trên chart Binance?**
Bình thường, thường lệch dưới 0.1%. Dùng giá SL / kích hoạt trong nhãn, hoặc mở chart MEXC để lấy đúng giá sàn
(tín hiệu giống nhau vì chỉ báo lấy OI Binance).

**Có nên vào lệnh khi thấy hình thoi vàng "Chuẩn bị"?**
Không. Đó chỉ là nhắc để ý; chưa đủ điều kiện.

**Có chỉnh thông số để lời hơn được không?**
Các thông số mặc định đã được chọn qua backtest 9 năm; nhiều cách chỉnh "đẹp hơn trên quá khứ" đã được thử và không
ổn định qua các năm. Khuyên giữ mặc định.
