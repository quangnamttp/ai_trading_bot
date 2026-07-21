"""
Module Market Data cho AI Trading Signal Bot
Thu thập dữ liệu thị trường từ nhiều nguồn khác nhau
"""
import logging
import asyncio
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from core.config import BINANCE_API_KEY, BINANCE_API_SECRET, SYMBOLS

logger = logging.getLogger(__name__)


class MarketDataEngine:
    """Thu thập và xử lý dữ liệu thị trường"""
    
    def __init__(self):
        self.exchanges = {}
        self.data_cache = {}
        self.last_update = {}
    
    async def initialize_exchanges(self):
        """Khởi tạo kết nối với các sàn"""
        try:
            # Binance
            self.exchanges['binance'] = ccxt.binance({
                'apiKey': BINANCE_API_KEY,
                'secret': BINANCE_API_SECRET,
                'enableRateLimit': True,
                'options': {'defaultType': 'future'}
            })
            
            # MEXC (không cần API key cho public data)
            self.exchanges['mexc'] = ccxt.mexc({
                'enableRateLimit': True,
                'options': {'defaultType': 'future'}
            })
            
            logger.info("Exchanges initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing exchanges: {e}")
    
    async def get_ticker(self, symbol: str, exchange: str = 'binance') -> Optional[Dict]:
        """Lấy dữ liệu ticker cho symbol"""
        try:
            if exchange not in self.exchanges:
                logger.error(f"Exchange {exchange} not initialized")
                return None
            
            exchange_instance = self.exchanges[exchange]
            ticker = await exchange_instance.fetch_ticker(symbol)
            
            self.data_cache[f"{symbol}_ticker"] = ticker
            self.last_update[f"{symbol}_ticker"] = datetime.now()
            
            return ticker
        except Exception as e:
            logger.error(f"Error fetching ticker for {symbol}: {e}")
            return None
    
    async def get_ohlcv(self, symbol: str, timeframe: str = '1h', 
                       limit: int = 100, exchange: str = 'binance') -> Optional[pd.DataFrame]:
        """Lấy dữ liệu OHLCV (Open, High, Low, Close, Volume)"""
        try:
            if exchange not in self.exchanges:
                logger.error(f"Exchange {exchange} not initialized")
                return None
            
            exchange_instance = self.exchanges[exchange]
            ohlcv = await exchange_instance.fetch_ohlcv(symbol, timeframe, limit=limit)
            
            # Chuyển thành DataFrame
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            self.data_cache[f"{symbol}_ohlcv_{timeframe}"] = df
            self.last_update[f"{symbol}_ohlcv_{timeframe}"] = datetime.now()
            
            return df
        except Exception as e:
            logger.error(f"Error fetching OHLCV for {symbol}: {e}")
            return None
    
    async def get_order_book(self, symbol: str, limit: int = 20, 
                           exchange: str = 'binance') -> Optional[Dict]:
        """Lấy Order Book"""
        try:
            if exchange not in self.exchanges:
                logger.error(f"Exchange {exchange} not initialized")
                return None
            
            exchange_instance = self.exchanges[exchange]
            order_book = await exchange_instance.fetch_order_book(symbol, limit=limit)
            
            self.data_cache[f"{symbol}_orderbook"] = order_book
            self.last_update[f"{symbol}_orderbook"] = datetime.now()
            
            return order_book
        except Exception as e:
            logger.error(f"Error fetching order book for {symbol}: {e}")
            return None
    
    async def get_open_interest(self, symbol: str, exchange: str = 'binance') -> Optional[Dict]:
        """Lấy Open Interest"""
        try:
            if exchange != 'binance':
                logger.warning("Open Interest only available on Binance")
                return None
            
            exchange_instance = self.exchanges[exchange]
            # Binance API endpoint cho Open Interest
            oi_data = await exchange_instance.fetch_open_interest(symbol)
            
            self.data_cache[f"{symbol}_open_interest"] = oi_data
            self.last_update[f"{symbol}_open_interest"] = datetime.now()
            
            return oi_data
        except Exception as e:
            logger.error(f"Error fetching open interest for {symbol}: {e}")
            return None
    
    async def get_funding_rate(self, symbol: str) -> Optional[Dict]:
        """Lấy Funding Rate với fallback logic (MEXC -> Bybit -> OKX)"""
        exchanges = ['mexc', 'bybit', 'okx']
        for exchange in exchanges:
            try:
                if exchange not in self.exchanges:
                    continue

                exchange_instance = self.exchanges[exchange]
                funding_rate = await exchange_instance.fetch_funding_rate(symbol)

                self.data_cache[f"{symbol}_funding_rate"] = funding_rate
                self.last_update[f"{symbol}_funding_rate"] = datetime.now()

                logger.info(f"Successfully fetched funding rate for {symbol} from {exchange}")
                return funding_rate
            except Exception as e:
                logger.warning(f"Failed to fetch funding rate from {exchange} for {symbol}: {e}")

        logger.warning(f"All exchanges failed for funding rate {symbol}, returning N/A")
        return {'fundingRate': 'N/A', 'timestamp': datetime.now().isoformat()}
    
    async def get_liquidations(self, symbol: str) -> Optional[List[Dict]]:
        """Lấy dữ liệu liquidation (giả lập - thực tế cần API premium)"""
        try:
            # Trong thực tế, cần API premium để lấy dữ liệu liquidation
            # Đây là dữ liệu mẫu
            liquidations = []

            # Lấy từ cache nếu có
            cache_key = f"{symbol}_liquidations"
            if cache_key in self.data_cache:
                return self.data_cache[cache_key]

            # Dữ liệu mẫu
            liquidations.append({
                'side': 'long',
                'quantity': 1.5,
                'price': 118000,
                'time': datetime.now()
            })

            self.data_cache[cache_key] = liquidations
            self.last_update[cache_key] = datetime.now()

            return liquidations
        except Exception as e:
            logger.error(f"Error fetching liquidations for {symbol}: {e}")
            return None
    
    async def get_volume_profile(self, symbol: str, timeframe: str = '1h') -> Optional[Dict]:
        """Tính toán Volume Profile"""
        try:
            df = await self.get_ohlcv(symbol, timeframe, limit=100)
            if df is None:
                return None
            
            # Chia giá thành các range
            price_range = df['high'].max() - df['low'].min()
            num_bins = 20
            bin_size = price_range / num_bins
            
            # Tính volume cho mỗi bin
            volume_profile = {}
            for i in range(num_bins):
                lower = df['low'].min() + i * bin_size
                upper = lower + bin_size
                
                # Filter candles trong range này
                mask = (df['low'] >= lower) & (df['high'] <= upper)
                volume = df[mask]['volume'].sum()
                
                volume_profile[f"{lower:.2f}-{upper:.2f}"] = volume
            
            self.data_cache[f"{symbol}_volume_profile"] = volume_profile
            self.last_update[f"{symbol}_volume_profile"] = datetime.now()
            
            return volume_profile
        except Exception as e:
            logger.error(f"Error calculating volume profile for {symbol}: {e}")
            return None
    
    async def get_cvd(self, symbol: str, timeframe: str = '1h') -> Optional[pd.Series]:
        """Tính toán CVD (Cumulative Volume Delta)"""
        try:
            df = await self.get_ohlcv(symbol, timeframe, limit=100)
            if df is None:
                return None
            
            # CVD = Cumulative (Buy Volume - Sell Volume)
            # Giả lập: sử dụng volume và price change
            df['price_change'] = df['close'] - df['open']
            df['buy_volume'] = df['volume'] * (df['price_change'] > 0).astype(int)
            df['sell_volume'] = df['volume'] * (df['price_change'] < 0).astype(int)
            df['delta'] = df['buy_volume'] - df['sell_volume']
            df['cvd'] = df['delta'].cumsum()
            
            cvd = df['cvd']
            
            self.data_cache[f"{symbol}_cvd"] = cvd
            self.last_update[f"{symbol}_cvd"] = datetime.now()
            
            return cvd
        except Exception as e:
            logger.error(f"Error calculating CVD for {symbol}: {e}")
            return None
    
    async def calculate_indicators(self, symbol: str, timeframe: str = '1h') -> Optional[Dict]:
        """Tính toán các chỉ số kỹ thuật"""
        try:
            df = await self.get_ohlcv(symbol, timeframe, limit=100)
            if df is None:
                return None
            
            indicators = {}
            
            # EMA (Exponential Moving Average)
            df['ema_9'] = df['close'].ewm(span=9).mean()
            df['ema_21'] = df['close'].ewm(span=21).mean()
            df['ema_50'] = df['close'].ewm(span=50).mean()
            
            # RSI (Relative Strength Index)
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))
            
            # MACD
            df['ema_12'] = df['close'].ewm(span=12).mean()
            df['ema_26'] = df['close'].ewm(span=26).mean()
            df['macd'] = df['ema_12'] - df['ema_26']
            df['macd_signal'] = df['macd'].ewm(span=9).mean()
            df['macd_histogram'] = df['macd'] - df['macd_signal']
            
            # Bollinger Bands
            df['bb_middle'] = df['close'].rolling(window=20).mean()
            df['bb_std'] = df['close'].rolling(window=20).std()
            df['bb_upper'] = df['bb_middle'] + (df['bb_std'] * 2)
            df['bb_lower'] = df['bb_middle'] - (df['bb_std'] * 2)
            
            # Lấy giá trị hiện tại
            latest = df.iloc[-1]
            
            indicators = {
                'price': latest['close'],
                'ema_9': latest['ema_9'],
                'ema_21': latest['ema_21'],
                'ema_50': latest['ema_50'],
                'rsi': latest['rsi'],
                'macd': latest['macd'],
                'macd_signal': latest['macd_signal'],
                'macd_histogram': latest['macd_histogram'],
                'bb_upper': latest['bb_upper'],
                'bb_middle': latest['bb_middle'],
                'bb_lower': latest['bb_lower'],
                'volume': latest['volume']
            }
            
            self.data_cache[f"{symbol}_indicators"] = indicators
            self.last_update[f"{symbol}_indicators"] = datetime.now()
            
            return indicators
        except Exception as e:
            logger.error(f"Error calculating indicators for {symbol}: {e}")
            return None
    
    async def detect_order_blocks(self, symbol: str, timeframe: str = '1h') -> List[Dict]:
        """Phát hiện Order Blocks"""
        try:
            df = await self.get_ohlcv(symbol, timeframe, limit=100)
            if df is None:
                return []
            
            order_blocks = []
            
            # Tìm bearish order block (candle giảm mạnh với volume lớn)
            for i in range(len(df) - 1):
                if (df.iloc[i]['close'] < df.iloc[i]['open'] and  # Bearish candle
                    df.iloc[i]['volume'] > df['volume'].mean() and  # Volume cao
                    df.iloc[i+1]['close'] < df.iloc[i]['low']):  # Breakout
                    
                    order_blocks.append({
                        'type': 'bearish',
                        'high': df.iloc[i]['high'],
                        'low': df.iloc[i]['low'],
                        'time': df.index[i]
                    })
            
            # Tìm bullish order block
            for i in range(len(df) - 1):
                if (df.iloc[i]['close'] > df.iloc[i]['open'] and  # Bullish candle
                    df.iloc[i]['volume'] > df['volume'].mean() and  # Volume cao
                    df.iloc[i+1]['close'] > df.iloc[i]['high']):  # Breakout
                    
                    order_blocks.append({
                        'type': 'bullish',
                        'high': df.iloc[i]['high'],
                        'low': df.iloc[i]['low'],
                        'time': df.index[i]
                    })
            
            self.data_cache[f"{symbol}_order_blocks"] = order_blocks
            self.last_update[f"{symbol}_order_blocks"] = datetime.now()
            
            return order_blocks
        except Exception as e:
            logger.error(f"Error detecting order blocks for {symbol}: {e}")
            return []
    
    async def detect_fvg(self, symbol: str, timeframe: str = '1h') -> List[Dict]:
        """Phát hiện Fair Value Gaps (FVG)"""
        try:
            df = await self.get_ohlcv(symbol, timeframe, limit=100)
            if df is None:
                return []
            
            fvgs = []
            
            # Bullish FVG: Gap giữa candle i-1 high và candle i+1 low
            for i in range(1, len(df) - 1):
                if df.iloc[i-1]['high'] < df.iloc[i+1]['low']:
                    fvgs.append({
                        'type': 'bullish',
                        'top': df.iloc[i+1]['low'],
                        'bottom': df.iloc[i-1]['high'],
                        'time': df.index[i]
                    })
            
            # Bearish FVG: Gap giữa candle i+1 high và candle i-1 low
            for i in range(1, len(df) - 1):
                if df.iloc[i+1]['high'] < df.iloc[i-1]['low']:
                    fvgs.append({
                        'type': 'bearish',
                        'top': df.iloc[i-1]['low'],
                        'bottom': df.iloc[i+1]['high'],
                        'time': df.index[i]
                    })
            
            self.data_cache[f"{symbol}_fvg"] = fvgs
            self.last_update[f"{symbol}_fvg"] = datetime.now()
            
            return fvgs
        except Exception as e:
            logger.error(f"Error detecting FVG for {symbol}: {e}")
            return []
    
    async def get_market_overview(self) -> str:
        """Lấy tổng quan thị trường"""
        try:
            overview = "📊 *Tổng quan thị trường*\n\n"

            for symbol in SYMBOLS:
                ticker = await self.get_ticker(symbol, exchange='mexc')
                if ticker:
                    change_percent = ticker.get('percentage', 0)
                    emoji = "🟢" if change_percent > 0 else "🔴"

                    overview += f"{emoji} *{symbol}*\n"
                    overview += f"💰 Giá: ${ticker.get('last', 0):,.2f}\n"
                    overview += f"📈 Thay đổi: {change_percent:.2f}%\n"
                    overview += f"📊 Volume: ${ticker.get('quoteVolume', 0):,.0f}\n\n"

            return overview
        except Exception as e:
            logger.error(f"Error getting market overview: {e}")
            return "❌ Không thể lấy dữ liệu thị trường"
    
    async def get_symbol_data(self, symbol: str) -> Dict:
        """Lấy toàn bộ dữ liệu cho một symbol"""
        try:
            data = {
                'symbol': symbol,
                'timestamp': datetime.now().isoformat()
            }

            # Ticker
            ticker = await self.get_ticker(symbol, exchange='mexc')
            if ticker:
                data['ticker'] = ticker

            # Indicators
            indicators = await self.calculate_indicators(symbol)
            if indicators:
                data['indicators'] = indicators

            # Order Book
            order_book = await self.get_order_book(symbol, exchange='mexc')
            if order_book:
                data['order_book'] = order_book

            # Funding Rate
            funding_rate = await self.get_funding_rate(symbol)
            if funding_rate:
                data['funding_rate'] = funding_rate

            # Open Interest
            open_interest = await self.get_open_interest(symbol)
            if open_interest:
                data['open_interest'] = open_interest

            # Order Blocks
            order_blocks = await self.detect_order_blocks(symbol)
            data['order_blocks'] = order_blocks

            # FVG
            fvgs = await self.detect_fvg(symbol)
            data['fvg'] = fvgs

            return data
        except Exception as e:
            logger.error(f"Error getting symbol data for {symbol}: {e}")
            return {}
    
    async def close(self):
        """Đóng kết nối với các sàn"""
        for exchange_name, exchange in self.exchanges.items():
            try:
                await exchange.close()
                logger.info(f"Closed connection to {exchange_name}")
            except Exception as e:
                logger.error(f"Error closing {exchange_name}: {e}")


# Singleton instance
market_data_engine = MarketDataEngine()
