"""
Module Gann Analysis Engine cho AI Trading Signal Bot
Phân tích theo lý thuyết Gann để xác định hướng giá và vùng hỗ trợ/kháng cự
"""
import logging
import pandas as pd
import numpy as np
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class GannEngine:
    """Gann Analysis Engine - xác định hướng giá và vùng hỗ trợ/kháng cự"""

    def __init__(self):
        self.analysis_cache = {}

    def calculate_gann_angles(self, df: pd.DataFrame) -> Dict:
        """Tính toán Gann angles từ dữ liệu giá"""
        try:
            if len(df) < 50:
                return {}

            latest = df.iloc[-1]
            price = latest['close']
            high = df['high'].max()
            low = df['low'].min()
            range_val = high - low

            if range_val == 0:
                return {}

            # Gann angles dựa trên 1x1 (45 độ) - mức quan trọng nhất
            # 1x1 = 1 unit price per 1 unit time
            gann_1x1 = range_val / len(df)

            # Các angles khác
            gann_2x1 = gann_1x1 * 2  # 63.75 độ
            gann_1x2 = gann_1x1 / 2  # 26.25 độ
            gann_4x1 = gann_1x1 * 4  # 75 độ
            gann_1x4 = gann_1x1 / 4  # 15 độ

            return {
                'gann_1x1': gann_1x1,
                'gann_2x1': gann_2x1,
                'gann_1x2': gann_1x2,
                'gann_4x1': gann_4x1,
                'gann_1x4': gann_1x4,
                'range': range_val
            }
        except Exception as e:
            logger.error(f"Error calculating Gann angles: {e}")
            return {}

    def identify_gann_levels(self, df: pd.DataFrame, angles: Dict) -> Dict:
        """Xác định các mức Gann support/resistance"""
        try:
            if not angles:
                return {}

            latest = df.iloc[-1]
            price = latest['close']
            high = df['high'].max()
            low = df['low'].min()

            gann_1x1 = angles.get('gann_1x1', 0)

            if gann_1x1 == 0:
                return {}

            # Tính các mức từ low và high
            support_levels = []
            resistance_levels = []

            # Từ low (cho uptrend)
            for i in range(1, 5):
                level = low + (gann_1x1 * i)
                if level < price:
                    support_levels.append(level)
                else:
                    resistance_levels.append(level)

            # Từ high (cho downtrend)
            for i in range(1, 5):
                level = high - (gann_1x1 * i)
                if level > price:
                    resistance_levels.append(level)
                else:
                    support_levels.append(level)

            # Lấy mức gần nhất
            nearest_support = max([s for s in support_levels if s < price]) if support_levels else low
            nearest_resistance = min([r for r in resistance_levels if r > price]) if resistance_levels else high

            return {
                'nearest_support': nearest_support,
                'nearest_resistance': nearest_resistance,
                'support_levels': sorted(support_levels),
                'resistance_levels': sorted(resistance_levels)
            }
        except Exception as e:
            logger.error(f"Error identifying Gann levels: {e}")
            return {}

    def determine_gann_trend(self, df: pd.DataFrame, levels: Dict) -> str:
        """Xác định xu hướng theo Gann"""
        try:
            if not levels:
                return 'neutral'

            latest = df.iloc[-1]
            price = latest['close']
            nearest_support = levels.get('nearest_support', 0)
            nearest_resistance = levels.get('nearest_resistance', 0)

            if nearest_support == 0 or nearest_resistance == 0:
                return 'neutral'

            # Khoảng cách đến support/resistance
            dist_to_support = (price - nearest_support) / price
            dist_to_resistance = (nearest_resistance - price) / price

            # Nếu gần support hơn → bullish bias
            if dist_to_support < dist_to_resistance:
                # Kiểm tra xem giá có đang trên 1x1 line không
                if price > nearest_support:
                    return 'bullish'
                else:
                    return 'bearish'
            else:
                # Nếu gần resistance hơn → bearish bias
                if price < nearest_resistance:
                    return 'bearish'
                else:
                    return 'bullish'

        except Exception as e:
            logger.error(f"Error determining Gann trend: {e}")
            return 'neutral'

    def calculate_gann_confidence(self, df: pd.DataFrame, trend: str) -> float:
        """Tính độ tin cậy của Gann analysis"""
        try:
            if trend == 'neutral':
                return 0.0

            latest = df.iloc[-1]
            price = latest['close']

            # Kiểm tra volume confirmation
            avg_volume = df['volume'].mean()
            current_volume = latest['volume']

            if current_volume > avg_volume:
                volume_confidence = 0.3
            else:
                volume_confidence = 0.1

            # Kiểm tra momentum
            if len(df) >= 5:
                recent_change = (price - df.iloc[-5]['close']) / df.iloc[-5]['close']
                if abs(recent_change) > 0.01:  # 1% change
                    momentum_confidence = 0.3
                else:
                    momentum_confidence = 0.1
            else:
                momentum_confidence = 0.1

            # Base confidence
            base_confidence = 0.4

            total_confidence = base_confidence + volume_confidence + momentum_confidence
            return min(0.9, total_confidence)

        except Exception as e:
            logger.error(f"Error calculating Gann confidence: {e}")
            return 0.0

    async def analyze(self, symbol: str, market_data_engine) -> Dict:
        """Phân tích Gann cho một symbol"""
        try:
            logger.info(f"Starting Gann analysis for {symbol}")

            # Lấy dữ liệu OHLCV
            df = await market_data_engine.get_ohlcv(symbol, timeframe='1h', limit=100)
            if df is None or len(df) < 50:
                logger.warning(f"Insufficient data for Gann analysis: {symbol}")
                return {
                    'symbol': symbol,
                    'trend': 'neutral',
                    'bias': 'neutral',
                    'support': None,
                    'resistance': None,
                    'confidence': 0.0,
                    'error': 'Insufficient data'
                }

            # Tính Gann angles
            angles = self.calculate_gann_angles(df)

            # Xác định các mức
            levels = self.identify_gann_levels(df, angles)

            # Xác định xu hướng
            trend = self.determine_gann_trend(df, levels)

            # Tính confidence
            confidence = self.calculate_gann_confidence(df, trend)

            result = {
                'symbol': symbol,
                'timestamp': datetime.now().isoformat(),
                'trend': trend,
                'bias': trend,  # bias = trend trong Gann
                'support': levels.get('nearest_support'),
                'resistance': levels.get('nearest_resistance'),
                'confidence': confidence,
                'gann_angles': angles,
                'gann_levels': levels
            }

            self.analysis_cache[symbol] = result

            logger.info(f"[GANN] symbol={symbol}, trend={trend}, confidence={confidence:.2f}")

            return result

        except Exception as e:
            logger.error(f"Error in Gann analysis for {symbol}: {e}")
            return {
                'symbol': symbol,
                'trend': 'neutral',
                'bias': 'neutral',
                'support': None,
                'resistance': None,
                'confidence': 0.0,
                'error': str(e)
            }


# Singleton instance
gann_engine = GannEngine()
