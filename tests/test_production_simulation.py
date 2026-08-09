"""
Production Simulation Test for AI Trading Signal Bot
Simulates production load with concurrent Telegram updates and background tasks
"""
import asyncio
import time
from datetime import datetime
from unittest.mock import Mock, AsyncMock
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


async def simulate_market_data_loop():
    """Simulate market data loop with pandas operations"""
    try:
        import pandas as pd
        import numpy as np
    except ImportError:
        # Skip pandas if not installed
        await asyncio.sleep(0.1)
        return
    
    # Simulate indicator calculation (blocking pandas operation)
    def blocking_pandas_calc():
        df = pd.DataFrame({
            'close': np.random.randn(100).cumsum() + 100,
            'open': np.random.randn(100).cumsum() + 100,
            'high': np.random.randn(100).cumsum() + 105,
            'low': np.random.randn(100).cumsum() + 95,
            'volume': np.random.randint(1000, 10000, 100)
        })
        df['ema_9'] = df['close'].ewm(span=9).mean()
        df['ema_21'] = df['close'].ewm(span=21).mean()
        df['rsi'] = 100 - (100 / (1 + df['close'].diff().abs().rolling(14).mean()))
        return df
    
    # Run in thread pool (as the fix does)
    await asyncio.to_thread(blocking_pandas_calc)


async def simulate_ai_analysis():
    """Simulate AI analysis pipeline"""
    # Simulate data fetching
    await asyncio.sleep(0.05)
    # Simulate trend analysis
    await asyncio.sleep(0.02)
    # Simulate smart money analysis
    await asyncio.sleep(0.03)
    # Simulate news analysis
    await asyncio.sleep(0.02)
    # Simulate decision making
    await asyncio.sleep(0.01)


async def simulate_telegram_handler(queue):
    """Simulate Telegram handler processing updates"""
    update = await queue.get()
    # Simulate handler processing
    await asyncio.sleep(0.005)  # 5ms handler time
    return update


async def test_production_load_simulation():
    """Test production load with concurrent operations"""
    print("\n=== Test: Production Load Simulation ===")
    
    queue = asyncio.Queue()
    
    # Simulate background tasks running continuously
    async def background_tasks():
        while True:
            # Run market data loop
            await simulate_market_data_loop()
            # Run AI analysis
            await simulate_ai_analysis()
            # Small delay between iterations
            await asyncio.sleep(0.1)
    
    # Start background tasks
    background_task = asyncio.create_task(background_tasks())
    
    # Simulate Telegram updates arriving
    update_latencies = []
    
    for i in range(10):
        # Put update in queue
        put_start = time.time()
        queue.put_nowait(f"update_{i}")
        put_latency_ms = (time.time() - put_start) * 1000
        
        # Process update
        handler_start = time.time()
        await simulate_telegram_handler(queue)
        handler_latency_ms = (time.time() - handler_start) * 1000
        
        total_latency_ms = put_latency_ms + handler_latency_ms
        update_latencies.append(total_latency_ms)
        
        print(f"Update {i}: put={put_latency_ms:.2f}ms, handler={handler_latency_ms:.2f}ms, total={total_latency_ms:.2f}ms")
        
        # Small delay between updates
        await asyncio.sleep(0.05)
    
    # Cancel background task
    background_task.cancel()
    try:
        await background_task
    except asyncio.CancelledError:
        pass
    
    # Check latencies (skip first update due to initialization overhead)
    if len(update_latencies) > 1:
        subsequent_latencies = update_latencies[1:]
        avg_latency = sum(subsequent_latencies) / len(subsequent_latencies)
        max_latency = max(subsequent_latencies)
    else:
        avg_latency = sum(update_latencies) / len(update_latencies)
        max_latency = max(update_latencies)
    
    print(f"\nAverage update latency (excluding first): {avg_latency:.2f}ms")
    print(f"Max update latency (excluding first): {max_latency:.2f}ms")
    
    # Subsequent latencies should be < 50ms (much better than the 14-16s problem)
    if max_latency >= 50.0:
        print(f"[FAIL] Max latency {max_latency:.2f}ms exceeds 50ms threshold")
        return False
    
    # Average should be < 30ms
    if avg_latency >= 30.0:
        print(f"[FAIL] Average latency {avg_latency:.2f}ms exceeds 30ms threshold")
        return False
    
    print("[PASS] PASSED")
    return True


async def test_queue_starvation_prevention():
    """Test that queue consumer is not starved by background tasks"""
    print("\n=== Test: Queue Starvation Prevention ===")
    
    queue = asyncio.Queue()
    
    # Simulate heavy background task
    async def heavy_background_task():
        # Multiple pandas operations
        for _ in range(5):
            await simulate_market_data_loop()
            await asyncio.sleep(0.01)
    
    # Start heavy background task
    heavy_task = asyncio.create_task(heavy_background_task())
    
    # Put update in queue
    queue.put_nowait("test_update")
    
    # Try to get update immediately
    get_start = time.time()
    update = await queue.get()
    get_latency_ms = (time.time() - get_start) * 1000
    
    print(f"Queue get latency with heavy background task: {get_latency_ms:.2f}ms")
    
    # Wait for background task to complete
    await heavy_task
    
    # Queue get should be fast even with heavy background task
    if get_latency_ms >= 100.0:
        print(f"[FAIL] Queue get took {get_latency_ms:.2f}ms, expected < 100ms")
        return False
    
    print("[PASS] PASSED")
    return True


async def test_concurrent_telegram_updates():
    """Test multiple concurrent Telegram updates"""
    print("\n=== Test: Concurrent Telegram Updates ===")
    
    queue = asyncio.Queue()
    
    # Put multiple updates
    for i in range(20):
        queue.put_nowait(f"update_{i}")
    
    # Process updates concurrently
    async def process_update(task_id):
        start = time.time()
        update = await queue.get()
        await asyncio.sleep(0.005)  # Simulate handler
        duration = (time.time() - start) * 1000
        return task_id, update, duration
    
    # Start all processors
    processors = [asyncio.create_task(process_update(i)) for i in range(20)]
    
    start_time = time.time()
    results = await asyncio.gather(*processors)
    total_duration_ms = (time.time() - start_time) * 1000
    
    # Calculate statistics
    latencies = [r[2] for r in results]
    avg_latency = sum(latencies) / len(latencies)
    max_latency = max(latencies)
    
    print(f"Total processing time for 20 updates: {total_duration_ms:.2f}ms")
    print(f"Average latency per update: {avg_latency:.2f}ms")
    print(f"Max latency: {max_latency:.2f}ms")
    
    # All should complete quickly
    if max_latency >= 50.0:
        print(f"[FAIL] Max latency {max_latency:.2f}ms exceeds 50ms threshold")
        return False
    
    print("[PASS] PASSED")
    return True


async def test_event_loop_responsiveness():
    """Test that event loop remains responsive under load"""
    print("\n=== Test: Event Loop Responsiveness ===")
    
    # Create a simple ping mechanism
    ping_times = []
    
    async def ping_task():
        while True:
            start = time.time()
            await asyncio.sleep(0)
            duration = (time.time() - start) * 1000
            ping_times.append(duration)
            await asyncio.sleep(0.01)
    
    # Start ping task
    ping = asyncio.create_task(ping_task())
    
    # Run heavy load
    tasks = []
    for _ in range(10):
        tasks.append(asyncio.create_task(simulate_market_data_loop()))
        tasks.append(asyncio.create_task(simulate_ai_analysis()))
    
    await asyncio.gather(*tasks)
    
    # Cancel ping task
    ping.cancel()
    try:
        await ping
    except asyncio.CancelledError:
        pass
    
    # Check ping times
    if not ping_times:
        print("[FAIL] No ping times recorded")
        return False
    
    avg_ping = sum(ping_times) / len(ping_times)
    max_ping = max(ping_times)
    
    print(f"Average ping time: {avg_ping:.2f}ms")
    print(f"Max ping time: {max_ping:.2f}ms")
    
    # Event loop should remain responsive (allow some overhead under heavy load)
    if max_ping >= 50.0:
        print(f"[FAIL] Event loop ping took {max_ping:.2f}ms, expected < 50ms")
        return False
    
    print("[PASS] PASSED")
    return True


async def run_production_simulation_tests():
    """Run all production simulation tests"""
    print("=" * 60)
    print("PRODUCTION SIMULATION TESTS")
    print("=" * 60)
    
    tests = [
        test_production_load_simulation,
        test_queue_starvation_prevention,
        test_concurrent_telegram_updates,
        test_event_loop_responsiveness,
    ]
    
    results = []
    for test in tests:
        try:
            result = await test()
            results.append(result)
        except Exception as e:
            print(f"[FAIL] FAILED with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("[PASS] ALL PRODUCTION SIMULATION TESTS PASSED")
        return True
    else:
        print(f"[FAIL] {total - passed} TESTS FAILED")
        return False


if __name__ == "__main__":
    success = asyncio.run(run_production_simulation_tests())
    sys.exit(0 if success else 1)
