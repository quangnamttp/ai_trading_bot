"""
Comprehensive tests for multi-timeframe signal pipeline
Tests all filters: 4H Macro, 1H Trend, Gann, 15M Entry, ATR, Volume, Funding, AI, R:R, Cooldown, Daily Limit
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timedelta
import math

# Import the signal engine
from analysis.signal_engine import SignalEngine
from data.market_data import MarketDataEngine
from analysis.gann_engine import GannEngine


class TestMultiTimeframePipeline:
    """Test suite for multi-timeframe signal filtering pipeline"""
    
    @pytest.fixture
    def signal_engine(self):
        """Create a fresh SignalEngine instance for each test"""
        engine = SignalEngine()
        # Reset daily counter for testing
        engine.signals_sent_today = 0
        engine.day_start_time = datetime.now().date()
        return engine
    
    @pytest.fixture
    def mock_market_data_engine(self):
        """Mock market data engine"""
        engine = Mock(spec=MarketDataEngine)
        return engine
    
    @pytest.fixture
    def mock_gann_engine(self):
        """Mock Gann engine"""
        engine = Mock(spec=GannEngine)
        return engine
    
    @pytest.fixture
    def sample_ai_analysis_long(self):
        """Sample AI analysis for LONG signal"""
        return {
            'symbol': 'BTC/USDT:USDT',
            'action': 'LONG',
            'ai_score': 85,
            'confidence': 0.85,
            'reasons': ['Strong bullish momentum']
        }
    
    @pytest.fixture
    def sample_ai_analysis_short(self):
        """Sample AI analysis for SHORT signal"""
        return {
            'symbol': 'BTC/USDT:USDT',
            'action': 'SHORT',
            'ai_score': 85,
            'confidence': 0.85,
            'reasons': ['Strong bearish momentum']
        }
    
    @pytest.fixture
    def sample_multi_timeframe_data_bullish(self):
        """Sample multi-timeframe data with bullish alignment"""
        return {
            'symbol': 'BTC/USDT:USDT',
            'timestamp': datetime.now().isoformat(),
            'indicators': {
                '4h': {
                    'price': 100000,
                    'ema_50': 99000,
                    'ema_200': 95000,
                    'atr': 2000,
                    'atr_ma50': 1500
                },
                '1h': {
                    'price': 100000,
                    'ema_50': 99000,
                    'ema_200': 95000,
                    'atr': 500,
                    'atr_ma50': 400
                },
                '15m': {
                    'price': 100000,
                    'ema_20': 99500,
                    'ema_50': 99000,
                    'ema_20_prev': 98900,  # For cross detection
                    'ema_50_prev': 99000,  # For cross detection
                    'atr': 100,
                    'atr_ma50': 80,
                    'volume': 1000000,
                    'volume_ma20': 500000
                }
            },
            'funding_rate': {
                'fundingRate': 0.0001  # 0.01%
            }
        }
    
    @pytest.fixture
    def sample_multi_timeframe_data_bearish(self):
        """Sample multi-timeframe data with bearish alignment"""
        return {
            'symbol': 'BTC/USDT:USDT',
            'timestamp': datetime.now().isoformat(),
            'indicators': {
                '4h': {
                    'price': 90000,
                    'ema_50': 91000,
                    'ema_200': 95000,
                    'atr': 2000,
                    'atr_ma50': 1500
                },
                '1h': {
                    'price': 90000,
                    'ema_50': 91000,
                    'ema_200': 95000,
                    'atr': 500,
                    'atr_ma50': 400
                },
                '15m': {
                    'price': 90000,
                    'ema_20': 90500,
                    'ema_50': 91000,
                    'ema_20_prev': 91100,  # For cross detection
                    'ema_50_prev': 91000,  # For cross detection
                    'atr': 100,
                    'atr_ma50': 80,
                    'volume': 1000000,
                    'volume_ma20': 500000
                }
            },
            'funding_rate': {
                'fundingRate': -0.0001  # -0.01%
            }
        }
    
    @pytest.mark.asyncio
    async def test_daily_limit_reached(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_ai_analysis_long):
        """Test that signals are rejected when daily limit is reached"""
        # Set daily counter to limit
        signal_engine.signals_sent_today = 5  # MAX_SIGNALS_PER_DAY = 5
        
        result = await signal_engine.filter_signal(sample_ai_analysis_long, mock_market_data_engine, mock_gann_engine)
        
        assert result['action'] == 'WAIT'
        assert result['reason'] == 'DAILY_LIMIT_REACHED'
    
    @pytest.mark.asyncio
    async def test_cooldown_active(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_ai_analysis_long):
        """Test that signals are rejected during cooldown period"""
        # Set last signal time to 10 minutes ago (cooldown is 30 minutes)
        signal_engine.last_signal_time['BTC/USDT:USDT'] = datetime.now() - timedelta(minutes=10)
        
        result = await signal_engine.filter_signal(sample_ai_analysis_long, mock_market_data_engine, mock_gann_engine)
        
        assert result['action'] == 'WAIT'
        assert result['reason'] == 'COOLDOWN_ACTIVE'
    
    @pytest.mark.asyncio
    async def test_no_market_data(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_ai_analysis_long):
        """Test that signals are rejected when no market data is available"""
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=None)
        
        result = await signal_engine.filter_signal(sample_ai_analysis_long, mock_market_data_engine, mock_gann_engine)
        
        assert result['action'] == 'WAIT'
        assert result['reason'] == 'NO_MARKET_DATA'
    
    @pytest.mark.asyncio
    async def test_macro_neutral(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_ai_analysis_long):
        """Test that signals are rejected when 4H macro trend is neutral"""
        # Data with neutral 4H trend (EMAs not aligned)
        neutral_data = {
            'symbol': 'BTC/USDT:USDT',
            'timestamp': datetime.now().isoformat(),
            'indicators': {
                '4h': {
                    'price': 100000,
                    'ema_50': 95000,
                    'ema_200': 99000,  # EMA50 < EMA200, not aligned
                    'atr': 2000,
                    'atr_ma50': 1500
                },
                '1h': {
                    'price': 100000,
                    'ema_50': 99000,
                    'ema_200': 95000,
                    'atr': 500,
                    'atr_ma50': 400
                },
                '15m': {
                    'price': 100000,
                    'ema_20': 99500,
                    'ema_50': 99000,
                    'atr': 100,
                    'atr_ma50': 80,
                    'volume': 1000000,
                    'volume_ma20': 500000
                }
            },
            'funding_rate': {'fundingRate': 0.0001}
        }
        
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=neutral_data)
        
        result = await signal_engine.filter_signal(sample_ai_analysis_long, mock_market_data_engine, mock_gann_engine)
        
        assert result['action'] == 'WAIT'
        assert result['reason'] == 'MACRO_NEUTRAL'
    
    @pytest.mark.asyncio
    async def test_trend_mismatch(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_ai_analysis_long):
        """Test that signals are rejected when 1H trend doesn't align with 4H"""
        # 4H bullish, 1H bearish
        mismatched_data = {
            'symbol': 'BTC/USDT:USDT',
            'timestamp': datetime.now().isoformat(),
            'indicators': {
                '4h': {
                    'price': 100000,
                    'ema_50': 99000,
                    'ema_200': 95000,  # Bullish
                    'atr': 2000,
                    'atr_ma50': 1500
                },
                '1h': {
                    'price': 90000,
                    'ema_50': 91000,
                    'ema_200': 95000,  # Bearish
                    'atr': 500,
                    'atr_ma50': 400
                },
                '15m': {
                    'price': 100000,
                    'ema_20': 99500,
                    'ema_50': 99000,
                    'atr': 100,
                    'atr_ma50': 80,
                    'volume': 1000000,
                    'volume_ma20': 500000
                }
            },
            'funding_rate': {'fundingRate': 0.0001}
        }
        
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=mismatched_data)
        
        result = await signal_engine.filter_signal(sample_ai_analysis_long, mock_market_data_engine, mock_gann_engine)
        
        assert result['action'] == 'WAIT'
        assert result['reason'] == 'TREND_MISMATCH'
    
    @pytest.mark.asyncio
    async def test_gann_confidence_low(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_multi_timeframe_data_bullish):
        """Test that signals are rejected when Gann confidence is below threshold"""
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=sample_multi_timeframe_data_bullish)
        mock_gann_engine.analyze = AsyncMock(return_value={
            'trend': 'bullish',
            'confidence': 0.65  # Below threshold of 0.70
        })
        
        ai_analysis = {'symbol': 'BTC/USDT:USDT', 'action': 'LONG', 'ai_score': 85}
        
        result = await signal_engine.filter_signal(ai_analysis, mock_market_data_engine, mock_gann_engine)
        
        assert result['action'] == 'WAIT'
        assert result['reason'] == 'GANN_CONFIDENCE_LOW'
    
    @pytest.mark.asyncio
    async def test_gann_conflict(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_multi_timeframe_data_bullish):
        """Test that signals are rejected when Gann trend conflicts with macro trend"""
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=sample_multi_timeframe_data_bullish)
        mock_gann_engine.analyze = AsyncMock(return_value={
            'trend': 'bearish',  # Conflicts with bullish 4H
            'confidence': 0.80
        })
        
        ai_analysis = {'symbol': 'BTC/USDT:USDT', 'action': 'LONG', 'ai_score': 85}
        
        result = await signal_engine.filter_signal(ai_analysis, mock_market_data_engine, mock_gann_engine)
        
        assert result['action'] == 'WAIT'
        assert result['reason'] == 'GANN_CONFLICT'
    
    @pytest.mark.asyncio
    async def test_entry_ema_neutral(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_multi_timeframe_data_bullish):
        """Test that signals are rejected when 15M entry EMAs are neutral"""
        # 15M EMAs not aligned with bullish trend
        data = sample_multi_timeframe_data_bullish.copy()
        data['indicators']['15m']['ema_20'] = 98500  # Below EMA50
        data['indicators']['15m']['ema_50'] = 99000
        
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=data)
        mock_gann_engine.analyze = AsyncMock(return_value={
            'trend': 'bullish',
            'confidence': 0.80
        })
        
        ai_analysis = {'symbol': 'BTC/USDT:USDT', 'action': 'LONG', 'ai_score': 85}
        
        result = await signal_engine.filter_signal(ai_analysis, mock_market_data_engine, mock_gann_engine)
        
        assert result['action'] == 'WAIT'
        assert result['reason'] == 'EMA_NEUTRAL'
    
    @pytest.mark.asyncio
    async def test_atr_invalid(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_multi_timeframe_data_bullish):
        """Test that signals are rejected when ATR is invalid"""
        data = sample_multi_timeframe_data_bullish.copy()
        data['indicators']['1h']['atr'] = 0  # Invalid ATR
        
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=data)
        mock_gann_engine.analyze = AsyncMock(return_value={
            'trend': 'bullish',
            'confidence': 0.80
        })
        
        ai_analysis = {'symbol': 'BTC/USDT:USDT', 'action': 'LONG', 'ai_score': 85}
        
        result = await signal_engine.filter_signal(ai_analysis, mock_market_data_engine, mock_gann_engine)
        
        assert result['action'] == 'WAIT'
        assert result['reason'] == 'ATR_INVALID'
    
    @pytest.mark.asyncio
    async def test_atr_regime_invalid(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_multi_timeframe_data_bullish):
        """Test that signals are rejected when ATR regime is outside valid range"""
        data = sample_multi_timeframe_data_bullish.copy()
        data['indicators']['1h']['atr'] = 100  # Too low relative to MA50
        data['indicators']['1h']['atr_ma50'] = 200  # Ratio = 0.5 < 0.7
        
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=data)
        mock_gann_engine.analyze = AsyncMock(return_value={
            'trend': 'bullish',
            'confidence': 0.80
        })
        
        ai_analysis = {'symbol': 'BTC/USDT:USDT', 'action': 'LONG', 'ai_score': 85}
        
        result = await signal_engine.filter_signal(ai_analysis, mock_market_data_engine, mock_gann_engine)
        
        assert result['action'] == 'WAIT'
        assert result['reason'] == 'ATR_REGIME_INVALID'
    
    @pytest.mark.asyncio
    async def test_volume_low(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_multi_timeframe_data_bullish):
        """Test that signals are rejected when volume is below threshold"""
        data = sample_multi_timeframe_data_bullish.copy()
        data['indicators']['15m']['volume'] = 500000  # Below 1.5x MA20
        data['indicators']['15m']['volume_ma20'] = 500000
        
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=data)
        mock_gann_engine.analyze = AsyncMock(return_value={
            'trend': 'bullish',
            'confidence': 0.80
        })
        
        ai_analysis = {'symbol': 'BTC/USDT:USDT', 'action': 'LONG', 'ai_score': 85}
        
        result = await signal_engine.filter_signal(ai_analysis, mock_market_data_engine, mock_gann_engine)
        
        assert result['action'] == 'WAIT'
        assert result['reason'] == 'VOLUME_LOW'
    
    @pytest.mark.asyncio
    async def test_funding_extreme(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_multi_timeframe_data_bullish):
        """Test that signals are rejected when funding rate is extreme"""
        data = sample_multi_timeframe_data_bullish.copy()
        data['funding_rate']['fundingRate'] = 0.001  # 0.1% > 0.05% (0.0005)
        
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=data)
        mock_gann_engine.analyze = AsyncMock(return_value={
            'trend': 'bullish',
            'confidence': 0.80
        })
        
        ai_analysis = {'symbol': 'BTC/USDT:USDT', 'action': 'LONG', 'ai_score': 85}
        
        result = await signal_engine.filter_signal(ai_analysis, mock_market_data_engine, mock_gann_engine)
        
        assert result['action'] == 'WAIT'
        assert result['reason'] == 'FUNDING_EXTREME'
    
    @pytest.mark.asyncio
    async def test_ai_score_below_threshold(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_multi_timeframe_data_bullish):
        """Test that signals are rejected when AI score is below threshold"""
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=sample_multi_timeframe_data_bullish)
        mock_gann_engine.analyze = AsyncMock(return_value={
            'trend': 'bullish',
            'confidence': 0.80
        })
        
        ai_analysis = {'symbol': 'BTC/USDT:USDT', 'action': 'LONG', 'ai_score': 75}  # Below 80
        
        result = await signal_engine.filter_signal(ai_analysis, mock_market_data_engine, mock_gann_engine)
        
        assert result['action'] == 'WAIT'
        assert result['reason'] == 'AI_SCORE_BELOW_THRESHOLD'
    
    @pytest.mark.asyncio
    async def test_macro_conflict_long(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_multi_timeframe_data_bearish):
        """Test that LONG signals are rejected when macro trend is bearish"""
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=sample_multi_timeframe_data_bearish)
        mock_gann_engine.analyze = AsyncMock(return_value={
            'trend': 'bearish',
            'confidence': 0.80
        })
        
        ai_analysis = {'symbol': 'BTC/USDT:USDT', 'action': 'LONG', 'ai_score': 85}
        
        result = await signal_engine.filter_signal(ai_analysis, mock_market_data_engine, mock_gann_engine)
        
        assert result['action'] == 'WAIT'
        assert result['reason'] == 'MACRO_CONFLICT'
    
    @pytest.mark.asyncio
    async def test_macro_conflict_short(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_multi_timeframe_data_bullish):
        """Test that SHORT signals are rejected when macro trend is bullish"""
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=sample_multi_timeframe_data_bullish)
        mock_gann_engine.analyze = AsyncMock(return_value={
            'trend': 'bullish',
            'confidence': 0.80
        })
        
        ai_analysis = {'symbol': 'BTC/USDT:USDT', 'action': 'SHORT', 'ai_score': 85}
        
        result = await signal_engine.filter_signal(ai_analysis, mock_market_data_engine, mock_gann_engine)
        
        assert result['action'] == 'WAIT'
        assert result['reason'] == 'MACRO_CONFLICT'
    
    @pytest.mark.asyncio
    async def test_rr_passes(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_multi_timeframe_data_bullish):
        """Test that R:R filter passes when calculated R:R is above minimum"""
        # The implementation calculates R:R as 2.2/1.2 = 1.83, which is above 1.8
        # This test verifies the filter passes when R:R is acceptable
        
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=sample_multi_timeframe_data_bullish)
        mock_gann_engine.analyze = AsyncMock(return_value={
            'trend': 'bullish',
            'confidence': 0.80
        })
        
        ai_analysis = {'symbol': 'BTC/USDT:USDT', 'action': 'LONG', 'ai_score': 85}
        
        result = await signal_engine.filter_signal(ai_analysis, mock_market_data_engine, mock_gann_engine)
        
        # R:R should pass (1.83 > 1.8), so signal should either pass or fail on another filter
        # It should NOT fail on RR_TOO_LOW
        assert result['reason'] != 'RR_TOO_LOW'
    
    @pytest.mark.asyncio
    async def test_all_filters_passed_long(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_multi_timeframe_data_bullish):
        """Test that LONG signals pass when all filters are satisfied"""
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=sample_multi_timeframe_data_bullish)
        mock_gann_engine.analyze = AsyncMock(return_value={
            'trend': 'bullish',
            'confidence': 0.80
        })
        
        ai_analysis = {'symbol': 'BTC/USDT:USDT', 'action': 'LONG', 'ai_score': 85}
        
        result = await signal_engine.filter_signal(ai_analysis, mock_market_data_engine, mock_gann_engine)
        
        # All filters should pass
        assert result['action'] == 'LONG'
        assert result['reason'] == 'ALL_FILTERS_PASSED'
        assert 'symbol_data' in result
        assert 'gann_analysis' in result
    
    @pytest.mark.asyncio
    async def test_missing_ema_values(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_ai_analysis_long):
        """Test that signals are rejected when EMA values are missing or NaN"""
        data = {
            'symbol': 'BTC/USDT:USDT',
            'timestamp': datetime.now().isoformat(),
            'indicators': {
                '4h': {
                    'price': 100000,
                    'ema_50': 0,  # Missing
                    'ema_200': 95000,
                    'atr': 2000,
                    'atr_ma50': 1500
                },
                '1h': {
                    'price': 100000,
                    'ema_50': 99000,
                    'ema_200': 95000,
                    'atr': 500,
                    'atr_ma50': 400
                },
                '15m': {
                    'price': 100000,
                    'ema_20': 99500,
                    'ema_50': 99000,
                    'atr': 100,
                    'atr_ma50': 80,
                    'volume': 1000000,
                    'volume_ma20': 500000
                }
            },
            'funding_rate': {'fundingRate': 0.0001}
        }
        
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=data)
        
        result = await signal_engine.filter_signal(sample_ai_analysis_long, mock_market_data_engine, mock_gann_engine)
        
        assert result['action'] == 'WAIT'
        assert result['reason'] == 'MACRO_NEUTRAL'
    
    @pytest.mark.asyncio
    async def test_nan_ema_values(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_ai_analysis_long):
        """Test that signals are rejected when EMA values are NaN"""
        data = {
            'symbol': 'BTC/USDT:USDT',
            'timestamp': datetime.now().isoformat(),
            'indicators': {
                '4h': {
                    'price': 100000,
                    'ema_50': float('nan'),  # NaN
                    'ema_200': 95000,
                    'atr': 2000,
                    'atr_ma50': 1500
                },
                '1h': {
                    'price': 100000,
                    'ema_50': 99000,
                    'ema_200': 95000,
                    'atr': 500,
                    'atr_ma50': 400
                },
                '15m': {
                    'price': 100000,
                    'ema_20': 99500,
                    'ema_50': 99000,
                    'atr': 100,
                    'atr_ma50': 80,
                    'volume': 1000000,
                    'volume_ma20': 500000
                }
            },
            'funding_rate': {'fundingRate': 0.0001}
        }
        
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=data)
        
        result = await signal_engine.filter_signal(sample_ai_analysis_long, mock_market_data_engine, mock_gann_engine)
        
        assert result['action'] == 'WAIT'
        assert result['reason'] == 'MACRO_NEUTRAL'
    
    def test_daily_limit_reset(self, signal_engine):
        """Test that daily limit resets on new day"""
        with patch('analysis.signal_engine.datetime') as mock_datetime:
            # Set to yesterday
            yesterday = datetime.now().date() - timedelta(days=1)
            signal_engine.day_start_time = yesterday
            signal_engine.signals_sent_today = 5
            
            # Mock datetime.now().date() to return today
            mock_datetime.now.return_value.date.return_value = datetime.now().date()
            
            # Check daily limit should reset
            result = signal_engine._check_daily_limit()
            
            assert result is True
            assert signal_engine.signals_sent_today == 0
    
    def test_increment_daily_count(self, signal_engine):
        """Test that daily count increments correctly"""
        initial_count = signal_engine.signals_sent_today
        signal_engine._increment_daily_count()
        
        assert signal_engine.signals_sent_today == initial_count + 1
    
    @pytest.mark.asyncio
    async def test_ema_no_cross(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_multi_timeframe_data_bullish):
        """Test that signals are rejected when EMA20/EMA50 cross is not detected"""
        # Data with aligned EMAs but no cross (already aligned for multiple candles)
        data = sample_multi_timeframe_data_bullish.copy()
        data['indicators']['15m']['ema_20_prev'] = 99400  # Already above EMA50
        data['indicators']['15m']['ema_50_prev'] = 98900  # Still below EMA20
        
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=data)
        mock_gann_engine.analyze = AsyncMock(return_value={
            'trend': 'bullish',
            'confidence': 0.80,
            'support': 98000,
            'resistance': 102000
        })
        
        ai_analysis = {'symbol': 'BTC/USDT:USDT', 'action': 'LONG', 'ai_score': 85}
        
        result = await signal_engine.filter_signal(ai_analysis, mock_market_data_engine, mock_gann_engine)
        
        assert result['action'] == 'WAIT'
        assert result['reason'] == 'EMA_NO_CROSS'
    
    @pytest.mark.asyncio
    async def test_ema_cross_detected(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_multi_timeframe_data_bullish):
        """Test that signals pass when EMA20/EMA50 cross is detected"""
        # Data with bullish cross in current candle
        data = sample_multi_timeframe_data_bullish.copy()
        data['indicators']['15m']['ema_20_prev'] = 98900  # Below EMA50
        data['indicators']['15m']['ema_50_prev'] = 99000  # Above EMA20 (cross happened)
        
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=data)
        mock_gann_engine.analyze = AsyncMock(return_value={
            'trend': 'bullish',
            'confidence': 0.80,
            'support': 98000,
            'resistance': 102000
        })
        
        ai_analysis = {'symbol': 'BTC/USDT:USDT', 'action': 'LONG', 'ai_score': 85}
        
        result = await signal_engine.filter_signal(ai_analysis, mock_market_data_engine, mock_gann_engine)
        
        # Should not fail on EMA_NO_CROSS
        assert result['reason'] != 'EMA_NO_CROSS'
    
    @pytest.mark.asyncio
    async def test_gann_too_far(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_multi_timeframe_data_bullish):
        """Test that signals are rejected when price is too far from Gann level"""
        # Data with price far from Gann resistance
        data = sample_multi_timeframe_data_bullish.copy()
        data['indicators']['15m']['ema_20_prev'] = 98900
        data['indicators']['15m']['ema_50_prev'] = 99000
        
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=data)
        mock_gann_engine.analyze = AsyncMock(return_value={
            'trend': 'bullish',
            'confidence': 0.80,
            'support': 98000,
            'resistance': 105000  # Far from price (100000)
        })
        
        ai_analysis = {'symbol': 'BTC/USDT:USDT', 'action': 'LONG', 'ai_score': 85}
        
        result = await signal_engine.filter_signal(ai_analysis, mock_market_data_engine, mock_gann_engine)
        
        assert result['action'] == 'WAIT'
        assert result['reason'] == 'GANN_TOO_FAR'
    
    @pytest.mark.asyncio
    async def test_gann_proximity_ok(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_multi_timeframe_data_bullish):
        """Test that signals pass when price is within Gann proximity threshold"""
        # Data with price close to Gann resistance (within 0.3 * ATR)
        data = sample_multi_timeframe_data_bullish.copy()
        data['indicators']['15m']['ema_20_prev'] = 98900
        data['indicators']['15m']['ema_50_prev'] = 99000
        data['indicators']['15m']['atr'] = 100  # 0.3 * 100 = 30
        
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=data)
        mock_gann_engine.analyze = AsyncMock(return_value={
            'trend': 'bullish',
            'confidence': 0.80,
            'support': 98000,
            'resistance': 100025  # Within 30 of price (100000)
        })
        
        ai_analysis = {'symbol': 'BTC/USDT:USDT', 'action': 'LONG', 'ai_score': 85}
        
        result = await signal_engine.filter_signal(ai_analysis, mock_market_data_engine, mock_gann_engine)
        
        # Should not fail on GANN_TOO_FAR
        assert result['reason'] != 'GANN_TOO_FAR'
    
    @pytest.mark.asyncio
    async def test_atr_ma50_invalid(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_multi_timeframe_data_bullish):
        """Test that signals are rejected when ATR_MA50 is missing or invalid"""
        data = sample_multi_timeframe_data_bullish.copy()
        data['indicators']['15m']['ema_20_prev'] = 98900
        data['indicators']['15m']['ema_50_prev'] = 99000
        data['indicators']['1h']['atr_ma50'] = 0  # Invalid
        
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=data)
        mock_gann_engine.analyze = AsyncMock(return_value={
            'trend': 'bullish',
            'confidence': 0.80,
            'support': 98000,
            'resistance': 100025  # Within Gann proximity threshold
        })
        
        ai_analysis = {'symbol': 'BTC/USDT:USDT', 'action': 'LONG', 'ai_score': 85}
        
        result = await signal_engine.filter_signal(ai_analysis, mock_market_data_engine, mock_gann_engine)
        
        assert result['action'] == 'WAIT'
        assert result['reason'] == 'ATR_MA50_INVALID'
    
    @pytest.mark.asyncio
    async def test_volume_ma20_invalid(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_multi_timeframe_data_bullish):
        """Test that signals are rejected when Volume_MA20 is missing or invalid"""
        data = sample_multi_timeframe_data_bullish.copy()
        data['indicators']['15m']['ema_20_prev'] = 98900
        data['indicators']['15m']['ema_50_prev'] = 99000
        data['indicators']['15m']['volume_ma20'] = 0  # Invalid
        
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=data)
        mock_gann_engine.analyze = AsyncMock(return_value={
            'trend': 'bullish',
            'confidence': 0.80,
            'support': 98000,
            'resistance': 100025  # Within Gann proximity threshold
        })
        
        ai_analysis = {'symbol': 'BTC/USDT:USDT', 'action': 'LONG', 'ai_score': 85}
        
        result = await signal_engine.filter_signal(ai_analysis, mock_market_data_engine, mock_gann_engine)
        
        assert result['action'] == 'WAIT'
        assert result['reason'] == 'VOLUME_MA20_INVALID'
    
    @pytest.mark.asyncio
    async def test_funding_missing(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_multi_timeframe_data_bullish):
        """Test that signals are rejected when funding data is missing"""
        data = sample_multi_timeframe_data_bullish.copy()
        data['indicators']['15m']['ema_20_prev'] = 98900
        data['indicators']['15m']['ema_50_prev'] = 99000
        data['funding_rate'] = {}  # Missing
        
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=data)
        mock_gann_engine.analyze = AsyncMock(return_value={
            'trend': 'bullish',
            'confidence': 0.80,
            'support': 98000,
            'resistance': 100025  # Within Gann proximity threshold
        })
        
        ai_analysis = {'symbol': 'BTC/USDT:USDT', 'action': 'LONG', 'ai_score': 85}
        
        result = await signal_engine.filter_signal(ai_analysis, mock_market_data_engine, mock_gann_engine)
        
        assert result['action'] == 'WAIT'
        assert result['reason'] == 'FUNDING_MISSING'
    
    @pytest.mark.asyncio
    async def test_funding_invalid(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_multi_timeframe_data_bullish):
        """Test that signals are rejected when funding rate is invalid"""
        data = sample_multi_timeframe_data_bullish.copy()
        data['indicators']['15m']['ema_20_prev'] = 98900
        data['indicators']['15m']['ema_50_prev'] = 99000
        data['funding_rate']['fundingRate'] = float('nan')  # Invalid
        
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=data)
        mock_gann_engine.analyze = AsyncMock(return_value={
            'trend': 'bullish',
            'confidence': 0.80,
            'support': 98000,
            'resistance': 100025  # Within Gann proximity threshold
        })
        
        ai_analysis = {'symbol': 'BTC/USDT:USDT', 'action': 'LONG', 'ai_score': 85}
        
        result = await signal_engine.filter_signal(ai_analysis, mock_market_data_engine, mock_gann_engine)
        
        assert result['action'] == 'WAIT'
        assert result['reason'] == 'FUNDING_INVALID'
    
    @pytest.mark.asyncio
    async def test_rr_calculation_from_actual_sl_tp(self, signal_engine, mock_market_data_engine, mock_gann_engine, sample_multi_timeframe_data_bullish):
        """Test that RR is calculated from actual SL/TP values (SL=1.2x, TP1=2.0x)"""
        data = sample_multi_timeframe_data_bullish.copy()
        data['indicators']['15m']['ema_20_prev'] = 98900
        data['indicators']['15m']['ema_50_prev'] = 99000
        
        mock_market_data_engine.get_symbol_data = AsyncMock(return_value=data)
        mock_gann_engine.analyze = AsyncMock(return_value={
            'trend': 'bullish',
            'confidence': 0.80,
            'support': 98000,
            'resistance': 102000
        })
        
        ai_analysis = {'symbol': 'BTC/USDT:USDT', 'action': 'LONG', 'ai_score': 85}
        
        result = await signal_engine.filter_signal(ai_analysis, mock_market_data_engine, mock_gann_engine)
        
        # RR = TP1 / SL = 2.0 / 1.2 = 1.67, which is >= 1.6 (new RR_MIN)
        # Should not fail on RR_TOO_LOW
        assert result['reason'] != 'RR_TOO_LOW'
    
    def test_sl_tp_calculation_15m_atr(self, signal_engine):
        """Test that SL/TP are calculated using 15m ATR values"""
        price = 100000
        atr_15m = 100
        
        # Test LONG
        tp_long = signal_engine.calculate_take_profit(price, 'LONG', atr_15m, 102000)
        sl_long = signal_engine.calculate_stop_loss(price, 'LONG', atr_15m)
        
        # SL = price - 1.2 * ATR = 100000 - 120 = 99880
        assert sl_long == 99880
        # TP1 = price + 2.0 * ATR = 100000 + 200 = 100200
        assert tp_long['TP1'] == 100200
        # TP2 = price + 3.5 * ATR = 100000 + 350 = 100350
        assert tp_long['TP2'] == 100350
        # TP3 should use Gann level (102000) since it's above TP2
        assert tp_long['TP3'] == 102000
        
        # Test SHORT
        tp_short = signal_engine.calculate_take_profit(price, 'SHORT', atr_15m, 98000)
        sl_short = signal_engine.calculate_stop_loss(price, 'SHORT', atr_15m)
        
        # SL = price + 1.2 * ATR = 100000 + 120 = 100120
        assert sl_short == 100120
        # TP1 = price - 2.0 * ATR = 100000 - 200 = 99800
        assert tp_short['TP1'] == 99800
        # TP2 = price - 3.5 * ATR = 100000 - 350 = 99650
        assert tp_short['TP2'] == 99650
        # TP3 should use Gann level (98000) since it's below TP2
        assert tp_short['TP3'] == 98000


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
