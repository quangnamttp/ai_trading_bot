"""
Module quản lý database SQLite cho AI Trading Signal Bot
Lưu trữ: User Telegram, Nhật ký tín hiệu, Nhật ký AI, Cấu hình Bot
"""
import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional
import logging
from .config import DATABASE_PATH

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Quản lý tất cả các thao tác database"""
    
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self):
        """Tạo kết nối database"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self):
        """Khởi tạo các bảng database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Bảng users - Lưu trữ Telegram users được phép nhận tín hiệu
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        telegram_id INTEGER UNIQUE NOT NULL,
                        username TEXT,
                        first_name TEXT,
                        is_admin BOOLEAN DEFAULT 0,
                        is_active BOOLEAN DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Bảng signals - Lưu trữ lịch sử tín hiệu
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS signals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        signal_type TEXT NOT NULL,
                        entry_price TEXT,
                        take_profit TEXT,
                        stop_loss TEXT,
                        confidence REAL,
                        ai_score INTEGER,
                        reasons TEXT,
                        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(symbol, signal_type, sent_at)
                    )
                """)
                
                # Bảng ai_logs - Lưu trữ nhật ký phân tích AI
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS ai_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        analysis_data TEXT,
                        decision TEXT,
                        ai_score INTEGER,
                        confidence REAL,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Bảng bot_config - Lưu trữ cấu hình bot
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS bot_config (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Bảng market_data - Lưu trữ dữ liệu thị trường
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS market_data (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        data_type TEXT NOT NULL,
                        data_value TEXT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Bảng signal_history - Lưu trữ chi tiết tín hiệu đã gửi
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS signal_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        signal_id INTEGER,
                        telegram_id INTEGER,
                        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        status TEXT DEFAULT 'sent',
                        FOREIGN KEY (signal_id) REFERENCES signals(id),
                        FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
                    )
                """)
                
                conn.commit()
                logger.info("Database initialized successfully")
                
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise
    
    # ==================== USER MANAGEMENT ====================
    
    def add_user(self, telegram_id: int, username: str = None, 
                 first_name: str = None, is_admin: bool = False) -> bool:
        """Thêm user mới vào database"""
        try:
            if not isinstance(telegram_id, int) or telegram_id <= 0:
                logger.error(f"Invalid telegram_id: {telegram_id}")
                return False
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO users 
                    (telegram_id, username, first_name, is_admin, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (telegram_id, username, first_name, is_admin))
                conn.commit()
                logger.info(f"User {telegram_id} added/updated successfully")
                return True
        except Exception as e:
            logger.error(f"Error adding user: {e}")
            return False
    
    def remove_user(self, telegram_id: int) -> bool:
        """Xóa user khỏi database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET is_active = 0 WHERE telegram_id = ?", 
                             (telegram_id,))
                conn.commit()
                logger.info(f"User {telegram_id} deactivated")
                return True
        except Exception as e:
            logger.error(f"Error removing user: {e}")
            return False
    
    def get_user(self, telegram_id: int) -> Optional[Dict]:
        """Lấy thông tin user theo telegram_id"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE telegram_id = ? AND is_active = 1", 
                             (telegram_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            return None
    
    def get_all_users(self) -> List[Dict]:
        """Lấy danh sách tất cả users active"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE is_active = 1")
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return []
    
    def is_admin(self, telegram_id: int) -> bool:
        """Kiểm tra xem user có phải admin không"""
        user = self.get_user(telegram_id)
        return user and user.get('is_admin', False)
    
    def is_authorized(self, telegram_id: int) -> bool:
        """Kiểm tra xem user có được phép nhận tín hiệu không"""
        user = self.get_user(telegram_id)
        return user is not None
    
    # ==================== SIGNAL MANAGEMENT ====================
    
    def save_signal(self, symbol: str, signal_type: str, entry_price: str,
                   take_profit: str, stop_loss: str, confidence: float,
                   ai_score: int, reasons: List[str]) -> Optional[int]:
        """Lưu tín hiệu vào database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO signals 
                    (symbol, signal_type, entry_price, take_profit, stop_loss, 
                     confidence, ai_score, reasons)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (symbol, signal_type, entry_price, take_profit, stop_loss,
                     confidence, ai_score, json.dumps(reasons)))
                conn.commit()
                signal_id = cursor.lastrowid
                logger.info(f"Signal saved: {signal_type} {symbol} (ID: {signal_id})")
                return signal_id
        except Exception as e:
            logger.error(f"Error saving signal: {e}")
            return None
    
    def get_recent_signals(self, symbol: str = None, limit: int = 10) -> List[Dict]:
        """Lấy các tín hiệu gần đây"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if symbol:
                    cursor.execute("""
                        SELECT * FROM signals 
                        WHERE symbol = ? 
                        ORDER BY sent_at DESC 
                        LIMIT ?
                    """, (symbol, limit))
                else:
                    cursor.execute("""
                        SELECT * FROM signals 
                        ORDER BY sent_at DESC 
                        LIMIT ?
                    """, (limit,))
                rows = cursor.fetchall()
                signals = []
                for row in rows:
                    signal = dict(row)
                    signal['reasons'] = json.loads(signal['reasons']) if signal['reasons'] else []
                    signals.append(signal)
                return signals
        except Exception as e:
            logger.error(f"Error getting recent signals: {e}")
            return []
    
    def get_last_signal_time(self, symbol: str, signal_type: str = None) -> Optional[datetime]:
        """Lấy thời gian tín hiệu cuối cùng cho symbol"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if signal_type:
                    cursor.execute("""
                        SELECT sent_at FROM signals 
                        WHERE symbol = ? AND signal_type = ?
                        ORDER BY sent_at DESC 
                        LIMIT 1
                    """, (symbol, signal_type))
                else:
                    cursor.execute("""
                        SELECT sent_at FROM signals 
                        WHERE symbol = ?
                        ORDER BY sent_at DESC 
                        LIMIT 1
                    """, (symbol,))
                row = cursor.fetchone()
                return datetime.fromisoformat(row['sent_at']) if row else None
        except Exception as e:
            logger.error(f"Error getting last signal time: {e}")
            return None
    
    def count_signals_last_hour(self) -> int:
        """Đếm số tín hiệu đã gửi trong giờ qua"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*) as count FROM signals 
                    WHERE sent_at >= datetime('now', '-1 hour')
                """)
                row = cursor.fetchone()
                return row['count'] if row else 0
        except Exception as e:
            logger.error(f"Error counting signals: {e}")
            return 0
    
    # ==================== AI LOG MANAGEMENT ====================
    
    def save_ai_log(self, symbol: str, analysis_data: Dict, decision: str,
                   ai_score: int, confidence: float) -> bool:
        """Lưu nhật ký phân tích AI"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO ai_logs 
                    (symbol, analysis_data, decision, ai_score, confidence)
                    VALUES (?, ?, ?, ?, ?)
                """, (symbol, json.dumps(analysis_data), decision, 
                     ai_score, confidence))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error saving AI log: {e}")
            return False
    
    def get_recent_ai_logs(self, symbol: str = None, limit: int = 20) -> List[Dict]:
        """Lấy nhật ký AI gần đây"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if symbol:
                    cursor.execute("""
                        SELECT * FROM ai_logs 
                        WHERE symbol = ? 
                        ORDER BY timestamp DESC 
                        LIMIT ?
                    """, (symbol, limit))
                else:
                    cursor.execute("""
                        SELECT * FROM ai_logs 
                        ORDER BY timestamp DESC 
                        LIMIT ?
                    """, (limit,))
                rows = cursor.fetchall()
                logs = []
                for row in rows:
                    log = dict(row)
                    log['analysis_data'] = json.loads(log['analysis_data']) if log['analysis_data'] else {}
                    logs.append(log)
                return logs
        except Exception as e:
            logger.error(f"Error getting AI logs: {e}")
            return []
    
    # ==================== CONFIG MANAGEMENT ====================
    
    def set_config(self, key: str, value: str) -> bool:
        """Lưu cấu hình bot"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO bot_config (key, value, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                """, (key, value))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error setting config: {e}")
            return False
    
    def get_config(self, key: str, default: str = None) -> Optional[str]:
        """Lấy cấu hình bot"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM bot_config WHERE key = ?", (key,))
                row = cursor.fetchone()
                return row['value'] if row else default
        except Exception as e:
            logger.error(f"Error getting config: {e}")
            return default
    
    def get_all_config(self) -> Dict[str, str]:
        """Lấy tất cả cấu hình"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT key, value FROM bot_config")
                rows = cursor.fetchall()
                return {row['key']: row['value'] for row in rows}
        except Exception as e:
            logger.error(f"Error getting all config: {e}")
            return {}
    
    # ==================== MARKET DATA MANAGEMENT ====================
    
    def save_market_data(self, symbol: str, data_type: str, data_value: Dict) -> bool:
        """Lưu dữ liệu thị trường"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO market_data (symbol, data_type, data_value)
                    VALUES (?, ?, ?)
                """, (symbol, data_type, json.dumps(data_value)))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error saving market data: {e}")
            return False
    
    def get_market_data(self, symbol: str, data_type: str = None, 
                       limit: int = 100) -> List[Dict]:
        """Lấy dữ liệu thị trường"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if data_type:
                    cursor.execute("""
                        SELECT * FROM market_data 
                        WHERE symbol = ? AND data_type = ?
                        ORDER BY timestamp DESC 
                        LIMIT ?
                    """, (symbol, data_type, limit))
                else:
                    cursor.execute("""
                        SELECT * FROM market_data 
                        WHERE symbol = ?
                        ORDER BY timestamp DESC 
                        LIMIT ?
                    """, (symbol, limit))
                rows = cursor.fetchall()
                data = []
                for row in rows:
                    item = dict(row)
                    item['data_value'] = json.loads(item['data_value']) if item['data_value'] else {}
                    data.append(item)
                return data
        except Exception as e:
            logger.error(f"Error getting market data: {e}")
            return []


# Singleton instance
db = DatabaseManager()
