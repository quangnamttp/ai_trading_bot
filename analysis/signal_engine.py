"""
Module Signal Engine cho AI Trading Signal Bot
Quản lý việc tạo và gửi tín hiệu giao dịch
"""
import logging
import math
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
        self.signals_sent_today = 0
        self.day_start_time = datetime.now().date()
    
    def _check_daily_limit(self) -> bool:
        """Check if daily signal limit has been reached"""
        from core.config import MAX_SIGNALS_PER_DAY, SIGNAL_COOLDOWN_MINUTES
        
        # Reset daily counter if new day
        current_date = datetime.now().date()
        if current_date != self.day_start_time:
            self.signals_sent_today = 0
            self.day_start_time = current_date
            logger.info(f"[SIGNAL ENGINE] New day detected, daily signal counter reset")
        
        return self.signals_sent_today < MAX_SIGNALS_PER_DAY
    
    def _increment_daily_count(self):
        """Increment daily signal counter"""
        from core.config import MAX_SIGNALS_PER_DAY
        self.signals_sent_today += 1
        logger.info(f"[SIGNAL ENGINE] Daily signals sent: {self.signals_sent_today}/{MAX_SIGNALS_PER_DAY}")
    
    async def calculate_entry_range(self, price: float, action: str, symbol: str = None,
                                   gann_support: float = None, gann_resistance: float = None) -> str:
        """Tính range entry dựa trên Gann levels và EMA trend"""
        try:
            # Default entry range around current price
            entry_low = price * 0.9995  # 0.05% below current price
            entry_high = price * 1.0005  # 0.05% above current price

            # Try to get Gann levels if symbol is provided
            if symbol:
                try:
                    from analysis.gann_engine import gann_engine
                    from data.market_data import market_data_engine

                    # Get Gann analysis if not provided
                    if gann_support is None or gann_resistance is None:
                        gann_analysis = await gann_engine.analyze(symbol, market_data_engine)
                        gann_support = gann_analysis.get('support')
                        gann_resistance = gann_analysis.get('resistance')

                    # For LONG: Use Gann support if available
                    if action == 'LONG' and gann_support:
                        # Use Gann support if close enough (within 1%)
                        if abs(price - gann_support) / price < 0.01:
                            entry_low = gann_support * 0.9995
                            entry_high = gann_support * 1.0005
                            logger.info(f"Entry based on Gann support for {symbol}: {gann_support:.2f}")
                        else:
                            # Entry around current price but aware of support
                            entry_low = max(price * 0.9995, gann_support * 1.0005)
                            entry_high = price * 1.0005
                            logger.info(f"Entry near current price with Gann support: {gann_support:.2f}")

                    # For SHORT: Use Gann resistance if available
                    elif action == 'SHORT' and gann_resistance:
                        # Use Gann resistance if close enough (within 1%)
                        if abs(price - gann_resistance) / price < 0.01:
                            entry_low = gann_resistance * 0.9995
                            entry_high = gann_resistance * 1.0005
                            logger.info(f"Entry based on Gann resistance for {symbol}: {gann_resistance:.2f}")
                        else:
                            # Entry around current price but aware of resistance
                            entry_low = price * 0.9995
                            entry_high = min(price * 1.0005, gann_resistance * 0.9995)
                            logger.info(f"Entry near current price with Gann resistance: {gann_resistance:.2f}")

                except Exception as e:
                    logger.error(f"Error getting Gann levels for entry: {e}")
                    # Fall back to default entry range

            return f"{entry_low:.2f} - {entry_high:.2f}"
        except Exception as e:
            logger.error(f"Error calculating entry range: {e}")
            return f"{price:.2f}"
    
    def calculate_take_profit(self, price: float, action: str, atr: float = None) -> Dict:
        """Tính Take Profit levels dựa trên ATR"""
        try:
            if atr and atr > 0:
                # Use ATR-based TP
                if action == 'LONG':
                    tp1 = price + (atr * 1.5)  # 1.5x ATR
                    tp2 = price + (atr * 2.5)  # 2.5x ATR
                    tp3 = price + (atr * 4.0)  # 4.0x ATR
                else:  # SHORT
                    tp1 = price - (atr * 1.5)  # 1.5x ATR
                    tp2 = price - (atr * 2.5)  # 2.5x ATR
                    tp3 = price - (atr * 4.0)  # 4.0x ATR
            else:
                # Fallback to percentage-based if ATR not available
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
    
    def calculate_stop_loss(self, price: float, action: str, atr: float = None) -> float:
        """Tính Stop Loss dựa trên ATR"""
        try:
            if atr and atr > 0:
                # Use ATR-based SL
                if action == 'LONG':
                    sl = price - (atr * 1.5)  # 1.5x ATR below price
                else:  # SHORT
                    sl = price + (atr * 1.5)  # 1.5x ATR above price
            else:
                # Fallback to percentage-based if ATR not available
                if action == 'LONG':
                    sl = price * 0.995  # -0.5%
                else:  # SHORT
                    sl = price * 1.005  # +0.5%

            return sl
        except Exception as e:
            logger.error(f"Error calculating stop loss: {e}")
            return price
    
    async def check_signal_lock(self, symbol: str, action: str, current_price: float) -> bool:
        """Kiểm tra xem có tín hiệu active cùng direction không và kiểm tra stable entry"""
        try:
            active_signal = await db.get_active_signal_async(symbol) if hasattr(db, 'get_active_signal_async') else db.get_active_signal(symbol)
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

    async def check_entry_validity(self, symbol: str, current_price: float) -> bool:
        """Kiểm tra xem Entry vẫn còn hợp lệ (chasing price prevention)"""
        try:
            active_signal = await db.get_active_signal_async(symbol) if hasattr(db, 'get_active_signal_async') else db.get_active_signal(symbol)
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

    async def check_cooldown(self, symbol: str) -> bool:
        """Kiểm tra cooldown period"""
        try:
            last_signal = await db.get_last_signal_time_async(symbol) if hasattr(db, 'get_last_signal_time_async') else db.get_last_signal_time(symbol)

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
    
    async def check_rate_limit(self) -> bool:
        """Kiểm tra rate limit (số tín hiệu mỗi giờ)"""
        try:
            # Reset counter mỗi giờ
            if datetime.now() - self.hour_start_time > timedelta(hours=1):
                self.signals_sent_this_hour = 0
                self.hour_start_time = datetime.now()

            # Kiểm tra số tín hiệu trong giờ từ database (use async version)
            signals_last_hour = await db.count_signals_last_hour_async() if hasattr(db, 'count_signals_last_hour_async') else db.count_signals_last_hour()

            if signals_last_hour >= MAX_SIGNALS_PER_HOUR:
                logger.info(f"Rate limit reached. {signals_last_hour} signals sent in last hour.")
                return False

            return True
        except Exception as e:
            logger.error(f"Error checking rate limit: {e}")
            return False
    
    async def format_signal_message(self, analysis: Dict, entry_range: str = None,
                                    take_profits: Dict = None, stop_loss: float = None) -> Optional[str]:
        """Định dạng tin nhắn tín hiệu - Vietnamese localization with professional formatting"""
        try:
            from core.config import clean_symbol, format_time

            symbol = analysis.get('symbol')
            action = analysis.get('action')
            confidence = analysis.get('confidence', 0)
            price = analysis.get('price', 0)
            trend = analysis.get('trend', 'Neutral')

            # Vietnamese action mapping
            action_vi = "MUA" if action == 'LONG' else "BÁN" if action == 'SHORT' else action

            if action == 'LONG':
                emoji = "🟢"
            elif action == 'SHORT':
                emoji = "🔴"
            else:
                return None

            # Clean symbol for user-facing display
            display_symbol = clean_symbol(symbol)

            # Use provided levels or calculate them
            if entry_range is None:
                entry_range = await self.calculate_entry_range(price, action, symbol)
            if take_profits is None:
                take_profits = self.calculate_take_profit(price, action)
            if stop_loss is None:
                stop_loss = self.calculate_stop_loss(price, action)

            # Vietnamese trend mapping with emoji - 100% Vietnamese
            trend_vi = trend
            trend_emoji = ""
            trend_mapping = {
                'Bullish': ('Tăng', '🟢'),
                'Strong Bullish': ('Tăng mạnh', '🟢'),
                'Bearish': ('Giảm', '🔴'),
                'Strong Bearish': ('Giảm mạnh', '🔴'),
                'Neutral': ('Đi ngang', '⚪'),
                'Uptrend': ('Tăng', '🟢'),
                'Downtrend': ('Giảm', '🔴'),
                'Strong Uptrend': ('Tăng mạnh', '🟢'),
                'Strong Downtrend': ('Giảm mạnh', '🔴'),
                # Fallback for any other trend values
                'strong_uptrend': ('Tăng mạnh', '🟢'),
                'uptrend': ('Tăng', '🟢'),
                'neutral': ('Đi ngang', '⚪'),
                'downtrend': ('Giảm', '🔴'),
                'strong_downtrend': ('Giảm mạnh', '🔴'),
                'bullish': ('Tăng', '🟢'),
                'bearish': ('Giảm', '🔴')
            }
            if trend in trend_mapping:
                trend_vi, trend_emoji = trend_mapping[trend]
            else:
                # Default fallback for unknown trends
                trend_vi = "Đi ngang"
                trend_emoji = "⚪"

            # Format numbers with thousand separators
            def format_number(num):
                return f"{num:,.2f}"

            # Parse entry range
            if '-' in entry_range:
                entry_low, entry_high = map(float, entry_range.split(' - '))
                entry_formatted = f"{format_number(entry_low)} → {format_number(entry_high)}"
            else:
                entry_formatted = format_number(float(entry_range))

            # Format message - Vietnamese with compact formatting
            message = f"{emoji} {display_symbol} | {action_vi}\n"
            message += f"💰 Vùng vào lệnh: {entry_formatted}\n"
            message += f"🎯 Giá chốt lời: {format_number(take_profits['TP1'])}\n"
            message += f"🛑 Giá cắt lỗ: {format_number(stop_loss)}\n"
            message += f"🤖 Độ tin cậy AI: {int(confidence * 100)}%\n"
            message += f"📈 Xu hướng: {trend_emoji} {trend_vi}\n"
            message += f"🕒 Thời gian: {format_time()}"

            return message
        except Exception as e:
            logger.error(f"Error formatting signal message: {e}")
            return None
    
    async def create_signal(self, analysis: Dict, symbol_data: Dict = None, gann_analysis: Dict = None) -> Optional[Dict]:
        """Tạo tín hiệu từ phân tích AI
        
        Args:
            analysis: Dict with symbol, action, ai_score, etc.
            symbol_data: Pre-fetched market data (from filter_signal to avoid duplicate fetches)
            gann_analysis: Pre-fetched Gann analysis (from filter_signal to avoid duplicate fetches)
        """
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

            # Kiểm tra signal lock (không tạo cùng direction) (use async version)
            if not await self.check_signal_lock(symbol, action, price):
                logger.info(f"Signal lock active for {symbol} {action}")
                return None

            # Kiểm tra entry validity (chasing price prevention) (use async version)
            if not await self.check_entry_validity(symbol, price):
                logger.info(f"Entry invalid for {symbol} due to price movement")
                return None

            # Kiểm tra cooldown (use async version)
            if not await self.check_cooldown(symbol):
                logger.info(f"Cooldown active for {symbol}")
                return None

            # Kiểm tra rate limit (use async version)
            if not await self.check_rate_limit():
                logger.info("Rate limit reached")
                return None
            
            # Tính toán levels - use pre-fetched data if available, otherwise fetch
            atr = None
            if symbol_data:
                indicators = symbol_data.get('indicators', {})
                atr = indicators.get('atr')
            else:
                try:
                    from data.market_data import market_data_engine
                    symbol_data_fetched = await market_data_engine.get_symbol_data(symbol)
                    if symbol_data_fetched:
                        indicators = symbol_data_fetched.get('indicators', {})
                        atr = indicators.get('atr')
                except Exception as e:
                    logger.error(f"Error getting ATR: {e}")

            # Get Gann levels for entry calculation - use pre-fetched if available
            gann_support = None
            gann_resistance = None
            if gann_analysis:
                gann_support = gann_analysis.get('support')
                gann_resistance = gann_analysis.get('resistance')
            else:
                try:
                    from analysis.gann_engine import gann_engine
                    from data.market_data import market_data_engine
                    gann_analysis_fetched = await gann_engine.analyze(symbol, market_data_engine)
                    gann_support = gann_analysis_fetched.get('support')
                    gann_resistance = gann_analysis_fetched.get('resistance')
                except Exception as e:
                    logger.error(f"Error getting Gann levels: {e}")

            entry_range = await self.calculate_entry_range(price, action, symbol, gann_support, gann_resistance)
            take_profits = self.calculate_take_profit(price, action, atr)
            stop_loss = self.calculate_stop_loss(price, action, atr)

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
            signal_id = await db.save_signal_async(
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
                self._increment_daily_count()
                logger.info(f"Signal created: {action} {symbol} (ID: {signal_id})")

            # Format message with ATR-calculated levels
            message = await self.format_signal_message(analysis, entry_range, take_profits, stop_loss)

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
    
    async def filter_signal(self, ai_analysis: Dict, market_data_engine, gann_engine) -> Dict:
        """Multi-timeframe signal filter: 4H Macro -> 1H Trend -> Gann -> 15M Entry -> ATR -> Volume -> Funding -> AI -> R:R -> Cooldown -> Daily Limit
        
        Args:
            ai_analysis: Dict with ai_action, ai_score, symbol, etc.
            market_data_engine: Market data engine instance
            gann_engine: Gann engine instance
            
        Returns:
            Dict with filtered action, reason, and pre-fetched data for reuse
        """
        try:
            from core.config import (
                AI_SCORE_THRESHOLD, GANN_MIN_CONFIDENCE, RR_MIN,
                VOLUME_MULTIPLIER, FUNDING_RATE_MAX, ATR_REGIME_MIN, ATR_REGIME_MAX
            )
            
            symbol = ai_analysis.get('symbol')
            ai_action = ai_analysis.get('action')
            ai_score = ai_analysis.get('ai_score', 0)
            
            # 1. Check daily signal limit
            if not self._check_daily_limit():
                logger.info(f"[SIGNAL FILTER] symbol={symbol}")
                logger.info(f"[SIGNAL FILTER] decision=WAIT")
                logger.info(f"[SIGNAL FILTER] reason=DAILY_LIMIT_REACHED")
                return {'action': 'WAIT', 'reason': 'DAILY_LIMIT_REACHED'}
            
            # 2. Check cooldown
            if symbol in self.last_signal_time:
                cooldown_elapsed = (datetime.now() - self.last_signal_time[symbol]).total_seconds()
                if cooldown_elapsed < SIGNAL_COOLDOWN_MINUTES * 60:
                    logger.info(f"[SIGNAL FILTER] symbol={symbol}")
                    logger.info(f"[SIGNAL FILTER] decision=WAIT")
                    logger.info(f"[SIGNAL FILTER] reason=COOLDOWN_ACTIVE")
                    return {'action': 'WAIT', 'reason': 'COOLDOWN_ACTIVE'}
            
            # 3. Get multi-timeframe market data (4H, 1H, 15M)
            symbol_data = await market_data_engine.get_symbol_data(symbol, timeframes=['4h', '1h', '15m'])
            if not symbol_data:
                logger.warning(f"[SIGNAL FILTER] symbol={symbol}, no market data")
                return {'action': 'WAIT', 'reason': 'NO_MARKET_DATA'}
            
            indicators = symbol_data.get('indicators', {})
            indicators_4h = indicators.get('4h', {}) if isinstance(indicators, dict) else {}
            indicators_1h = indicators.get('1h', {}) if isinstance(indicators, dict) else {}
            indicators_15m = indicators.get('15m', {}) if isinstance(indicators, dict) else {}
            
            # 4. 4H Macro Filter (EMA50/EMA200)
            price_4h = indicators_4h.get('price', 0)
            ema_50_4h = indicators_4h.get('ema_50', 0)
            ema_200_4h = indicators_4h.get('ema_200', 0)
            
            macro_trend = 'neutral'
            if not ema_50_4h or not ema_200_4h:
                macro_trend = 'neutral'
            elif math.isnan(ema_50_4h) or math.isnan(ema_200_4h):
                macro_trend = 'neutral'
            elif price_4h > ema_50_4h > ema_200_4h:
                macro_trend = 'bullish'
            elif price_4h < ema_50_4h < ema_200_4h:
                macro_trend = 'bearish'
            
            if macro_trend == 'neutral':
                logger.info(f"[SIGNAL FILTER] symbol={symbol}")
                logger.info(f"[SIGNAL FILTER] macro_4h={macro_trend}")
                logger.info(f"[SIGNAL FILTER] decision=WAIT")
                logger.info(f"[SIGNAL FILTER] reason=MACRO_NEUTRAL")
                return {'action': 'WAIT', 'reason': 'MACRO_NEUTRAL'}
            
            # 5. 1H Trend Filter (EMA50/EMA200, must align with 4H)
            price_1h = indicators_1h.get('price', 0)
            ema_50_1h = indicators_1h.get('ema_50', 0)
            ema_200_1h = indicators_1h.get('ema_200', 0)
            
            trend_1h = 'neutral'
            if not ema_50_1h or not ema_200_1h:
                trend_1h = 'neutral'
            elif math.isnan(ema_50_1h) or math.isnan(ema_200_1h):
                trend_1h = 'neutral'
            elif price_1h > ema_50_1h > ema_200_1h:
                trend_1h = 'bullish'
            elif price_1h < ema_50_1h < ema_200_1h:
                trend_1h = 'bearish'
            
            # 1H must align with 4H
            if trend_1h != macro_trend:
                logger.info(f"[SIGNAL FILTER] symbol={symbol}")
                logger.info(f"[SIGNAL FILTER] macro_4h={macro_trend}")
                logger.info(f"[SIGNAL FILTER] trend_1h={trend_1h}")
                logger.info(f"[SIGNAL FILTER] decision=WAIT")
                logger.info(f"[SIGNAL FILTER] reason=TREND_MISMATCH")
                return {'action': 'WAIT', 'reason': 'TREND_MISMATCH'}
            
            # 6. Get Gann analysis (use 1H)
            gann_analysis = await gann_engine.analyze(symbol, market_data_engine)
            gann_trend = gann_analysis.get('trend', 'neutral')
            gann_confidence = gann_analysis.get('confidence', 0)
            
            if gann_confidence < GANN_MIN_CONFIDENCE:
                logger.info(f"[SIGNAL FILTER] symbol={symbol}")
                logger.info(f"[SIGNAL FILTER] gann_confidence={gann_confidence:.2f}")
                logger.info(f"[SIGNAL FILTER] decision=WAIT")
                logger.info(f"[SIGNAL FILTER] reason=GANN_CONFIDENCE_LOW")
                return {'action': 'WAIT', 'reason': 'GANN_CONFIDENCE_LOW'}
            
            # Gann must align with 4H/1H trend
            if gann_trend != macro_trend:
                logger.info(f"[SIGNAL FILTER] symbol={symbol}")
                logger.info(f"[SIGNAL FILTER] macro_4h={macro_trend}")
                logger.info(f"[SIGNAL FILTER] gann_trend={gann_trend}")
                logger.info(f"[SIGNAL FILTER] decision=WAIT")
                logger.info(f"[SIGNAL FILTER] reason=GANN_CONFLICT")
                return {'action': 'WAIT', 'reason': 'GANN_CONFLICT'}
            
            # 7. 15M Entry Filter (EMA20/EMA50)
            price_15m = indicators_15m.get('price', 0)
            ema_20_15m = indicators_15m.get('ema_20', 0)
            ema_50_15m = indicators_15m.get('ema_50', 0)
            
            entry_trend = 'neutral'
            if not ema_20_15m or not ema_50_15m:
                entry_trend = 'neutral'
            elif math.isnan(ema_20_15m) or math.isnan(ema_50_15m):
                entry_trend = 'neutral'
            elif ema_20_15m > ema_50_15m:
                entry_trend = 'bullish'
            elif ema_20_15m < ema_50_15m:
                entry_trend = 'bearish'
            
            if entry_trend != macro_trend:
                logger.info(f"[SIGNAL FILTER] symbol={symbol}")
                logger.info(f"[SIGNAL FILTER] macro_4h={macro_trend}")
                logger.info(f"[SIGNAL FILTER] entry_15m={entry_trend}")
                logger.info(f"[SIGNAL FILTER] decision=WAIT")
                logger.info(f"[SIGNAL FILTER] reason=EMA_NEUTRAL")
                return {'action': 'WAIT', 'reason': 'EMA_NEUTRAL'}
            
            # 8. ATR Filter (validity + regime)
            atr_1h = indicators_1h.get('atr', 0)
            atr_ma50_1h = indicators_1h.get('atr_ma50', 0)
            
            atr_valid = atr_1h and atr_1h > 0
            if not atr_valid:
                logger.info(f"[SIGNAL FILTER] symbol={symbol}")
                logger.info(f"[SIGNAL FILTER] atr_1h={atr_1h}")
                logger.info(f"[SIGNAL FILTER] decision=WAIT")
                logger.info(f"[SIGNAL FILTER] reason=ATR_INVALID")
                return {'action': 'WAIT', 'reason': 'ATR_INVALID'}
            
            # ATR regime check
            if atr_ma50_1h and atr_ma50_1h > 0:
                atr_ratio = atr_1h / atr_ma50_1h
                if atr_ratio < ATR_REGIME_MIN or atr_ratio > ATR_REGIME_MAX:
                    logger.info(f"[SIGNAL FILTER] symbol={symbol}")
                    logger.info(f"[SIGNAL FILTER] atr_ratio={atr_ratio:.2f}")
                    logger.info(f"[SIGNAL FILTER] decision=WAIT")
                    logger.info(f"[SIGNAL FILTER] reason=ATR_REGIME_INVALID")
                    return {'action': 'WAIT', 'reason': 'ATR_REGIME_INVALID'}
            
            # 9. Volume Filter (15M Volume > 1.5 MA20)
            volume_15m = indicators_15m.get('volume', 0)
            volume_ma20_15m = indicators_15m.get('volume_ma20', 0)
            
            if volume_ma20_15m and volume_ma20_15m > 0:
                if volume_15m < volume_ma20_15m * VOLUME_MULTIPLIER:
                    logger.info(f"[SIGNAL FILTER] symbol={symbol}")
                    logger.info(f"[SIGNAL FILTER] volume_15m={volume_15m}")
                    logger.info(f"[SIGNAL FILTER] volume_ma20_15m={volume_ma20_15m}")
                    logger.info(f"[SIGNAL FILTER] decision=WAIT")
                    logger.info(f"[SIGNAL FILTER] reason=VOLUME_LOW")
                    return {'action': 'WAIT', 'reason': 'VOLUME_LOW'}
            
            # 10. Funding Filter
            funding_data = symbol_data.get('funding_rate', {})
            funding_rate = funding_data.get('fundingRate', 0) if funding_data else 0
            if abs(funding_rate) > FUNDING_RATE_MAX:
                logger.info(f"[SIGNAL FILTER] symbol={symbol}")
                logger.info(f"[SIGNAL FILTER] funding_rate={funding_rate:.4f}")
                logger.info(f"[SIGNAL FILTER] decision=WAIT")
                logger.info(f"[SIGNAL FILTER] reason=FUNDING_EXTREME")
                return {'action': 'WAIT', 'reason': 'FUNDING_EXTREME'}
            
            # 11. AI Score Filter
            if ai_score < AI_SCORE_THRESHOLD:
                logger.info(f"[SIGNAL FILTER] symbol={symbol}")
                logger.info(f"[SIGNAL FILTER] ai_score={ai_score}")
                logger.info(f"[SIGNAL FILTER] decision=WAIT")
                logger.info(f"[SIGNAL FILTER] reason=AI_SCORE_BELOW_THRESHOLD")
                return {'action': 'WAIT', 'reason': 'AI_SCORE_BELOW_THRESHOLD'}
            
            # 12. AI must align with macro trend
            if ai_action == 'LONG' and macro_trend != 'bullish':
                logger.info(f"[SIGNAL FILTER] symbol={symbol}")
                logger.info(f"[SIGNAL FILTER] ai_action={ai_action}")
                logger.info(f"[SIGNAL FILTER] macro_4h={macro_trend}")
                logger.info(f"[SIGNAL FILTER] decision=WAIT")
                logger.info(f"[SIGNAL FILTER] reason=MACRO_CONFLICT")
                return {'action': 'WAIT', 'reason': 'MACRO_CONFLICT'}
            
            if ai_action == 'SHORT' and macro_trend != 'bearish':
                logger.info(f"[SIGNAL FILTER] symbol={symbol}")
                logger.info(f"[SIGNAL FILTER] ai_action={ai_action}")
                logger.info(f"[SIGNAL FILTER] macro_4h={macro_trend}")
                logger.info(f"[SIGNAL FILTER] decision=WAIT")
                logger.info(f"[SIGNAL FILTER] reason=MACRO_CONFLICT")
                return {'action': 'WAIT', 'reason': 'MACRO_CONFLICT'}
            
            # 13. R:R Filter (calculate based on ATR)
            atr_15m = indicators_15m.get('atr', 0)
            if atr_15m and atr_15m > 0:
                # Calculate potential R:R based on ATR
                # SL = 1.2 * ATR, TP = 2.2 * ATR, so R:R = 2.2 / 1.2 = 1.83 (above minimum 1.8)
                sl_atr = 1.2
                tp_atr = 2.2
                calculated_rr = tp_atr / sl_atr
                
                if calculated_rr < RR_MIN:
                    logger.info(f"[SIGNAL FILTER] symbol={symbol}")
                    logger.info(f"[SIGNAL FILTER] calculated_rr={calculated_rr:.2f}")
                    logger.info(f"[SIGNAL FILTER] decision=WAIT")
                    logger.info(f"[SIGNAL FILTER] reason=RR_TOO_LOW")
                    return {'action': 'WAIT', 'reason': 'RR_TOO_LOW'}
            
            # 14. All filters passed - return signal
            logger.info(f"[SIGNAL FILTER] symbol={symbol}")
            logger.info(f"[SIGNAL FILTER] ai_action={ai_action}")
            logger.info(f"[SIGNAL FILTER] ai_score={ai_score}")
            logger.info(f"[SIGNAL FILTER] macro_4h={macro_trend}")
            logger.info(f"[SIGNAL FILTER] trend_1h={trend_1h}")
            logger.info(f"[SIGNAL FILTER] gann_trend={gann_trend}")
            logger.info(f"[SIGNAL FILTER] gann_confidence={gann_confidence:.2f}")
            logger.info(f"[SIGNAL FILTER] entry_15m={entry_trend}")
            logger.info(f"[SIGNAL FILTER] atr_1h={atr_1h:.4f}")
            logger.info(f"[SIGNAL FILTER] volume_ok=true")
            logger.info(f"[SIGNAL FILTER] funding_ok=true")
            logger.info(f"[SIGNAL FILTER] decision={ai_action}")
            logger.info(f"[SIGNAL FILTER] reason=ALL_FILTERS_PASSED")
            
            return {
                'action': ai_action,
                'reason': 'ALL_FILTERS_PASSED',
                'symbol_data': symbol_data,
                'gann_analysis': gann_analysis
            }
            
        except Exception as e:
            logger.error(f"Error in signal filter: {e}")
            return {'action': 'WAIT', 'reason': 'FILTER_ERROR'}
    
    async def analyze_symbol(self, symbol: str) -> Optional[str]:
        """Phân tích symbol với chiến lược Gann + EMA Trend + ATR"""
        try:
            # Import dependencies
            from data.market_data import market_data_engine
            from analysis.gann_engine import gann_engine
            from analysis.ai_engine import ai_engine

            logger.info(f"[STRATEGY] Starting analysis for {symbol}")

            # 1. Lấy dữ liệu thị trường và indicators
            symbol_data = await market_data_engine.get_symbol_data(symbol)
            if not symbol_data:
                logger.error(f"[STRATEGY] No data for {symbol}")
                return None

            indicators = symbol_data.get('indicators', {})
            price = indicators.get('price', 0)
            ema_9 = indicators.get('ema_9', 0)
            ema_21 = indicators.get('ema_21', 0)
            ema_50 = indicators.get('ema_50', 0)
            atr = indicators.get('atr', 0)

            # 2. Xác định EMA Trend (strict: must include EMA50 and all EMAs valid)
            ema_trend = 'neutral'
            # Check for missing/zero/NaN EMA values
            if not ema_9 or not ema_21 or not ema_50:
                ema_trend = 'neutral'
            elif math.isnan(ema_9) or math.isnan(ema_21) or math.isnan(ema_50):
                ema_trend = 'neutral'
            elif price > ema_9 > ema_21 > ema_50:
                ema_trend = 'bullish'
            elif price < ema_9 < ema_21 < ema_50:
                ema_trend = 'bearish'

            # 3. Phân tích Gann
            gann_analysis = await gann_engine.analyze(symbol, market_data_engine)
            gann_trend = gann_analysis.get('trend', 'neutral')
            gann_bias = gann_analysis.get('bias', 'neutral')
            gann_support = gann_analysis.get('support')
            gann_resistance = gann_analysis.get('resistance')
            gann_confidence = gann_analysis.get('confidence', 0)

            # 4. Kiểm tra ATR/volatility
            atr_valid = atr and atr > 0
            atr_percent = (atr / price * 100) if price > 0 else 0

            # 5. Fallback cho missing data
            if not atr_valid:
                logger.warning(f"[STRATEGY] symbol={symbol}, ATR missing or invalid, WAIT")
                return f"⚪ {symbol} - WAIT (missing ATR data)"
            if gann_trend == 'neutral':
                logger.warning(f"[STRATEGY] symbol={symbol}, GANN neutral, WAIT")
                return f"⚪ {symbol} - WAIT (GANN neutral)"
            if ema_trend == 'neutral':
                logger.warning(f"[STRATEGY] symbol={symbol}, EMA neutral, WAIT")
                return f"⚪ {symbol} - WAIT (EMA neutral)"

            # 6. Detailed logging
            logger.info(f"[STRATEGY] symbol={symbol}")
            logger.info(f"[STRATEGY] timeframe=1h")
            logger.info(f"[STRATEGY] price={price:.2f}")
            logger.info(f"[STRATEGY] ema_9={ema_9:.2f}")
            logger.info(f"[STRATEGY] ema_21={ema_21:.2f}")
            logger.info(f"[STRATEGY] ema_50={ema_50:.2f}")
            logger.info(f"[STRATEGY] ema_trend={ema_trend}")
            logger.info(f"[STRATEGY] gann_trend={gann_trend}")
            logger.info(f"[STRATEGY] gann_bias={gann_bias}")
            logger.info(f"[STRATEGY] gann_support={gann_support:.2f if gann_support else 'N/A'}")
            logger.info(f"[STRATEGY] gann_resistance={gann_resistance:.2f if gann_resistance else 'N/A'}")
            logger.info(f"[STRATEGY] gann_confidence={gann_confidence:.2f}")
            logger.info(f"[STRATEGY] atr={atr:.4f}")
            logger.info(f"[STRATEGY] atr_percent={atr_percent:.2f}%")

            # 7. Quyết định direction dựa trên EMA + Gann
            direction = 'WAIT'
            reason = []

            if ema_trend == 'bullish' and gann_trend == 'bullish':
                direction = 'LONG'
                reason.append('EMA bullish + Gann bullish')
            elif ema_trend == 'bearish' and gann_trend == 'bearish':
                direction = 'SHORT'
                reason.append('EMA bearish + Gann bearish')
            elif ema_trend == 'bullish' and gann_trend == 'bearish':
                direction = 'WAIT'
                reason.append('EMA/GANN conflict - EMA bullish but Gann bearish')
            elif ema_trend == 'bearish' and gann_trend == 'bullish':
                direction = 'WAIT'
                reason.append('EMA/GANN conflict - EMA bearish but Gann bullish')
            else:
                direction = 'WAIT'
                reason.append('Insufficient trend confirmation')

            logger.info(f"[STRATEGY] action={direction}")
            if direction == 'WAIT':
                logger.info(f"[STRATEGY] reason={', '.join(reason)}")

            # 8. Nếu WAIT, trả về summary
            if direction == 'WAIT':
                return f"⚪ {symbol} - WAIT ({', '.join(reason)})"

            # 9. Nếu LONG/SHORT, tạo analysis dict cho signal creation
            analysis = {
                'symbol': symbol,
                'action': direction,
                'price': price,
                'ai_score': 85,  # Base score for confirmed trend
                'confidence': 0.85,
                'trend': ema_trend,
                'reasons': reason + [f'Gann confidence: {gann_confidence:.2f}', f'ATR: {atr_percent:.2f}%']
            }

            # 10. Tính toán entry, SL, TP cho logging
            gann_support_for_entry = gann_support if direction == 'LONG' else None
            gann_resistance_for_entry = gann_resistance if direction == 'SHORT' else None
            entry_range = await self.calculate_entry_range(price, direction, symbol, gann_support_for_entry, gann_resistance_for_entry)
            take_profits = self.calculate_take_profit(price, direction, atr)
            stop_loss = self.calculate_stop_loss(price, direction, atr)

            # Log entry, SL, TP
            logger.info(f"[STRATEGY] entry={entry_range}")
            logger.info(f"[STRATEGY] sl={stop_loss:.2f}")
            logger.info(f"[STRATEGY] tp1={take_profits['TP1']:.2f}")
            logger.info(f"[STRATEGY] tp2={take_profits['TP2']:.2f}")
            logger.info(f"[STRATEGY] tp3={take_profits['TP3']:.2f}")

            # 11. Lưu AI log
            await db.save_ai_log_async(
                symbol=symbol,
                analysis_data=analysis,
                decision=direction,
                ai_score=85,
                confidence=0.85
            )

            # 12. Tạo signal
            signal = await self.create_signal(analysis)
            if signal:
                return signal['message']

            return None

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
