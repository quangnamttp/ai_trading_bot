"""
Module Auto Cleanup cho AI Trading Signal Bot V2.0
Tự động cleanup cache, logs, và temp files
"""
import logging
import asyncio
import os
from datetime import datetime, timedelta
from typing import List
from ..utils.cache_manager import cache_manager

logger = logging.getLogger(__name__)


class AutoCleanup:
    """Tự động cleanup tài nguyên hệ thống"""
    
    def __init__(self):
        self.log_retention_days = 7  # Keep logs for 7 days
        self.temp_retention_hours = 24  # Keep temp files for 24 hours
        self.cache_cleanup_interval = 300  # 5 minutes
        self.full_cleanup_interval = 3600  # 1 hour
    
    async def cleanup_cache(self):
        """Cleanup cache hết hạn"""
        try:
            cache_manager.cleanup_expired()
            stats = cache_manager.get_stats()
            logger.info(f"Cache cleanup completed. Active items: {stats.get('active_items', 0)}")
        except Exception as e:
            logger.error(f"Error cleaning up cache: {e}")
    
    async def cleanup_logs(self):
        """Cleanup log files cũ"""
        try:
            log_dir = "logs"
            if not os.path.exists(log_dir):
                return
            
            cutoff_time = datetime.now() - timedelta(days=self.log_retention_days)
            deleted_count = 0
            
            for filename in os.listdir(log_dir):
                if filename.endswith('.log'):
                    filepath = os.path.join(log_dir, filename)
                    file_time = datetime.fromtimestamp(os.path.getmtime(filepath))
                    
                    if file_time < cutoff_time:
                        os.remove(filepath)
                        deleted_count += 1
                        logger.info(f"Deleted old log file: {filename}")
            
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old log files")
            
        except Exception as e:
            logger.error(f"Error cleaning up logs: {e}")
    
    async def cleanup_temp_files(self):
        """Cleanup temp files cũ"""
        try:
            temp_dir = "temp"
            if not os.path.exists(temp_dir):
                return
            
            cutoff_time = datetime.now() - timedelta(hours=self.temp_retention_hours)
            deleted_count = 0
            
            for filename in os.listdir(temp_dir):
                filepath = os.path.join(temp_dir, filename)
                
                # Skip .gitkeep
                if filename == '.gitkeep':
                    continue
                
                file_time = datetime.fromtimestamp(os.path.getmtime(filepath))
                
                if file_time < cutoff_time:
                    os.remove(filepath)
                    deleted_count += 1
                    logger.info(f"Deleted old temp file: {filename}")
            
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old temp files")
            
        except Exception as e:
            logger.error(f"Error cleaning up temp files: {e}")
    
    async def cleanup_database(self):
        """Cleanup database records cũ"""
        try:
            from ..core.database import db
            
            # Cleanup old market data (older than 30 days)
            cutoff_date = datetime.now() - timedelta(days=30)
            # This would require adding a cleanup method to database.py
            # For now, just log
            logger.info("Database cleanup skipped (requires implementation)")
            
        except Exception as e:
            logger.error(f"Error cleaning up database: {e}")
    
    async def run_full_cleanup(self):
        """Chạy full cleanup"""
        try:
            logger.info("Starting full cleanup...")
            
            await self.cleanup_cache()
            await self.cleanup_logs()
            await self.cleanup_temp_files()
            await self.cleanup_database()
            
            logger.info("Full cleanup completed")
            
        except Exception as e:
            logger.error(f"Error in full cleanup: {e}")
    
    async def cleanup_loop(self):
        """Loop cleanup định kỳ"""
        logger.info("Starting auto cleanup loop")
        
        while True:
            try:
                # Quick cache cleanup every 5 minutes
                await self.cleanup_cache()
                await asyncio.sleep(self.cache_cleanup_interval)
                
                # Full cleanup every hour
                await self.run_full_cleanup()
                await asyncio.sleep(self.full_cleanup_interval - self.cache_cleanup_interval)
                
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
                await asyncio.sleep(60)
    
    def get_disk_usage(self) -> dict:
        """Lấy thông tin sử dụng disk"""
        try:
            import shutil
            total, used, free = shutil.disk_usage(".")
            
            return {
                'total_gb': total / (1024**3),
                'used_gb': used / (1024**3),
                'free_gb': free / (1024**3),
                'percent_used': (used / total) * 100
            }
        except Exception as e:
            logger.error(f"Error getting disk usage: {e}")
            return {}


# Singleton instance
auto_cleanup = AutoCleanup()
