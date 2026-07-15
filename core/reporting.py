"""
Module Reporting cho AI Trading Signal Bot V2.0
Tạo báo cáo ngày/tuần/tháng và gửi tự động
"""
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from ..core.database import db
from ..core.statistics import statistics_manager
from ..core.config import TELEGRAM_ADMIN_ID

logger = logging.getLogger(__name__)


class ReportingManager:
    """Quản lý báo cáo tự động"""
    
    def __init__(self):
        self.last_daily_report = None
        self.last_weekly_report = None
        self.last_monthly_report = None
    
    async def generate_daily_report(self) -> str:
        """Tạo báo cáo ngày"""
        try:
            report = statistics_manager.generate_daily_report()
            
            # Lưu vào database
            statistics_manager.save_statistics_report('daily', 'day')
            
            self.last_daily_report = datetime.now()
            logger.info("Daily report generated")
            
            return report
        except Exception as e:
            logger.error(f"Error generating daily report: {e}")
            return "❌ Không thể tạo báo cáo ngày"
    
    async def generate_weekly_report(self) -> str:
        """Tạo báo cáo tuần"""
        try:
            report = statistics_manager.generate_weekly_report()
            
            # Lưu vào database
            statistics_manager.save_statistics_report('weekly', 'week')
            
            self.last_weekly_report = datetime.now()
            logger.info("Weekly report generated")
            
            return report
        except Exception as e:
            logger.error(f"Error generating weekly report: {e}")
            return "❌ Không thể tạo báo cáo tuần"
    
    async def generate_monthly_report(self) -> str:
        """Tạo báo cáo tháng"""
        try:
            report = statistics_manager.generate_monthly_report()
            
            # Lưu vào database
            statistics_manager.save_statistics_report('monthly', 'month')
            
            self.last_monthly_report = datetime.now()
            logger.info("Monthly report generated")
            
            return report
        except Exception as e:
            logger.error(f"Error generating monthly report: {e}")
            return "❌ Không thể tạo báo cáo tháng"
    
    async def send_report_to_admin(self, report: str, report_type: str, telegram_bot):
        """Gửi báo cáo đến admin"""
        try:
            emoji = "📅" if report_type == 'daily' else "📊" if report_type == 'weekly' else "📈"
            message = f"{emoji} *BÁO CÁO TỰ ĐỘNG*\n\n{report}"
            
            await telegram_bot.application.bot.send_message(
                chat_id=TELEGRAM_ADMIN_ID,
                text=message,
                parse_mode='Markdown'
            )
            
            logger.info(f"{report_type.capitalize()} report sent to admin")
            
        except Exception as e:
            logger.error(f"Error sending {report_type} report: {e}")
    
    async def check_and_send_daily_report(self, telegram_bot):
        """Kiểm tra và gửi báo cáo ngày (chạy lúc 00:00)"""
        try:
            now = datetime.now()
            
            # Chỉ gửi lúc 00:00
            if now.hour != 0 or now.minute != 0:
                return
            
            # Kiểm tra đã gửi chưa hôm nay
            if self.last_daily_report:
                if self.last_daily_report.date() == now.date():
                    return
            
            report = await self.generate_daily_report()
            await self.send_report_to_admin(report, 'daily', telegram_bot)
            
        except Exception as e:
            logger.error(f"Error in check_and_send_daily_report: {e}")
    
    async def check_and_send_weekly_report(self, telegram_bot):
        """Kiểm tra và gửi báo cáo tuần (chạy thứ 2 lúc 00:00)"""
        try:
            now = datetime.now()
            
            # Chỉ gửi thứ 2 lúc 00:00
            if now.weekday() != 0 or now.hour != 0 or now.minute != 0:
                return
            
            # Kiểm tra đã gửi tuần này chưa
            if self.last_weekly_report:
                week_start = now - timedelta(days=now.weekday())
                if self.last_weekly_report >= week_start:
                    return
            
            report = await self.generate_weekly_report()
            await self.send_report_to_admin(report, 'weekly', telegram_bot)
            
        except Exception as e:
            logger.error(f"Error in check_and_send_weekly_report: {e}")
    
    async def check_and_send_monthly_report(self, telegram_bot):
        """Kiểm tra và gửi báo cáo tháng (chạy ngày 1 lúc 00:00)"""
        try:
            now = datetime.now()
            
            # Chỉ gửi ngày 1 lúc 00:00
            if now.day != 1 or now.hour != 0 or now.minute != 0:
                return
            
            # Kiểm tra đã gửi tháng này chưa
            if self.last_monthly_report:
                if self.last_monthly_report.month == now.month and self.last_monthly_report.year == now.year:
                    return
            
            report = await self.generate_monthly_report()
            await self.send_report_to_admin(report, 'monthly', telegram_bot)
            
        except Exception as e:
            logger.error(f"Error in check_and_send_monthly_report: {e}")
    
    async def reporting_loop(self, telegram_bot):
        """Loop kiểm tra và gửi báo cáo"""
        logger.info("Starting reporting loop")
        
        while True:
            try:
                await self.check_and_send_daily_report(telegram_bot)
                await self.check_and_send_weekly_report(telegram_bot)
                await self.check_and_send_monthly_report(telegram_bot)
                
                # Check mỗi phút
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"Error in reporting loop: {e}")
                await asyncio.sleep(60)
    
    async def send_manual_report(self, report_type: str, telegram_bot):
        """Gửi báo cáo thủ công (khi admin yêu cầu)"""
        try:
            if report_type == 'daily':
                report = await self.generate_daily_report()
            elif report_type == 'weekly':
                report = await self.generate_weekly_report()
            elif report_type == 'monthly':
                report = await self.generate_monthly_report()
            else:
                return "❌ Loại báo cáo không hợp lệ"
            
            await self.send_report_to_admin(report, report_type, telegram_bot)
            return f"✅ Đã gửi báo cáo {report_type}"
            
        except Exception as e:
            logger.error(f"Error sending manual report: {e}")
            return f"❌ Lỗi gửi báo cáo: {str(e)}"


# Singleton instance
reporting_manager = ReportingManager()
