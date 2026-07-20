"""
Module AI Analysis Engine cho AI Trading Signal Bot
Phân tích dữ liệu thị trường và đưa ra quyết định giao dịch
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional
from core.config import AI_SCORE_THRESHOLD, MIN_CONFIDENCE

logger = logging.getLogger(__name__)


class AIEngine:
    """AI Engine phân tích thị trường và đưa ra tín hiệu"""
    
    def __init__(self):
        self.analysis_cache = {}
    
    def analyze_trend(self, indicators: Dict) -> Dict:
        """Phân tích xu hướng từ các chỉ số kỹ thuật"""
        try:
            trend_analysis = {
                'trend': 'neutral',
                'strength': 0,
                'signals': []
            }
            
            price = indicators.get('price', 0)
            ema_9 = indicators.get('ema_9', 0)
            ema_21 = indicators.get('ema_21', 0)
            ema_50 = indicators.get('ema_50', 0)
            rsi = indicators.get('rsi', 50)
            macd = indicators.get('macd', 0)
            macd_signal = indicators.get('macd_signal', 0)
            macd_hist = indicators.get('macd_histogram', 0)
            
            # EMA Analysis
            if price > ema_9 > ema_21 > ema_50:
                trend_analysis['trend'] = 'strong_uptrend'
                trend_analysis['strength'] += 3
                trend_analysis['signals'].append('EMA bullish alignment')
            elif price > ema_9 > ema_21:
                trend_analysis['trend'] = 'uptrend'
                trend_analysis['strength'] += 2
                trend_analysis['signals'].append('Price above EMAs')
            elif price < ema_9 < ema_21 < ema_50:
                trend_analysis['trend'] = 'strong_downtrend'
                trend_analysis['strength'] -= 3
                trend_analysis['signals'].append('EMA bearish alignment')
            elif price < ema_9 < ema_21:
                trend_analysis['trend'] = 'downtrend'
                trend_analysis['strength'] -= 2
                trend_analysis['signals'].append('Price below EMAs')
            
            # RSI Analysis
            if rsi > 70:
                trend_analysis['strength'] -= 1
                trend_analysis['signals'].append('RSI overbought')
            elif rsi < 30:
                trend_analysis['strength'] += 1
                trend_analysis['signals'].append('RSI oversold')
            elif rsi > 50:
                trend_analysis['strength'] += 0.5
                trend_analysis['signals'].append('RSI bullish')
            elif rsi < 50:
                trend_analysis['strength'] -= 0.5
                trend_analysis['signals'].append('RSI bearish')
            
            # MACD Analysis
            if macd > macd_signal and macd_hist > 0:
                trend_analysis['strength'] += 2
                trend_analysis['signals'].append('MACD bullish crossover')
            elif macd < macd_signal and macd_hist < 0:
                trend_analysis['strength'] -= 2
                trend_analysis['signals'].append('MACD bearish crossover')
            
            # Bollinger Bands
            bb_upper = indicators.get('bb_upper', 0)
            bb_lower = indicators.get('bb_lower', 0)
            if price > bb_upper:
                trend_analysis['strength'] -= 1
                trend_analysis['signals'].append('Price above BB upper')
            elif price < bb_lower:
                trend_analysis['strength'] += 1
                trend_analysis['signals'].append('Price below BB lower')
            
            return trend_analysis
        except Exception as e:
            logger.error(f"Error analyzing trend: {e}")
            return {'trend': 'neutral', 'strength': 0, 'signals': []}
    
    def calculate_probabilities(self, trend_analysis: Dict, smart_money: Dict, 
                               news_sentiment: str) -> Dict:
        """Tính toán xác suất tăng/giảm"""
        try:
            probabilities = {
                'long_probability': 50,
                'short_probability': 50,
                'trend_strength': 0
            }
            
            # Từ trend analysis
            trend_strength = trend_analysis.get('strength', 0)
            probabilities['trend_strength'] = abs(trend_strength)
            
            if trend_strength > 0:
                probabilities['long_probability'] += trend_strength * 10
                probabilities['short_probability'] -= trend_strength * 10
            elif trend_strength < 0:
                probabilities['long_probability'] += trend_strength * 10
                probabilities['short_probability'] -= trend_strength * 10
            
            # Từ smart money
            smart_trend = smart_money.get('trend', 'neutral')
            if smart_trend == 'strongly_bullish':
                probabilities['long_probability'] += 15
                probabilities['short_probability'] -= 15
            elif smart_trend == 'bullish':
                probabilities['long_probability'] += 10
                probabilities['short_probability'] -= 10
            elif smart_trend == 'strongly_bearish':
                probabilities['long_probability'] -= 15
                probabilities['short_probability'] += 15
            elif smart_trend == 'bearish':
                probabilities['long_probability'] -= 10
                probabilities['short_probability'] += 10
            
            # Từ news sentiment
            if news_sentiment == 'bullish':
                probabilities['long_probability'] += 10
                probabilities['short_probability'] -= 10
            elif news_sentiment == 'bearish':
                probabilities['long_probability'] -= 10
                probabilities['short_probability'] += 10
            
            # Normalize về 0-100
            total = probabilities['long_probability'] + probabilities['short_probability']
            if total > 0:
                probabilities['long_probability'] = (probabilities['long_probability'] / total) * 100
                probabilities['short_probability'] = (probabilities['short_probability'] / total) * 100
            
            # Clamp values
            probabilities['long_probability'] = max(0, min(100, probabilities['long_probability']))
            probabilities['short_probability'] = max(0, min(100, probabilities['short_probability']))
            
            return probabilities
        except Exception as e:
            logger.error(f"Error calculating probabilities: {e}")
            return {'long_probability': 50, 'short_probability': 50, 'trend_strength': 0}
    
    def calculate_risk_level(self, trend_analysis: Dict, smart_money: Dict) -> str:
        """Tính toán mức độ rủi ro"""
        try:
            risk_score = 0
            
            # RSI extreme levels
            rsi = trend_analysis.get('signals', [])
            if 'RSI overbought' in rsi or 'RSI oversold' in rsi:
                risk_score += 2
            
            # Smart money divergence
            smart_trend = smart_money.get('trend', 'neutral')
            trend = trend_analysis.get('trend', 'neutral')
            
            if ('uptrend' in trend and 'bearish' in smart_trend) or \
               ('downtrend' in trend and 'bullish' in smart_trend):
                risk_score += 3
            
            # Liquidation cascade risk
            cascade_risk = smart_money.get('cascade_risk', 'low')
            if cascade_risk == 'high':
                risk_score += 3
            elif cascade_risk == 'medium':
                risk_score += 1
            
            # Determine risk level
            if risk_score >= 5:
                return 'high'
            elif risk_score >= 3:
                return 'medium'
            else:
                return 'low'
        except Exception as e:
            logger.error(f"Error calculating risk level: {e}")
            return 'medium'
    
    def generate_ai_decision(self, probabilities: Dict, risk_level: str, 
                            trend_analysis: Dict) -> Dict:
        """Tạo quyết định AI"""
        try:
            long_prob = probabilities.get('long_probability', 50)
            short_prob = probabilities.get('short_probability', 50)
            trend_strength = probabilities.get('trend_strength', 0)
            
            decision = {
                'action': 'WAIT',
                'ai_score': 0,
                'confidence': 0,
                'reasons': []
            }
            
            # Tính AI Score dựa trên nhiều yếu tố
            base_score = max(long_prob, short_prob)
            
            # Điều chỉnh theo trend strength
            if trend_strength > 2:
                base_score += 5
            elif trend_strength > 1:
                base_score += 3
            
            # Điều chỉnh theo risk level
            if risk_level == 'high':
                base_score -= 10
            elif risk_level == 'medium':
                base_score -= 5
            
            # Clamp AI Score
            decision['ai_score'] = max(0, min(100, base_score))
            decision['confidence'] = decision['ai_score'] / 100
            
            # Xác định action
            if decision['ai_score'] >= AI_SCORE_THRESHOLD:
                if long_prob > short_prob:
                    decision['action'] = 'LONG'
                    decision['reasons'].append(f'Long probability: {long_prob:.1f}%')
                else:
                    decision['action'] = 'SHORT'
                    decision['reasons'].append(f'Short probability: {short_prob:.1f}%')
                
                # Thêm reasons từ trend analysis
                for signal in trend_analysis.get('signals', []):
                    decision['reasons'].append(signal)
            else:
                decision['action'] = 'WAIT'
                decision['reasons'].append(f'AI Score below threshold ({AI_SCORE_THRESHOLD})')
            
            return decision
        except Exception as e:
            logger.error(f"Error generating AI decision: {e}")
            return {'action': 'WAIT', 'ai_score': 0, 'confidence': 0, 'reasons': ['Error in analysis']}
    
    async def analyze(self, symbol: str, market_data, smart_money_tracker, 
                     news_engine) -> Dict:
        """Phân tích toàn diện cho một symbol"""
        try:
            logger.info(f"Starting AI analysis for {symbol}")
            
            # 1. Lấy dữ liệu thị trường
            symbol_data = await market_data.get_symbol_data(symbol)
            indicators = symbol_data.get('indicators', {})
            
            # 2. Phân tích xu hướng
            trend_analysis = self.analyze_trend(indicators)
            
            # 3. Lấy Smart Money analysis
            smart_money = await smart_money_tracker.analyze_smart_money_confluence(symbol, market_data)
            
            # 4. Lấy news sentiment
            news_summary = await news_engine.get_news_summary()
            news_sentiment = 'neutral'  # Simplified - trong thực tế cần phân tích sentiment
            
            # 5. Tính toán xác suất
            probabilities = self.calculate_probabilities(trend_analysis, smart_money, news_sentiment)
            
            # 6. Tính toán rủi ro
            risk_level = self.calculate_risk_level(trend_analysis, smart_money)
            
            # 7. Tạo quyết định AI
            decision = self.generate_ai_decision(probabilities, risk_level, trend_analysis)
            
            # 8. Tổng hợp kết quả
            analysis_result = {
                'symbol': symbol,
                'timestamp': datetime.now().isoformat(),
                'trend': trend_analysis.get('trend'),
                'trend_strength': trend_analysis.get('strength'),
                'long_probability': probabilities.get('long_probability'),
                'short_probability': probabilities.get('short_probability'),
                'risk_level': risk_level,
                'action': decision.get('action'),
                'ai_score': decision.get('ai_score'),
                'confidence': decision.get('confidence'),
                'reasons': decision.get('reasons'),
                'trend_signals': trend_analysis.get('signals'),
                'smart_money_trend': smart_money.get('trend'),
                'smart_money_signals': smart_money.get('signals'),
                'price': indicators.get('price'),
                'rsi': indicators.get('rsi'),
                'macd': indicators.get('macd')
            }
            
            self.analysis_cache[symbol] = analysis_result
            logger.info(f"AI analysis completed for {symbol}: {decision.get('action')} (Score: {decision.get('ai_score')})")
            
            return analysis_result
        except Exception as e:
            logger.error(f"Error in AI analysis for {symbol}: {e}")
            return {
                'symbol': symbol,
                'action': 'WAIT',
                'ai_score': 0,
                'confidence': 0,
                'reasons': ['Analysis error'],
                'error': str(e)
            }
    
    def get_analysis_summary(self, symbol: str) -> str:
        """Lấy tóm tắt phân tích"""
        try:
            analysis = self.analysis_cache.get(symbol)
            
            if not analysis:
                return "❌ Không có dữ liệu phân tích"
            
            action = analysis.get('action', 'WAIT')
            ai_score = analysis.get('ai_score', 0)
            confidence = analysis.get('confidence', 0)
            
            if action == 'LONG':
                emoji = "🟢"
            elif action == 'SHORT':
                emoji = "🔴"
            else:
                emoji = "⚪"
            
            summary = f"{emoji} *AI Analysis - {analysis.get('symbol')}*\n\n"
            summary += f"📊 *Action:* {action}\n"
            summary += f"🎯 *AI Score:* {ai_score}/100\n"
            summary += f"📈 *Confidence:* {confidence:.1%}\n"
            summary += f"📉 *Risk Level:* {analysis.get('risk_level', 'N/A')}\n\n"
            
            summary += f"📊 *Probabilities:*\n"
            summary += f"• Long: {analysis.get('long_probability', 0):.1f}%\n"
            summary += f"• Short: {analysis.get('short_probability', 0):.1f}%\n\n"
            
            summary += f"📈 *Trend:* {analysis.get('trend', 'N/A')}\n"
            summary += f"🐋 *Smart Money:* {analysis.get('smart_money_trend', 'N/A')}\n\n"
            
            summary += f"📋 *Reasons:*\n"
            for reason in analysis.get('reasons', [])[:5]:
                summary += f"• {reason}\n"
            
            return summary
        except Exception as e:
            logger.error(f"Error getting analysis summary for {symbol}: {e}")
            return "❌ Không thể lấy tóm tắt phân tích"


# Singleton instance
ai_engine = AIEngine()
