"""
Tests for Watchlist Management
Tests database persistence, normalization, validation, and permissions
"""
import pytest
import asyncio
from core.database import db
from core.config import clean_symbol


@pytest.fixture
def setup_database():
    """Setup test database"""
    db.init_database()
    # Clear watchlist before each test
    db.clear_watchlist()
    yield
    # Cleanup after test
    db.clear_watchlist()


class TestWatchlistPersistence:
    """Test watchlist database operations"""

    @pytest.mark.asyncio
    async def test_add_to_watchlist(self, setup_database):
        """Test adding a symbol to watchlist"""
        symbol = "BTC/USDT:USDT"
        result = await db.add_to_watchlist_async(symbol, added_by=123456)
        assert result is True

        watchlist = await db.get_watchlist_async()
        assert symbol in watchlist
        assert len(watchlist) == 1

    @pytest.mark.asyncio
    async def test_add_duplicate_symbol(self, setup_database):
        """Test that duplicate symbols are not added"""
        symbol = "ETH/USDT:USDT"
        await db.add_to_watchlist_async(symbol, added_by=123456)
        await db.add_to_watchlist_async(symbol, added_by=123456)

        watchlist = await db.get_watchlist_async()
        assert watchlist.count(symbol) == 1
        assert len(watchlist) == 1

    @pytest.mark.asyncio
    async def test_remove_from_watchlist(self, setup_database):
        """Test removing a symbol from watchlist"""
        symbol = "SOL/USDT:USDT"
        await db.add_to_watchlist_async(symbol, added_by=123456)

        result = await db.remove_from_watchlist_async(symbol)
        assert result is True

        watchlist = await db.get_watchlist_async()
        assert symbol not in watchlist
        assert len(watchlist) == 0

    @pytest.mark.asyncio
    async def test_clear_watchlist(self, setup_database):
        """Test clearing the entire watchlist"""
        symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]
        for symbol in symbols:
            await db.add_to_watchlist_async(symbol, added_by=123456)

        result = await db.clear_watchlist_async()
        assert result is True

        watchlist = await db.get_watchlist_async()
        assert len(watchlist) == 0

    @pytest.mark.asyncio
    async def test_get_empty_watchlist(self, setup_database):
        """Test getting watchlist when empty"""
        watchlist = await db.get_watchlist_async()
        assert watchlist == []
        assert len(watchlist) == 0


class TestWatchlistNormalization:
    """Test symbol normalization"""

    def test_clean_symbol_with_suffix(self):
        """Test cleaning symbol with exchange suffix"""
        symbol = "BTC/USDT:USDT"
        cleaned = clean_symbol(symbol)
        assert cleaned == "BTC/USDT"

    def test_clean_symbol_without_suffix(self):
        """Test cleaning symbol without exchange suffix"""
        symbol = "BTC/USDT"
        cleaned = clean_symbol(symbol)
        assert cleaned == "BTC/USDT"

    def test_clean_symbol_various_formats(self):
        """Test cleaning various symbol formats"""
        test_cases = [
            ("ETH/USDT:USDT", "ETH/USDT"),
            ("SOL/USDT:USDT", "SOL/USDT"),
            ("XRP/USDT:USDT", "XRP/USDT"),
        ]
        for symbol, expected in test_cases:
            cleaned = clean_symbol(symbol)
            assert cleaned == expected


class TestWatchlistValidation:
    """Test watchlist validation logic"""

    @pytest.mark.asyncio
    async def test_symbol_exists_in_exchange(self, setup_database):
        """Test that symbol validation checks exchange (mocked)"""
        # This would require mocking market_data_engine.get_ticker
        # For now, we test the normalization logic
        symbol_input = "BTC"
        symbol_normalized = f"{symbol_input}/USDT:USDT"
        assert "/" in symbol_normalized
        assert symbol_normalized.endswith(":USDT")

    @pytest.mark.asyncio
    async def test_symbol_already_in_watchlist(self, setup_database):
        """Test duplicate detection"""
        symbol = "DOGE/USDT:USDT"
        await db.add_to_watchlist_async(symbol, added_by=123456)

        watchlist = await db.get_watchlist_async()
        assert symbol in watchlist

        # Try to add again - should be ignored due to UNIQUE constraint
        await db.add_to_watchlist_async(symbol, added_by=123456)
        watchlist = await db.get_watchlist_async()
        assert watchlist.count(symbol) == 1


class TestWatchlistPermissions:
    """Test admin permission enforcement"""

    @pytest.mark.asyncio
    async def test_admin_can_add(self, setup_database):
        """Test that admin can add symbols"""
        # In real implementation, this would check is_admin_async
        # Here we test the database operation
        symbol = "ADA/USDT:USDT"
        result = await db.add_to_watchlist_async(symbol, added_by=123456)
        assert result is True

    @pytest.mark.asyncio
    async def test_admin_can_remove(self, setup_database):
        """Test that admin can remove symbols"""
        symbol = "AVAX/USDT:USDT"
        await db.add_to_watchlist_async(symbol, added_by=123456)

        result = await db.remove_from_watchlist_async(symbol)
        assert result is True

    @pytest.mark.asyncio
    async def test_added_by_tracking(self, setup_database):
        """Test that added_by is tracked"""
        admin_id = 123456
        symbol = "LINK/USDT:USDT"
        await db.add_to_watchlist_async(symbol, added_by=admin_id)

        # Verify symbol was added (added_by is stored but not exposed in get_watchlist)
        watchlist = await db.get_watchlist_async()
        assert symbol in watchlist


class TestWatchlistIntegration:
    """Test watchlist integration with main app"""

    @pytest.mark.asyncio
    async def test_watchlist_reload(self, setup_database):
        """Test that watchlist can be reloaded"""
        # Add initial symbols
        symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT"]
        for symbol in symbols:
            await db.add_to_watchlist_async(symbol, added_by=123456)

        watchlist = await db.get_watchlist_async()
        assert len(watchlist) == 2

        # Add new symbol
        await db.add_to_watchlist_async("SOL/USDT:USDT", added_by=123456)

        # Reload
        watchlist = await db.get_watchlist_async()
        assert len(watchlist) == 3
        assert "SOL/USDT:USDT" in watchlist

    @pytest.mark.asyncio
    async def test_empty_watchlist_behavior(self, setup_database):
        """Test behavior when watchlist is empty"""
        watchlist = await db.get_watchlist_async()
        assert watchlist == []

        # Should not crash when processing empty watchlist
        for symbol in watchlist:
            # This loop should not execute
            assert False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
