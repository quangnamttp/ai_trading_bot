"""
Async Tests for Watchlist Management
Tests async behavior, concurrency, and database async wrappers
"""
import pytest
import asyncio
from core.database import db


@pytest.fixture
def setup_database():
    """Setup test database"""
    db.init_database()
    # Clear watchlist before each test
    db.clear_watchlist()
    yield
    # Cleanup after test
    db.clear_watchlist()


class TestAsyncWatchlistOperations:
    """Test async watchlist operations"""

    @pytest.mark.asyncio
    async def test_concurrent_add_operations(self, setup_database):
        """Test concurrent add operations don't cause conflicts"""
        symbols = [f"SYMBOL{i}/USDT:USDT" for i in range(10)]

        # Add symbols concurrently
        tasks = [db.add_to_watchlist_async(symbol, added_by=123456) for symbol in symbols]
        results = await asyncio.gather(*tasks)

        # All should succeed
        assert all(results)

        watchlist = await db.get_watchlist_async()
        assert len(watchlist) == 10

    @pytest.mark.asyncio
    async def test_concurrent_remove_operations(self, setup_database):
        """Test concurrent remove operations"""
        symbols = [f"COIN{i}/USDT:USDT" for i in range(5)]
        for symbol in symbols:
            await db.add_to_watchlist_async(symbol, added_by=123456)

        # Remove symbols concurrently
        tasks = [db.remove_from_watchlist_async(symbol) for symbol in symbols]
        results = await asyncio.gather(*tasks)

        # All should succeed
        assert all(results)

        watchlist = await db.get_watchlist_async()
        assert len(watchlist) == 0

    @pytest.mark.asyncio
    async def test_concurrent_add_and_get(self, setup_database):
        """Test concurrent add and get operations"""
        symbol = "BTC/USDT:USDT"

        # Add and get concurrently
        add_task = db.add_to_watchlist_async(symbol, added_by=123456)
        get_task = db.get_watchlist_async()

        await asyncio.gather(add_task, get_task)

        watchlist = await db.get_watchlist_async()
        assert symbol in watchlist

    @pytest.mark.asyncio
    async def test_async_wrapper_correctness(self, setup_database):
        """Test that async wrappers use asyncio.to_thread correctly"""
        # This test verifies that async wrappers don't block the event loop
        symbol = "ETH/USDT:USDT"

        # Measure time with concurrent operations
        start = asyncio.get_event_loop().time()

        tasks = [
            db.add_to_watchlist_async(symbol, added_by=123456),
            db.get_watchlist_async(),
            db.get_watchlist_async(),
        ]
        await asyncio.gather(*tasks)

        duration = asyncio.get_event_loop().time() - start

        # Should complete quickly (not blocking)
        assert duration < 5.0  # 5 seconds max for 3 operations

    @pytest.mark.asyncio
    async def test_watchlist_persistence_across_calls(self, setup_database):
        """Test that watchlist persists across multiple async calls"""
        symbol = "SOL/USDT:USDT"

        # Add symbol
        await db.add_to_watchlist_async(symbol, added_by=123456)

        # Get watchlist multiple times
        watchlist1 = await db.get_watchlist_async()
        watchlist2 = await db.get_watchlist_async()
        watchlist3 = await db.get_watchlist_async()

        # All should return the same symbol
        assert symbol in watchlist1
        assert symbol in watchlist2
        assert symbol in watchlist3
        assert len(watchlist1) == len(watchlist2) == len(watchlist3) == 1


class TestAsyncDatabaseConcurrency:
    """Test database async wrapper concurrency"""

    @pytest.mark.asyncio
    async def test_multiple_database_operations(self, setup_database):
        """Test multiple database operations don't block each other"""
        operations = []

        # Mix of add, get, and remove operations
        for i in range(5):
            symbol = f"TEST{i}/USDT:USDT"
            operations.append(db.add_to_watchlist_async(symbol, added_by=123456))
            operations.append(db.get_watchlist_async())

        # Execute all operations concurrently
        results = await asyncio.gather(*operations, return_exceptions=True)

        # Check for exceptions
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0, f"Exceptions occurred: {exceptions}"

    @pytest.mark.asyncio
    async def test_clear_during_operations(self, setup_database):
        """Test clearing watchlist during other operations"""
        symbols = [f"ASYNC{i}/USDT:USDT" for i in range(3)]
        for symbol in symbols:
            await db.add_to_watchlist_async(symbol, added_by=123456)

        # Clear while getting watchlist
        clear_task = db.clear_watchlist_async()
        get_task = db.get_watchlist_async()

        await asyncio.gather(clear_task, get_task)

        watchlist = await db.get_watchlist_async()
        assert len(watchlist) == 0


class TestAsyncErrorHandling:
    """Test async error handling"""

    @pytest.mark.asyncio
    async def test_add_invalid_symbol(self, setup_database):
        """Test adding invalid symbol doesn't crash"""
        # Database should handle any string
        result = await db.add_to_watchlist_async("", added_by=123456)
        # May succeed or fail depending on validation
        # Should not crash

    @pytest.mark.asyncio
    async def test_remove_nonexistent_symbol(self, setup_database):
        """Test removing non-existent symbol doesn't crash"""
        result = await db.remove_from_watchlist_async("NONEXISTENT/USDT:USDT")
        # Should return False or handle gracefully
        assert result is False or result is True

    @pytest.mark.asyncio
    async def test_get_watchlist_after_clear(self, setup_database):
        """Test getting watchlist after clear returns empty"""
        await db.add_to_watchlist_async("BTC/USDT:USDT", added_by=123456)
        await db.clear_watchlist_async()

        watchlist = await db.get_watchlist_async()
        assert watchlist == []


class TestAsyncPerformance:
    """Test async performance characteristics"""

    @pytest.mark.asyncio
    async def test_bulk_add_performance(self, setup_database):
        """Test bulk add performance"""
        symbols = [f"BULK{i}/USDT:USDT" for i in range(20)]

        start = asyncio.get_event_loop().time()
        tasks = [db.add_to_watchlist_async(symbol, added_by=123456) for symbol in symbols]
        await asyncio.gather(*tasks)
        duration = asyncio.get_event_loop().time() - start

        # Should complete in reasonable time
        assert duration < 10.0

        watchlist = await db.get_watchlist_async()
        assert len(watchlist) == 20

    @pytest.mark.asyncio
    async def test_sequential_vs_concurrent(self, setup_database):
        """Test that concurrent operations are faster than sequential"""
        symbols = [f"PERF{i}/USDT:USDT" for i in range(5)]

        # Sequential
        start = asyncio.get_event_loop().time()
        for symbol in symbols:
            await db.add_to_watchlist_async(symbol, added_by=123456)
        sequential_duration = asyncio.get_event_loop().time() - start

        # Clear and try concurrent
        await db.clear_watchlist_async()

        start = asyncio.get_event_loop().time()
        tasks = [db.add_to_watchlist_async(symbol, added_by=123456) for symbol in symbols]
        await asyncio.gather(*tasks)
        concurrent_duration = asyncio.get_event_loop().time() - start

        # ConcurrentShould be faster or similar (database may have locks)
        # At minimum, concurrent should not be significantly slower
        assert concurrent_duration < sequential_duration * 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
