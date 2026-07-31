"""
Module Chart Generator cho AI Trading Signal Bot V2.0
Tạo biểu đồ phân tích thị trường từ dữ liệu thật
"""
import logging
import asyncio
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from typing import Dict, Optional, List
import pandas as pd
import numpy as np
import os
import re

logger = logging.getLogger(__name__)


def sanitize_filename(filename: str) -> str:
    """Sanitize filename by replacing invalid characters with underscores"""
    # Replace characters that are invalid in filenames
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Also replace spaces with underscores for consistency
    sanitized = sanitized.replace(' ', '_')
    # Remove leading/trailing dots and underscores
    sanitized = sanitized.strip('._')
    return sanitized


class ChartGenerator:
    """Tạo biểu đồ phân tích thị trường"""

    def __init__(self):
        self.chart_cache = {}
        plt.style.use('seaborn-v0_8-darkgrid')
        plt.rcParams['figure.facecolor'] = '#131722'
        plt.rcParams['axes.facecolor'] = '#131722'
        plt.rcParams['text.color'] = '#d1d4dc'
        plt.rcParams['axes.labelcolor'] = '#d1d4dc'
        plt.rcParams['xtick.color'] = '#d1d4dc'
        plt.rcParams['ytick.color'] = '#d1d4dc'
        plt.rcParams['grid.color'] = '#2a2e39'
        plt.rcParams['grid.alpha'] = 0.3
    
    async def generate_signal_chart(self, symbol: str, signal_type: str, 
                                   entry_price: float, tp1: float, tp2: float, tp3: float,
                                   stop_loss: float, ai_score: int, timeframe: str = '1h',
                                   analysis_data: Dict = None) -> Optional[str]:
        """Tạo biểu đồ cho tín hiệu"""
        try:
            # Lấy dữ liệu nến
            from data.market_data import market_data_engine
            df = await market_data_engine.get_ohlcv(symbol, timeframe, limit=100)
            
            if df is None or df.empty:
                logger.warning(f"No data available for {symbol}")
                return None
            
            # Tạo biểu đồ
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), 
                                            gridspec_kw={'height_ratios': [3, 1]})
            fig.suptitle(f'{symbol} - {timeframe.upper()} - AI Score: {ai_score}/100', 
                        fontsize=14, fontweight='bold')
            
            # Vẽ nến
            self._plot_candlestick(ax1, df, symbol)
            
            # Vẽ các mức Entry, TP, SL
            self._plot_levels(ax1, entry_price, tp1, tp2, tp3, stop_loss, signal_type)

            # Vẽ Support & Resistance zones
            self._plot_support_resistance(ax1, df)

            # Vẽ Supply & Demand zones
            self._plot_supply_demand(ax1, df)

            # Vẽ trend line
            self._plot_trend_line(ax1, df, signal_type)

            # Vẽ các chỉ báo nếu có
            if analysis_data:
                self._plot_indicators(ax1, ax2, df, analysis_data)

            # Vẽ mũi tên dự báo
            self._plot_prediction_arrow(ax1, df, signal_type, entry_price)
            
            # Thêm thông tin
            self._add_info_text(fig, symbol, signal_type, ai_score, timeframe)

            # Lưu ảnh
            # Ensure temp directory exists
            temp_dir = "temp"
            os.makedirs(temp_dir, exist_ok=True)

            # Sanitize symbol for filename
            sanitized_symbol = sanitize_filename(symbol)
            chart_path = f"{temp_dir}/chart_{sanitized_symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"

            # Save chart
            plt.savefig(chart_path, dpi=100, bbox_inches='tight')
            plt.close()

            # Verify file was created successfully
            if os.path.exists(chart_path):
                logger.info(f"Chart generated for {symbol}: {chart_path}")
                return chart_path
            else:
                logger.error(f"Chart file not created for {symbol}: {chart_path}")
                return None
            
        except Exception as e:
            logger.error(f"Error generating chart for {symbol}: {e}")
            return None
    
    def _plot_candlestick(self, ax, df, symbol):
        """Vẽ biểu đồ nến"""
        try:
            # Tính toán màu cho nến
            colors = pd.Series('#26a69a', index=df.index)  # TradingView green
            colors[df['close'] < df['open']] = '#ef5350'  # TradingView red

            # Vẽ nến
            for i, (idx, row) in enumerate(df.iterrows()):
                # Shadow
                ax.plot([i, i], [row['low'], row['high']],
                       color=colors[idx], linewidth=1, alpha=0.8)
                # Body
                ax.plot([i, i], [row['open'], row['close']],
                       color=colors[idx], linewidth=3, alpha=0.9)

            # Format trục x
            ax.set_xlim(-0.5, len(df) - 0.5)
            ax.set_ylabel('Price', fontsize=10)
            ax.grid(True, alpha=0.3)

        except Exception as e:
            logger.error(f"Error plotting candlestick: {e}")
    
    def _plot_levels(self, ax, entry_price, tp1, tp2, tp3, stop_loss, signal_type):
        """Vẽ các mức Entry, TP, SL"""
        try:
            # Entry
            ax.axhline(y=entry_price, color='#2962ff', linestyle='--', linewidth=2, label='Entry')
            ax.text(len(ax.get_xlim()) * 0.02, entry_price, 'Entry',
                   color='#2962ff', fontsize=9, fontweight='bold')

            # TP1
            ax.axhline(y=tp1, color='#26a69a', linestyle='--', linewidth=1.5, label='TP1')
            ax.text(len(ax.get_xlim()) * 0.02, tp1, 'TP1',
                   color='#26a69a', fontsize=9)

            # TP2
            ax.axhline(y=tp2, color='#26a69a', linestyle='--', linewidth=1.5, alpha=0.7, label='TP2')
            ax.text(len(ax.get_xlim()) * 0.02, tp2, 'TP2',
                   color='#26a69a', fontsize=9)

            # TP3
            ax.axhline(y=tp3, color='#26a69a', linestyle='--', linewidth=1.5, alpha=0.5, label='TP3')
            ax.text(len(ax.get_xlim()) * 0.02, tp3, 'TP3',
                   color='#26a69a', fontsize=9)

            # Stop Loss
            ax.axhline(y=stop_loss, color='#ef5350', linestyle='--', linewidth=2, label='SL')
            ax.text(len(ax.get_xlim()) * 0.02, stop_loss, 'SL',
                   color='#ef5350', fontsize=9, fontweight='bold')

            ax.legend(loc='upper right', fontsize=8, facecolor='#1e222d', edgecolor='#2a2e39', labelcolor='#d1d4dc')

        except Exception as e:
            logger.error(f"Error plotting levels: {e}")
    
    def _plot_indicators(self, ax1, ax2, df, analysis_data):
        """Vẽ các chỉ báo kỹ thuật"""
        try:
            # Vẽ EMA nếu có trong indicators
            indicators = analysis_data.get('indicators', {})
            
            if 'ema_9' in indicators:
                ema_9 = df['close'].ewm(span=9).mean()
                ax1.plot(range(len(df)), ema_9, color='orange', linewidth=1, label='EMA 9')
            
            if 'ema_21' in indicators:
                ema_21 = df['close'].ewm(span=21).mean()
                ax1.plot(range(len(df)), ema_21, color='yellow', linewidth=1, label='EMA 21')
            
            if 'ema_50' in indicators:
                ema_50 = df['close'].ewm(span=50).mean()
                ax1.plot(range(len(df)), ema_50, color='purple', linewidth=1, label='EMA 50')
            
            # Vẽ Volume ở ax2
            ax2.bar(range(len(df)), df['volume'], color='gray', alpha=0.5)
            ax2.set_ylabel('Volume', fontsize=10)
            ax2.grid(True, alpha=0.3)
            
            # Vẽ RSI nếu có
            if 'rsi' in indicators:
                rsi = self._calculate_rsi(df['close'])
                ax2_twin = ax2.twinx()
                ax2_twin.plot(range(len(df)), rsi, color='purple', linewidth=1, label='RSI')
                ax2_twin.axhline(y=70, color='red', linestyle='--', linewidth=0.5, alpha=0.5)
                ax2_twin.axhline(y=30, color='green', linestyle='--', linewidth=0.5, alpha=0.5)
                ax2_twin.set_ylabel('RSI', fontsize=10)
                ax2_twin.legend(loc='upper left', fontsize=8)
            
        except Exception as e:
            logger.error(f"Error plotting indicators: {e}")
    
    def _plot_prediction_arrow(self, ax, df, signal_type, entry_price):
        """Vẽ mũi tên dự báo"""
        try:
            last_idx = len(df) - 1
            last_price = df.iloc[-1]['close']

            if signal_type == 'LONG':
                # Mũi tên tăng
                ax.annotate('▲', xy=(last_idx + 0.5, entry_price),
                           xytext=(last_idx + 2, entry_price * 1.02),
                           fontsize=20, color='#26a69a', fontweight='bold',
                           arrowprops=dict(arrowstyle='->', color='#26a69a', lw=2))
            else:
                # Mũi tên giảm
                ax.annotate('▼', xy=(last_idx + 0.5, entry_price),
                           xytext=(last_idx + 2, entry_price * 0.98),
                           fontsize=20, color='#ef5350', fontweight='bold',
                           arrowprops=dict(arrowstyle='->', color='#ef5350', lw=2))

        except Exception as e:
            logger.error(f"Error plotting prediction arrow: {e}")

    def _plot_support_resistance(self, ax, df):
        """Vẽ Support & Resistance zones"""
        try:
            # Calculate recent highs and lows
            recent_data = df.tail(30)
            highs = recent_data['high'].values
            lows = recent_data['low'].values

            # Find resistance levels (recent highs)
            resistance_levels = []
            for i in range(len(highs)):
                if highs[i] >= np.percentile(highs, 90):
                    resistance_levels.append(highs[i])

            # Find support levels (recent lows)
            support_levels = []
            for i in range(len(lows)):
                if lows[i] <= np.percentile(lows, 10):
                    support_levels.append(lows[i])

            # Plot resistance zones (red horizontal lines with transparency)
            for level in resistance_levels[:3]:
                ax.axhline(y=level, color='#ef5350', linestyle='-', linewidth=1, alpha=0.3)
                ax.axhspan(level - 0.001 * level, level + 0.001 * level,
                          color='#ef5350', alpha=0.1)

            # Plot support zones (green horizontal lines with transparency)
            for level in support_levels[:3]:
                ax.axhline(y=level, color='#26a69a', linestyle='-', linewidth=1, alpha=0.3)
                ax.axhspan(level - 0.001 * level, level + 0.001 * level,
                          color='#26a69a', alpha=0.1)

        except Exception as e:
            logger.error(f"Error plotting support/resistance: {e}")

    def _plot_supply_demand(self, ax, df):
        """Vẽ Supply & Demand zones"""
        try:
            # Simple supply/demand detection based on volume spikes
            recent_data = df.tail(50)
            avg_volume = recent_data['volume'].mean()

            # Find supply zones (high volume at resistance)
            supply_zones = []
            for i in range(len(recent_data)):
                if recent_data.iloc[i]['volume'] > 2 * avg_volume:
                    if recent_data.iloc[i]['close'] < recent_data.iloc[i]['open']:
                        # Bearish candle with high volume = supply
                        supply_zones.append(recent_data.iloc[i]['high'])

            # Find demand zones (high volume at support)
            demand_zones = []
            for i in range(len(recent_data)):
                if recent_data.iloc[i]['volume'] > 2 * avg_volume:
                    if recent_data.iloc[i]['close'] > recent_data.iloc[i]['open']:
                        # Bullish candle with high volume = demand
                        demand_zones.append(recent_data.iloc[i]['low'])

            # Plot supply zones (red rectangles)
            for zone in supply_zones[:2]:
                ax.axhspan(zone - 0.002 * zone, zone + 0.002 * zone,
                          color='#ef5350', alpha=0.15, label='Supply Zone')

            # Plot demand zones (green rectangles)
            for zone in demand_zones[:2]:
                ax.axhspan(zone - 0.002 * zone, zone + 0.002 * zone,
                          color='#26a69a', alpha=0.15, label='Demand Zone')

        except Exception as e:
            logger.error(f"Error plotting supply/demand: {e}")

    def _plot_trend_line(self, ax, df, signal_type):
        """Vẽ trend line"""
        try:
            recent_data = df.tail(30)
            x = np.arange(len(recent_data))
            y = recent_data['close'].values

            # Calculate linear regression for trend
            z = np.polyfit(x, y, 1)
            p = np.poly1d(z)

            # Plot trend line
            ax.plot(x, p(x), color='#2962ff', linestyle='--', linewidth=1.5, alpha=0.7, label='Trend Line')

        except Exception as e:
            logger.error(f"Error plotting trend line: {e}")
    
    def _add_info_text(self, fig, symbol, signal_type, ai_score, timeframe):
        """Thêm thông tin văn bản"""
        try:
            info_text = f"""
Symbol: {symbol}
Timeframe: {timeframe.upper()}
Signal: {signal_type}
AI Score: {ai_score}/100
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            """
            
            fig.text(0.02, 0.02, info_text.strip(), fontsize=8, 
                    bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
            
        except Exception as e:
            logger.error(f"Error adding info text: {e}")
    
    def _calculate_rsi(self, prices, period=14):
        """Tính RSI"""
        try:
            delta = prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            return rsi
        except Exception as e:
            logger.error(f"Error calculating RSI: {e}")
            return pd.Series([50] * len(prices))
    
    async def generate_vietnamese_analysis(self, symbol: str, signal_type: str, 
                                          analysis_data: Dict) -> str:
        """Tạo nội dung phân tích bằng tiếng Việt"""
        try:
            trend = analysis_data.get('trend', 'neutral')
            ai_score = analysis_data.get('ai_score', 0)
            reasons = analysis_data.get('reasons', [])
            
            # Phân tích xu hướng
            if trend in ['strong_uptrend', 'uptrend']:
                trend_text = "Xu hướng hiện tại: Tăng mạnh"
            elif trend in ['strong_downtrend', 'downtrend']:
                trend_text = "Xu hướng hiện tại: Giảm mạnh"
            else:
                trend_text = "Xu hướng hiện tại: Trung lập"
            
            # Lý do AI
            reasons_text = "Lý do AI đưa ra tín hiệu:\n"
            for i, reason in enumerate(reasons[:5], 1):
                reasons_text += f"{i}. {reason}\n"
            
            # Điều kiện làm mất hiệu lực
            invalidation_text = """
Điều kiện làm mất hiệu lực kịch bản:
• Giá phá vỡ Stop Loss
• Xu hướng đảo chiều mạnh
• Volume giảm đột ngột
            """
            
            analysis = f"""
📊 *PHÂN TÍCH {symbol}*

{trend_text}

🎯 *Tín hiệu: {signal_type}*
🤖 *AI Score: {ai_score}/100*

{reasons_text}

{invalidation_text}

⚠️ *Lưu ý:* Đây là phân tích kỹ thuật, không phải lời khuyên đầu tư. Hãy tự nghiên cứu và chịu trách nhiệm với quyết định giao dịch của bạn.
            """
            
            return analysis
            
        except Exception as e:
            logger.error(f"Error generating Vietnamese analysis: {e}")
            return "❌ Không thể tạo phân tích"


# Singleton instance
chart_generator = ChartGenerator()
