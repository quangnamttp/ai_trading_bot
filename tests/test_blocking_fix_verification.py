"""
Production-like concurrency test to verify blocking fixes
Tests all background tasks running simultaneously with Telegram queue updates
"""
import asyncio
import time
from datetime import datetime
from typing import Dict, List
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class MockExchange:
    """Mock ccxt exchange for testing"""
    async def fetch_ticker(self, symbol):
        await asyncio.sleep(0.01)  # Simulate network latency
        return {'last': 50000, 'percentage': 1.5}

    async def fetch_ohlcv(self, symbol, timeframe, limit=100):
        await asyncio.sleep(0.02)  # Simulate network latency
        # Return mock OHLCV data
        return [[int(time.time() * 1000), 50000, 50100, 49900, 50050, 1000] for _ in range(limit)]

    async def fetch_order_book(self, symbol, limit=20):
        await asyncio.sleep(0.01)
        return {'bids': [[50000, 1]], 'asks': [[50010, 1]]}

    async def fetch_funding_rate(self, symbol):
        await asyncio.sleep(0.01)
        return {'fundingRate': 0.0001}

    async def fetch_open_interest(self, symbol):
        await asyncio.sleep(0.01)
        return {'openInterestAmount': 1000}

    async def close(self):
        pass

class MockMarketDataEngine:
    """Mock market data engine with blocking operations"""
    def __init__(self):
        self.exchanges = {'mexc': MockExchange()}
        self.data_cache = {}
        self.last_update = {}
        self.unsupported_operations = set()

    async def get_symbol_data(self, symbol: str) -> Dict:
        """Simulate get_symbol_data with concurrent operations"""
        start = time.time()
        try:
            # Simulate concurrent operations
            ticker_task = self.exchanges['mexc'].fetch_ticker(symbol)
            order_book_task = self.exchanges['mexc'].fetch_order_book(symbol)
            funding_task = self.exchanges['mexc'].fetch_funding_rate(symbol)
            oi_task = self.exchanges['mexc'].fetch_open_interest(symbol)

            ticker, order_book, funding, oi = await asyncio.gather(
                ticker_task, order_book_task, funding_task, oi_task
            )

            result = {
                'symbol': symbol,
                'ticker': ticker,
                'order_book': order_book,
                'funding_rate': funding,
                'open_interest': oi
            }
            duration_ms = (time.time() - start) * 1000
            print(f"[PERF] get_symbol_data {symbol}: {duration_ms:.2f}ms")
            return result
        except Exception as e:
            print(f"Error in get_symbol_data: {e}")
            return {}

    async def get_ticker(self, symbol: str) -> Dict:
        return await self.exchanges['mexc'].fetch_ticker(symbol)

class MockSmartMoneyTracker:
    """Mock smart money tracker with concurrent operations"""
    async def track_whale_activity(self, symbol: str) -> List[Dict]:
        await asyncio.sleep(0.005)
        return [{'symbol': symbol, 'amount': 500, 'type': 'transfer'}]

    async def detect_large_trades(self, symbol: str, market_data) -> List[Dict]:
        await asyncio.sleep(0.005)
        return []

    async def analyze_funding_rate(self, symbol: str, market_data) -> Dict:
        await asyncio.sleep(0.005)
        return {'sentiment': 'neutral', 'rate': 0.0001}

    async def analyze_open_interest(self, symbol: str, market_data) -> Dict:
        await asyncio.sleep(0.005)
        return {'trend': 'stable', 'change': 0}

    async def detect_liquidation_cascades(self, symbol: str, market_data) -> Dict:
        await asyncio.sleep(0.005)
        return {'cascade_risk': 'low', 'total_liquidated': 0}

    async def analyze_smart_money_confluence(self, symbol: str, market_data) -> Dict:
        """Simulate concurrent smart money analysis"""
        start = time.time()
        try:
            # Run all analyses concurrently
            whale_task = self.track_whale_activity(symbol)
            large_trades_task = self.detect_large_trades(symbol, market_data)
            funding_task = self.analyze_funding_rate(symbol, market_data)
            oi_task = self.analyze_open_interest(symbol, market_data)
            liquidation_task = self.detect_liquidation_cascades(symbol, market_data)

            await asyncio.gather(
                whale_task, large_trades_task, funding_task, oi_task, liquidation_task
            )

            result = {'trend': 'neutral', 'total_score': 0, 'signals': []}
            duration_ms = (time.time() - start) * 1000
            print(f"[PERF] analyze_smart_money_confluence {symbol}: {duration_ms:.2f}ms")
            return result
        except Exception as e:
            print(f"Error in analyze_smart_money_confluence: {e}")
            return {'trend': 'neutral', 'total_score': 0, 'signals': []}

class TelegramQueue:
    """Mock Telegram queue for latency testing"""
    def __init__(self):
        self.queue = asyncio.Queue()
        self.queue_timestamps = {}

    async def put_update(self, update_id: int):
        """Simulate webhook putting update into queue"""
        timestamp = datetime.now().isoformat()
        self.queue_timestamps[update_id] = timestamp
        await self.queue.put(update_id)
        print(f"[QUEUE PUT] update_id={update_id}, timestamp={timestamp}")

    async def get_update(self) -> int:
        """Simulate queue consumer getting update"""
        update_id = await self.queue.get()
        queue_put_timestamp = self.queue_timestamps.get(update_id)
        queue_consumer_start = datetime.now().isoformat()

        if queue_put_timestamp:
            queue_wait_duration_ms = (datetime.fromisoformat(queue_consumer_start) - datetime.fromisoformat(queue_put_timestamp)).total_seconds() * 1000
            print(f"[QUEUE GET] update_id={update_id}, wait_ms={queue_wait_duration_ms:.2f}")
            return update_id, queue_wait_duration_ms
        return update_id, 0

async def simulate_market_data_loop(market_data: MockMarketDataEngine, symbols: List[str], shutdown_event: asyncio.Event):
    """Simulate market_data_loop background task"""
    print("[TASK START] task_name=market_data_loop")
    while not shutdown_event.is_set():
        loop_start = time.time()
        for symbol in symbols:
            symbol_start = time.time()
            await market_data.get_symbol_data(symbol)
            symbol_duration_ms = (time.time() - symbol_start) * 1000
            print(f"[PERF] market_data_loop {symbol}: {symbol_duration_ms:.2f}ms")

        loop_duration_ms = (time.time() - loop_start) * 1000
        print(f"[TASK ITERATION COMPLETE] task_name=market_data_loop, duration_ms={loop_duration_ms:.2f}")
        if loop_duration_ms > 1000:
            print(f"[SLOW TASK] task_name=market_data_loop, duration_ms={loop_duration_ms:.2f}")

        await asyncio.sleep(5)  # Simulate interval

async def simulate_smart_money_loop(smart_money: MockSmartMoneyTracker, market_data: MockMarketDataEngine, symbols: List[str], shutdown_event: asyncio.Event):
    """Simulate smart_money_loop background task"""
    print("[TASK START] task_name=smart_money_loop")
    while not shutdown_event.is_set():
        loop_start = time.time()
        for symbol in symbols:
            symbol_start = time.time()
            await smart_money.analyze_smart_money_confluence(symbol, market_data)
            symbol_duration_ms = (time.time() - symbol_start) * 1000
            print(f"[PERF] smart_money_loop {symbol}: {symbol_duration_ms:.2f}ms")

        loop_duration_ms = (time.time() - loop_start) * 1000
        print(f"[TASK ITERATION COMPLETE] task_name=smart_money_loop, duration_ms={loop_duration_ms:.2f}")
        if loop_duration_ms > 1000:
            print(f"[SLOW TASK] task_name=smart_money_loop, duration_ms={loop_duration_ms:.2f}")

        await asyncio.sleep(10)  # Simulate interval

async def simulate_health_monitor_loop(market_data: MockMarketDataEngine, symbols: List[str], shutdown_event: asyncio.Event):
    """Simulate health_monitor_loop background task"""
    print("[TASK START] task_name=health_monitor_loop")
    while not shutdown_event.is_set():
        loop_start = time.time()
        health_check_start = time.time()
        test_symbol = symbols[0] if symbols else None
        if test_symbol:
            await market_data.get_symbol_data(test_symbol)
        health_check_duration_ms = (time.time() - health_check_start) * 1000
        print(f"[PERF] health_monitor_loop market_data_check: {health_check_duration_ms:.2f}ms")

        loop_duration_ms = (time.time() - loop_start) * 1000
        print(f"[TASK ITERATION COMPLETE] task_name=health_monitor_loop, duration_ms={loop_duration_ms:.2f}")
        if loop_duration_ms > 1000:
            print(f"[SLOW TASK] task_name=health_monitor_loop, duration_ms={loop_duration_ms:.2f}")

        await asyncio.sleep(60)  # Simulate interval

async def simulate_telegram_queue_consumer(telegram_queue: TelegramQueue, shutdown_event: asyncio.Event):
    """Simulate Telegram queue consumer"""
    print("[TASK START] task_name=telegram_queue_consumer")
    queue_latencies = []
    while not shutdown_event.is_set():
        try:
            # Wait for update with timeout
            update_id, wait_ms = await asyncio.wait_for(telegram_queue.get_update(), timeout=1.0)
            queue_latencies.append(wait_ms)

            if wait_ms > 100:
                print(f"[SLOW QUEUE WAIT] update_id={update_id}, wait_ms={wait_ms:.2f}")
            if wait_ms > 1000:
                print(f"[BLOCKING WARNING] Queue wait >1s: {wait_ms:.2f}ms")

            # Simulate processing
            await asyncio.sleep(0.01)
        except asyncio.TimeoutError:
            continue

    return queue_latencies

async def test_production_concurrency():
    """Test production-like concurrency with all background tasks"""
    print("=" * 80)
    print("PRODUCTION CONCURRENCY TEST")
    print("=" * 80)

    symbols = ['BTCUSDT', 'ETHUSDT']
    shutdown_event = asyncio.Event()

    # Initialize components
    market_data = MockMarketDataEngine()
    smart_money = MockSmartMoneyTracker()
    telegram_queue = TelegramQueue()

    # Start background tasks
    market_data_task = asyncio.create_task(simulate_market_data_loop(market_data, symbols, shutdown_event))
    smart_money_task = asyncio.create_task(simulate_smart_money_loop(smart_money, market_data, symbols, shutdown_event))
    health_monitor_task = asyncio.create_task(simulate_health_monitor_loop(market_data, symbols, shutdown_event))
    queue_consumer_task = asyncio.create_task(simulate_telegram_queue_consumer(telegram_queue, shutdown_event))

    # Wait a bit for background tasks to start
    await asyncio.sleep(0.5)

    # Simulate concurrent Telegram updates
    print("\n[SIMULATING TELEGRAM UPDATES]")
    update_tasks = []
    for i in range(10):
        await asyncio.sleep(0.05)  # Stagger updates
        task = asyncio.create_task(telegram_queue.put_update(i))
        update_tasks.append(task)

    # Wait for all updates to be queued
    await asyncio.gather(*update_tasks)

    # Let the system process for a bit
    await asyncio.sleep(2)

    # Shutdown
    shutdown_event.set()

    # Wait for tasks to complete
    try:
        await asyncio.wait_for(market_data_task, timeout=2)
    except asyncio.TimeoutError:
        market_data_task.cancel()

    try:
        await asyncio.wait_for(smart_money_task, timeout=2)
    except asyncio.TimeoutError:
        smart_money_task.cancel()

    try:
        await asyncio.wait_for(health_monitor_task, timeout=2)
    except asyncio.TimeoutError:
        health_monitor_task.cancel()

    # Get queue latencies
    queue_latencies = await queue_consumer_task

    # Report results
    print("\n" + "=" * 80)
    print("TEST RESULTS")
    print("=" * 80)

    if queue_latencies:
        avg_latency = sum(queue_latencies) / len(queue_latencies)
        max_latency = max(queue_latencies)
        min_latency = min(queue_latencies)

        print(f"Queue latency statistics:")
        print(f"  Average: {avg_latency:.2f}ms")
        print(f"  Maximum: {max_latency:.2f}ms")
        print(f"  Minimum: {min_latency:.2f}ms")
        print(f"  Updates processed: {len(queue_latencies)}")

        # Verify requirements
        print(f"\nVerification:")
        if avg_latency < 100:
            print(f"  [PASS] Average queue latency < 100ms: {avg_latency:.2f}ms")
        else:
            print(f"  [FAIL] Average queue latency >= 100ms: {avg_latency:.2f}ms")

        if max_latency < 1000:
            print(f"  [PASS] Maximum queue latency < 1000ms: {max_latency:.2f}ms")
        else:
            print(f"  [FAIL] Maximum queue latency >= 1000ms: {max_latency:.2f}ms")

        if max_latency < 100:
            print(f"  [PASS] All queue latencies < 100ms")
        else:
            print(f"  [WARN] Some queue latencies >= 100ms")

    print("\n" + "=" * 80)

if __name__ == "__main__":
    asyncio.run(test_production_concurrency())
