# 🤖 Bot tín hiệu swing crypto (v3)

Bot Telegram quét top coin Binance Futures mỗi giờ và gửi **1–5 tín hiệu/ngày**. Mỗi tín hiệu có vùng vào lệnh, SL, TP,
biểu đồ kiểu TradingView, và được theo dõi tới khi đóng lệnh (báo dời SL, chốt lời, cắt lỗ). Có 2 chế độ:
**Spot** (chỉ MUA) và **Futures** (LONG/SHORT, kèm khối lượng và đòn bẩy an toàn). Toàn bộ dữ liệu miễn phí.

> Code cũ (v2) vẫn còn ở tag `legacy-v2`.

## Bot quyết định thế nào

Khung thời gian: **1D** (xu hướng lớn) → **4H** (xu hướng + vùng giá trị) → **1H** (thời điểm vào lệnh).
Chỉ đánh **thuận xu hướng**, vào ngay khi setup vừa hình thành thay vì đuổi theo sau khi giá đã chạy:

- **PULLBACK**: xu hướng 4H khỏe, giá hồi về EMA20 4H rồi bật lại.
- **RETEST**: vừa phá đỉnh/đáy 48 nến 1H với volume lớn, giá còn sát mốc vừa phá.

Điểm 0–100 gồm 6 nhóm dữ liệu độc lập:

| Nhóm | Điểm | Dữ liệu (miễn phí) |
|---|---|---|
| Xu hướng | 30 | EMA 1D/4H, ADX/DI 4H |
| Động lượng | 15 | RSI 4H, MACD 1H |
| Setup | 20 | Pullback / Retest |
| Dòng tiền | 15 | Taker buy/sell, CVD 24h, volume (Binance) |
| Phái sinh | 10 | Funding, Open Interest 24h, tỉ lệ long/short đám đông & top trader |
| Thị trường chung | 10 | Xu hướng BTC, Fear & Greed, cung stablecoin (DefiLlama), sentiment tin tức (RSS) |

**Bộ lọc chặn cứng**: dòng tiền yếu, Fear & Greed ≤ 13, funding quá nóng, biến động quá thấp hoặc quá cao,
sát kháng cự/hỗ trợ ngày, tin xấu nghiêm trọng về coin (hack, delist, kiện tụng...), và **3 giờ trước đến 1 giờ sau
tin vĩ mô Mỹ** (CPI, FOMC, NFP — lịch ForexFactory).

**Quản lý lệnh**: lãi +1R thì dời SL về entry; tại TP1 (2R) chốt 50%; phần còn lại chạy trailing stop
(giá đóng cửa 1H tốt nhất ∓ 2.5×ATR 4H); giữ tối đa 7 ngày.

## Kết quả backtest (trung thực)

`python -m app.backtest --days 365 --top 30` — 1 năm, 30 coin, cùng code với bot live, tính phí 0.1%, nến chạm
cả SL lẫn TP thì tính SL:

| Chỉ số | Giá trị |
|---|---|
| Tín hiệu | ~2.3/ngày |
| Lệnh có lời | **~33%** (lợi nhuận đến từ số ít lệnh chạy xa) |
| Kỳ vọng | **+0.16R/lệnh** · profit factor 1.35 |
| Sụt giảm tối đa | **34R** — với rủi ro 0.5%/lệnh ≈ −17% tài khoản |
| Tháng lỗ | 4/13 |

Theo mức điểm: nhóm 60 điểm −0.10R, 70 điểm +0.08R, 75 điểm +0.20R, 85 điểm +0.36R/lệnh.
Điểm càng cao thì kết quả càng tốt, vì vậy bot dùng ngưỡng 75.

Hạn chế: danh sách top coin lấy theo khối lượng *hiện tại* (thiên lệch sống sót); OI, long/short và tin tức
không có lịch sử miễn phí nên backtest tính điểm trung tính cho các nhóm này. **Kết quả quá khứ không đảm bảo tương lai.**

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
| `/mode` — Spot/Futures, % rủi ro | `/add SOL` `/remove SOL` — thêm/bớt coin ngoài top |
| `/phantich SOL` — phân tích 1 coin | `/users` `/ban ID` `/unban ID` |
| `/thongke` — thống kê thật + backtest | `/broadcast nội dung` |

Lịch tự động (giờ VN): quét mỗi giờ ở phút :01, theo dõi lệnh mỗi 5 phút, tổng quan thị trường 07:30, tổng kết 21:00.

## Cấu trúc

```
app/
  main.py            web server aiohttp (webhook + /health) và lịch chạy job
  service.py         phát tín hiệu, theo dõi lệnh, báo cáo
  chart.py           biểu đồ kiểu TradingView
  storage.py         SQLite / Postgres
  backtest.py        backtest và hiệu chỉnh ngưỡng
  data/              Binance (+Bybit dự phòng), vĩ mô, tin tức
  strategy/
    core.py          đặc trưng đa khung + chấm điểm (dùng chung cho live và backtest)
    trade.py         máy trạng thái lệnh (dùng chung cho live và backtest)
    scanner.py       quét live + áp dữ liệu phái sinh/tin tức
    custom.py        chỗ gắn chỉ báo TradingView riêng (xem tradingview/README.md)
    calibration.json kết quả backtest theo mức điểm
  bot/               menu, lệnh, nội dung tin nhắn
```

Chạy lại backtest định kỳ (ví dụ mỗi tháng) và lưu hiệu chỉnh mới:
`python -m app.backtest --days 365 --top 30 --save`

⚠️ Công cụ hỗ trợ phân tích, không phải lời khuyên đầu tư. Luôn đặt SL và chỉ dùng số vốn bạn chấp nhận mất.
