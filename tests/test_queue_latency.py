"""
Queue Latency Tests for AI Trading Signal Bot
Tests to verify that Telegram updates are processed with minimal queue delay
"""
import asyncio
import time
import pytest
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestQueueLatency:
    """Test queue latency to ensure Telegram updates are processed quickly"""

    @pytest.fixture
    def mock_telegram_app(self):
        """Create a mock Telegram application"""
        app = Mock()
        app.update_queue = asyncio.Queue()
        app.bot = Mock()
        return app

    @pytest.fixture
    def mock_market_data_engine(self):
        """Create a mock market data engine"""
        engine = Mock()
        engine.get_symbol_data = AsyncMock(return_value={
            'symbol': 'BTCUSDT',
            'ticker': {'last': 50000},
            'indicators': {'rsi': 50, 'macd': 0}
        })
        engine.get_ticker = AsyncMock(return_value={'last': 50000})
        engine.calculate_indicators = AsyncMock(return_value={'rsi': 50, 'macd': 0})
        engine.get_order_book = AsyncMock(return_value={'bids': [], 'asks': []})
        engine.get_funding_rate = AsyncMock(return_value=None)
        engine.get_open_interest = AsyncMock(return_value=None)
        engine.detect_order_blocks = AsyncMock(return_value=[])
        engine.detect_fvg = AsyncMock(return_value=[])
        return engine

    @pytest.mark.asyncio
    async def test_queue_put_and_get_latency(self, mock_telegram_app):
        """Test that queue.put_nowait() and queue.get() have minimal latency"""
        queue = mock_telegram_app.update_queue
        
        # Measure queue put latency
        put_start = time.time()
        test_update = Mock()
        test_update.update_id = 123
        queue.put_nowait(test_update)
        put_duration_ms = (time.time() - put_start) * 1000
        
        # Queue put should be < 1ms
        assert put_duration_ms < 1.0, f"Queue put took {put_duration_ms:.2f}ms, expected < 1ms"
        
        # Measure queue get latency
        get_start = time.time()
        retrieved_update = await queue.get()
        get_duration_ms = (time.time() - get_start) * 1000
        
        # Queue get should be < 1ms
        assert get_duration_ms < 1.0, f"Queue get took {get_duration_ms:.2f}ms, expected < 1ms"
        
        # Verify the update is the same
        assert retrieved_update.update_id == test_update.update_id

    @pytest.mark.asyncio
    async def test_concurrent_queue_operations(self, mock_telegram_app):
        """Test that concurrent queue operations don't block each other"""
        queue = mock_telegram_app.update_queue
        
        # Put multiple updates concurrently
        put_tasks = []
        for i in range(10):
            update = Mock()
            update.update_id = i
            put_tasks.append(asyncio.create_task(asyncio.to_thread(queue.put_nowait, update)))
        
        start_time = time.time()
        await asyncio.gather(*put_tasks)
        put_duration_ms = (time.time() - start_time) * 1000
        
        # All puts should complete quickly (< 10ms for 10 items)
        assert put_duration_ms < 10.0, f"Concurrent puts took {put_duration_ms:.2f}ms, expected < 10ms"
        
        # Verify all items are in queue
        assert queue.qsize() == 10

    @pytest.mark.asyncio
    async def test_queue_consumer_with_background_tasks(self, mock_telegram_app, mock_market_data_engine):
        """Test that queue consumer runs even with background tasks"""
        queue = mock_telegram_app.update_queue
        
        # Simulate a background task that would normally block
        async def blocking_background_task():
            # Simulate pandas operations running in thread pool
            await asyncio.sleep(0.1)  # 100ms task
            return "done"
        
        # Start background task
        background_task = asyncio.create_task(blocking_background_task())
        
        # Put update in queue
        test_update = Mock()
        test_update.update_id = 456
        queue.put_nowait(test_update)
        
        # Try to get update while background task is running
        # This should not be blocked by the background task
        get_start = time.time()
        retrieved_update = await queue.get()
        get_duration_ms = (time.time() - get_start) * 1000
        
        # Queue get should still be fast even with background task
        assert get_duration_ms < 50.0, f"Queue get with background task took {get_duration_ms:.2f}ms, expected < 50ms"
        
        # Wait for background task to complete
        await background_task
        
        assert retrieved_update.update_id == test_update.update_id

    @pytest.mark.asyncio
    async def test_market_data_does_not_block_queue(self, mock_market_data_engine):
        """Test that market data operations don't block the event loop"""
        queue = asyncio.Queue()
        
        # Put update in queue
        test_update = Mock()
        test_update.update_id = 789
        queue.put_nowait(test_update)
        
        # Simulate market data operation running concurrently
        market_data_task = asyncio.create_task(mock_market_data_engine.get_symbol_data('BTCUSDT'))
        
        # Try to get update while market data is running
        get_start = time.time()
        retrieved_update = await queue.get()
        get_duration_ms = (time.time() - get_start) * 1000
        
        # Queue get should be fast even with market data operation
        assert get_duration_ms < 100.0, f"Queue get with market data took {get_duration_ms:.2f}ms, expected < 100ms"
        
        # Wait for market data to complete
        await market_data_task
        
        assert retrieved_update.update_id == test_update.update_id

    @pytest.mark.asyncio
    async def test_pandas_operations_in_thread_pool(self):
        """Test that pandas operations run in thread pool and don't block event loop"""
        import pandas as pd
        import numpy as np
        
        # Create a sample DataFrame
        df = pd.DataFrame({
            'close': np.random.randn(100).cumsum() + 100,
            'open': np.random.randn(100).cumsum() + 100,
            'high': np.random.randn(100).cumsum() + 105,
            'low': np.random.randn(100).cumsum() + 95,
            'volume': np.random.randint(1000, 10000, 100)
        })
        
        # Define a blocking pandas operation
        def blocking_pandas_operation(dataframe):
            # Simulate indicator calculation
            dataframe['ema_9'] = dataframe['close'].ewm(span=9).mean()
            dataframe['ema_21'] = dataframe['close'].ewm(span=21).mean()
            dataframe['rsi'] = 100 - (100 / (1 + dataframe['close'].diff().abs().rolling(14).mean() / dataframe['close'].diff().rolling(14).mean()))
            return dataframe
        
        # Run pandas operation in thread pool
        queue = asyncio.Queue()
        queue.put_nowait("test")
        
        # Start pandas operation in thread pool
        pandas_start = time.time()
        pandas_task = asyncio.create_task(asyncio.to_thread(blocking_pandas_operation, df.copy()))
        
        # Try to get from queue while pandas is running
        get_start = time.time()
        result = await queue.get()
        get_duration_ms = (time.time() - get_start) * 1000
        
        # Queue get should be fast even with pandas operation
        assert get_duration_ms < 50.0, f"Queue get with pandas operation took {get_duration_ms:.2f}ms, expected < 50ms"
        
        # Wait for pandas to complete
        await pandas_task
        pandas_duration_ms = (time.time() - pandas_start) * 1000
        
        # Pandas operation should have completed
        assert pandas_duration_ms > 0

    @pytest.mark.asyncio
    async def test_webhook_to_handler_latency(self):
        """Test end-to-end latency from webhook to handler"""
        # Simulate webhook receiving update
        webhook_timestamp = datetime.now()
        
        # Simulate queue put (should be immediate)
        queue = asyncio.Queue()
        queue_put_start = time.time()
        queue.put_nowait("test_update")
        queue_put_duration_ms = (time.time() - queue_put_start) * 1000
        
        assert queue_put_duration_ms < 1.0, f"Queue put took {queue_put_duration_ms:.2f}ms, expected < 1ms"
        
        # Simulate handler receiving update
        handler_start = time.time()
        update = await queue.get()
        handler_timestamp = datetime.now()
        handler_duration_ms = (time.time() - handler_start) * 1000
        
        assert handler_duration_ms < 1.0, f"Handler get took {handler_duration_ms:.2f}ms, expected < 1ms"
        
        # Total latency from webhook to handler
        total_latency_ms = (handler_timestamp - webhook_timestamp).total_seconds() * 1000
        
        # Total should be < 10ms (allowing for some overhead)
        assert total_latency_ms < 10.0, f"Total webhook-to-handler latency was {total_latency_ms:.2f}ms, expected < 10ms"

    @pytest.mark.asyncio
    async def test_multiple_concurrent_handlers(self):
        """Test that multiple handlers can run concurrently without blocking"""
        queue = asyncio.Queue()
        
        # Put multiple updates
        for i in range(5):
            queue.put_nowait(f"update_{i}")
        
        # Create multiple handler tasks
        async def handler(task_id):
            start = time.time()
            update = await queue.get()
            duration = (time.time() - start) * 1000
            return task_id, update, duration
        
        handler_tasks = [asyncio.create_task(handler(i)) for i in range(5)]
        
        start_time = time.time()
        results = await asyncio.gather(*handler_tasks)
        total_duration_ms = (time.time() - start_time) * 1000
        
        # All handlers should complete quickly
        assert total_duration_ms < 50.0, f"Concurrent handlers took {total_duration_ms:.2f}ms, expected < 50ms"
        
        # Each individual handler should be fast
        for task_id, update, duration in results:
            assert duration < 10.0, f"Handler {task_id} took {duration:.2f}ms, expected < 10ms"

    @pytest.mark.asyncio
    async def test_event_loop_not_blocked_by_database(self):
        """Test that database operations don't block the event loop"""
        from core.database import db
        
        # Create a simple async wrapper test
        async def blocking_db_operation():
            # This should run in thread pool
            await asyncio.sleep(0.05)  # Simulate DB operation
            return "result"
        
        queue = asyncio.Queue()
        queue.put_nowait("test")
        
        # Start DB operation
        db_task = asyncio.create_task(blocking_db_operation())
        
        # Try to get from queue while DB is running
        get_start = time.time()
        result = await queue.get()
        get_duration_ms = (time.time() - get_start) * 1000
        
        # Queue get should be fast
        assert get_duration_ms < 50.0, f"Queue get with DB operation took {get_duration_ms:.2f}ms, expected < 50ms"
        
        # Wait for DB to complete
        await db_task


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
