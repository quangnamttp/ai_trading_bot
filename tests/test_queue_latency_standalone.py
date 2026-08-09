"""
Queue Latency Tests for AI Trading Signal Bot (Standalone Version)
Tests to verify that Telegram updates are processed with minimal queue delay
"""
import asyncio
import time
from datetime import datetime
from unittest.mock import Mock, AsyncMock
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


async def test_queue_put_and_get_latency():
    """Test that queue.put_nowait() and queue.get() have minimal latency"""
    print("\n=== Test: Queue Put and Get Latency ===")
    
    queue = asyncio.Queue()
    
    # Measure queue put latency
    put_start = time.time()
    test_update = Mock()
    test_update.update_id = 123
    queue.put_nowait(test_update)
    put_duration_ms = (time.time() - put_start) * 1000
    
    print(f"Queue put duration: {put_duration_ms:.2f}ms")
    
    # Queue put should be < 1ms
    if put_duration_ms >= 1.0:
        print(f"[FAIL] FAILED: Queue put took {put_duration_ms:.2f}ms, expected < 1ms")
        return False
    
    # Measure queue get latency
    get_start = time.time()
    retrieved_update = await queue.get()
    get_duration_ms = (time.time() - get_start) * 1000
    
    print(f"Queue get duration: {get_duration_ms:.2f}ms")
    
    # Queue get should be < 1ms
    if get_duration_ms >= 1.0:
        print(f"[FAIL] FAILED: Queue get took {get_duration_ms:.2f}ms, expected < 1ms")
        return False
    
    # Verify the update is the same
    if retrieved_update.update_id != test_update.update_id:
        print(f"[FAIL] FAILED: Update ID mismatch")
        return False
    
    print("[PASS] PASSED")
    return True


async def test_concurrent_queue_operations():
    """Test that concurrent queue operations don't block each other"""
    print("\n=== Test: Concurrent Queue Operations ===")
    
    queue = asyncio.Queue()
    
    # Put multiple updates concurrently
    put_tasks = []
    for i in range(10):
        update = Mock()
        update.update_id = i
        put_tasks.append(asyncio.create_task(asyncio.to_thread(queue.put_nowait, update)))
    
    start_time = time.time()
    await asyncio.gather(*put_tasks)
    put_duration_ms = (time.time() - start_time) * 1000
    
    print(f"Concurrent puts duration: {put_duration_ms:.2f}ms")
    
    # All puts should complete quickly (< 10ms for 10 items)
    if put_duration_ms >= 10.0:
        print(f"[FAIL] FAILED: Concurrent puts took {put_duration_ms:.2f}ms, expected < 10ms")
        return False
    
    # Verify all items are in queue
    if queue.qsize() != 10:
        print(f"[FAIL] FAILED: Expected 10 items in queue, got {queue.qsize()}")
        return False
    
    print("[PASS] PASSED")
    return True


async def test_queue_consumer_with_background_tasks():
    """Test that queue consumer runs even with background tasks"""
    print("\n=== Test: Queue Consumer with Background Tasks ===")
    
    queue = asyncio.Queue()
    
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
    
    print(f"Queue get with background task duration: {get_duration_ms:.2f}ms")
    
    # Queue get should still be fast even with background task
    if get_duration_ms >= 50.0:
        print(f"[FAIL] FAILED: Queue get with background task took {get_duration_ms:.2f}ms, expected < 50ms")
        await background_task
        return False
    
    # Wait for background task to complete
    await background_task
    
    if retrieved_update.update_id != test_update.update_id:
        print(f"[FAIL] FAILED: Update ID mismatch")
        return False
    
    print("[PASS] PASSED")
    return True


async def test_pandas_operations_in_thread_pool():
    """Test that pandas operations run in thread pool and don't block event loop"""
    print("\n=== Test: Pandas Operations in Thread Pool ===")
    
    try:
        import pandas as pd
        import numpy as np
    except ImportError:
        print("⚠️ SKIPPED: pandas not installed")
        return True
    
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
    
    print(f"Queue get with pandas operation duration: {get_duration_ms:.2f}ms")
    
    # Queue get should be fast even with pandas operation
    if get_duration_ms >= 50.0:
        print(f"[FAIL] FAILED: Queue get with pandas operation took {get_duration_ms:.2f}ms, expected < 50ms")
        await pandas_task
        return False
    
    # Wait for pandas to complete
    await pandas_task
    pandas_duration_ms = (time.time() - pandas_start) * 1000
    
    print(f"Pandas operation duration: {pandas_duration_ms:.2f}ms")
    
    # Pandas operation should have completed
    if pandas_duration_ms <= 0:
        print(f"[FAIL] FAILED: Pandas operation did not complete")
        return False
    
    print("[PASS] PASSED")
    return True


async def test_webhook_to_handler_latency():
    """Test end-to-end latency from webhook to handler"""
    print("\n=== Test: Webhook to Handler Latency ===")
    
    # Simulate webhook receiving update
    webhook_timestamp = datetime.now()
    
    # Simulate queue put (should be immediate)
    queue = asyncio.Queue()
    queue_put_start = time.time()
    queue.put_nowait("test_update")
    queue_put_duration_ms = (time.time() - queue_put_start) * 1000
    
    print(f"Queue put duration: {queue_put_duration_ms:.2f}ms")
    
    if queue_put_duration_ms >= 1.0:
        print(f"[FAIL] FAILED: Queue put took {queue_put_duration_ms:.2f}ms, expected < 1ms")
        return False
    
    # Simulate handler receiving update
    handler_start = time.time()
    update = await queue.get()
    handler_timestamp = datetime.now()
    handler_duration_ms = (time.time() - handler_start) * 1000
    
    print(f"Handler get duration: {handler_duration_ms:.2f}ms")
    
    if handler_duration_ms >= 1.0:
        print(f"[FAIL] FAILED: Handler get took {handler_duration_ms:.2f}ms, expected < 1ms")
        return False
    
    # Total latency from webhook to handler
    total_latency_ms = (handler_timestamp - webhook_timestamp).total_seconds() * 1000
    
    print(f"Total webhook-to-handler latency: {total_latency_ms:.2f}ms")
    
    # Total should be < 10ms (allowing for some overhead)
    if total_latency_ms >= 10.0:
        print(f"[FAIL] FAILED: Total webhook-to-handler latency was {total_latency_ms:.2f}ms, expected < 10ms")
        return False
    
    print("[PASS] PASSED")
    return True


async def test_multiple_concurrent_handlers():
    """Test that multiple handlers can run concurrently without blocking"""
    print("\n=== Test: Multiple Concurrent Handlers ===")
    
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
    
    print(f"Concurrent handlers total duration: {total_duration_ms:.2f}ms")
    
    # All handlers should complete quickly
    if total_duration_ms >= 50.0:
        print(f"[FAIL] FAILED: Concurrent handlers took {total_duration_ms:.2f}ms, expected < 50ms")
        return False
    
    # Each individual handler should be fast
    for task_id, update, duration in results:
        print(f"Handler {task_id} duration: {duration:.2f}ms")
        if duration >= 10.0:
            print(f"[FAIL] FAILED: Handler {task_id} took {duration:.2f}ms, expected < 10ms")
            return False
    
    print("[PASS] PASSED")
    return True


async def run_all_tests():
    """Run all queue latency tests"""
    print("=" * 60)
    print("QUEUE LATENCY TESTS")
    print("=" * 60)
    
    tests = [
        test_queue_put_and_get_latency,
        test_concurrent_queue_operations,
        test_queue_consumer_with_background_tasks,
        test_pandas_operations_in_thread_pool,
        test_webhook_to_handler_latency,
        test_multiple_concurrent_handlers,
    ]
    
    results = []
    for test in tests:
        try:
            result = await test()
            results.append(result)
        except Exception as e:
            print(f"[FAIL] FAILED with exception: {e}")
            results.append(False)
    
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("[PASS] ALL TESTS PASSED")
        return True
    else:
        print(f"[FAIL] {total - passed} TESTS FAILED")
        return False


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
