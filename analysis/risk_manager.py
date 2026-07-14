"""
Module Risk Manager cho AI Trading Signal Bot
Quản lý rủi ro và kiểm soát tín hiệu
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
from ..core.config import MAX_RISK_PER_TRADE, MAX_POSITIONS, AI_SCORE_THRESHOLD

logger = logging.getLogger(__name__)


class RiskManager:
    """Quản lý rủi ro cho tín hiệu giao dịch"""
    
    def __init__(self):
        self.active_positions = {}
        self.daily_loss_limit = 0.05  # 5% daily loss limit
        self.daily_pnl = 0
        self.risk_events = []
    
    def calculate_position_size(self, account_balance: float, risk_per_trade: float = None) -> float:
        """Tính toán kích thước vị trí dựa trên rủi ro"""
        try:
            if risk_per_trade is None:
                risk_per_trade = MAX_RISK_PER_TRADE
            
            position_size = account_balance * risk_per_trade
            logger.info(f"Calculated position size: {position_size} (Risk: {risk_per_trade * 100}%)")
            return position_size
        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            return 0
    
    def validate_signal(self, analysis: Dict) -> Dict:
        """Kiểm tra tín hiệu trước khi gửi"""
        try:
            validation = {
                'valid': True,
                'reasons': [],
                'adjusted_ai_score': analysis.get('ai_score', 0)
            }
            
            ai_score = analysis.get('ai_score', 0)
            risk_level = analysis.get('risk_level', 'medium')
            confidence = analysis.get('confidence', 0)
            
            # 1. Kiểm tra AI Score
            if ai_score < AI_SCORE_THRESHOLD:
                validation['valid'] = False
                validation['reasons'].append(f'AI Score {ai_score} below threshold {AI_SCORE_THRESHOLD}')
            
            # 2. Kiểm tra confidence
            if confidence < 0.7:
                validation['valid'] = False
                validation['reasons'].append(f'Confidence {confidence:.1%} too low')
            
            # 3. Kiểm tra risk level
            if risk_level == 'high':
                validation['adjusted_ai_score'] -= 10
                validation['reasons'].append('High risk level detected')
                if validation['adjusted_ai_score'] < AI_SCORE_THRESHOLD:
                    validation['valid'] = False
            
            # 4. Kiểm tra số lượng vị trí active
            if len(self.active_positions) >= MAX_POSITIONS:
                validation['valid'] = False
                validation['reasons'].append(f'Maximum positions ({MAX_POSITIONS}) reached')
            
            # 5. Kiểm tra daily loss limit
            if self.daily_pnl < -self.daily_loss_limit:
                validation['valid'] = False
                validation['reasons'].append('Daily loss limit reached')
            
            return validation
        except Exception as e:
            logger.error(f"Error validating signal: {e}")
            return {'valid': False, 'reasons': ['Validation error'], 'adjusted_ai_score': 0}
    
    def check_market_conditions(self, market_data: Dict) -> Dict:
        """Kiểm tra điều kiện thị trường"""
        try:
            conditions = {
                'volatile': False,
                'low_liquidity': False,
                'extreme_price': False,
                'safe_to_trade': True
            }
            
            # Kiểm tra volatility (giả lập)
            volatility = market_data.get('volatility', 0)
            if volatility > 0.05:  # > 5% volatility
                conditions['volatile'] = True
                conditions['safe_to_trade'] = False
            
            # Kiểm tra liquidity (giả lập)
            volume = market_data.get('volume', 0)
            if volume < 1000000:  # < $1M volume
                conditions['low_liquidity'] = True
                conditions['safe_to_trade'] = False
            
            # Kiểm tra extreme price (giả lập)
            price = market_data.get('price', 0)
            if price and (price < 1000 or price > 200000):
                conditions['extreme_price'] = True
            
            return conditions
        except Exception as e:
            logger.error(f"Error checking market conditions: {e}")
            return {'safe_to_trade': True}
    
    def calculate_stop_loss_distance(self, entry_price: float, action: str, 
                                   atr: float = None) -> float:
        """Tính khoảng cách Stop Loss"""
        try:
            if atr:
                # Sử dụng ATR nếu có
                sl_distance = atr * 1.5
            else:
                # Mặc định 0.5%
                sl_distance = entry_price * 0.005
            
            return sl_distance
        except Exception as e:
            logger.error(f"Error calculating stop loss distance: {e}")
            return entry_price * 0.005
    
    def calculate_take_profit_distance(self, entry_price: float, action: str, 
                                      risk_reward_ratio: float = 2.0) -> float:
        """Tính khoảng cách Take Profit dựa trên risk/reward ratio"""
        try:
            sl_distance = self.calculate_stop_loss_distance(entry_price, action)
            tp_distance = sl_distance * risk_reward_ratio
            return tp_distance
        except Exception as e:
            logger.error(f"Error calculating take profit distance: {e}")
            return entry_price * 0.01
    
    def log_risk_event(self, event_type: str, details: Dict):
        """Ghi log sự kiện rủi ro"""
        try:
            event = {
                'type': event_type,
                'details': details,
                'timestamp': datetime.now().isoformat()
            }
            self.risk_events.append(event)
            logger.info(f"Risk event logged: {event_type}")
        except Exception as e:
            logger.error(f"Error logging risk event: {e}")
    
    def get_risk_summary(self) -> str:
        """Lấy tóm tắt rủi ro"""
        try:
            summary = "⚠️ *Risk Management Summary*\n\n"
            summary += f"📊 *Active Positions:* {len(self.active_positions)}/{MAX_POSITIONS}\n"
            summary += f"💰 *Daily PnL:* {self.daily_pnl:.2%}\n"
            summary += f"🚫 *Daily Loss Limit:* {self.daily_loss_limit:.1%}\n"
            summary += f"⚡ *Risk per Trade:* {MAX_RISK_PER_TRADE:.1%}\n\n"
            
            if self.risk_events:
                summary += "📋 *Recent Risk Events:*\n"
                for event in self.risk_events[-5:]:
                    summary += f"• {event['type']} - {event['timestamp']}\n"
            
            return summary
        except Exception as e:
            logger.error(f"Error getting risk summary: {e}")
            return "❌ Không thể lấy tóm tắt rủi ro"
    
    def reset_daily_pnl(self):
        """Reset daily PnL"""
        self.daily_pnl = 0
        logger.info("Daily PnL reset")
    
    def add_position(self, symbol: str, position: Dict):
        """Thêm vị trí active"""
        self.active_positions[symbol] = position
        logger.info(f"Position added: {symbol}")
    
    def remove_position(self, symbol: str):
        """Xóa vị trí active"""
        if symbol in self.active_positions:
            del self.active_positions[symbol]
            logger.info(f"Position removed: {symbol}")


# Singleton instance
risk_manager = RiskManager()
