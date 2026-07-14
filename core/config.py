"""
Cấu hình hệ thống AI Trading Signal Bot
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_ADMIN_ID = os.getenv("TELEGRAM_ADMIN_ID")
TELEGRAM_WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL", "")

# Database Configuration
DATABASE_PATH = os.getenv("DATABASE_PATH", "database/trading_bot.db")

# Trading Configuration
SYMBOLS = ["BTCUSDT", "XAUUSD"]
EXCHANGE = "MEXC"
AI_SCORE_THRESHOLD = float(os.getenv("AI_SCORE_THRESHOLD", "85"))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.85"))

# API Keys
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
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
MARKET_DATA_INTERVAL = int(os.getenv("MARKET_DATA_INTERVAL", "60"))  # seconds
NEWS_CHECK_INTERVAL = int(os.getenv("NEWS_CHECK_INTERVAL", "300"))  # seconds

# AI Configuration
AI_MODEL = os.getenv("AI_MODEL", "rule_based")
AI_UPDATE_INTERVAL = int(os.getenv("AI_UPDATE_INTERVAL", "120"))  # seconds

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
