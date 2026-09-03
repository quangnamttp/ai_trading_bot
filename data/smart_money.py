"""
Module Smart Money Tracker cho AI Trading Signal Bot
Theo dõi dòng tiền thông minh, cá voi, và hoạt động lớn trên thị trường
"""
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from core.config import SYMBOLS

logger = logging.getLogger(__name__)


class SmartMoneyTracker:
    """Theo dõi hoạt động Smart Money và dòng tiền cá voi"""
    
    def __init__(self):
        self.whale_alerts = []
        self.large_trades = []
        self.smart_money_indicators = {}
        # Lịch sử Open Interest thực tế để tính % thay đổi thật (thay cho số liệu giả trước đây)
        self.oi_history = {}  # {symbol: [(timestamp, oi_value), ...]}
    
    async def track_whale_activity(self, symbol: str) -> List[Dict]:
        """Theo dõi hoạt động cá voi"""
        try:
            # Trong thực tế, cần API từ Whale Alert, Glassnode, hoặc similar
            # Đây là dữ liệu mẫu
            
            whale_activity = []
            
            # Mô phỏng phát hiện giao dịch lớn
            whale_activity.append({
                'symbol': symbol,
                'amount': 500,  # BTC
                'value_usd': 59000000,  # $59M
                'type': 'transfer',
                'from': 'exchange',
                'to': 'wallet',
                'timestamp': datetime.now().isoformat(),
                'significance': 'high'
            })
            
            self.whale_alerts.extend(whale_activity)
            logger.info(f"Tracked {len(whale_activity)} whale activities for {symbol}")
            
            return whale_activity
        except Exception as e:
            logger.error(f"Error tracking whale activity for {symbol}: {e}")
            return []
    
    async def detect_large_trades(self, symbol: str, market_data) -> List[Dict]:
        """Phát hiện các giao dịch lớn"""
        try:
            large_trades = []
            
            # Lấy order book
            order_book = await market_data.get_order_book(symbol)
            if order_book:
                bids = order_book.get('bids', [])
                asks = order_book.get('asks', [])
                
                # Phát hiện lệnh lớn ở bid (mua)
                if bids:
                    total_bid_volume = sum(bid[1] for bid in bids[:5])
                    if total_bid_volume > 1000000:  # > $1M
                        large_trades.append({
                            'side': 'buy',
                            'volume': total_bid_volume,
                            'price': bids[0][0],
                            'timestamp': datetime.now().isoformat(),
                            'significance': 'high'
                        })
                
                # Phát hiện lệnh lớn ở ask (bán)
                if asks:
                    total_ask_volume = sum(ask[1] for ask in asks[:5])
                    if total_ask_volume > 1000000:  # > $1M
                        large_trades.append({
                            'side': 'sell',
                            'volume': total_ask_volume,
                            'price': asks[0][0],
                            'timestamp': datetime.now().isoformat(),
                            'significance': 'high'
                        })
            
            self.large_trades.extend(large_trades)
            logger.info(f"Detected {len(large_trades)} large trades for {symbol}")
            
            return large_trades
        except Exception as e:
            logger.error(f"Error detecting large trades for {symbol}: {e}")
            return []
    
    async def analyze_funding_rate(self, symbol: str, market_data) -> Dict:
        """Phân tích Funding Rate để xác định tâm lý thị trường"""
        try:
            funding_data = await market_data.get_funding_rate(symbol)

            if not funding_data:
                return {'sentiment': 'neutral', 'rate': 0}

            funding_rate = funding_data.get('fundingRate', 0)

            # Handle string values like 'N/A'
            if isinstance(funding_rate, str):
                logger.debug(f"Funding rate is string for {symbol}: {funding_rate}")
                return {'sentiment': 'neutral', 'rate': 0}

            # Funding rate dương = longs pay shorts = bullish sentiment
            # Funding rate âm = shorts pay longs = bearish sentiment

            if funding_rate > 0.01:  # > 1%
                sentiment = 'strongly_bullish'
            elif funding_rate > 0:
                sentiment = 'bullish'
            elif funding_rate < -0.01:  # < -1%
                sentiment = 'strongly_bearish'
            elif funding_rate < 0:
                sentiment = 'bearish'
            else:
                sentiment = 'neutral'

            return {
                'sentiment': sentiment,
                'rate': funding_rate,
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error analyzing funding rate for {symbol}: {e}")
            return {'sentiment': 'neutral', 'rate': 0}
    
    async def analyze_open_interest(self, symbol: str, market_data) -> Dict:
        """Phân tích Open Interest - so sánh với lịch sử thực tế đã ghi nhận
        (trước đây dùng số liệu giả cố định 5.2%, đã fix để tính % thay đổi thật)"""
        try:
            oi_data = await market_data.get_open_interest(symbol)

            if not oi_data:
                return {'trend': 'neutral', 'change': 0}

            open_interest = oi_data.get('openInterestAmount', 0)

            # Handle string values like 'N/A'
            if isinstance(open_interest, str):
                logger.debug(f"Open interest is string for {symbol}: {open_interest}")
                return {'trend': 'neutral', 'change': 0}

            if not open_interest or open_interest <= 0:
                return {'trend': 'neutral', 'change': 0}

            now = datetime.now()
            history = self.oi_history.setdefault(symbol, [])
            history.append((now, open_interest))

            # Chỉ giữ lịch sử trong 6 giờ gần nhất để so sánh
            cutoff = now - timedelta(hours=6)
            history[:] = [(t, v) for (t, v) in history if t > cutoff]

            # Cần ít nhất 1 điểm dữ liệu cũ (~1h trước) để so sánh có ý nghĩa
            reference = None
            for t, v in history:
                if t <= now - timedelta(minutes=45):
                    reference = v
                    break  # điểm cũ nhất còn trong cửa sổ 6h, gần mốc 1h nhất

            if reference is None or reference == 0:
                # Chưa đủ lịch sử để so sánh (mới khởi động bot) -> trung lập, không suy diễn
                return {
                    'trend': 'neutral',
                    'change': 0,
                    'open_interest': open_interest,
                    'note': 'Chưa đủ dữ liệu lịch sử để so sánh (cần chạy thêm ~45-60 phút)',
                    'timestamp': now.isoformat()
                }

            change_percent = ((open_interest - reference) / reference) * 100

            if change_percent > 10:
                trend = 'strongly_increasing'
            elif change_percent > 5:
                trend = 'increasing'
            elif change_percent < -10:
                trend = 'strongly_decreasing'
            elif change_percent < -5:
                trend = 'decreasing'
            else:
                trend = 'stable'

            return {
                'trend': trend,
                'change': round(change_percent, 2),
                'open_interest': open_interest,
                'timestamp': now.isoformat()
            }
        except Exception as e:
            logger.error(f"Error analyzing open interest for {symbol}: {e}")
            return {'trend': 'neutral', 'change': 0}
    
    async def detect_liquidation_cascades(self, symbol: str, market_data) -> Dict:
        """Phát hiện chuỗi liquidation"""
        try:
            liquidations = await market_data.get_liquidations(symbol)
            
            if not liquidations:
                return {'cascade_risk': 'low', 'total_liquidated': 0}
            
            total_liquidated = sum(liq.get('quantity', 0) for liq in liquidations)
            
            # Nếu nhiều liquidation trong thời gian ngắn
            if total_liquidated > 1000:  # > 1000 BTC
                cascade_risk = 'high'
            elif total_liquidated > 500:
                cascade_risk = 'medium'
            else:
                cascade_risk = 'low'
            
            return {
                'cascade_risk': cascade_risk,
                'total_liquidated': total_liquidated,
                'count': len(liquidations),
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error detecting liquidation cascades for {symbol}: {e}")
            return {'cascade_risk': 'low', 'total_liquidated': 0}
    
    async def analyze_smart_money_confluence(self, symbol: str, market_data) -> Dict:
        """Phân tích sự hội tụ của các tín hiệu Smart Money - uses concurrent operations"""
        try:
            confluence = {
                'bullish_signals': 0,
                'bearish_signals': 0,
                'neutral_signals': 0,
                'total_score': 0,
                'signals': []
            }

            # Run all analyses concurrently to reduce total time
            whale_task = self.track_whale_activity(symbol)
            large_trades_task = self.detect_large_trades(symbol, market_data)
            funding_task = self.analyze_funding_rate(symbol, market_data)
            oi_task = self.analyze_open_interest(symbol, market_data)
            liquidation_task = self.detect_liquidation_cascades(symbol, market_data)

            # Wait for all operations to complete concurrently
            whale_activity, large_trades, funding_analysis, oi_analysis, liquidation_risk = await asyncio.gather(
                whale_task, large_trades_task, funding_task, oi_task, liquidation_task,
                return_exceptions=True
            )

            # 1. Whale Activity
            if isinstance(whale_activity, list):
                for activity in whale_activity:
                    if activity.get('to') == 'wallet' and activity.get('from') == 'exchange':
                        confluence['bullish_signals'] += 1
                        confluence['signals'].append('Whale accumulation detected')
                    elif activity.get('to') == 'exchange' and activity.get('from') == 'wallet':
                        confluence['bearish_signals'] += 1
                        confluence['signals'].append('Whale distribution detected')

            # 2. Large Trades
            if isinstance(large_trades, list):
                for trade in large_trades:
                    if trade.get('side') == 'buy':
                        confluence['bullish_signals'] += 1
                        confluence['signals'].append('Large buy orders detected')
                    else:
                        confluence['bearish_signals'] += 1
                        confluence['signals'].append('Large sell orders detected')

            # 3. Funding Rate
            if isinstance(funding_analysis, dict):
                funding_sentiment = funding_analysis.get('sentiment')
                if 'bullish' in funding_sentiment:
                    confluence['bullish_signals'] += 1
                    confluence['signals'].append(f'Funding rate {funding_sentiment}')
                elif 'bearish' in funding_sentiment:
                    confluence['bearish_signals'] += 1
                    confluence['signals'].append(f'Funding rate {funding_sentiment}')
                else:
                    confluence['neutral_signals'] += 1

            # 4. Open Interest
            if isinstance(oi_analysis, dict):
                oi_trend = oi_analysis.get('trend')
                if 'increasing' in oi_trend:
                    confluence['bullish_signals'] += 1
                    confluence['signals'].append(f'Open interest {oi_trend}')
                elif 'decreasing' in oi_trend:
                    confluence['bearish_signals'] += 1
                    confluence['signals'].append(f'Open interest {oi_trend}')
                else:
                    confluence['neutral_signals'] += 1

            # 5. Liquidation Cascade Risk
            if isinstance(liquidation_risk, dict):
                if liquidation_risk.get('cascade_risk') == 'high':
                    confluence['bearish_signals'] += 2  # High risk
                    confluence['signals'].append('High liquidation cascade risk')

            # Tính tổng điểm
            total_signals = confluence['bullish_signals'] + confluence['bearish_signals'] + confluence['neutral_signals']
            if total_signals > 0:
                confluence['total_score'] = (confluence['bullish_signals'] - confluence['bearish_signals']) / total_signals

            # Xác định xu hướng
            if confluence['total_score'] > 0.3:
                confluence['trend'] = 'strongly_bullish'
            elif confluence['total_score'] > 0.1:
                confluence['trend'] = 'bullish'
            elif confluence['total_score'] < -0.3:
                confluence['trend'] = 'strongly_bearish'
            elif confluence['total_score'] < -0.1:
                confluence['trend'] = 'bearish'
            else:
                confluence['trend'] = 'neutral'

            self.smart_money_indicators[symbol] = confluence

            return confluence
        except Exception as e:
            logger.error(f"Error analyzing smart money confluence for {symbol}: {e}")
            return {'trend': 'neutral', 'total_score': 0, 'signals': []}
    
    async def get_smart_money_summary(self, symbol: str) -> str:
        """Lấy tóm tắt Smart Money"""
        try:
            confluence = self.smart_money_indicators.get(symbol)
            
            if not confluence:
                return "❌ Không có dữ liệu Smart Money"
            
            summary = f"🐋 *Smart Money Analysis - {symbol}*\n\n"
            
            trend = confluence.get('trend', 'neutral')
            if trend == 'strongly_bullish':
                summary += "🟢 *Xu hướng: Tăng mạnh*\n"
            elif trend == 'bullish':
                summary += "🟢 *Xu hướng: Tăng*\n"
            elif trend == 'strongly_bearish':
                summary += "🔴 *Xu hướng: Giảm mạnh*\n"
            elif trend == 'bearish':
                summary += "🔴 *Xu hướng: Giảm*\n"
            else:
                summary += "⚪ *Xu hướng: Trung lập*\n"
            
            summary += f"\n📊 *Tín hiệu:*\n"
            for signal in confluence.get('signals', []):
                summary += f"• {signal}\n"
            
            summary += f"\n📈 *Bullish signals: {confluence.get('bullish_signals', 0)}*\n"
            summary += f"📉 *Bearish signals: {confluence.get('bearish_signals', 0)}*\n"
            summary += f"⚪ *Neutral signals: {confluence.get('neutral_signals', 0)}*\n"
            
            return summary
        except Exception as e:
            logger.error(f"Error getting smart money summary for {symbol}: {e}")
            return "❌ Không thể lấy tóm tắt Smart Money"

    async def get_cashflow_verdict(self, symbol: str, market_data) -> Dict:
        """Đánh giá 'Dòng tiền' cho 1 coin: kết hợp Funding Rate (tâm lý phe Long/Short)
        + Open Interest thật (tiền mới vào/ra thị trường futures) + biến động giá gần nhất,
        theo logic OI+Price kinh điển dùng trong phân tích futures crypto:

        - OI tăng + Giá tăng  -> Long mới mở vị thế (dòng tiền MỚI đang bơm vào, xu hướng tăng có lực)
        - OI tăng + Giá giảm  -> Short mới mở vị thế (dòng tiền MỚI đang bơm vào, xu hướng giảm có lực)
        - OI giảm + Giá tăng  -> Short đóng vị thế / short covering (tiền rút khỏi phe Short)
        - OI giảm + Giá giảm  -> Long đóng vị thế / chốt lời-cắt lỗ (tiền rút khỏi phe Long)
        """
        try:
            funding = await self.analyze_funding_rate(symbol, market_data)
            oi = await self.analyze_open_interest(symbol, market_data)
            ticker = await market_data.get_ticker(symbol)

            price_change_percent = 0
            if ticker:
                price_change_percent = ticker.get('percentage', 0) or 0

            oi_trend = oi.get('trend', 'neutral')
            oi_increasing = oi_trend in ('increasing', 'strongly_increasing')
            oi_decreasing = oi_trend in ('decreasing', 'strongly_decreasing')

            if oi.get('note'):
                verdict = 'Chưa đủ dữ liệu'
                detail = oi['note']
            elif oi_increasing and price_change_percent > 0:
                verdict = '🟢 Dòng tiền MỚI đang bơm vào (Long)'
                detail = 'Open Interest tăng cùng chiều giá tăng - lực mua thực sự, không phải hồi kỹ thuật.'
            elif oi_increasing and price_change_percent < 0:
                verdict = '🔴 Dòng tiền MỚI đang bơm vào (Short)'
                detail = 'Open Interest tăng trong khi giá giảm - phe Short đang vào mạnh, xu hướng giảm có lực đẩy.'
            elif oi_decreasing and price_change_percent > 0:
                verdict = '🟡 Dòng tiền đang RÚT (Short đóng lệnh)'
                detail = 'Open Interest giảm trong khi giá tăng - nhiều khả năng là short covering, cần thận trọng vì có thể chỉ là hồi kỹ thuật ngắn hạn.'
            elif oi_decreasing and price_change_percent < 0:
                verdict = '🟡 Dòng tiền đang RÚT (Long đóng lệnh)'
                detail = 'Open Interest giảm cùng chiều giá giảm - long đang chốt lời/cắt lỗ, áp lực bán có thể hạ nhiệt dần.'
            else:
                verdict = '⚪ Dòng tiền ổn định / chưa rõ xu hướng'
                detail = 'Open Interest chưa biến động đáng kể.'

            return {
                'symbol': symbol,
                'verdict': verdict,
                'detail': detail,
                'funding_rate': funding.get('rate', 0),
                'funding_sentiment': funding.get('sentiment', 'neutral'),
                'oi_change_percent': oi.get('change', 0),
                'oi_trend': oi_trend,
                'price_change_percent': price_change_percent
            }
        except Exception as e:
            logger.error(f"Error getting cashflow verdict for {symbol}: {e}")
            return {
                'symbol': symbol,
                'verdict': '⚪ Không lấy được dữ liệu',
                'detail': str(e),
                'funding_rate': 0,
                'funding_sentiment': 'neutral',
                'oi_change_percent': 0,
                'oi_trend': 'neutral',
                'price_change_percent': 0
            }


# Singleton instance
smart_money_tracker = SmartMoneyTracker()
