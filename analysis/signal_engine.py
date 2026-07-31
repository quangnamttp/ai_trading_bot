"""
Module Signal Engine cho AI Trading Signal Bot
Quản lý việc tạo và gửi tín hiệu giao dịch
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
from core.config import SYMBOLS, AI_SCORE_THRESHOLD, SIGNAL_COOLDOWN_MINUTES, MAX_SIGNALS_PER_HOUR
from core.database import db

logger = logging.getLogger(__name__)


class SignalEngine:
    """Quản lý tạo và gửi tín hiệu giao dịch"""
    
    def __init__(self):
        self.last_signal_time = {}
        self.signals_sent_this_hour = 0
        self.hour_start_time = datetime.now()
    
    async def calculate_entry_range(self, price: float, action: str, symbol: str = None) -> str:
        """Tính range entry dựa trên technical levels"""
        try:
            # Default entry range around current price
            entry_low = price * 0.9995  # 0.05% below current price
            entry_high = price * 1.0005  # 0.05% above current price

            # Try to get technical levels if symbol is provided
            if symbol:
                try:
                    from ..data.market_data import market_data_engine
                    symbol_data = await market_data_engine.get_symbol_data(symbol)
                    if symbol_data:
                        indicators = symbol_data.get('indicators', {})
                        current_price = price

                        # For LONG: Look for support levels below current price
                        if action == 'LONG':
                            # Check if near support (EMA levels, recent lows)
                            ema_20 = indicators.get('ema_20')
                            ema_50 = indicators.get('ema_50')
                            recent_low = indicators.get('recent_low')

                            # Use EMA as support if close enough (within 0.5%)
                            if ema_20 and abs(current_price - ema_20) / current_price < 0.005:
                                entry_low = ema_20 * 0.9995
                                entry_high = ema_20 * 1.0005
                                logger.info(f"Entry based on EMA20 support for {symbol}")
                            elif ema_50 and abs(current_price - ema_50) / current_price < 0.005:
                                entry_low = ema_50 * 0.9995
                                entry_high = ema_50 * 1.0005
                                logger.info(f"Entry based on EMA50 support for {symbol}")
                            elif recent_low and abs(current_price - recent_low) / current_price < 0.005:
                                entry_low = recent_low * 0.9995
                                entry_high = recent_low * 1.0005
                                logger.info(f"Entry based on recent low support for {symbol}")

                        # For SHORT: Look for resistance levels above current price
                        else:
                            # Check if near resistance (EMA levels, recent highs)
                            ema_20 = indicators.get('ema_20')
                            ema_50 = indicators.get('ema_50')
                            recent_high = indicators.get('recent_high')

                            # Use EMA as resistance if close enough (within 0.5%)
                            if ema_20 and abs(current_price - ema_20) / current_price < 0.005:
                                entry_low = ema_20 * 0.9995
                                entry_high = ema_20 * 1.0005
                                logger.info(f"Entry based on EMA20 resistance for {symbol}")
                            elif ema_50 and abs(current_price - ema_50) / current_price < 0.005:
                                entry_low = ema_50 * 0.9995
                                entry_high = ema_50 * 1.0005
                                logger.info(f"Entry based on EMA50 resistance for {symbol}")
                            elif recent_high and abs(current_price - recent_high) / current_price < 0.005:
                                entry_low = recent_high * 0.9995
                                entry_high = recent_high * 1.0005
                                logger.info(f"Entry based on recent high resistance for {symbol}")
                except Exception as e:
                    logger.error(f"Error getting technical levels for entry: {e}")
                    # Fall back to default entry range

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
    
    def check_signal_lock(self, symbol: str, action: str, current_price: float) -> bool:
        """Kiểm tra xem có tín hiệu active cùng direction không và kiểm tra stable entry"""
        try:
            active_signal = db.get_active_signal(symbol)
            if not active_signal:
                logger.debug(f"No active signal for {symbol}. Signal lock check passed.")
                return True  # No active signal, can create new one

            # If active signal has same direction, don't create new one
            if active_signal['signal_type'] == action:
                logger.info(f"Signal lock active: {action} signal already exists for {symbol}. Entry locked at {active_signal['entry_price']}. Skipping new signal.")
                return False

            # If opposite direction, allow (market structure reversed)
            logger.info(f"Market structure reversal detected for {symbol}: {active_signal['signal_type']} -> {action}. Allowing new signal.")
            return True
        except Exception as e:
            logger.error(f"Error checking signal lock for {symbol}: {e}")
            return True  # On error, allow signal creation

    def check_entry_validity(self, symbol: str, current_price: float) -> bool:
        """Kiểm tra xem Entry vẫn còn hợp lệ (chasing price prevention)"""
        try:
            active_signal = db.get_active_signal(symbol)
            if not active_signal:
                return True  # No active signal, entry is valid

            # Parse entry range
            entry_price_str = active_signal['entry_price']
            try:
                if '-' in entry_price_str:
                    entry_low, entry_high = map(float, entry_price_str.split(' - '))
                else:
                    entry_low = entry_high = float(entry_price_str)
            except:
                return True  # Can't parse, allow

            # Calculate distance from current price to entry
            distance_percent = abs(current_price - entry_low) / current_price * 100

            # If price moved more than 1% away from entry, expire signal
            if distance_percent > 1.0:
                logger.info(f"Price moved {distance_percent:.2f}% from entry for {symbol}. Expiring signal.")
                db.update_signal_status(active_signal['id'], 'expired')
                return False

            # Entry still valid
            return True
        except Exception as e:
            logger.error(f"Error checking entry validity: {e}")
            return True  # On error, allow

    def check_entry_practicality(self, entry_range: str, current_price: float) -> bool:
        """Kiểm tra xem Entry có thực tế để execution không"""
        try:
            # Parse entry range
            if '-' in entry_range:
                entry_low, entry_high = map(float, entry_range.split(' - '))
            else:
                entry_low = entry_high = float(entry_range)

            # Calculate distance from current price to entry
            distance_percent = abs(current_price - entry_low) / current_price * 100

            # Entry should be within 0.5% of current price for practical execution
            if distance_percent > 0.5:
                logger.warning(f"Entry too far from current price: {distance_percent:.2f}% (max allowed: 0.5%). Rejecting signal.")
                return False

            logger.debug(f"Entry practicality check passed: {distance_percent:.2f}% from current price")
            return True
        except Exception as e:
            logger.error(f"Error checking entry practicality: {e}")
            return True  # On error, allow

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
    
    async def format_signal_message(self, analysis: Dict) -> Optional[str]:
        """Định dạng tin nhắn tín hiệu - simplified compact format"""
        try:
            from core.config import clean_symbol

            symbol = analysis.get('symbol')
            action = analysis.get('action')
            confidence = analysis.get('confidence', 0)
            price = analysis.get('price', 0)
            trend = analysis.get('trend', 'Neutral')

            if action == 'LONG':
                emoji = "🟢"
            elif action == 'SHORT':
                emoji = "🔴"
            else:
                return None

            # Clean symbol for user-facing display
            display_symbol = clean_symbol(symbol)

            # Tính levels
            entry_range = await self.calculate_entry_range(price, action, symbol)
            take_profits = self.calculate_take_profit(price, action)
            stop_loss = self.calculate_stop_loss(price, action)

            # Format message - simplified compact format
            message = f"{emoji} {display_symbol} | {action}\n"
            message += f"📍 Entry: {entry_range}\n"
            message += f"🎯 TP: {take_profits['TP1']:.2f}\n"
            message += f"🛑 SL: {stop_loss:.2f}\n"
            message += f"💎 Confidence: {int(confidence * 100)}%\n"
            message += f"📈 Trend: {trend}\n"
            message += f"⏰ {datetime.now().strftime('%H:%M')}"

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

            # Kiểm tra signal lock (không tạo cùng direction)
            if not self.check_signal_lock(symbol, action, price):
                logger.info(f"Signal lock active for {symbol} {action}")
                return None

            # Kiểm tra entry validity (chasing price prevention)
            if not self.check_entry_validity(symbol, price):
                logger.info(f"Entry invalid for {symbol} due to price movement")
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
            entry_range = await self.calculate_entry_range(price, action, symbol)
            take_profits = self.calculate_take_profit(price, action)
            stop_loss = self.calculate_stop_loss(price, action)

            # Kiểm tra entry practicality (không quá xa current price)
            if not self.check_entry_practicality(entry_range, price):
                logger.info(f"Entry not practical for {symbol}. Rejecting signal.")
                return None

            # Format take profit string
            tp_string = f"TP1: {take_profits['TP1']:.2f}, TP2: {take_profits['TP2']:.2f}, TP3: {take_profits['TP3']:.2f}"

            # Generate chart
            chart_path = None
            try:
                from analysis.chart_generator import chart_generator
                chart_path = await chart_generator.generate_signal_chart(
                    symbol=symbol,
                    signal_type=action,
                    entry_price=price,
                    tp1=take_profits['TP1'],
                    tp2=take_profits['TP2'],
                    tp3=take_profits['TP3'],
                    stop_loss=stop_loss,
                    ai_score=ai_score,
                    timeframe='1h'
                )
                if chart_path:
                    logger.info(f"Chart generated for {symbol}: {chart_path}")
            except Exception as e:
                logger.error(f"Error generating chart: {e}")

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
            message = await self.format_signal_message(analysis)

            return {
                'signal_id': signal_id,
                'message': message,
                'symbol': symbol,
                'action': action,
                'ai_score': ai_score,
                'chart_path': chart_path
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
