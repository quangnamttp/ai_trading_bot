"""
Module Signal Engine cho AI Trading Signal Bot
Quản lý việc tạo và gửi tín hiệu giao dịch
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
from ..core.config import SYMBOLS, AI_SCORE_THRESHOLD, SIGNAL_COOLDOWN_MINUTES, MAX_SIGNALS_PER_HOUR
from ..core.database import db

logger = logging.getLogger(__name__)


class SignalEngine:
    """Quản lý tạo và gửi tín hiệu giao dịch"""
    
    def __init__(self):
        self.last_signal_time = {}
        self.signals_sent_this_hour = 0
        self.hour_start_time = datetime.now()
    
    def calculate_entry_range(self, price: float, action: str) -> str:
        """Tính range entry"""
        try:
            if action == 'LONG':
                entry_low = price * 0.9995  # 0.05% below current price
                entry_high = price * 1.0005  # 0.05% above current price
            else:  # SHORT
                entry_low = price * 0.9995
                entry_high = price * 1.0005
            
            return f"{entry_low:.2f} - {entry_high:.2f}"
        except Exception as e:
            logger.error(f"Error calculating entry range: {e}")
            return f"{price:.2f}"
    
    def calculate_take_profit(self, price: float, action: str) -> Dict:
        """Tính Take Profit levels"""
        try:
            if action == 'LONG':
                tp1 = price * 1.01  # +1%
                tp2 = price * 1.02  # +2%
                tp3 = price * 1.03  # +3%
            else:  # SHORT
                tp1 = price * 0.99  # -1%
                tp2 = price * 0.98  # -2%
                tp3 = price * 0.97  # -3%
            
            return {
                'TP1': tp1,
                'TP2': tp2,
                'TP3': tp3
            }
        except Exception as e:
            logger.error(f"Error calculating take profit: {e}")
            return {'TP1': price, 'TP2': price, 'TP3': price}
    
    def calculate_stop_loss(self, price: float, action: str) -> float:
        """Tính Stop Loss"""
        try:
            if action == 'LONG':
                sl = price * 0.995  # -0.5%
            else:  # SHORT
                sl = price * 1.005  # +0.5%
            
            return sl
        except Exception as e:
            logger.error(f"Error calculating stop loss: {e}")
            return price
    
    def check_cooldown(self, symbol: str) -> bool:
        """Kiểm tra xem có thể gửi tín hiệu không (cooldown)"""
        try:
            last_signal = db.get_last_signal_time(symbol)
            
            if not last_signal:
                return True
            
            time_since_last = datetime.now() - last_signal
            cooldown_period = timedelta(minutes=SIGNAL_COOLDOWN_MINUTES)
            
            if time_since_last < cooldown_period:
                logger.info(f"Cooldown active for {symbol}. Last signal {time_since_last.seconds} seconds ago.")
                return False
            
            return True
        except Exception as e:
            logger.error(f"Error checking cooldown: {e}")
            return False
    
    def check_rate_limit(self) -> bool:
        """Kiểm tra rate limit (số tín hiệu mỗi giờ)"""
        try:
            # Reset counter mỗi giờ
            if datetime.now() - self.hour_start_time > timedelta(hours=1):
                self.signals_sent_this_hour = 0
                self.hour_start_time = datetime.now()
            
            # Kiểm tra số tín hiệu trong giờ từ database
            signals_last_hour = db.count_signals_last_hour()
            
            if signals_last_hour >= MAX_SIGNALS_PER_HOUR:
                logger.info(f"Rate limit reached. {signals_last_hour} signals sent in last hour.")
                return False
            
            return True
        except Exception as e:
            logger.error(f"Error checking rate limit: {e}")
            return False
    
    def format_signal_message(self, analysis: Dict) -> str:
        """Định dạng tin nhắn tín hiệu"""
        try:
            symbol = analysis.get('symbol')
            action = analysis.get('action')
            ai_score = analysis.get('ai_score', 0)
            confidence = analysis.get('confidence', 0)
            price = analysis.get('price', 0)
            reasons = analysis.get('reasons', [])
            
            if action == 'LONG':
                emoji = "🟢"
            elif action == 'SHORT':
                emoji = "🔴"
            else:
                return None
            
            # Tính levels
            entry_range = self.calculate_entry_range(price, action)
            take_profits = self.calculate_take_profit(price, action)
            stop_loss = self.calculate_stop_loss(price, action)
            
            # Format message
            message = f"{emoji} {action} {symbol}\n\n"
            message += f"🎯 Độ tin cậy: {int(confidence * 100)}%\n\n"
            
            message += f"📍 Entry:\n{entry_range}\n\n"
            
            message += f"🎯 Take Profit:\n"
            message += f"TP1: {take_profits['TP1']:.2f}\n"
            message += f"TP2: {take_profits['TP2']:.2f}\n"
            message += f"TP3: {take_profits['TP3']:.2f}\n\n"
            
            message += f"🛑 Stop Loss:\n{stop_loss:.2f}\n\n"
            
            message += f"📋 Lý do:\n"
            for reason in reasons[:8]:
                message += f"• {reason}\n"
            
            message += f"\n🤖 AI Score: {ai_score}/100\n"
            message += f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            message += f"📊 Sàn tham khảo: MEXC Futures\n\n"
            message += f"⚠️ *Bot chỉ phân tích, không tự động giao dịch. Bạn tự quyết định vào lệnh thủ công.*"
            
            return message
        except Exception as e:
            logger.error(f"Error formatting signal message: {e}")
            return None
    
    async def create_signal(self, analysis: Dict) -> Optional[Dict]:
        """Tạo tín hiệu từ phân tích AI"""
        try:
            symbol = analysis.get('symbol')
            action = analysis.get('action')
            ai_score = analysis.get('ai_score', 0)
            confidence = analysis.get('confidence', 0)
            price = analysis.get('price', 0)
            reasons = analysis.get('reasons', [])
            
            # Chỉ tạo tín hiệu nếu AI Score đủ cao
            if ai_score < AI_SCORE_THRESHOLD:
                logger.info(f"AI Score {ai_score} below threshold {AI_SCORE_THRESHOLD}. No signal created.")
                return None
            
            # Kiểm tra cooldown
            if not self.check_cooldown(symbol):
                logger.info(f"Cooldown active for {symbol}")
                return None
            
            # Kiểm tra rate limit
            if not self.check_rate_limit():
                logger.info("Rate limit reached")
                return None
            
            # Tính toán levels
            entry_range = self.calculate_entry_range(price, action)
            take_profits = self.calculate_take_profit(price, action)
            stop_loss = self.calculate_stop_loss(price, action)
            
            # Format take profit string
            tp_string = f"TP1: {take_profits['TP1']:.2f}, TP2: {take_profits['TP2']:.2f}, TP3: {take_profits['TP3']:.2f}"
            
            # Lưu vào database
            signal_id = db.save_signal(
                symbol=symbol,
                signal_type=action,
                entry_price=entry_range,
                take_profit=tp_string,
                stop_loss=str(stop_loss),
                confidence=confidence,
                ai_score=ai_score,
                reasons=reasons
            )
            
            if signal_id:
                self.signals_sent_this_hour += 1
                logger.info(f"Signal created: {action} {symbol} (ID: {signal_id})")
            
            # Format message
            message = self.format_signal_message(analysis)
            
            return {
                'signal_id': signal_id,
                'message': message,
                'symbol': symbol,
                'action': action,
                'ai_score': ai_score
            }
        except Exception as e:
            logger.error(f"Error creating signal: {e}")
            return None
    
    async def analyze_symbol(self, symbol: str) -> Optional[str]:
        """Phân tích symbol và trả về kết quả"""
        try:
            # Import dependencies để avoid circular import
            from ..data.market_data import market_data_engine
            from ..data.smart_money import smart_money_tracker
            from ..analysis.ai_engine import ai_engine
            from ..data.news_engine import news_engine
            
            # Phân tích AI
            analysis = await ai_engine.analyze(symbol, market_data_engine, smart_money_tracker, news_engine)
            
            # Lưu AI log
            db.save_ai_log(
                symbol=symbol,
                analysis_data=analysis,
                decision=analysis.get('action'),
                ai_score=analysis.get('ai_score'),
                confidence=analysis.get('confidence')
            )
            
            # Nếu là tín hiệu BUY/SELL với AI Score cao, tạo signal
            if analysis.get('action') in ['LONG', 'SHORT']:
                signal = await self.create_signal(analysis)
                if signal:
                    return signal['message']
            
            # Nếu không phải tín hiệu, trả về analysis summary
            from ..analysis.ai_engine import ai_engine
            return ai_engine.get_analysis_summary(symbol)
        except Exception as e:
            logger.error(f"Error analyzing symbol {symbol}: {e}")
            return f"❌ Lỗi phân tích {symbol}: {str(e)}"
    
    async def scan_all_symbols(self) -> list:
        """Quét tất cả symbols"""
        try:
            signals = []
            
            for symbol in SYMBOLS:
                try:
                    result = await self.analyze_symbol(symbol)
                    if result and ("LONG" in result or "SHORT" in result):
                        signals.append(result)
                except Exception as e:
                    logger.error(f"Error scanning {symbol}: {e}")
            
            return signals
        except Exception as e:
            logger.error(f"Error scanning all symbols: {e}")
            return []
    
    def get_recent_signals(self, limit: int = 5) -> list:
        """Lấy các tín hiệu gần đây"""
        try:
            return db.get_recent_signals(limit=limit)
        except Exception as e:
            logger.error(f"Error getting recent signals: {e}")
            return []


# Singleton instance
signal_engine = SignalEngine()
