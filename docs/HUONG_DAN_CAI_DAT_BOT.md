# Hướng dẫn cài đặt và vận hành bot

Dành cho người **cài đặt và quản lý** bot (admin). Người dùng bình thường đọc
[HUONG_DAN_SU_DUNG_BOT.md](HUONG_DAN_SU_DUNG_BOT.md).

Toàn bộ dịch vụ dùng gói **miễn phí**. Thời gian cài lần đầu: khoảng 45–60 phút.

---

## 1. Hệ thống gồm những gì

```
Telegram ──► 🤖 Bot Tín hiệu  ┐
         ──► 📰 Bot Tin tức   ┘── 1 dịch vụ trên Render (máy chủ chạy 24/24)
                                   │
                                   ├── Neon (database: người dùng, lệnh, danh mục)
                                   ├── Binance / Bybit / MEXC (giá, nến, OI — miễn phí, không cần tài khoản)
                                   ├── RSS tin tức, lịch kinh tế, DefiLlama
                                   └── AI: Gemini → Groq → OpenRouter (dịch, tóm tắt tin, trả lời câu hỏi)
UptimeRobot ──► gọi /health mỗi 5 phút để Render không "ngủ"
GitHub ──► mỗi lần có code mới, Render tự cập nhật
```

| Dịch vụ | Dùng để | Bắt buộc? |
|---|---|---|
| Telegram (@BotFather) | Tạo 2 bot | Có |
| GitHub | Chứa code, Render lấy code từ đây | Có |
| Render | Máy chủ chạy bot | Có |
| Neon | Lưu dữ liệu (Render miễn phí xóa ổ đĩa mỗi lần khởi động lại) | Có |
| UptimeRobot | Giữ bot luôn thức | Có |
| Google AI Studio (Gemini) | AI chính: dịch, tóm tắt tin tiếng Việt, hỏi đáp | Rất nên có |
| Groq, OpenRouter | AI dự phòng khi Gemini hết lượt | Nên có |
| CryptoPanic | Thêm nguồn tin | Không |

> **Bảo mật**: token bot, khóa AI, chuỗi kết nối Neon là **mật khẩu**. Chỉ dán vào mục Environment của Render.
> Không gửi qua chat, không đưa lên GitHub. Lộ token thì vào @BotFather → `/revoke` để đổi.

## 2. Tạo 2 bot Telegram

1. Mở Telegram, tìm **@BotFather**, bấm Start.
2. Gõ `/newbot` → đặt **tên hiển thị** (ví dụ "Tín Hiệu Crypto AI") → đặt **username** kết thúc bằng `bot`
   (ví dụ `tinhieucrypto_ai_bot`).
3. BotFather trả về **token** dạng `123456789:AAH...`. Lưu lại: đây là `TELEGRAM_BOT_TOKEN`.
4. Làm lại bước 2–3 để tạo **Bot Tin tức** (ví dụ `tintuccrypto_ai_bot`). Token này là `NEWS_BOT_TOKEN`.
5. Lấy **Telegram ID** của admin: tìm **@userinfobot**, bấm Start, bot trả về dãy số `Id`. Đây là `ADMIN_IDS`
   (nhiều admin: cách nhau dấu phẩy, ví dụ `111111,222222`).

Tùy chọn: trong @BotFather dùng `/setuserpic` (ảnh đại diện), `/setdescription` (mô tả hiện khi mở bot lần đầu).

## 3. Tạo database Neon

1. Vào [neon.tech](https://neon.tech) → đăng ký (dùng tài khoản Google cho nhanh).
2. **Create project**: tên tùy ý, **Region: AWS Europe Central 1 (Frankfurt)** (gần máy chủ Render).
3. Ở trang project bấm **Connect** → copy **Connection string**, dạng
   `postgresql://user:matkhau@ep-xxx.eu-central-1.aws.neon.tech/neondb?sslmode=require`.
   Đây là `DATABASE_URL`.

Bot tự tạo bảng và tự thêm cột khi nâng cấp, không cần chạy lệnh gì trong Neon.

## 4. Lấy khóa AI (miễn phí)

| Biến | Lấy ở đâu |
|---|---|
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) → **Get API key** → Create API key |
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) → **API Keys** → Create |
| `OPENROUTER_API_KEY` | [openrouter.ai](https://openrouter.ai) → **Keys** → Create |

Không có khóa AI thì bot vẫn chạy, nhưng tin tức sẽ **không dịch / không tóm tắt được** (tin nóng sẽ không gửi vì
khách không đọc tiếng Anh). Nên có ít nhất 2 khóa để dự phòng khi một bên hết lượt miễn phí.

## 5. Đưa code lên GitHub

Nếu nhận bàn giao dưới dạng repo GitHub: bấm **Fork** (hoặc được thêm làm người sở hữu repo) để repo nằm trong
tài khoản của bạn. Render sẽ lấy code từ repo này.

## 6. Tạo dịch vụ trên Render

1. Vào [render.com](https://render.com) → đăng ký bằng tài khoản GitHub.
2. **New → Blueprint** → chọn repo bot. Render đọc file `render.yaml` và tạo dịch vụ `ai-signal-bot-v3`
   (gói Free, region **Frankfurt** — bắt buộc ở ngoài Mỹ vì Binance chặn IP Mỹ).
3. Điền các biến Render hỏi:

| Biến | Giá trị |
|---|---|
| `TELEGRAM_BOT_TOKEN` | token Bot Tín hiệu |
| `NEWS_BOT_TOKEN` | token Bot Tin tức |
| `ADMIN_IDS` | Telegram ID admin |
| `DATABASE_URL` | chuỗi kết nối Neon |
| `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY` | khóa AI |
| `CRYPTOPANIC_TOKEN` | để trống nếu không có |

`WEBHOOK_SECRET` Render tự tạo; địa chỉ web (`RENDER_EXTERNAL_URL`) Render tự cấp — không cần điền.

4. Bấm **Apply**. Chờ 3–5 phút cho lần build đầu. Mục **Logs** hiện dòng khởi động là xong.
5. Kiểm tra: mở `https://<tên-dịch-vụ>.onrender.com/health` trên trình duyệt, thấy `{"ok": true, ...}` là bot đang chạy.

Thay đổi biến sau này: Render → dịch vụ → **Environment** → sửa → **Save Changes** (bot tự khởi động lại).

## 7. Giữ bot luôn thức (UptimeRobot)

Render miễn phí cho "ngủ" sau 15 phút không có ai gọi. Khi ngủ, bot không quét và không báo gì.

1. Vào [uptimerobot.com](https://uptimerobot.com) → đăng ký.
2. **New monitor** → loại **HTTP(s)** → URL `https://<tên-dịch-vụ>.onrender.com/health` → chu kỳ **5 phút** → Create.
3. Thêm email báo khi bot bị sập (UptimeRobot tự gửi).

## 8. Thiết lập lần đầu trên Telegram

1. Admin mở **Bot Tín hiệu** → `/start`. Menu có thêm nút **👥 Quản lý** (chỉ admin thấy).
2. Mở **Bot Tin tức** → `/start`.
3. **Topic nhật ký** (nơi nhận báo lỗi, tóm tắt sức khỏe 23:00, file sao lưu):
   - Tạo nhóm Telegram riêng, bật **Topics** (Cài đặt nhóm → Topics).
   - Thêm **cả 2 bot** vào nhóm và đặt làm **admin**.
   - Tạo 1 topic, ví dụ "Cài đặt". Trong topic đó gõ `/set_log`. Bot trả lời "✅ Từ giờ báo lỗi..." là xong.
   - Nhóm này chứa dữ liệu quản trị (danh sách người dùng trong file sao lưu): **chỉ để admin và 2 bot trong nhóm**.
4. Tùy chọn — **nhóm thành viên tự duyệt**: gõ `/set_news` trong một nhóm Telegram khác; ai là thành viên nhóm đó bấm
   Start sẽ được tự duyệt dùng Bot Tín hiệu.
5. Thử: 👥 Quản lý → **🔍 Quét ngay**. Vài phút sau bot báo kết quả quét.

## 9. Quản lý người dùng

Mặc định bot ở **chế độ riêng tư** (`PRIVATE_MODE=1`): người lạ phải được admin duyệt.

- Người lạ bấm Start ở **bot nào** thì admin nhận tin trong **Bot Tín hiệu** kèm nút
  **[✅ Duyệt bot đó] [✅ Duyệt cả 2 bot] [❌ Từ chối]**.
- **👥 Quản lý → 👥 Danh sách**: bấm tên người dùng để mở thẻ: bật/tắt quyền **🤖 Tín hiệu** và **📰 Tin tức** riêng,
  tắt tín hiệu, **🗑 Xóa**, **⛔ Chặn** (chặn / xóa áp dụng cho cả 2 bot).
- **👥 Quản lý → ⏳ Chờ duyệt**: các yêu cầu chưa xử lý.
- Dữ liệu từng người (danh mục, coin theo dõi, lệnh) là riêng; người dùng không thấy của nhau, không thấy mục quản lý.

## 10. Sao lưu và khôi phục

- Tối Chủ nhật 23:30 bot tự gửi **file sao lưu** (JSON) vào topic nhật ký. Muốn sao lưu ngay: 👥 Quản lý → **📦 Sao lưu dữ liệu**.
- Khôi phục: gửi file sao lưu vào **chat riêng với Bot Tín hiệu** (admin) → bấm **✅ Khôi phục**.
- Neon còn tự giữ lịch sử dữ liệu vài ngày (mục Branches / Restore trong Neon).

## 11. Theo dõi hằng ngày

| Nhìn ở đâu | Bình thường | Cần xử lý khi |
|---|---|---|
| Topic nhật ký, 23:00 | 🟢 **Sức khỏe bot** | 🟠: quét trễ, có lỗi, nguồn dữ liệu bị giới hạn |
| Topic nhật ký, bất kỳ lúc nào | Không có tin | Có tin ⚠️ / 🚑 báo sự cố |
| Email UptimeRobot | Không có | "Monitor is DOWN" |
| 👥 Quản lý → 🩺 Trạng thái bot | Quét gần nhất < 90 phút | Lâu hơn |

Bot tự xử lý phần lớn sự cố: Binance giới hạn tần suất thì chuyển sang Bybit/MEXC, AI hết lượt thì chuyển nhà cung
cấp khác, quá 3 giờ không quét được thì báo admin.

## 12. Cập nhật code

Mỗi lần có code mới trên nhánh `main` của GitHub, Render tự build và khởi động lại (3–5 phút). Trong lúc khởi động
lại bot không trả lời vài phút — bình thường. Tin khởi động gửi vào topic nhật ký.

## 13. Sự cố thường gặp

| Hiện tượng | Nguyên nhân / cách xử lý |
|---|---|
| Bot không trả lời | Mở `/health`. Không mở được → Render đang build hoặc sập: xem Render → Logs. UptimeRobot còn chạy không |
| Build lỗi trên Render | Xem Logs dòng đỏ cuối cùng; thường do sửa code sai. Render → **Rollback** về bản trước |
| "Lỗi lấy dữ liệu" khi phân tích | Nguồn giá tạm lỗi; thử lại sau vài phút. Nhiều lần liên tiếp → xem topic nhật ký |
| Tin tức còn tiếng Anh / không có tóm tắt | Khóa AI hết lượt hoặc sai: 👥 Quản lý → **🤖 Kiểm tra AI**; thêm khóa dự phòng |
| Người dùng mất dữ liệu sau khi khởi động lại | `DATABASE_URL` đang trống (dùng SQLite tạm) → điền chuỗi Neon |
| Binance báo lỗi 451 | Dịch vụ Render đặt ở Mỹ → tạo lại ở region Frankfurt |

## 14. Chi phí

Tất cả gói miễn phí, 0đ/tháng, với giới hạn:
- Render Free: 750 giờ chạy/tháng (đủ 1 dịch vụ chạy 24/24), RAM 512MB. Bot đang dùng khoảng 1 dịch vụ.
- Neon Free: 0.5GB dữ liệu (đủ nhiều năm với vài trăm người dùng).
- Gemini/Groq/OpenRouter: giới hạn số câu mỗi ngày; bot tự chia tải và giới hạn mỗi người 50 câu/ngày ở Bot Tín hiệu,
  100 câu/ngày ở Bot Tin tức.

Khi số người dùng lớn (hàng trăm người hỏi AI liên tục), nên nâng Render lên gói trả phí (~7 USD/tháng) để không bị
giới hạn RAM.

## 15. Các biến cấu hình khác (không bắt buộc)

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `PRIVATE_MODE` | 1 | 1 = người mới phải được duyệt; 0 = ai cũng dùng được |
| `TOP_N` | 20 | Số coin thanh khoản cao nhất bot quét |
| `MAX_SIGNALS_PER_DAY` | 3 | Tín hiệu swing ngắn tối đa mỗi ngày |
| `DEFAULT_RISK_PCT` | 0.5 | % vốn rủi ro mỗi lệnh cho người dùng mới |
| `MAX_LEVERAGE` | 10 | Đòn bẩy tối đa gợi ý |
| `QUIET_START`, `QUIET_END` | 22, 6 | Giờ yên lặng (giờ VN): không gửi tín hiệu swing ngắn mới |
| `MAX_USER_COINS` | 20 | Số coin tự chọn tối đa mỗi người |
| `AI_DAILY_LIMIT`, `AI_NEWS_DAILY_LIMIT` | 50, 100 | Số câu hỏi AI mỗi người mỗi ngày ở 2 bot |
| `LOG_LEVEL` | INFO | Mức chi tiết của Logs trên Render |
