"""
Module Statistics cho AI Trading Signal Bot V2.0
Quản lý thống kê và lệnh /stats
"""
import logging
from datetime import datetime, timedelta
from typing import Dict
from .database import db

logger = logging.getLogger(__name__)


class StatisticsManager:
    """Quản lý thống kê tín hiệu"""
    
    def __init__(self):
        self.stats_cache = {}
        self.last_update = None
    
    def get_statistics_summary(self, period: str = 'all') -> Dict:
        """Lấy tóm tắt thống kê"""
        try:
            stats = db.calculate_statistics(period)
            
            if not stats:
                return self._get_empty_stats()
            
            return stats
        except Exception as e:
            logger.error(f"Error getting statistics summary: {e}")
            return self._get_empty_stats()
    
    def _get_empty_stats(self) -> Dict:
        """Trả về thống kê rỗng"""
        return {
            'total_signals': 0,
            'winning_signals': 0,
            'losing_signals': 0,
            'tp1_hits': 0,
            'tp2_hits': 0,
            'tp3_hits': 0,
            'sl_hits': 0,
            'avg_ai_score': 0,
            'total_pnl': 0,
            'win_rate': 0
        }
    
    def format_stats_message(self, period: str = 'all') -> str:
        """Định dạng tin nhắn thống kê"""
        try:
            stats = self.get_statistics_summary(period)
            
            period_text = {
                'day': 'Hôm nay',
                'week': 'Tuần này',
                'month': 'Tháng này',
                'all': 'Tất cả'
            }.get(period, 'Tất cả')
            
            message = f"""
📊 *THỐNG KÊ TÍN HIỆU - {period_text.upper()}*

📈 *Tổng quan:*
• Tổng tín hiệu: {stats['total_signals']}
• Tín hiệu thắng: {stats['winning_signals']}
• Tín hiệu thua: {stats['losing_signals']}
• Win Rate: {stats['win_rate']:.1f}%

🎯 *Take Profit:*
• TP1 đạt: {stats['tp1_hits']}
• TP2 đạt: {stats['tp2_hits']}
• TP3 đạt: {stats['tp3_hits']}

🛑 *Stop Loss:*
• SL đạt: {stats['sl_hits']}

🤖 *AI:*
• AI Score trung bình: {stats['avg_ai_score']:.1f}/100

💰 *Lợi nhuận giả lập:*
• Tổng PNL: {stats['total_pnl']:.2f}%

⏰ *Cập nhật:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            """
            
            return message.strip()
            
        except Exception as e:
            logger.error(f"Error formatting stats message: {e}")
            return "❌ Không thể lấy thống kê"
    
    def generate_daily_report(self) -> str:
        """Tạo báo cáo ngày"""
        try:
            stats = self.get_statistics_summary('day')
            
            report = f"""
📅 *BÁO CÁO NGÀY - {datetime.now().strftime('%d/%m/%Y')}*

📊 *Tổng quan:*
• Tổng tín hiệu: {stats['total_signals']}
• Win Rate: {stats['win_rate']:.1f}%

🎯 *Chi tiết:*
• TP1: {stats['tp1_hits']}
• TP2: {stats['tp2_hits']}
• TP3: {stats['tp3_hits']}
• SL: {stats['sl_hits']}

💰 *PNL: {stats['total_pnl']:.2f}%*
            """
            
            return report.strip()
            
        except Exception as e:
            logger.error(f"Error generating daily report: {e}")
            return "❌ Không thể tạo báo cáo ngày"
    
    def generate_weekly_report(self) -> str:
        """Tạo báo cáo tuần"""
        try:
            stats = self.get_statistics_summary('week')
            
            report = f"""
📅 *BÁO CÁO TUẦN - Tuần {datetime.now().strftime('%W/%Y')}*

📊 *Tổng quan:*
• Tổng tín hiệu: {stats['total_signals']}
• Win Rate: {stats['win_rate']:.1f}%

🎯 *Chi tiết:*
• TP1: {stats['tp1_hits']}
• TP2: {stats['tp2_hits']}
• TP3: {stats['tp3_hits']}
• SL: {stats['sl_hits']}

💰 *PNL: {stats['total_pnl']:.2f}%*
            """
            
            return report.strip()
            
        except Exception as e:
            logger.error(f"Error generating weekly report: {e}")
            return "❌ Không thể tạo báo cáo tuần"
    
    def generate_monthly_report(self) -> str:
        """Tạo báo cáo tháng"""
        try:
            stats = self.get_statistics_summary('month')
            
            report = f"""
📅 *BÁO CÁO THÁNG - {datetime.now().strftime('%m/%Y')}*

📊 *Tổng quan:*
• Tổng tín hiệu: {stats['total_signals']}
• Win Rate: {stats['win_rate']:.1f}%

🎯 *Chi tiết:*
• TP1: {stats['tp1_hits']}
• TP2: {stats['tp2_hits']}
• TP3: {stats['tp3_hits']}
• SL: {stats['sl_hits']}

💰 *PNL: {stats['total_pnl']:.2f}%*
            """
            
            return report.strip()
            
        except Exception as e:
            logger.error(f"Error generating monthly report: {e}")
            return "❌ Không thể tạo báo cáo tháng"
    
    def save_statistics_report(self, report_type: str, period: str):
        """Lưu báo cáo thống kê vào database"""
        try:
            stats = self.get_statistics_summary(period)
            db.save_statistics(report_type, period, stats)
            logger.info(f"Statistics report saved: {report_type} - {period}")
        except Exception as e:
            logger.error(f"Error saving statistics report: {e}")
    
    def get_detailed_stats(self, period: str = 'all') -> Dict:
        """Lấy thống kê chi tiết"""
        try:
            stats = self.get_statistics_summary(period)
            
            # Thêm các chỉ số bổ sung
            if stats['total_signals'] > 0:
                stats['tp1_hit_rate'] = (stats['tp1_hits'] / stats['total_signals'] * 100)
                stats['tp2_hit_rate'] = (stats['tp2_hits'] / stats['total_signals'] * 100)
                stats['tp3_hit_rate'] = (stats['tp3_hits'] / stats['total_signals'] * 100)
                stats['sl_hit_rate'] = (stats['sl_hits'] / stats['total_signals'] * 100)
                stats['avg_pnl_per_signal'] = stats['total_pnl'] / stats['total_signals']
            else:
                stats['tp1_hit_rate'] = 0
                stats['tp2_hit_rate'] = 0
                stats['tp3_hit_rate'] = 0
                stats['sl_hit_rate'] = 0
                stats['avg_pnl_per_signal'] = 0
            
            return stats
        except Exception as e:
            logger.error(f"Error getting detailed stats: {e}")
            return self._get_empty_stats()


# Singleton instance
statistics_manager = StatisticsManager()
