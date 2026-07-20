"""
Module Anti-Duplicate cho AI Trading Signal Bot V2.0
Ngăn chặn gửi tín hiệu trùng lặp
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
from core.database import db
from core.config import SIGNAL_COOLDOWN_MINUTES

logger = logging.getLogger(__name__)


class AntiDuplicate:
    """Ngăn chặn tín hiệu trùng lặp"""
    
    def __init__(self):
        self.recent_signals = {}
        self.cooldown_minutes = SIGNAL_COOLDOWN_MINUTES
    
    def is_duplicate_signal(self, symbol: str, signal_type: str, 
                           entry_price: float, timeframe: str = '1h') -> bool:
        """Kiểm tra xem tín hiệu có trùng không"""
        try:
            # Kiểm tra cooldown
            if self._check_cooldown(symbol, signal_type):
                logger.info(f"Signal blocked by cooldown: {signal_type} {symbol}")
                return True
            
            # Kiểm tra tín hiệu tương tự gần đây
            if self._check_similar_signals(symbol, signal_type, entry_price):
                logger.info(f"Signal blocked by similarity: {signal_type} {symbol}")
                return True
            
            # Lưu tín hiệu này
            self._save_recent_signal(symbol, signal_type, entry_price, timeframe)
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking duplicate signal: {e}")
            return False  # Cho phép gửi nếu có lỗi
    
    def _check_cooldown(self, symbol: str, signal_type: str) -> bool:
        """Kiểm tra cooldown period"""
        try:
            last_signal = db.get_last_signal_time(symbol, signal_type)
            
            if not last_signal:
                return False
            
            time_since_last = datetime.now() - last_signal
            cooldown_period = timedelta(minutes=self.cooldown_minutes)
            
            if time_since_last < cooldown_period:
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking cooldown: {e}")
            return False
    
    def _check_similar_signals(self, symbol: str, signal_type: str, 
                             entry_price: float) -> bool:
        """Kiểm tra tín hiệu tương tự trong thời gian gần"""
        try:
            # Lấy các tín hiệu gần đây
            recent_signals = db.get_recent_signals(symbol=symbol, limit=5)
            
            if not recent_signals:
                return False
            
            for signal in recent_signals:
                # Kiểm tra cùng loại tín hiệu
                if signal['signal_type'] != signal_type:
                    continue
                
                # Kiểm tra thời gian (trong 1 giờ)
                signal_time = datetime.fromisoformat(signal['sent_at'])
                time_diff = datetime.now() - signal_time
                
                if time_diff > timedelta(hours=1):
                    continue
                
                # Kiểm tra giá entry tương tự (chênh lệch < 0.5%)
                try:
                    signal_entry = float(signal['entry_price'].split('-')[0].strip())
                    price_diff = abs(entry_price - signal_entry) / signal_entry
                    
                    if price_diff < 0.005:  # 0.5%
                        return True
                except:
                    continue
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking similar signals: {e}")
            return False
    
    def _save_recent_signal(self, symbol: str, signal_type: str, 
                          entry_price: float, timeframe: str):
        """Lưu tín hiệu vào cache"""
        try:
            key = f"{symbol}_{signal_type}_{timeframe}"
            self.recent_signals[key] = {
                'symbol': symbol,
                'signal_type': signal_type,
                'entry_price': entry_price,
                'timeframe': timeframe,
                'timestamp': datetime.now()
            }
            
            # Cleanup old signals
            self._cleanup_old_signals()
            
        except Exception as e:
            logger.error(f"Error saving recent signal: {e}")
    
    def _cleanup_old_signals(self):
        """Xóa tín hiệu cũ khỏi cache"""
        try:
            cutoff_time = datetime.now() - timedelta(hours=2)
            
            keys_to_remove = []
            for key, signal in self.recent_signals.items():
                if signal['timestamp'] < cutoff_time:
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                del self.recent_signals[key]
            
            if keys_to_remove:
                logger.info(f"Cleaned up {len(keys_to_remove)} old signals from cache")
                
        except Exception as e:
            logger.error(f"Error cleaning up old signals: {e}")
    
    def get_recent_signals_count(self) -> int:
        """Lấy số lượng tín hiệu gần đây trong cache"""
        return len(self.recent_signals)
    
    def clear_cache(self):
        """Xóa cache"""
        self.recent_signals.clear()
        logger.info("Anti-duplicate cache cleared")


# Singleton instance
anti_duplicate = AntiDuplicate()
