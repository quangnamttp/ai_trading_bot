# 🤖 AI Trading Signal Bot Telegram

Bot AI phân tích thị trường và gửi tín hiệu giao dịch Bitcoin (BTCUSDT) và Vàng (XAUUSD) qua Telegram.

## ✨ Tính năng

### V2.0 - Cập nhật mới
- 📈 **Signal Tracking**: Theo dõi tự động TP1, TP2, TP3 và Stop Loss với thông báo
- 📊 **Chart Generation**: Tạo biểu đồ phân tích thị trường với annotation chi tiết
- 📉 **Statistics Module**: Lệnh `/stats` xem thống kê win rate, tổng tín hiệu, PNL
- 📨 **Message Queue**: Hệ thống hàng đợi tin nhắn tránh Telegram flood limits
- 🚫 **Anti-Duplicate**: Ngăn chặn gửi tín hiệu trùng lặp
- 💾 **Caching System**: Cache API calls để giảm số lần gọi
- 🏥 **Health Check**: Kiểm tra sức khỏe hệ thống (CPU, RAM, DB, API) và alert admin
- 🧹 **Auto Cleanup**: Tự động cleanup cache, logs, temp files
- 📅 **Auto Reporting**: Báo cáo tự động ngày/tuần/tháng gửi admin
- 🔒 **User Management**: Lệnh `/ban` và `/unban` quản lý users
- 🇻🇳 **Vietnamese Analysis**: Phân tích bằng tiếng Việt

### V1.0 - Tính năng gốc
- 📊 **Phân tích thị trường 24/7**: Quét dữ liệu giá, khối lượng, Open Interest, Funding Rate
- 🤖 **AI Analysis**: Phân tích bằng AI với độ chính xác cao
- 🎯 **Tín hiệu giao dịch**: Gửi tín hiệu LONG/SHORT khi AI Score > 85%
- 🐋 **Smart Money Tracking**: Theo dõi dòng tiền cá voi và hoạt động lớn
- 📰 **Tin tức thị trường**: Cập nhật tin tức Crypto và Forex
- ⚠️ **Quản lý rủi ro**: Hệ thống kiểm soát rủi ro tích hợp
- 👥 **Quản trị**: Admin quản lý users và cấu hình bot

## 📋 Yêu cầu

- Python 3.12+
- Telegram Bot Token
- Telegram Admin ID

**Lưu ý**: Bot hoạt động chủ yếu với MEXC (không cần API key cho public data). Các API keys khác là optional.

## 📚 Tài liệu chi tiết

Xem thêm trong thư mục `docs/`:
- **[Công Dụng Bot](docs/CONG_DUNG_BOT.md)** - Bot hoạt động như thế nào, lợi ích cho người dùng
- **[Phương Pháp Giao Dịch](docs/PHUONG_PHUC_GIAO_DICH.md)** - Chi tiết phương pháp phân tích của AI
- **[Hướng Dẫn Test](docs/HUONG_DAN_TEST.md)** - Cách test hiệu quả bot trước khi dùng thật
- **[Hướng Dẫn Cài Đặt](docs/HUONG_DAN_CAI_DAT.md)** - Hướng dẫn cài đặt chi tiết từng bước
- **[Deploy Trực Tiếp Lên Render](docs/DEPLOY_RENDER.md)** - Deploy lên Render KHÔNG cần cài gì trên máy

## �🚀 Cài đặt

### 1. Clone repository

```bash
git clone https://github.com/yourusername/ai-trading-bot.git
cd ai-trading-bot
```

### 2. Cài đặt dependencies

```bash
pip install -r requirements.txt
```

### 3. Cấu hình môi trường

Copy file `.env.example` sang `.env` và điền thông tin:

```bash
cp .env.example .env
```

Cập nhật các biến trong file `.env`:

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_ADMIN_ID=your_telegram_admin_id_here
```

**Chỉ cần 2 biến trên là đủ để bot hoạt động!** Bot sử dụng MEXC cho dữ liệu thị trường (không cần API key) và có dữ liệu mẫu cho tin tức nếu không có NewsAPI key.

### 4. Lấy Telegram Bot Token

1. Mở [@BotFather](https://t.me/botfather) trên Telegram
2. Gửi `/newbot` và làm theo hướng dẫn
3. Copy token được cung cấp

### 5. Lấy Telegram Admin ID

1. Mở [@userinfobot](https://t.me/userinfobot) trên Telegram
2. Gửi bất kỳ tin nhắn nào
3. Copy ID của bạn

## 🏃 Chạy Bot

### Local development

```bash
python main.py
```

### Deploy lên Render

1. Push code lên GitHub
2. Tạo new web service trên Render
3. Connect repository
4. Render sẽ tự động deploy dựa trên `render.yaml`

### Giữ bot hoạt động 24/7 với UptimeRobot

1. Đăng ký [UptimeRobot](https://uptimerobot.com/)
2. Thêm monitor mới
3. URL: `https://your-app-name.onrender.com/health`
4. Interval: 15 minutes

## 📱 Lệnh Telegram

### Lệnh cơ bản

- `/start` - Khởi động bot
- `/help` - Xem trợ giúp
- `/status` - Trạng thái bot
- `/id` - Xem Telegram ID của bạn

### Phân tích thị trường

- `/btc` - Phân tích Bitcoin (BTCUSDT)
- `/gold` - Phân tích Vàng (XAUUSD)
- `/market` - Tổng quan thị trường
- `/news` - Tin tức mới nhất

### Lệnh Admin (chỉ admin)

- `/adduser <user_id>` - Thêm user nhận tín hiệu
- `/removeuser <user_id>` - Xóa user
- `/ban <user_id> [reason]` - Ban user
- `/unban <user_id>` - Unban user
- `/users` - Danh sách users
- `/broadcast <message>` - Gửi thông báo đến tất cả users
- `/settings` - Cấu hình bot

### Thống kê

- `/stats [period]` - Xem thống kê tín hiệu (period: day/week/month/all)

## 📊 Cấu trúc Project

```
ai_trading_bot/
├── main.py                   # Entry point
├── requirements.txt          # Dependencies
├── .env.example             # Environment variables template
├── render.yaml              # Render deployment config
├── README.md                # Documentation chính
├── .gitignore               # Git ignore rules
│
├── core/                    # Core modules
│   ├── __init__.py
│   ├── config.py           # System configuration
│   ├── database.py         # SQLite database management
│   ├── main.py             # Main application
│   ├── signal_tracker.py   # Signal TP/SL tracking (V2.0)
│   ├── statistics.py       # Statistics module (V2.0)
│   ├── health_check.py     # System health monitoring (V2.0)
│   └── reporting.py        # Auto reporting (V2.0)
│
├── data/                    # Data collection modules
│   ├── __init__.py
│   ├── market_data.py      # Market data from MEXC
│   ├── news_engine.py      # News aggregation
│   └── smart_money.py      # Smart money tracking
│
├── analysis/                # Analysis modules
│   ├── __init__.py
│   ├── ai_engine.py        # AI analysis engine
│   ├── signal_engine.py    # Signal generation
│   ├── risk_manager.py     # Risk management
│   └── chart_generator.py  # Chart generation (V2.0)
│
├── telegram/                # Telegram integration
│   ├── __init__.py
│   └── telegram_bot.py     # Telegram bot handler
│
├── utils/                   # Utility functions
│   ├── __init__.py
│   ├── utils.py            # Helper functions
│   ├── message_queue.py    # Telegram message queue (V2.0)
│   ├── anti_duplicate.py   # Anti-duplicate signals (V2.0)
│   ├── cache_manager.py    # API caching system (V2.0)
│   └── auto_cleanup.py     # Auto cleanup system (V2.0)
│
├── docs/                    # Tài liệu chi tiết
│   ├── CONG_DUNG_BOT.md           # Công dụng bot
│   ├── PHUONG_PHUC_GIAO_DICH.md   # Phương pháp giao dịch
│   ├── HUONG_DAN_TEST.md          # Hướng dẫn test
│   └── HUONG_DAN_CAI_DAT.md       # Hướng dẫn cài đặt
│
├── logs/                    # Log files
├── database/                # SQLite database files
├── temp/                    # Temporary files (charts, etc.)
└── tests/                   # Unit tests
```

## 🔧 Cấu hình

### AI Score Threshold

Ngưỡng AI Score để gửi tín hiệu (mặc định: 85)

```env
AI_SCORE_THRESHOLD=85
```

### Signal Cooldown

Thời gian chờ giữa các tín hiệu (mặc định: 30 phút)

```env
SIGNAL_COOLDOWN_MINUTES=30
```

### Rate Limit

Số tín hiệu tối đa mỗi giờ (mặc định: 2)

```env
MAX_SIGNALS_PER_HOUR=2
```

## 📈 Dữ liệu thị trường

Bot thu thập các dữ liệu sau:

### Dữ liệu chính (MEXC - Không cần API key)
- Giá và Volume ✅
- Order Book ✅
- Technical Indicators (EMA, RSI, MACD, Bollinger Bands) ✅
- Market Structure (Order Blocks, FVG) ✅

### Dữ liệu phụ (Có fallback khi không có API)
- **Open Interest & Funding Rate**: Sử dụng Binance nếu có API key, nếu không sẽ dùng dữ liệu mẫu
- **Smart Money & Whale Activity**: Phân tích từ Order Book và Volume, có dữ liệu mẫu khi cần
- **Tin tức**: Sử dụng NewsAPI nếu có key, nếu không sẽ dùng dữ liệu mẫu
- **Economic Calendar**: Dữ liệu mẫu (FOMC, CPI, NFP, etc.)
- **Fear & Greed Index**: Lấy từ API miễn phí, có fallback
- **DXY & Bond Yields**: Dữ liệu mẫu

### ⚠️ Ảnh hưởng khi không có API keys

**Không ảnh hưởng đáng kể đến tín hiệu** vì:
- **Technical Analysis** (quan trọng nhất): Hoạt động 100% với MEXC data
- **Smart Money**: Phân tích từ Order Book và Volume real-time
- **AI Score**: Tính toán chủ yếu từ technical indicators
- **Dữ liệu mẫu**: Chỉ là bổ sung, không quyết định tín hiệu

Bot vẫn hoạt động tốt và đưa ra tín hiệu chất lượng mà không cần các API keys bổ sung.

## 🤖 AI Analysis

AI phân tích dựa trên:

- **Technical Indicators**: EMA, RSI, MACD, Bollinger Bands
- **Smart Money**: Whale activity, large trades, funding rate
- **Market Structure**: Order blocks, Fair Value Gaps (FVG)
- **News Sentiment**: Crypto và Forex news
- **Risk Assessment**: Volatility, liquidity, market conditions

Output AI:

- Action: LONG / SHORT / WAIT
- AI Score: 0-100
- Confidence: 0-100%
- Reasons: Danh sách lý do

## ⚠️ Disclaimer

- Bot chỉ cung cấp tín hiệu phân tích, KHÔNG tự động giao dịch
- Người dùng tự quyết định vào lệnh thủ công
- Không đảm bảo lợi nhuận, trading có rủi ro
- Sử dụng tín hiệu với trách nhiệm của riêng bạn

## 🔒 Security

- Không commit file `.env` vào GitHub
- Bảo mật API keys
- Chỉ admin mới có quyền quản trị
- Database lưu local trên server

## 🐛 Troubleshooting

### Bot không khởi động

- Kiểm tra `.env` file có đúng cấu hình
- Đảm bảo tất cả dependencies đã cài đặt
- Kiểm tra log file trong thư mục `logs/`

### Không nhận được tín hiệu

- Kiểm tra AI Score threshold
- Đảm bảo bạn đã được admin thêm vào danh sách
- Kiểm tra cooldown period

### Lỗi kết nối API

- Bot hoạt động tốt với MEXC mà không cần API key
- Nếu có lỗi kết nối, bot sẽ tự reconnect
- Kiểm tra internet connection
- Các API keys (Binance, NewsAPI) là optional - bot vẫn hoạt động mà không cần chúng

## 📞 Support

Nếu gặp vấn đề, hãy:

1. Kiểm tra log file
2. Đọc documentation này
3. Mở issue trên GitHub

## 📝 License

MIT License

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

## 📄 Disclaimer

This bot is for educational purposes only. Trading cryptocurrencies and forex involves significant risk. You are responsible for your own trading decisions. The authors are not responsible for any financial losses incurred.

---

**⚠️ Lưu ý quan trọng**: Bot này chỉ cung cấp tín hiệu phân tích để tham khảo. Không phải là lời khuyên đầu tư. Hãy tự nghiên cứu và chịu trách nhiệm với quyết định giao dịch của bạn.
