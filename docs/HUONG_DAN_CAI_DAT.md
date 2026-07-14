# 🚀 Hướng Dẫn Cài Đặt Chi Tiết AI Trading Signal Bot

## 📋 Yêu cầu hệ thống

### Phần cứng
- CPU: 1 core trở lên
- RAM: 512MB trở lên
- Disk: 1GB trở lên

### Phần mềm
- **Python 3.12+** (Bắt buộc)
- Git (optional, nếu clone từ GitHub)
- Truy cập internet

---

## 🔧 Bước 1: Cài đặt Python

### Windows

#### Cách 1: Download từ python.org
1. Truy cập https://www.python.org/downloads/
2. Download Python 3.12+
3. Run installer
4. **QUAN TRỌNG:** Check "Add Python to PATH"
5. Click "Install Now"

#### Cách 2: Sử dụng Microsoft Store
1. Mở Microsoft Store
2. Search "Python 3.12"
3. Click "Get" hoặc "Install"

#### Kiểm tra cài đặt
Mở Command Prompt hoặc PowerShell:
```bash
python --version
# Hoặc
python3 --version
```

Nên hiển thị: `Python 3.12.x`

### Linux (Ubuntu/Debian)
```bash
sudo apt update
sudo apt install python3.12 python3-pip python3-venv
```

### macOS
```bash
brew install python@3.12
```

---

## 📁 Bước 2: Tải project

### Cách 1: Clone từ GitHub (nếu đã push)
```bash
git clone https://github.com/yourusername/ai-trading-bot.git
cd ai-trading-bot
```

### Cách 2: Download ZIP
1. Truy cập GitHub repository
2. Click "Code" → "Download ZIP"
3. Extract file
4. Mở folder trong terminal

### Cách 3: Sử dụng project hiện có
```bash
cd C:\Users\quang\CascadeProjects\ai_trading_bot
```

---

## 🐍 Bước 3: Tạo Virtual Environment (Khuyến nghị)

### Windows
```bash
# Tạo virtual environment
python -m venv venv

# Kích hoạt
venv\Scripts\activate
```

### Linux/macOS
```bash
# Tạo virtual environment
python3 -m venv venv

# Kích hoạt
source venv/bin/activate
```

### Kiểm tra kích hoạt
Terminal sẽ hiển thị `(venv)` ở đầu dòng

---

## 📦 Bước 4: Cài đặt Dependencies

### Cài đặt tất cả dependencies
```bash
pip install -r requirements.txt
```

### Nếu gặp lỗi, thử cài từng package
```bash
pip install python-telegram-bot==20.7
pip install python-dotenv==1.0.0
pip install requests==2.31.0
pip install pandas==2.1.4
pip install numpy==1.26.2
pip install ccxt==4.1.90
pip install yfinance==0.2.32
pip install scikit-learn==1.3.2
pip install ta-lib==0.4.28
pip install schedule==1.2.0
pip install python-dateutil==2.8.2
pip install loguru==0.7.2
pip install aiohttp==3.9.1
pip install flask==3.0.0
```

### Lưu ý về TA-Lib
TA-Lib có thể gặp lỗi khi cài đặt trên Windows:

**Giải pháp 1: Sử dụng pre-built wheel**
```bash
pip install https://github.com/cgohlke/talib-build/releases/download/v0.4.28/TA_Lib-0.4.28-cp312-cp312-win_amd64.whl
```

**Giải pháp 2: Skip TA-Lib (bot vẫn hoạt động)**
Xóa `ta-lib==0.4.28` khỏi `requirements.txt`

### Kiểm tra cài đặt
```bash
pip list
```

Nên thấy các packages đã cài

---

## 🔑 Bước 5: Lấy Telegram Bot Token

### 5.1 Tạo Bot với BotFather

1. Mở Telegram
2. Search **@BotFather**
3. Gửi `/newbot`
4. BotFather sẽ hỏi:
   - **Bot name:** `AI Trading Signal Bot` (hoặc tên bạn muốn)
   - **Bot username:** `my_trading_bot` (phải kết thúc bằng `bot`)

### 5.2 Lấy Token
BotFather sẽ gửi token như:
```
1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
```

**Copy token này!**

### 5.3 Test Bot
Mở browser, nhập:
```
https://api.telegram.org/bot<TOKEN>/getMe
```
Nếu thấy JSON response về bot info → Token đúng

---

## 👤 Bước 6: Lấy Telegram User ID

### 6.1 Sử dụng @userinfobot
1. Mở Telegram
2. Search **@userinfobot**
3. Gửi bất kỳ tin nhắn nào
4. Bot sẽ trả về ID của bạn

Ví dụ: `123456789`

### 6.2 Kiểm tra ID
ID là số nguyên, không phải username

---

## ⚙️ Bước 7: Cấu hình Environment Variables

### 7.1 Tạo file .env
```bash
# Copy template
cp .env.example .env

# Hoặc tạo mới
type nul > .env  # Windows
touch .env       # Linux/macOS
```

### 7.2 Điền thông tin vào .env
Mở file `.env` với text editor (Notepad, VS Code, etc.)

```env
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_ADMIN_ID=123456789
TELEGRAM_WEBHOOK_URL=

# Database Configuration
DATABASE_PATH=database/trading_bot.db

# Trading Configuration
AI_SCORE_THRESHOLD=85
MIN_CONFIDENCE=0.85

# API Keys (Optional - Bot hoạt động mà không cần)
BINANCE_API_KEY=
BINANCE_API_SECRET=
COINAPI_KEY=
NEWS_API_KEY=

# Risk Management
MAX_RISK_PER_TRADE=0.02
MAX_POSITIONS=3

# Signal Configuration
SIGNAL_COOLDOWN_MINUTES=30
MAX_SIGNALS_PER_HOUR=2

# Logging Configuration
LOG_LEVEL=INFO
LOG_FILE=logs/trading_bot.log

# Market Data Configuration
MARKET_DATA_INTERVAL=60
NEWS_CHECK_INTERVAL=300

# AI Configuration
AI_MODEL=rule_based
AI_UPDATE_INTERVAL=120

# Deployment Configuration
DEPLOYMENT_ENV=development
PORT=8080
```

### 7.3 Các biến BẮT BUỘC điền
- `TELEGRAM_BOT_TOKEN` - Token từ BotFather
- `TELEGRAM_ADMIN_ID` - ID của bạn từ userinfobot

### 7.4 Các biến OPTIONAL
- Các API keys khác có thể để trống
- Bot vẫn hoạt động bình thường

---

## 🏃 Bước 8: Chạy Bot

### 8.1 Chạy bot (Development mode)
```bash
python main.py
```

### 8.2 Kiểm tra bot hoạt động
Terminal nên hiển thị:
```
2024-07-13 21:00:00 - root - INFO - Logging initialized at INFO level
2024-07-13 21:00:00 - root - INFO - Initializing AI Trading Signal Bot...
2024-07-13 21:00:01 - root - INFO - Configuration validated
2024-07-13 21:00:01 - root - INFO - Database initialized
2024-07-13 21:00:02 - root - INFO - Market data engine initialized
2024-07-13 21:00:03 - root - INFO - Telegram bot initialized
2024-07-13 21:00:03 - root - INFO - Admin 123456789 added to database
2024-07-13 21:00:03 - root - INFO - All components initialized successfully
2024-07-13 21:00:03 - root - INFO - Flask server started on port 8080
2024-07-13 21:00:04 - root - INFO - Starting market data loop
2024-07-13 21:00:04 - root - INFO - Starting news loop
2024-07-13 21:00:04 - root - INFO - Starting AI analysis loop
2024-07-13 21:00:04 - root - INFO - Starting smart money loop
2024-07-13 21:00:05 - root - INFO - All loops started successfully
2024-07-13 21:00:05 - root - INFO - Bot is now running 24/7
```

### 8.3 Test Telegram Bot
1. Mở Telegram
2. Tìm bot của bạn
3. Gửi `/start`
4. Bot nên trả欢迎 message

### 8.4 Test các lệnh cơ bản
```
/start - Khởi động bot
/help - Xem trợ giúp
/status - Trạng thái bot
/btc - Phân tích BTC
/gold - Phân tích Vàng
/market - Tổng quan thị trường
```

---

## 🐛 Bước 9: Xử lý lỗi thường gặp

### Lỗi 1: "Module not found"
**Giải pháp:**
```bash
pip install -r requirements.txt
```

### Lỗi 2: "TELEGRAM_BOT_TOKEN is required"
**Giải pháp:**
- Kiểm tra file `.env` có tồn tại
- Kiểm tra `TELEGRAM_BOT_TOKEN` đã điền chưa
- Kiểm tra không có space thừa

### Lỗi 3: "TELEGRAM_ADMIN_ID is required"
**Giải pháp:**
- Kiểm tra `TELEGRAM_ADMIN_ID` đã điền chưa
- ID phải là số, không phải username

### Lỗi 4: Bot không trả lời
**Giải pháp:**
- Kiểm tra bot đã chạy chưa
- Kiểm tra terminal có error không
- Kiểm tra bạn đã `/start` chưa
- Kiểm tra bạn có trong danh sách user không

### Lỗi 5: "ccxt error"
**Giải pháp:**
- Kiểm tra internet connection
- Bot sẽ tự reconnect
- MEXC có thể maintenance, thử lại sau

### Lỗi 6: TA-Lib install error
**Giải pháp:**
- Skip TA-Lib (xóa khỏi requirements.txt)
- Bot vẫn hoạt động với các indicators khác

---

## 🌐 Bước 10: Deploy lên Render (Optional)

### 10.1 Push code lên GitHub
```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/yourusername/ai-trading-bot.git
git push -u origin main
```

### 10.2 Tạo service trên Render
1. Truy cập https://render.com
2. Sign up / Login
3. Click "New +" → "Web Service"
4. Connect GitHub repository
5. Render sẽ tự động detect `render.yaml`

### 10.3 Cấu hình Environment Variables trên Render
Trong Render dashboard:
1. Vào "Environment"
2. Add các biến:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_ADMIN_ID`
   - Các biến khác (optional)

### 10.4 Deploy
Render sẽ tự deploy. Chờ vài phút.

### 10.5 Kiểm tra deploy
1. Vào Render dashboard
2. Kiểm tra "Logs" xem có error không
3. Test bot trên Telegram

---

## ⏰ Bước 11: Setup UptimeRobot (Giữ bot 24/7)

### 11.1 Đăng ký UptimeRobot
1. Truy cập https://uptimerobot.com/
2. Sign up (free)

### 11.2 Thêm Monitor
1. Click "Add New Monitor"
2. **Monitor Type:** HTTPS
3. **URL:** `https://your-app-name.onrender.com/health`
4. **Interval:** 15 minutes
5. Click "Create Monitor"

### 11.3 Kiểm tra
UptimeRobot sẽ ping bot mỗi 15 phút để giữ bot awake

---

## 📱 Bước 12: Thêm Users (Optional)

### 12.1 Thêm user bằng lệnh Telegram
Admin gửi:
```
/adduser 123456789
```

### 12.2 Xem danh sách users
```
/users
```

### 12.3 Xóa user
```
/removeuser 123456789
```

---

## 🔧 Bước 13: Tùy chỉnh Cấu hình (Optional)

### 13.1 Điều chỉnh AI Score Threshold
Mở `.env`:
```env
AI_SCORE_THRESHOLD=90  # Tăng lên để ít tín hiệu hơn nhưng chất lượng hơn
```

### 13.2 Điều chỉnh Cooldown
```env
SIGNAL_COOLDOWN_MINUTES=60  # Tăng lên để tránh spam
```

### 13.3 Điều chỉnh Rate Limit
```env
MAX_SIGNALS_PER_HOUR=1  # Giảm xuống 1 tín hiệu/giờ
```

### 13.4 Điều chỉnh Risk
```env
MAX_RISK_PER_TRADE=0.01  # Giảm risk xuống 1%
```

---

## 📊 Bước 14: Theo dõi Bot

### 14.1 Kiểm tra Logs
```bash
# Windows
type logs\trading_bot.log

# Linux/macOS
tail -f logs/trading_bot.log
```

### 14.2 Kiểm tra Database
```bash
# Windows
cd database
dir

# Linux/macOS
ls -la database/
```

### 14.3 Kiểm tra Status trên Telegram
Gửi `/status` để xem:
- Số users
- Số tín hiệu gần đây
- Trạng thái bot

---

## 🎯 Checklist Cài Đặt

### Pre-Installation
- [ ] Python 3.12+ đã cài
- [ ] Git đã cài (nếu clone từ GitHub)
- [ ] Internet connection ổn định

### Installation
- [ ] Project đã tải/cloned
- [ ] Virtual environment đã tạo
- [ ] Dependencies đã cài
- [ ] Telegram Bot Token đã lấy
- [ ] Telegram Admin ID đã lấy
- [ ] File .env đã tạo và điền
- [ ] Bot chạy được locally

### Testing
- [ ] Lệnh `/start` hoạt động
- [ ] Lệnh `/help` hoạt động
- [ ] Lệnh `/status` hoạt động
- [ ] Lệnh `/btc` hoạt động
- [ ] Lệnh `/gold` hoạt động
- [ ] Lệnh `/market` hoạt động

### Deployment (Optional)
- [ ] Code đã push lên GitHub
- [ ] Render service đã tạo
- [ ] Environment variables đã cấu hình
- [ ] Deploy thành công
- [ ] UptimeRobot đã setup

---

## 🆘 Hỗ trợ

### Nếu gặp lỗi
1. Kiểm tra logs trong `logs/trading_bot.log`
2. Kiểm tra terminal output
3. Đọc file troubleshooting trong README
4. Search error message trên Google

### Nếu cần giúp đỡ
- Mở issue trên GitHub
- Đọc documentation trong folder docs/
- Kiểm tra các file .md trong project

---

## ✅ Hoàn tất!

Sau khi hoàn tất các bước:
- Bot sẽ chạy 24/7
- Tự động quét thị trường
- Gửi tín hiệu khi AI Score > 85
- Bạn sẽ nhận thông báo qua Telegram

**Chúc bạn sử dụng bot hiệu quả! 🎉**
