# Hướng dẫn sử dụng 2 bot Telegram

Hệ thống có 2 bot, dùng song song:

| Bot | Dùng để |
|---|---|
| 🤖 **Bot Tín hiệu** | Nhận tín hiệu vào lệnh (giá vào, cắt lỗ, trailing stop), theo dõi lệnh, danh mục Spot, phân tích coin, hỏi AI về lệnh / danh mục của mình |
| 📰 **Bot Tin tức** | Tin tức đã dịch và tóm tắt tiếng Việt, tin gấp, lịch kinh tế, thị trường 24h, dấu hiệu coin sắp chạy, hỏi AI về thị trường |

> Bot là công cụ hỗ trợ, không đảm bảo thắng. Khoảng một nửa số lệnh sẽ lỗ; lợi nhuận đến từ việc lệnh lời chạy xa
> hơn lệnh lỗ. **Luôn đặt cắt lỗ (SL)** và chỉ rủi ro 0.5–1% vốn mỗi lệnh.

---

## 1. Bắt đầu

1. Mở link bot admin gửi, bấm **Start** (hoặc gõ `/start`).
2. Lần đầu bot báo "đang chờ duyệt". Khi admin duyệt, bot nhắn cho bạn — bấm `/start` lại để mở menu.
3. Menu nằm ở **bàn phím nút** phía dưới ô nhập tin. Không thấy thì bấm biểu tượng ⌘ / bàn phím cạnh ô nhập, hoặc gõ `/start`.
4. Làm tương tự với Bot Tin tức.

## 2. Bot Tín hiệu

### 2.1 Cài đặt lần đầu (⚙️ Cài đặt)

| Mục | Chọn |
|---|---|
| **Spot / Futures** | Spot: chỉ nhận lệnh MUA, có 💼 Danh mục. Futures: nhận MUA (LONG) và BÁN (SHORT), có 🪙 Coin theo dõi |
| **% rủi ro mỗi lệnh** | 0.5% (mặc định) hoặc 1%. Là số % vốn mất nếu lệnh chạm SL |
| **Kiểu swing** | ⚡ Swing ngắn (giữ vài giờ → vài ngày, tối đa 3 tín hiệu/ngày), 🌙 Swing dài (khoảng 1 tín hiệu/tuần), hoặc cả hai |
| **Sàn** | Binance hoặc **MEXC** (chọn MEXC thì tin tín hiệu có thêm giá MEXC lúc báo) |
| **Đơn vị tiền** | USDT hoặc **VNĐ** (danh mục hiển thị theo tỉ giá USDT/VNĐ) |
| **Bật / tắt tín hiệu** | Tắt khi muốn nghỉ, bật lại lúc nào cũng được |

Menu tự đổi theo chế độ:
- **Futures**: 📊 Lệnh đang chạy · 🔍 Phân tích coin · 🤖 Hỏi AI · 🪙 Coin theo dõi · ⚙️ Cài đặt · 📈 Thống kê · ℹ️ Hướng dẫn
- **Spot**: 💼 Danh mục của tôi · 🔍 Phân tích coin · 🤖 Hỏi AI · 📊 Tín hiệu Spot · ⚙️ Cài đặt · 📈 Thống kê · ℹ️ Hướng dẫn

### 2.2 Đọc tin tín hiệu

Ví dụ:

```
🟢 SOL/USDT | MUA · Futures · LONG
⚡ Swing ngắn (giữ vài giờ → vài ngày) · Hạng A
💰 Vào ngay: 120.37 (giá thị trường)
⛔ Không vào nếu giá đã vượt: 121.98
🛑 Cắt lỗ (SL): 115.00 (-4.5%)
🧱 Kháng cự gần: 128.40 (cách 1.5R) · Hỗ trợ gần: 101.40
🔁 Trailing Stop (cả lệnh): kích hoạt 125.74, callback 5.1%
🎯 Mục tiêu tham khảo: 131.11 (+8.9%) — không đặt chốt cố định, trailing tự chốt lời
⚖️ Khối lượng 11% vốn · đòn bẩy tối đa x10 · rủi ro 0.5% vốn
```

| Dòng | Ý nghĩa |
|---|---|
| 🟢 MUA / 🔴 BÁN | Chiều lệnh. Spot chỉ có MUA |
| 💰 Vào ngay | Vào bằng giá thị trường (Market) ngay khi nhận tin |
| ⛔ Không vào nếu giá đã vượt | Giá chạy quá mức này thì **bỏ qua**, không đuổi theo |
| 🛑 Cắt lỗ (SL) | Đặt ngay trên sàn. Chạm SL = mất đúng % rủi ro đã chọn |
| 🧱 Kháng cự / hỗ trợ gần | Vùng giá gần nhất phía trước / phía sau lệnh — để tham khảo |
| 🔁 Trailing Stop | Lệnh dừng di động: khi giá tới mức **kích hoạt**, sàn tự bám theo giá và đóng lệnh khi giá quay đầu **callback %** |
| 🎯 Mục tiêu tham khảo | Chỉ để hình dung, **không đặt lệnh chốt lời cố định** |
| ⚖️ Khối lượng | Giá trị vị thế nên vào (% vốn) để chạm SL chỉ mất đúng % rủi ro. Đòn bẩy chỉ giảm ký quỹ, không đổi số tiền mất |

Nút dưới tin: **📈 Mở chart TradingView** (xem chart), **🧠 Vì sao có tín hiệu này?** (AI giải thích).

### 2.3 Đặt lệnh trên sàn (ví dụ MEXC Futures)

1. Chọn đúng coin, chế độ ký quỹ **Isolated** (cô lập), đòn bẩy ≤ mức gợi ý.
2. Vào lệnh **Market** với khối lượng gợi ý.
3. Đặt **SL** (Stop-Loss) tại giá SL trong tin.
4. Đặt **Trailing Stop** cho toàn bộ vị thế: giá kích hoạt + callback % trong tin, chọn chỉ giảm vị thế (Reduce-Only).
5. Xong. Không cần canh chart; bot theo dõi và báo khi có thay đổi.

Sàn / tài khoản **không có Trailing Stop** (hoặc Spot): khi bot báo "giá tới +1R", tự dời SL về giá vào lệnh; sau đó dời
SL theo các tin bot báo.

### 2.4 Bot theo dõi lệnh giúp bạn

Bot trả lời ngay vào tin tín hiệu gốc khi:
- 🔒 Giá tới +1R: trailing đã kích hoạt (hoặc dời SL về giá vào nếu không dùng trailing).
- ❌ Chạm cắt lỗ / 🏁 Đóng lệnh (trailing chốt): kèm kết quả bằng R và % vốn.
- ⚠️ Có tin xấu ngược chiều lệnh (bấm vào tin để đọc tóm tắt tiếng Việt).
- 📋 **Tổng kết lệnh** sau khi đóng: lãi lớn nhất từng đạt, lý do đóng, nhận xét.

**📊 Lệnh đang chạy**: danh sách lệnh bạn đã nhận và còn mở. **📈 Thống kê**: kết quả thật của bot + số liệu backtest.

### 2.5 🔍 Phân tích coin

Gõ tên coin (ví dụ `SOL`, `PEPE`). Bot trả về điểm LONG/SHORT, dữ liệu phái sinh, tin tức và **KẾT LUẬN**:
- ✅ **CÓ THỂ VÀO LONG/SHORT**: kèm giá vào, SL, trailing, mức "không vào nếu đã vượt".
- ⏸ / ⛔ **CHƯA NÊN VÀO**: kèm lý do và **📋 Kịch bản chờ**: vùng giá nên chờ (theo đúng setup của bot), SL tham
  khảo, mức hủy kịch bản. Không đặt lệnh chờ sẵn; bấm **➕ Theo dõi** để bot tự gửi tín hiệu chính xác khi coin đạt chuẩn.
  Xu hướng không rõ thì bot ghi "đứng ngoài".

Bot phân tích coin có hợp đồng futures trên Binance (hầu hết coin phổ biến).

### 2.6 🪙 Coin theo dõi (Futures)

Thêm tối đa 20 coin muốn nhận tín hiệu ngoài Top 20. Chọn nhận tín hiệu từ: **Top 20**, **chỉ coin của tôi**, hoặc
**cả hai**. Ở đây cũng bật **🎯 Tín hiệu chỉ báo Swing** — nên chọn khung **4H** (backtest 9 năm tốt hơn nhiều so với 1H).

### 2.7 💼 Danh mục của tôi (Spot)

- **➕ Thêm coin**, bấm tên coin để: **➕ Mua / DCA** (gõ số tiền đã mua, ví dụ `100` hoặc `2tr`), **➖ Bán** (ví dụ `50%`),
  xem giá vốn, lời/lỗ, lịch sử.
- **🎯 Đặt vốn DCA**: gõ tổng tiền dự kiến mua thêm → bot chia vào 3 vùng hỗ trợ (30% / 30% / 40%) và **nhắc khi giá
  chạm vùng**. Mua xong bấm **✅ Đã mua** để danh mục tự cập nhật.
- Bot cảnh báo coin trong danh mục khi xu hướng đổi chiều, thủng vùng giá, OI / funding bất thường, có tin xấu.

### 2.8 🤖 Hỏi AI

Hỏi như nói chuyện bình thường; AI **nhớ các câu trước** (trong 2 giờ) nên có thể hỏi tiếp, ví dụ
"SOL có nên vào không?" rồi "vậy giá nào thì vào?".
- Hỏi về **bất kỳ coin nào**: AI dùng đúng phân tích của bot (kết luận có nên vào + kịch bản chờ).
- Futures: hỏi về lệnh bot đã gửi cho bạn (vì sao LONG, khi nào về bờ...), hoặc reply thẳng vào tin tín hiệu.
- Spot: hỏi về danh mục (nên DCA bao nhiêu, ở đâu, đang lời hay lỗ...).
- Hỏi kiến thức: funding là gì, đặt trailing stop trên sàn thế nào, quản lý vốn ra sao...
- Giá, mốc vào lệnh, SL **luôn lấy từ dữ liệu bot**; AI không tự đoán giá. 50 câu/ngày; câu ngoài chủ đề crypto
  không tính lượt.

### 2.9 Lịch tự động

| Giờ (VN) | Nội dung |
|---|---|
| Mỗi giờ, 6h–22h | Quét tín hiệu swing ngắn (ban đêm không gửi tín hiệu ngắn mới) |
| Khi nến 4H đóng | Quét swing dài; ban đêm gửi **không chuông** |
| 15:05 | Nếu cả ngày chưa có tín hiệu: danh sách coin đang hình thành setup (chưa phải tín hiệu) |
| 22:00 | Tổng kết cá nhân: lệnh trong ngày, lệnh giữ qua đêm, danh mục |
| Chủ nhật 22:05 | Tổng kết lệnh tuần |

Bot **tạm dừng tín hiệu mới từ 3 giờ trước đến 1 giờ sau** tin kinh tế Mỹ quan trọng (CPI, lãi suất Fed, việc làm...).

## 3. Bot Tin tức

### 3.1 Menu

| Nút | Nội dung |
|---|---|
| 📰 Tin mới nhất | 8 tin quan trọng nhất 24h. **Bấm vào tin** → bản tóm tắt tiếng Việt + nút mở bài gốc |
| 📅 Lịch tuần | Tin kinh tế Mỹ trong tuần; bấm từng tin để xem giải thích và thống kê ảnh hưởng tới BTC |
| 🌍 Thị trường 24h | BTC, ETH, coin tăng/giảm mạnh, Fear & Greed, OI, funding, dòng tiền stablecoin |
| 🔥 Coin đáng chú ý | Coin tăng/giảm mạnh, OI biến động mạnh, coin gần đủ điều kiện vào lệnh |
| 🤖 Hỏi AI crypto | Hỏi bất kỳ điều gì về thị trường crypto, tin tức, vĩ mô (100 câu/ngày) |
| ⚙️ Cài đặt tin | Bật 🔔 / tắt 🔕 từng loại tin tự động |

### 3.2 Tin tự động

| Tin | Khi nào |
|---|---|
| 🌅 Thị trường 7h | Mỗi sáng; kèm lịch tin kinh tế hôm nay nếu có tin mạnh |
| ⏰ Tin vĩ mô Mỹ | Trước 1 giờ và 1 giờ sau khi ra tin (thị trường phản ứng thế nào) |
| ⚡ Tin nóng | Tin ảnh hưởng xu hướng — gửi **ngay**, kèm tóm tắt tiếng Việt |
| 💰 Tiền lớn vào / ra | Stablecoin phát hành / rút ≥ 1 tỉ USD trong 24h |
| 🆕 Niêm yết | Coin sắp niêm yết trên Binance / Upbit (thường biến động rất mạnh) |
| 🚀 Dấu hiệu sớm | Coin có dấu hiệu gom hàng / dễ bị ép short — **trước khi** chạy (tối đa 5 tin/ngày, kèm ảnh) |
| 📈 Coin chạy mạnh | Coin Top 20 tăng/giảm mạnh kèm khối lượng lớn (tối đa 1 tin / 4 giờ) |
| 📊 Tổng kết tuần | Chủ nhật 20:00 |

Tin gấp (⚡ 💰 🆕) luôn có chuông; tin thường ban đêm (22h–6h) gửi không chuông.

### 3.3 Dùng tin 🚀 "dấu hiệu sớm" thế nào

Tin này báo **sắp có biến động mạnh**, **chưa biết chắc hướng**:
- Gom hàng: 2 năm qua, 24h sau đó 33% lần giá tăng ≥10%, 16% lần giảm ≥10% (bình thường 9% / 7%).
- Ép short: 46% lần tăng ≥10%, nhưng 32% lần giảm ≥10% — biến động mạnh cả 2 chiều.

Cách dùng: bấm nút **🔍 … có nên vào không?** → Bot Tín hiệu kiểm tra ngay và trả lời **CÓ THỂ VÀO** (kèm giá vào,
SL, trailing) hoặc **CHƯA NÊN VÀO**. Chưa nên vào thì bấm **➕ Theo dõi** để bot tự báo khi đạt chuẩn.
**Không vào lệnh chỉ vì tin dấu hiệu sớm.**

## 4. Dữ liệu và sàn giao dịch

- Bot tính tín hiệu bằng dữ liệu **Binance Futures** (thanh khoản lớn nhất, giá chuẩn của thị trường). Khi Binance
  tạm giới hạn, bot tự chuyển sang Bybit / MEXC nên vẫn chạy bình thường.
- **Giao dịch trên MEXC**: giá MEXC thường lệch Binance dưới 0.1–0.3% với coin lớn. Chọn sàn **MEXC** trong ⚙️ Cài đặt
  để tin tín hiệu hiện thêm giá MEXC lúc báo và mức lệch. Coin nhỏ, thanh khoản thấp có thể lệch nhiều hơn — kiểm tra
  giá trước khi vào.
- **Sàn Việt Nam**: giá coin trên sàn Việt bám theo giá quốc tế (USDT); chọn đơn vị **VNĐ** để danh mục hiển thị
  theo tỉ giá USDT/VNĐ. Tín hiệu vẫn dùng được, chỉ cần so giá trên sàn với giá trong tin trước khi vào.
- Sàn không có hợp đồng Futures hoặc Trailing Stop: dùng chế độ **Spot** và dời SL tay theo tin bot báo.

## 5. Kỳ vọng thực tế (backtest)

| | Có lời | Lời TB / lệnh | Ghi chú |
|---|---|---|---|
| ⚡ Swing ngắn (Futures) | 45% | +0.21R | 2 năm, 40 coin; sụt giảm tệ nhất ~15R |
| 🌙 Swing dài (Futures) | 42% | +0.43R | ~1 lệnh/tuần |
| 🎯 Chỉ báo Swing 4H | 48% | +0.29R | 9 năm, 53 coin |

R = số tiền mất nếu chạm SL. Với rủi ro 0.5%/lệnh, +0.2R/lệnh ≈ +0.1% vốn mỗi lệnh trung bình; sẽ có chuỗi thua liên
tiếp và tuần / tháng lỗ. Đánh giá sau vài chục lệnh, không phải vài lệnh. Kết quả quá khứ không đảm bảo tương lai.

## 6. Câu hỏi thường gặp

**Bấm menu không thấy gì?** Gõ `/start` để hiện lại menu.

**Nhận tín hiệu nhưng giá đã chạy xa?** So với mức "Không vào nếu giá đã vượt"; quá mức thì bỏ qua.

**Sao lâu rồi không có tín hiệu?** Bot chỉ báo khi đủ điều kiện; có ngày không có tín hiệu nào là bình thường. Thêm
coin ở 🪙 Coin theo dõi để có nhiều cơ hội hơn.

**Lệnh lỗ liên tục mấy lệnh?** Bình thường trong hệ thống có tỉ lệ thắng dưới 50%. Không tăng khối lượng để gỡ.

**Có nên dời SL ra xa khi giá sắp chạm?** Không. SL là giới hạn rủi ro đã tính trước.

**Tin tức hiện chưa dịch?** Hiếm khi xảy ra (AI tạm hết lượt); thử lại sau ít phút.
