"""
Cấu hình hệ thống AI Trading Signal Bot
"""
import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Timezone Configuration
TIMEZONE = timezone(timedelta(hours=7))  # UTC+7 (Asia/Ho_Chi_Minh)

def get_current_time():
    """Get current time in UTC+7"""
    return datetime.now(TIMEZONE)

def format_time(dt=None):
    """Format datetime to UTC+7 string"""
    if dt is None:
        dt = datetime.now(TIMEZONE)
    return dt.strftime("%H:%M (GMT+7)")

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_ADMIN_ID = os.getenv("TELEGRAM_ADMIN_ID")
ADMIN_IDS = os.getenv("ADMIN_IDS", TELEGRAM_ADMIN_ID or "").split(",")
ADMIN_IDS = [int(id.strip()) for id in ADMIN_IDS if id.strip().isdigit()] if ADMIN_IDS else []
TELEGRAM_WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL", "")

# Database Configuration
DATABASE_PATH = os.getenv("DATABASE_PATH", "database/trading_bot.db")

# Trading Configuration
SYMBOLS = os.getenv("TRADING_SYMBOLS", "BTC/USDT:USDT,XAU/USDT:USDT").split(",")
SYMBOLS = [s.strip() for s in SYMBOLS if s.strip()]
EXCHANGE = "MEXC"
AI_SCORE_THRESHOLD = float(os.getenv("AI_SCORE_THRESHOLD", "80"))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.80"))

def clean_symbol(symbol: str) -> str:
    """Clean symbol for user-facing display (remove exchange suffix)"""
    if ":USDT" in symbol:
        return symbol.replace(":USDT", "")
    return symbol

# API Keys (all optional - using free public APIs)
COINAPI_KEY = os.getenv("COINAPI_KEY", "")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

# Risk Management
MAX_RISK_PER_TRADE = float(os.getenv("MAX_RISK_PER_TRADE", "0.02"))
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "3"))

# Signal Configuration
SIGNAL_COOLDOWN_MINUTES = int(os.getenv("SIGNAL_COOLDOWN_MINUTES", "30"))
MAX_SIGNALS_PER_HOUR = int(os.getenv("MAX_SIGNALS_PER_HOUR", "2"))

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = "logs/trading_bot.log"

# Market Data Configuration
MARKET_DATA_INTERVAL = int(os.getenv("MARKET_DATA_INTERVAL", "120"))  # seconds (increased from 60)
NEWS_CHECK_INTERVAL = int(os.getenv("NEWS_CHECK_INTERVAL", "600"))  # seconds (increased from 300)

# AI Configuration
AI_MODEL = os.getenv("AI_MODEL", "rule_based")
AI_UPDATE_INTERVAL = int(os.getenv("AI_UPDATE_INTERVAL", "180"))  # seconds (increased from 120)

# Deployment Configuration
DEPLOYMENT_ENV = os.getenv("DEPLOYMENT_ENV", "development")
PORT = int(os.getenv("PORT", "8080"))

# Validation
def validate_config():
    """Kiểm tra cấu hình bắt buộc"""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")
    if not TELEGRAM_ADMIN_ID:
        raise ValueError("TELEGRAM_ADMIN_ID is required")
    return True
