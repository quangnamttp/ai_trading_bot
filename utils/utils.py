"""
Module Utilities cho AI Trading Signal Bot
Các hàm tiện ích chung
"""
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Callable
import functools

logger = logging.getLogger(__name__)


def setup_logging(log_level: str = "INFO", log_file: str = "logs/trading_bot.log"):
    """Thiết lập logging"""
    try:
        logging.basicConfig(
            level=getattr(logging, log_level.upper()),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        logger.info(f"Logging initialized at {log_level} level")
    except Exception as e:
        print(f"Error setting up logging: {e}")


def retry(max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """Decorator để retry hàm khi lỗi"""
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            retries = 0
            current_delay = delay
            
            while retries < max_retries:
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    retries += 1
                    if retries >= max_retries:
                        logger.error(f"Max retries ({max_retries}) reached for {func.__name__}: {e}")
                        raise
                    
                    logger.warning(f"Retry {retries}/{max_retries} for {func.__name__} after {current_delay}s: {e}")
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff
            
            return None
        return wrapper
    return decorator


def format_number(number: float, decimals: int = 2) -> str:
    """Format số với số thập phân xác định"""
    try:
        return f"{number:.{decimals}f}"
    except Exception as e:
        logger.error(f"Error formatting number: {e}")
        return str(number)


def format_percentage(value: float, decimals: int = 2) -> str:
    """Format phần trăm"""
    try:
        return f"{value * 100:.{decimals}f}%"
    except Exception as e:
        logger.error(f"Error formatting percentage: {e}")
        return str(value)


def format_currency(value: float, currency: str = "USD") -> str:
    """Format tiền tệ"""
    try:
        if value >= 1000000:
            return f"${value / 1000000:.2f}M"
        elif value >= 1000:
            return f"${value / 1000:.2f}K"
        else:
            return f"${value:.2f}"
    except Exception as e:
        logger.error(f"Error formatting currency: {e}")
        return str(value)


def calculate_time_ago(timestamp: datetime) -> str:
    """Tính thời gian đã trôi qua"""
    try:
        now = datetime.now()
        delta = now - timestamp
        
        if delta < timedelta(minutes=1):
            return "vừa xong"
        elif delta < timedelta(hours=1):
            minutes = int(delta.total_seconds() / 60)
            return f"{minutes} phút trước"
        elif delta < timedelta(days=1):
            hours = int(delta.total_seconds() / 3600)
            return f"{hours} giờ trước"
        elif delta < timedelta(weeks=1):
            days = delta.days
            return f"{days} ngày trước"
        else:
            return timestamp.strftime("%Y-%m-%d")
    except Exception as e:
        logger.error(f"Error calculating time ago: {e}")
        return "N/A"


def validate_symbol(symbol: str) -> bool:
    """Kiểm tra symbol có hợp lệ không"""
    try:
        valid_symbols = ["BTCUSDT", "XAUUSD", "ETHUSDT", "BTC/USDT", "XAU/USD"]
        return symbol.upper() in valid_symbols
    except Exception as e:
        logger.error(f"Error validating symbol: {e}")
        return False


def truncate_string(text: str, max_length: int = 100) -> str:
    """Cắt chuỗi nếu quá dài"""
    try:
        if len(text) <= max_length:
            return text
        return text[:max_length] + "..."
    except Exception as e:
        logger.error(f"Error truncating string: {e}")
        return text


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Chia an toàn, tránh division by zero"""
    try:
        if denominator == 0:
            return default
        return numerator / denominator
    except Exception as e:
        logger.error(f"Error in safe divide: {e}")
        return default


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Giới hạn giá trị trong khoảng"""
    try:
        return max(min_val, min(max_val, value))
    except Exception as e:
        logger.error(f"Error clamping value: {e}")
        return value


def moving_average(data: list, window: int) -> list:
    """Tính trung bình động"""
    try:
        if len(data) < window:
            return []
        
        ma = []
        for i in range(len(data) - window + 1):
            window_data = data[i:i + window]
            ma.append(sum(window_data) / window)
        
        return ma
    except Exception as e:
        logger.error(f"Error calculating moving average: {e}")
        return []


def percentage_change(old_value: float, new_value: float) -> float:
    """Tính phần trăm thay đổi"""
    try:
        if old_value == 0:
            return 0.0
        return ((new_value - old_value) / old_value) * 100
    except Exception as e:
        logger.error(f"Error calculating percentage change: {e}")
        return 0.0


async def async_sleep(seconds: float):
    """Async sleep với logging"""
    try:
        logger.debug(f"Sleeping for {seconds} seconds")
        await asyncio.sleep(seconds)
    except Exception as e:
        logger.error(f"Error in async sleep: {e}")


def get_current_timestamp() -> str:
    """Lấy timestamp hiện tại"""
    try:
        return datetime.now().isoformat()
    except Exception as e:
        logger.error(f"Error getting timestamp: {e}")
        return ""


def parse_timestamp(timestamp: str) -> Optional[datetime]:
    """Parse timestamp string"""
    try:
        return datetime.fromisoformat(timestamp)
    except Exception as e:
        logger.error(f"Error parsing timestamp: {e}")
        return None


def is_market_open() -> bool:
    """Kiểm tra xem thị trường có mở không (cho Forex)"""
    try:
        now = datetime.now()
        # Thị trường Forex đóng cuối tuần
        if now.weekday() >= 5:  # Saturday (5) or Sunday (6)
            return False
        return True
    except Exception as e:
        logger.error(f"Error checking market open: {e}")
        return True


def format_signal_reasons(reasons: list, max_reasons: int = 5) -> str:
    """Format lý do tín hiệu"""
    try:
        if not reasons:
            return "Không có lý do"
        
        formatted = ""
        for i, reason in enumerate(reasons[:max_reasons]):
            formatted += f"• {reason}\n"
        
        if len(reasons) > max_reasons:
            formatted += f"... và {len(reasons) - max_reasons} lý do khác\n"
        
        return formatted
    except Exception as e:
        logger.error(f"Error formatting signal reasons: {e}")
        return "Lỗi format lý do"


def clean_text(text: str) -> str:
    """Làm sạch text"""
    try:
        # Remove extra whitespace
        text = ' '.join(text.split())
        # Remove special characters if needed
        return text
    except Exception as e:
        logger.error(f"Error cleaning text: {e}")
        return text


def validate_config(config: dict) -> bool:
    """Kiểm tra cấu hình"""
    try:
        required_keys = ['TELEGRAM_BOT_TOKEN', 'TELEGRAM_ADMIN_ID']
        
        for key in required_keys:
            if key not in config or not config[key]:
                logger.error(f"Missing required config key: {key}")
                return False
        
        return True
    except Exception as e:
        logger.error(f"Error validating config: {e}")
        return False


class RateLimiter:
    """Giới hạn tốc độ gọi API"""
    
    def __init__(self, max_calls: int, time_window: float):
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = []
    
    async def acquire(self):
        """Chờ nếu vượt giới hạn"""
        try:
            now = datetime.now()
            
            # Xóa các cuộc gọi cũ
            self.calls = [call for call in self.calls if now - call < timedelta(seconds=self.time_window)]
            
            # Nếu vượt giới hạn, chờ
            if len(self.calls) >= self.max_calls:
                wait_time = self.time_window - (now - self.calls[0]).total_seconds()
                if wait_time > 0:
                    logger.info(f"Rate limit reached, waiting {wait_time:.2f}s")
                    await asyncio.sleep(wait_time)
            
            self.calls.append(now)
        except Exception as e:
            logger.error(f"Error in rate limiter: {e}")


class CircuitBreaker:
    """Circuit Breaker pattern để tránh gọi API lỗi liên tục"""
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time = None
        self.state = 'closed'  # closed, open, half-open
    
    async def call(self, func: Callable, *args, **kwargs):
        """Gọi hàm với circuit breaker"""
        try:
            if self.state == 'open':
                if datetime.now() - self.last_failure_time > timedelta(seconds=self.recovery_timeout):
                    self.state = 'half-open'
                    logger.info("Circuit breaker entering half-open state")
                else:
                    raise Exception("Circuit breaker is OPEN")
            
            result = await func(*args, **kwargs)
            
            # Reset nếu thành công
            if self.state == 'half-open':
                self.state = 'closed'
                self.failures = 0
                logger.info("Circuit breaker reset to CLOSED")
            
            return result
        except Exception as e:
            self.failures += 1
            self.last_failure_time = datetime.now()
            
            if self.failures >= self.failure_threshold:
                self.state = 'open'
                logger.error(f"Circuit breaker opened after {self.failures} failures")
            
            raise
