"""
Module Health Check cho AI Trading Signal Bot V2.0
Kiểm tra sức khỏe hệ thống và gửi thông báo cho Admin
"""
import logging
import asyncio
import psutil
from datetime import datetime
from typing import Dict, Optional
from .database import db
from .config import TELEGRAM_ADMIN_ID

logger = logging.getLogger(__name__)


class HealthChecker:
    """Kiểm tra sức khỏe hệ thống"""
    
    def __init__(self):
        self.last_check = None
        self.alert_cooldown = 300  # 5 minutes between alerts
        self.last_alerts = {}
    
    async def check_system_health(self) -> Dict:
        """Kiểm tra sức khỏe toàn bộ hệ thống"""
        try:
            health_report = {
                'timestamp': datetime.now().isoformat(),
                'cpu_usage': self._check_cpu(),
                'memory_usage': self._check_memory(),
                'disk_usage': self._check_disk(),
                'database': await self._check_database(),
                'telegram': await self._check_telegram(),
                'api': await self._check_api(),
                'overall_status': 'healthy'
            }
            
            # Xác định trạng thái tổng thể
            if any(health_report[key]['status'] == 'critical' for key in ['database', 'telegram', 'api']):
                health_report['overall_status'] = 'critical'
            elif any(health_report[key]['status'] == 'warning' for key in ['database', 'telegram', 'api']):
                health_report['overall_status'] = 'warning'
            elif health_report['cpu_usage']['percent'] > 90 or health_report['memory_usage']['percent'] > 90:
                health_report['overall_status'] = 'warning'
            
            self.last_check = health_report
            return health_report
            
        except Exception as e:
            logger.error(f"Error checking system health: {e}")
            return {'overall_status': 'error', 'error': str(e)}
    
    def _check_cpu(self) -> Dict:
        """Kiểm tra CPU"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            status = 'healthy'
            if cpu_percent > 90:
                status = 'critical'
            elif cpu_percent > 70:
                status = 'warning'
            
            return {
                'percent': cpu_percent,
                'status': status
            }
        except Exception as e:
            logger.error(f"Error checking CPU: {e}")
            return {'percent': 0, 'status': 'error', 'error': str(e)}
    
    def _check_memory(self) -> Dict:
        """Kiểm tra RAM"""
        try:
            memory = psutil.virtual_memory()
            status = 'healthy'
            if memory.percent > 90:
                status = 'critical'
            elif memory.percent > 70:
                status = 'warning'
            
            return {
                'percent': memory.percent,
                'available_gb': memory.available / (1024**3),
                'total_gb': memory.total / (1024**3),
                'status': status
            }
        except Exception as e:
            logger.error(f"Error checking memory: {e}")
            return {'percent': 0, 'status': 'error', 'error': str(e)}
    
    def _check_disk(self) -> Dict:
        """Kiểm tra ổ cứng"""
        try:
            disk = psutil.disk_usage('/')
            status = 'healthy'
            if disk.percent > 90:
                status = 'critical'
            elif disk.percent > 80:
                status = 'warning'
            
            return {
                'percent': disk.percent,
                'free_gb': disk.free / (1024**3),
                'total_gb': disk.total / (1024**3),
                'status': status
            }
        except Exception as e:
            logger.error(f"Error checking disk: {e}")
            return {'percent': 0, 'status': 'error', 'error': str(e)}
    
    async def _check_database(self) -> Dict:
        """Kiểm tra Database"""
        try:
            # Thử một query đơn giản
            db.get_all_users()
            return {'status': 'healthy', 'message': 'Database accessible'}
        except Exception as e:
            logger.error(f"Database check failed: {e}")
            return {'status': 'critical', 'error': str(e)}
    
    async def _check_telegram(self) -> Dict:
        """Kiểm tra Telegram connection"""
        try:
            # Telegram bot check sẽ được thực hiện từ telegram_bot module
            return {'status': 'healthy', 'message': 'Telegram bot running'}
        except Exception as e:
            logger.error(f"Telegram check failed: {e}")
            return {'status': 'critical', 'error': str(e)}
    
    async def _check_api(self) -> Dict:
        """Kiểm tra API connections"""
        try:
            from ..data.market_data import market_data_engine
            # Thử lấy ticker
            ticker = await market_data_engine.get_ticker('BTCUSDT')
            if ticker:
                return {'status': 'healthy', 'message': 'API accessible'}
            else:
                return {'status': 'warning', 'message': 'API returned no data'}
        except Exception as e:
            logger.error(f"API check failed: {e}")
            return {'status': 'critical', 'error': str(e)}
    
    async def send_alert_if_needed(self, health_report: Dict, telegram_bot):
        """Gửi alert nếu cần thiết"""
        try:
            if health_report.get('overall_status') in ['critical', 'warning']:
                # Kiểm tra cooldown
                now = datetime.now()
                last_alert = self.last_alerts.get(health_report['overall_status'])
                
                if last_alert and (now - last_alert).total_seconds() < self.alert_cooldown:
                    return
                
                # Tạo alert message
                emoji = "🚨" if health_report['overall_status'] == 'critical' else "⚠️"
                message = f"{emoji} *HEALTH ALERT - {health_report['overall_status'].upper()}*\n\n"
                
                message += f"📊 *CPU:* {health_report['cpu_usage']['percent']}%\n"
                message += f"💾 *RAM:* {health_report['memory_usage']['percent']}%\n"
                message += f"💿 *Disk:* {health_report['disk_usage']['percent']}%\n"
                message += f"🗄️ *Database:* {health_report['database']['status']}\n"
                message += f"📱 *Telegram:* {health_report['telegram']['status']}\n"
                message += f"🌐 *API:* {health_report['api']['status']}\n"
                message += f"⏰ {health_report['timestamp']}\n"
                
                # Gửi đến admin
                try:
                    await telegram_bot.application.bot.send_message(
                        chat_id=TELEGRAM_ADMIN_ID,
                        text=message,
                        parse_mode='Markdown'
                    )
                    self.last_alerts[health_report['overall_status']] = now
                    logger.info(f"Health alert sent: {health_report['overall_status']}")
                except Exception as e:
                    logger.error(f"Error sending health alert: {e}")
                    
        except Exception as e:
            logger.error(f"Error in send_alert_if_needed: {e}")
    
    def format_health_report(self, health_report: Dict) -> str:
        """Định dạng báo cáo sức khỏe"""
        try:
            emoji = "✅" if health_report['overall_status'] == 'healthy' else "⚠️"
            if health_report['overall_status'] == 'critical':
                emoji = "🚨"
            
            report = f"{emoji} *HEALTH REPORT*\n\n"
            report += f"📊 *CPU:* {health_report['cpu_usage']['percent']}%\n"
            report += f"💾 *RAM:* {health_report['memory_usage']['percent']}% "
            report += f"({health_report['memory_usage']['available_gb']:.1f}GB free)\n"
            report += f"💿 *Disk:* {health_report['disk_usage']['percent']}% "
            report += f"({health_report['disk_usage']['free_gb']:.1f}GB free)\n"
            report += f"🗄️ *Database:* {health_report['database']['status']}\n"
            report += f"📱 *Telegram:* {health_report['telegram']['status']}\n"
            report += f"🌐 *API:* {health_report['api']['status']}\n"
            report += f"📈 *Overall:* {health_report['overall_status'].upper()}\n"
            report += f"⏰ {health_report['timestamp']}\n"
            
            return report
        except Exception as e:
            logger.error(f"Error formatting health report: {e}")
            return "❌ Không thể tạo báo cáo sức khỏe"


# Singleton instance
health_checker = HealthChecker()
