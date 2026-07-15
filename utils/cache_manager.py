"""
Module Cache Manager cho AI Trading Signal Bot V2.0
Quản lý cache cho API calls để giảm số lần gọi
"""
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
import hashlib
import json

logger = logging.getLogger(__name__)


class CacheManager:
    """Quản lý cache cho API calls"""
    
    def __init__(self):
        self.cache = {}
        self.default_ttl = 300  # 5 minutes default TTL
        self.max_cache_size = 1000
    
    def _generate_key(self, prefix: str, **kwargs) -> str:
        """Tạo cache key từ parameters"""
        try:
            key_data = f"{prefix}_{json.dumps(kwargs, sort_keys=True)}"
            return hashlib.md5(key_data.encode()).hexdigest()
        except Exception as e:
            logger.error(f"Error generating cache key: {e}")
            return f"{prefix}_{hash(str(kwargs))}"
    
    def get(self, prefix: str, **kwargs) -> Optional[Any]:
        """Lấy dữ liệu từ cache"""
        try:
            key = self._generate_key(prefix, **kwargs)
            
            if key not in self.cache:
                return None
            
            cached_item = self.cache[key]
            
            # Kiểm tra TTL
            if datetime.now() > cached_item['expires_at']:
                del self.cache[key]
                return None
            
            logger.debug(f"Cache hit for key: {key}")
            return cached_item['data']
            
        except Exception as e:
            logger.error(f"Error getting from cache: {e}")
            return None
    
    def set(self, prefix: str, data: Any, ttl: int = None, **kwargs):
        """Lưu dữ liệu vào cache"""
        try:
            # Kiểm tra cache size
            if len(self.cache) >= self.max_cache_size:
                self._cleanup_oldest()
            
            key = self._generate_key(prefix, **kwargs)
            ttl = ttl or self.default_ttl
            
            self.cache[key] = {
                'data': data,
                'created_at': datetime.now(),
                'expires_at': datetime.now() + timedelta(seconds=ttl),
                'ttl': ttl
            }
            
            logger.debug(f"Cached data for key: {key} (TTL: {ttl}s)")
            
        except Exception as e:
            logger.error(f"Error setting cache: {e}")
    
    def invalidate(self, prefix: str, **kwargs):
        """Xóa cache cụ thể"""
        try:
            key = self._generate_key(prefix, **kwargs)
            if key in self.cache:
                del self.cache[key]
                logger.debug(f"Invalidated cache for key: {key}")
        except Exception as e:
            logger.error(f"Error invalidating cache: {e}")
    
    def invalidate_prefix(self, prefix: str):
        """Xóa tất cả cache với prefix"""
        try:
            keys_to_remove = []
            for key in self.cache.keys():
                if key.startswith(prefix):
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                del self.cache[key]
            
            logger.info(f"Invalidated {len(keys_to_remove)} cache entries with prefix: {prefix}")
            
        except Exception as e:
            logger.error(f"Error invalidating prefix cache: {e}")
    
    def _cleanup_oldest(self):
        """Xóa cache cũ nhất"""
        try:
            if not self.cache:
                return
            
            # Tìm item cũ nhất
            oldest_key = min(self.cache.keys(), 
                          key=lambda k: self.cache[k]['created_at'])
            del self.cache[oldest_key]
            
            logger.debug("Removed oldest cache entry")
            
        except Exception as e:
            logger.error(f"Error cleaning up oldest cache: {e}")
    
    def cleanup_expired(self):
        """Xóa cache hết hạn"""
        try:
            now = datetime.now()
            keys_to_remove = []
            
            for key, item in self.cache.items():
                if now > item['expires_at']:
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                del self.cache[key]
            
            if keys_to_remove:
                logger.info(f"Cleaned up {len(keys_to_remove)} expired cache entries")
            
        except Exception as e:
            logger.error(f"Error cleaning up expired cache: {e}")
    
    def get_stats(self) -> Dict:
        """Lấy thống kê cache"""
        try:
            total_items = len(self.cache)
            expired_items = sum(1 for item in self.cache.values() 
                              if datetime.now() > item['expires_at'])
            
            return {
                'total_items': total_items,
                'expired_items': expired_items,
                'active_items': total_items - expired_items,
                'max_size': self.max_cache_size,
                'usage_percent': (total_items / self.max_cache_size * 100) if self.max_cache_size > 0 else 0
            }
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return {}
    
    def clear_all(self):
        """Xóa tất cả cache"""
        self.cache.clear()
        logger.info("All cache cleared")


# Singleton instance
cache_manager = CacheManager()
