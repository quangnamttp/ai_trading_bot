"""
Module Message Queue cho AI Trading Signal Bot V2.0
Quản lý hàng đợi tin nhắn Telegram để tránh flood
"""
import logging
import asyncio
from datetime import datetime
from typing import Dict, Optional, Callable
from collections import deque
import time

logger = logging.getLogger(__name__)


class MessageQueue:
    """Hàng đợi tin nhắn Telegram"""
    
    def __init__(self):
        self.queue = deque()
        self.is_processing = False
        self.telegram_bot = None
        self.rate_limit = 30  # messages per minute
        self.message_interval = 2.0  # seconds between messages
        self.last_message_time = 0
        self.message_count = 0
        self.count_reset_time = time.time()
    
    def set_telegram_bot(self, telegram_bot):
        """Set telegram bot reference"""
        self.telegram_bot = telegram_bot
    
    async def enqueue(self, message: str, chat_id: int = None, parse_mode: str = 'Markdown'):
        """Thêm tin nhắn vào hàng đợi"""
        try:
            message_item = {
                'message': message,
                'chat_id': chat_id,
                'parse_mode': parse_mode,
                'timestamp': datetime.now(),
                'retries': 0
            }
            
            self.queue.append(message_item)
            logger.info(f"Message enqueued. Queue size: {len(self.queue)}")
            
            # Bắt đầu xử lý nếu chưa chạy
            if not self.is_processing:
                asyncio.create_task(self.process_queue())
            
        except Exception as e:
            logger.error(f"Error enqueuing message: {e}")
    
    async def process_queue(self):
        """Xử lý hàng đợi tin nhắn"""
        if self.is_processing:
            return
        
        self.is_processing = True
        logger.info("Starting message queue processing")
        
        while self.queue:
            try:
                # Kiểm tra rate limit
                await self._check_rate_limit()
                
                # Lấy tin nhắn từ hàng đợi
                message_item = self.queue.popleft()
                
                # Gửi tin nhắn
                await self._send_message(message_item)
                
                # Đợi giữa các tin nhắn
                await asyncio.sleep(self.message_interval)
                
            except Exception as e:
                logger.error(f"Error processing queue: {e}")
                await asyncio.sleep(5)
        
        self.is_processing = False
        logger.info("Message queue processing completed")
    
    async def _check_rate_limit(self):
        """Kiểm tra giới hạn tốc độ"""
        try:
            current_time = time.time()
            
            # Reset counter mỗi phút
            if current_time - self.count_reset_time >= 60:
                self.message_count = 0
                self.count_reset_time = current_time
            
            # Nếu vượt giới hạn, chờ
            if self.message_count >= self.rate_limit:
                wait_time = 60 - (current_time - self.count_reset_time)
                if wait_time > 0:
                    logger.info(f"Rate limit reached. Waiting {wait_time:.1f}s")
                    await asyncio.sleep(wait_time)
                    self.message_count = 0
                    self.count_reset_time = time.time()
            
        except Exception as e:
            logger.error(f"Error checking rate limit: {e}")
    
    async def _send_message(self, message_item: Dict):
        """Gửi tin nhắn"""
        try:
            if not self.telegram_bot:
                logger.error("Telegram bot not set")
                return
            
            message = message_item['message']
            chat_id = message_item.get('chat_id')
            parse_mode = message_item.get('parse_mode', 'Markdown')
            
            if chat_id:
                # Gửi đến user cụ thể
                await self.telegram_bot.application.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode=parse_mode
                )
            else:
                # Gửi đến tất cả users (broadcast)
                from ..core.database import db
                users = db.get_all_users()
                
                success_count = 0
                for user in users:
                    try:
                        await self.telegram_bot.application.bot.send_message(
                            chat_id=user['telegram_id'],
                            text=message,
                            parse_mode=parse_mode
                        )
                        success_count += 1
                        await asyncio.sleep(0.5)  # Small delay between users
                    except Exception as e:
                        logger.error(f"Error sending to user {user['telegram_id']}: {e}")
                
                logger.info(f"Broadcast sent to {success_count}/{len(users)} users")
            
            self.message_count += 1
            self.last_message_time = time.time()
            
            logger.info(f"Message sent successfully")
            
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            
            # Retry logic
            message_item['retries'] += 1
            if message_item['retries'] < 3:
                logger.info(f"Retrying message (attempt {message_item['retries']})")
                self.queue.appendleft(message_item)
            else:
                logger.error(f"Message failed after 3 retries")
    
    def get_queue_size(self) -> int:
        """Lấy kích thước hàng đợi"""
        return len(self.queue)
    
    def clear_queue(self):
        """Xóa hàng đợi"""
        self.queue.clear()
        logger.info("Message queue cleared")


# Singleton instance
message_queue = MessageQueue()
