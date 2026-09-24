# 🤖 Bot tín hiệu swing crypto (v3)

Bot Telegram quét top 20 coin Binance Futures và gửi tín hiệu có điểm vào, SL, TP1, trailing stop và biểu đồ
kiểu TradingView. Bot theo dõi từng lệnh tới khi đóng. Có 2 kiểu giao dịch: **⚡ Swing ngắn** (1–3 tín hiệu/ngày, 6h–22h)
và **🌙 Swing dài** (khoảng 1 tín hiệu/tuần). Chế độ **Spot** chỉ nhận lệnh MUA; **Futures** nhận LONG/SHORT kèm đòn bẩy
an toàn. Toàn bộ dữ liệu miễn phí.

> Code cũ nằm ở tag `legacy-v2` / `legacy-final`. Hai chỉ báo TradingView: xem [tradingview/README.md](tradingview/README.md).

## Bot quyết định thế nào

| | ⚡ Swing ngắn | 🌙 Swing dài |
|---|---|---|
| Khung (setup / xu hướng / bối cảnh) | 1H / 4H / 1D | 4H / 1D / 1W |
| Quét | mỗi giờ, chỉ 6h–22h giờ VN | khi nến 4H đóng; ban đêm gửi **không chuông** |
| Ngưỡng điểm | 75 (hạng B: 70, chỉ sau 15h nếu cả ngày chưa có tín hiệu) | 70 |
| Cổng chất lượng | OI biến động ≥ 5% (24h) **hoặc** đám đông nghiêng ≥ 3:1 về phía ngược lại **hoặc** setup Retest | OI biến động ≥ 5% (3 ngày) |
| Giới hạn | 3 tín hiệu/ngày | 3 tín hiệu/tuần |

Áp dụng cho cả 2 kiểu:
- Chỉ đánh thuận xu hướng. Có 2 kiểu setup: hồi về EMA20 khung xu hướng (Pullback) và kiểm tra lại mốc vừa phá (Retest).
- **Bỏ Pullback LONG**, vì backtest cho kết quả kém ở mọi giai đoạn.
- Điểm 0–100 gồm 6 nhóm: xu hướng, động lượng, setup, dòng tiền taker/CVD, phái sinh, thị trường chung.
- Chặn tín hiệu khi: dòng tiền yếu, Fear & Greed ≤ 13, funding quá nóng, biến động bất thường, sát kháng cự ngày,
  tin xấu nghiêm trọng, và **3 giờ trước đến 1 giờ sau** tin vĩ mô Mỹ.
- Tối đa 2 lệnh cùng chiều mở cùng lúc. Bỏ coin niêm yết dưới 90 ngày. Mỗi coin nghỉ 12h (ngắn) / 72h (dài) sau tín hiệu.

**Quản lý lệnh (đặt 1 lần trên sàn)**: SL cố định · chốt 50% tại 2R · **Trailing Stop của sàn** cho cả lệnh,
kích hoạt ở +1R, callback = 3×ATR khung xu hướng (tối đa 10%).
Bot dùng đúng cách này để mô phỏng và theo dõi lệnh, nên số liệu thống kê khớp với cách anh/chị đặt lệnh.

## Kết quả backtest 2 năm (09/2024 → 09/2026, 40 coin)

`python -m app.backtest --save`. Backtest dùng cùng code với bot live, tính phí 0.1%. Nếu một nến chạm cả SL lẫn TP thì
tính là chạm SL. Top N được xếp hạng lại mỗi ngày theo khối lượng.

| | Lệnh | Có lời | TB/lệnh | 60% đầu | 40% sau | Sụt giảm tối đa | Tháng lỗ |
|---|---|---|---|---|---|---|---|
| ⚡ Swing ngắn · Futures | 595 (~0.8/ngày) | 43% | **+0.20R** | +0.20 | +0.22 | 16.5R | 5/25 |
| ⚡ Swing ngắn · Spot | 260 | 43% | **+0.21R** | +0.26 | +0.12 | 12.5R | 11/25 |
| 🌙 Swing dài · Futures | 92 (~1/tuần) | 44% | **+0.27R** | +0.16 | +0.44 | 10.7R | 10/25 |
| 🌙 Swing dài · Spot | 47 | 45% | +0.07R | +0.17 | **−0.17** | 7.6R | → **không gửi cho Spot** |

Các ý tưởng đã thử nhưng không đưa vào vì **không cải thiện ở cả 2 phần dữ liệu**:
- Quét và vào lệnh theo khung 15m: lỗ ở mọi cấu hình.
- Cộng điểm theo OI/đám đông: kém hơn so với dùng làm cổng lọc.
- Tín hiệu của 2 chỉ báo TradingView cũ, FVG, nén biến động, chỉ số choppiness.
- Gann và sóng Elliott: không kiểm chứng được một cách khách quan.

Hạn chế: danh sách coin lấy theo thời điểm hiện tại (thiên lệch sống sót); tin tức không có lịch sử miễn phí nên
không backtest được (bot ghi lại mỗi lần tin tức chặn tín hiệu để đánh giá sau). **Kết quả quá khứ không đảm bảo tương lai.**

## Người dùng, coin tự chọn, tin tức, AI

- **Chế độ riêng tư** (`PRIVATE_MODE=1`, mặc định): người mới bấm Start → admin nhận nút ✅ Duyệt / ❌ Từ chối.
  Lệnh admin: `/allow ID`, `/ban ID`, `/unban ID`, `/users`.
- **🪙 Coin của tôi**: mỗi người tối đa 20 coin, chọn nhận tín hiệu *Top 20* / *chỉ coin của tôi* / *cả hai*;
  📌 *đang giữ* để nhận cảnh báo xu hướng, vùng giá, OI/funding, tin xấu. Tín hiệu coin tự chọn không chiếm giới hạn của
  Top 20; mỗi người tối đa 3 tín hiệu swing ngắn/ngày. Tổng số coin quét tối đa 60 (ưu tiên coin nhiều người theo dõi).
- **Nhóm Telegram có Topic**: gõ `/set_news` trong topic tin tức, `/set_ai` trong topic hỏi đáp (admin).
  Tín hiệu luôn gửi chat riêng (mỗi người cài đặt khác nhau); tin tức gửi topic + chat riêng (tắt được trong ⚙️).
- **📅 Lịch sự kiện**: ForexFactory (miễn phí) — giải thích tiếng Việt từng loại tin + thống kê BTC 24h sau tin
  (FOMC, NFP có sẵn 2 năm; CPI và tin khác bot tự tích lũy dần).
- **🤖 AI** (tùy chọn): đặt `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY` trên Render. Thử lần lượt
  Gemini → Groq → OpenRouter, tự dò model còn dùng được; lỗi hết thì trả lời bằng dữ liệu có sẵn. 20 câu/người/ngày
  (`AI_DAILY_LIMIT`). Admin gõ `/ai_ping` để kiểm tra. AI chỉ giải thích dựa trên dữ liệu bot — không tạo tín hiệu.

## Lịch tự động (giờ VN)

| Giờ | Việc |
|---|---|
| Mỗi giờ :01 | Quét ⚡ Swing ngắn (6h–22h); khi nến 4H đóng thì quét thêm 🌙 Swing dài |
| Mỗi 5 phút | Theo dõi lệnh đang mở: kích hoạt trailing, TP1, đóng lệnh (trả lời ngay dưới tin nhắn tín hiệu) |
| Mỗi 10–15 phút | Nhắc trước 1 giờ khi có tin vĩ mô Mỹ · cảnh báo tin xấu về coin đang có lệnh |
| 07:00 | Thị trường 24h (BTC/ETH, top tăng/giảm, Fear & Greed, OI, funding, stablecoin, tin chính, coin đang theo dõi) + tin kinh tế hôm nay; **thứ 2: lịch cả tuần** |
| 15:05 | Nếu cả ngày chưa có tín hiệu: gửi danh sách coin đang hình thành setup (không phải tín hiệu) |
| 22:00 | Tổng kết lời/lỗ từng lệnh (R và % vốn), lệnh giữ qua đêm, cộng dồn 7 và 30 ngày |
| Mỗi 15 phút | Cảnh báo BTC chạy ≥ 3%/giờ, funding cực đoan ở coin lớn |
| Mỗi giờ :05 | Theo dõi coin 📌 đang giữ của từng người |
| Chủ nhật 22:05 | Tổng kết tuần của từng người |
| Mỗi 30 phút | Tự kiểm tra: quá 3 giờ không quét được thì báo admin |

## Triển khai miễn phí (Render + Neon + UptimeRobot)

1. **Bot Telegram**: chat với [@BotFather](https://t.me/BotFather) → `/newbot` → lấy token. Lấy ID của bạn từ [@userinfobot](https://t.me/userinfobot).
2. **Database**: tạo project miễn phí tại [neon.tech](https://neon.tech) (region Frankfurt), copy *connection string*.
   Render free xóa ổ đĩa mỗi lần khởi động lại nên không dùng SQLite trên Render.
3. **Render**: *New → Blueprint* → chọn repo này (đọc `render.yaml`, region **Frankfurt** vì Binance chặn IP Mỹ).
   Điền `TELEGRAM_BOT_TOKEN`, `ADMIN_IDS`, `DATABASE_URL`. Render tự cấp `RENDER_EXTERNAL_URL` để bot đặt webhook.
4. **UptimeRobot**: tạo monitor HTTP(s) tới `https://<tên-app>.onrender.com/health`, chu kỳ 5 phút,
   để Render free không ngủ (ngủ sau 15 phút không có request).
5. Mở bot trên Telegram → `/start`. Admin gõ `/scan` để quét thử ngay.

### Chạy trên máy cá nhân

```bash
pip install -r requirements-dev.txt
cp .env.example .env        # điền TELEGRAM_BOT_TOKEN, ADMIN_IDS
python main.py              # không có PUBLIC_URL => chạy polling
pytest                      # chạy test
```

## Lệnh

| Người dùng | Admin |
|---|---|
| `/start` `/menu` — menu chính | `/scan` — quét ngay |
| `/mode` — Spot/Futures, % rủi ro, kiểu swing | `/add SOL` `/remove SOL` — thêm/bớt coin ngoài top |
| `/phantich SOL` — phân tích 1 coin | `/users` `/ban ID` `/unban ID` |
| `/thongke` — thống kê thật + backtest | `/broadcast nội dung` |


## Cấu trúc

```
app/
  main.py            web server aiohttp (webhook + /health) và lịch chạy job
  service.py         phát tín hiệu, theo dõi lệnh
  reports.py         báo cáo 07:00 / 15:05 / 22:00, cảnh báo tin, nhắc tin vĩ mô, tự kiểm tra
  chart.py           biểu đồ kiểu TradingView
  storage.py         SQLite / Postgres (tự thêm cột mới khi nâng cấp)
  backtest.py        backtest 2 năm cho cả 2 kiểu swing + lưu calibration.json
  data/              Binance (nến, funding), Bybit (OI, long/short), vĩ mô, tin tức
  strategy/
    core.py          đặc trưng đa khung + chấm điểm (dùng chung cho live và backtest)
    trade.py         máy trạng thái lệnh (dùng chung cho live và backtest)
    scanner.py       quét live 2 kiểu swing, cổng chất lượng, hạng A/B, giờ yên lặng
    tv_indicators.py 2 chỉ báo TradingView chuyển sang Python (để backtest)
    custom.py        điểm cộng từ chỉ báo TradingView (đang tắt — backtest không cải thiện)
    calibration.json kết quả backtest theo từng kiểu swing
  bot/               menu, lệnh, nội dung tin nhắn
```

Chạy lại backtest định kỳ (ví dụ mỗi tháng) và lưu hiệu chỉnh mới:
`python -m app.backtest --download --save` (lần đầu tải dữ liệu khoảng 15 phút)

⚠️ Công cụ hỗ trợ phân tích, không phải lời khuyên đầu tư. Luôn đặt SL và chỉ dùng số vốn bạn chấp nhận mất.
