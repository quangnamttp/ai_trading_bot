"""
Integration Tests for Complete Webhook Flow
Tests the full flow from Telegram webhook to watchlist synchronization
"""
import pytest
import asyncio
import json
from unittest.mock import Mock, AsyncMock, patch, MagicMock


class TestWebhookIntegration:
    """Integration tests for complete webhook flow"""

    @pytest.fixture
    def setup_database(self):
        """Setup test database"""
        from core.database import db
        db.init_database()
        db.clear_watchlist()
        yield
        db.clear_watchlist()

    def test_webhook_to_active_symbols_integration(self, setup_database):
        """Test complete integration: database → active_symbols"""
        from core.main import TradingBotApp
        from core.database import db

        # Simulate: Handler writes to database
        db.add_to_watchlist("PEPE/USDT:USDT", added_by=123456)

        # Verify database state
        watchlist = db.get_watchlist()
        assert "PEPE/USDT:USDT" in watchlist

        # Create app and reload watchlist (simulating reload_watchlist() call)
        app = TradingBotApp()
        asyncio.run(app.reload_watchlist())

        # Verify active_symbols updated
        assert "PEPE/USDT:USDT" in app.active_symbols

    def test_remove_integration(self, setup_database):
        """Test complete remove flow: database → active_symbols"""
        from core.main import TradingBotApp
        from core.database import db

        # Add symbol first
        db.add_to_watchlist("PEPE/USDT:USDT", added_by=123456)

        # Create app and load watchlist
        app = TradingBotApp()
        asyncio.run(app.load_watchlist())
        assert "PEPE/USDT:USDT" in app.active_symbols

        # Simulate: Handler removes from database
        db.remove_from_watchlist("PEPE/USDT:USDT")

        # Verify database state
        watchlist = db.get_watchlist()
        assert "PEPE/USDT:USDT" not in watchlist

        # Reload watchlist (simulating reload_watchlist() call)
        asyncio.run(app.reload_watchlist())

        # Verify active_symbols updated
        assert "PEPE/USDT:USDT" not in app.active_symbols

    def test_analysis_loop_uses_active_symbols(self, setup_database):
        """Test that analysis_loop uses active_symbols from database"""
        from core.main import TradingBotApp
        from core.database import db

        # Add symbol to database
        db.add_to_watchlist("PEPE/USDT:USDT", added_by=123456)

        # Create app and load watchlist
        app = TradingBotApp()
        asyncio.run(app.load_watchlist())

        # Verify active_symbols
        assert "PEPE/USDT:USDT" in app.active_symbols
        assert len(app.active_symbols) == 1

        # Verify analysis_loop would use this symbol
        # (We can't actually run the loop in test, but we verify the data source)
        assert app.active_symbols == db.get_watchlist()

    def test_multi_symbol_integration(self, setup_database):
        """Test integration with multiple symbols"""
        from core.main import TradingBotApp
        from core.database import db

        # Add multiple symbols
        db.add_to_watchlist("BTC/USDT:USDT", added_by=123456)
        db.add_to_watchlist("ETH/USDT:USDT", added_by=123456)
        db.add_to_watchlist("SUI/USDT:USDT", added_by=123456)

        # Create app and load watchlist
        app = TradingBotApp()
        asyncio.run(app.load_watchlist())

        # Verify all symbols in active_symbols
        assert len(app.active_symbols) == 3
        assert "BTC/USDT:USDT" in app.active_symbols
        assert "ETH/USDT:USDT" in app.active_symbols
        assert "SUI/USDT:USDT" in app.active_symbols

        # Verify matches database
        assert set(app.active_symbols) == set(db.get_watchlist())

    def test_empty_watchlist_integration(self, setup_database):
        """Test integration with empty watchlist"""
        from core.main import TradingBotApp
        from core.database import db

        # Ensure empty
        db.clear_watchlist()

        # Create app and load watchlist
        app = TradingBotApp()
        asyncio.run(app.load_watchlist())

        # Verify empty
        assert len(app.active_symbols) == 0
        assert app.active_symbols == []

    def test_restart_persistence_integration(self, setup_database):
        """Test that watchlist persists across app restart"""
        from core.main import TradingBotApp
        from core.database import db

        # Add symbol to database
        db.add_to_watchlist("PEPE/USDT:USDT", added_by=123456)

        # Simulate restart - create new app instance
        app = TradingBotApp()

        # Load watchlist
        asyncio.run(app.load_watchlist())

        # Verify loaded correctly
        assert "PEPE/USDT:USDT" in app.active_symbols
        assert len(app.active_symbols) == 1

    def test_database_path_consistency(self, setup_database):
        """Test that all components use same database path"""
        from core.database import db
        from core.config import DATABASE_PATH

        # Verify database path
        assert db.db_path == DATABASE_PATH

        # Add symbol
        db.add_to_watchlist("PEPE/USDT:USDT", added_by=123456)

        # Verify it's in the same database
        watchlist = db.get_watchlist()
        assert "PEPE/USDT:USDT" in watchlist


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
