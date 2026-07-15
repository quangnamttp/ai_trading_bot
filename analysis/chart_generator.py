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

logger = logging.getLogger(__name__)


class ChartGenerator:
    """Tạo biểu đồ phân tích thị trường"""
    
    def __init__(self):
        self.chart_cache = {}
        plt.style.use('seaborn-v0_8-darkgrid')
    
    async def generate_signal_chart(self, symbol: str, signal_type: str, 
                                   entry_price: float, tp1: float, tp2: float, tp3: float,
                                   stop_loss: float, ai_score: int, timeframe: str = '1h',
                                   analysis_data: Dict = None) -> Optional[str]:
        """Tạo biểu đồ cho tín hiệu"""
        try:
            # Lấy dữ liệu nến
            from ..data.market_data import market_data_engine
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
            
            # Vẽ các chỉ báo nếu có
            if analysis_data:
                self._plot_indicators(ax1, ax2, df, analysis_data)
            
            # Vẽ mũi tên dự báo
            self._plot_prediction_arrow(ax1, df, signal_type, entry_price)
            
            # Thêm thông tin
            self._add_info_text(fig, symbol, signal_type, ai_score, timeframe)
            
            # Lưu ảnh
            chart_path = f"temp/chart_{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            plt.savefig(chart_path, dpi=100, bbox_inches='tight')
            plt.close()
            
            logger.info(f"Chart generated for {symbol}: {chart_path}")
            return chart_path
            
        except Exception as e:
            logger.error(f"Error generating chart for {symbol}: {e}")
            return None
    
    def _plot_candlestick(self, ax, df, symbol):
        """Vẽ biểu đồ nến"""
        try:
            # Tính toán màu cho nến
            colors = pd.Series('green', index=df.index)
            colors[df['close'] < df['open']] = 'red'
            
            # Vẽ nến
            for i, (idx, row) in enumerate(df.iterrows()):
                # Shadow
                ax.plot([i, i], [row['low'], row['high']], 
                       color=colors[idx], linewidth=1)
                # Body
                ax.plot([i, i], [row['open'], row['close']], 
                       color=colors[idx], linewidth=3)
            
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
            ax.axhline(y=entry_price, color='blue', linestyle='--', linewidth=2, label='Entry')
            ax.text(len(ax.get_xlim()) * 0.02, entry_price, 'Entry', 
                   color='blue', fontsize=9, fontweight='bold')
            
            # TP1
            ax.axhline(y=tp1, color='green', linestyle='--', linewidth=1.5, label='TP1')
            ax.text(len(ax.get_xlim()) * 0.02, tp1, 'TP1', 
                   color='green', fontsize=9)
            
            # TP2
            ax.axhline(y=tp2, color='green', linestyle='--', linewidth=1.5, alpha=0.7, label='TP2')
            ax.text(len(ax.get_xlim()) * 0.02, tp2, 'TP2', 
                   color='green', fontsize=9)
            
            # TP3
            ax.axhline(y=tp3, color='green', linestyle='--', linewidth=1.5, alpha=0.5, label='TP3')
            ax.text(len(ax.get_xlim()) * 0.02, tp3, 'TP3', 
                   color='green', fontsize=9)
            
            # Stop Loss
            ax.axhline(y=stop_loss, color='red', linestyle='--', linewidth=2, label='SL')
            ax.text(len(ax.get_xlim()) * 0.02, stop_loss, 'SL', 
                   color='red', fontsize=9, fontweight='bold')
            
            ax.legend(loc='upper right', fontsize=8)
            
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
                           fontsize=20, color='green', fontweight='bold',
                           arrowprops=dict(arrowstyle='->', color='green', lw=2))
            else:
                # Mũi tên giảm
                ax.annotate('▼', xy=(last_idx + 0.5, entry_price), 
                           xytext=(last_idx + 2, entry_price * 0.98),
                           fontsize=20, color='red', fontweight='bold',
                           arrowprops=dict(arrowstyle='->', color='red', lw=2))
            
        except Exception as e:
            logger.error(f"Error plotting prediction arrow: {e}")
    
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
