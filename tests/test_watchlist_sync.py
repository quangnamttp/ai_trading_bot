"""
Tests for Watchlist → Analysis Loop Immediate Synchronization
Tests that Telegram watchlist changes immediately sync to TradingBotApp.active_symbols
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch


class TestWatchlistSync:
    """Test immediate synchronization between watchlist and active_symbols"""

    @pytest.fixture
    def setup_database(self):
        """Setup test database"""
        from core.database import db
        db.init_database()
        db.clear_watchlist()
        yield
        db.clear_watchlist()

    def test_bot_app_reference_set(self):
        """Test that TradingBotApp reference is set in TelegramBot"""
        from bot.telegram_bot import TelegramBot
        from core.main import TradingBotApp

        bot = TelegramBot()
        app = TradingBotApp()

        bot.set_bot_app(app)

        assert bot.bot_app is app

    def test_reload_watchlist_updates_active_symbols(self, setup_database):
        """Test that reload_watchlist updates active_symbols immediately"""
        from core.main import TradingBotApp
        from core.database import db

        app = TradingBotApp()

        # Add symbol to database
        db.add_to_watchlist("PEPE/USDT:USDT", added_by=123456)

        # Reload watchlist
        import asyncio
        asyncio.run(app.reload_watchlist())

        # Verify active_symbols updated
        assert "PEPE/USDT:USDT" in app.active_symbols
        assert len(app.active_symbols) == 1

    def test_add_symbol_syncs_immediately(self, setup_database):
        """Test that adding symbol via database syncs to active_symbols"""
        from core.main import TradingBotApp
        from core.database import db

        app = TradingBotApp()

        # Initial state - empty
        import asyncio
        asyncio.run(app.load_watchlist())
        assert len(app.active_symbols) == 0

        # Add symbol
        db.add_to_watchlist("PEPE/USDT:USDT", added_by=123456)

        # Reload
        asyncio.run(app.reload_watchlist())

        # Verify sync
        assert "PEPE/USDT:USDT" in app.active_symbols
        assert len(app.active_symbols) == 1

    def test_remove_symbol_syncs_immediately(self, setup_database):
        """Test that removing symbol via database syncs to active_symbols"""
        from core.main import TradingBotApp
        from core.database import db

        app = TradingBotApp()

        # Add symbol
        db.add_to_watchlist("PEPE/USDT:USDT", added_by=123456)
        import asyncio
        asyncio.run(app.load_watchlist())

        # Verify initial state
        assert "PEPE/USDT:USDT" in app.active_symbols

        # Remove symbol
        db.remove_from_watchlist("PEPE/USDT:USDT")

        # Reload
        asyncio.run(app.reload_watchlist())

        # Verify sync
        assert "PEPE/USDT:USDT" not in app.active_symbols
        assert len(app.active_symbols) == 0

    def test_telegram_add_triggers_reload(self, setup_database):
        """Test that Telegram add triggers immediate reload"""
        from bot.telegram_bot import TelegramBot
        from core.main import TradingBotApp
        from core.database import db

        bot = TelegramBot()
        app = TradingBotApp()
        bot.set_bot_app(app)
        bot.market_data = Mock()
        bot.market_data.get_ticker = AsyncMock(return_value={'last': 50000.0})

        # Create mock update for symbol input
        from telegram import Update, Message, User
        message_update = Mock(spec=Update)
        message = Mock(spec=Message)
        user = Mock(spec=User)
        user.id = 123456
        message.text = "PEPE"
        message.reply_text = AsyncMock()
        message_update.message = message
        message_update.effective_user = user

        # Create mock context
        from telegram.ext import ContextTypes
        context = Mock(spec=ContextTypes.DEFAULT_TYPE)
        context.user_data = {'waiting_for_symbol': True}

        # Mock database
        with patch('bot.telegram_bot.db') as mock_db:
            mock_db.is_admin_async = AsyncMock(return_value=True)
            mock_db.get_watchlist_async = AsyncMock(return_value=[])
            mock_db.add_to_watchlist_async = AsyncMock(return_value=True)

            # Mock app reload
            app.reload_watchlist = AsyncMock()

            import asyncio
            asyncio.run(bot.handle_symbol_input(message_update, context))

            # Verify reload was called
            app.reload_watchlist.assert_called_once()

    def test_telegram_remove_triggers_reload(self, setup_database):
        """Test that Telegram remove triggers immediate reload"""
        from bot.telegram_bot import TelegramBot
        from core.main import TradingBotApp
        from telegram import Update, CallbackQuery, User

        bot = TelegramBot()
        app = TradingBotApp()
        bot.set_bot_app(app)

        # Create mock update for remove callback
        update = Mock(spec=Update)
        query = Mock(spec=CallbackQuery)
        user = Mock(spec=User)
        user.id = 123456
        query.from_user = user
        query.data = "watchlist_remove_PEPE/USDT:USDT"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query

        # Create mock context
        from telegram.ext import ContextTypes
        context = Mock(spec=ContextTypes.DEFAULT_TYPE)

        # Mock database
        with patch('bot.telegram_bot.db') as mock_db:
            mock_db.is_admin_async = AsyncMock(return_value=True)
            mock_db.remove_from_watchlist_async = AsyncMock(return_value=True)

            # Mock app reload
            app.reload_watchlist = AsyncMock()

            import asyncio
            asyncio.run(bot.handle_watchlist_callback(update, context))

            # Verify reload was called
            app.reload_watchlist.assert_called_once()

    def test_restart_loads_watchlist_correctly(self, setup_database):
        """Test that bot restart loads watchlist correctly"""
        from core.main import TradingBotApp
        from core.database import db

        # Add symbol to database
        db.add_to_watchlist("PEPE/USDT:USDT", added_by=123456)

        # Simulate restart - create new app instance
        app = TradingBotApp()

        # Load watchlist
        import asyncio
        asyncio.run(app.load_watchlist())

        # Verify loaded correctly
        assert "PEPE/USDT:USDT" in app.active_symbols
        assert len(app.active_symbols) == 1

    def test_multiple_symbols_sync_correctly(self, setup_database):
        """Test that multiple symbols sync correctly"""
        from core.main import TradingBotApp
        from core.database import db

        app = TradingBotApp()

        # Add multiple symbols
        db.add_to_watchlist("BTC/USDT:USDT", added_by=123456)
        db.add_to_watchlist("ETH/USDT:USDT", added_by=123456)
        db.add_to_watchlist("PEPE/USDT:USDT", added_by=123456)

        # Reload
        import asyncio
        asyncio.run(app.reload_watchlist())

        # Verify all symbols synced
        assert len(app.active_symbols) == 3
        assert "BTC/USDT:USDT" in app.active_symbols
        assert "ETH/USDT:USDT" in app.active_symbols
        assert "PEPE/USDT:USDT" in app.active_symbols

    def test_reload_logs_transition(self, setup_database):
        """Test that reload logs the transition from old to new symbols"""
        from core.main import TradingBotApp
        from core.database import db
        import logging
        from io import StringIO

        app = TradingBotApp()

        # Setup logging capture
        log_capture = StringIO()
        handler = logging.StreamHandler(log_capture)
        logger = logging.getLogger('core.main')
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Initial load
        import asyncio
        asyncio.run(app.load_watchlist())

        # Add symbol
        db.add_to_watchlist("PEPE/USDT:USDT", added_by=123456)

        # Reload
        asyncio.run(app.reload_watchlist())

        # Check logs
        log_output = log_capture.getvalue()
        assert "Reloaded watchlist" in log_output
        assert "PEPE/USDT:USDT" in log_output

        logger.removeHandler(handler)

    def test_empty_watchlist_sync(self, setup_database):
        """Test that empty watchlist syncs correctly"""
        from core.main import TradingBotApp
        from core.database import db

        app = TradingBotApp()

        # Ensure empty
        db.clear_watchlist()

        # Reload
        import asyncio
        asyncio.run(app.reload_watchlist())

        # Verify empty
        assert len(app.active_symbols) == 0
        assert app.active_symbols == []

    def test_bot_app_none_handling(self, setup_database):
        """Test that bot_app=None is handled gracefully"""
        from bot.telegram_bot import TelegramBot
        from core.database import db

        bot = TelegramBot()
        # Don't set bot_app - should handle gracefully
        bot.market_data = Mock()
        bot.market_data.get_ticker = AsyncMock(return_value={'last': 50000.0})

        # Create mock update for symbol input
        from telegram import Update, Message, User
        message_update = Mock(spec=Update)
        message = Mock(spec=Message)
        user = Mock(spec=User)
        user.id = 123456
        message.text = "PEPE"
        message.reply_text = AsyncMock()
        message_update.message = message
        message_update.effective_user = user

        # Create mock context
        from telegram.ext import ContextTypes
        context = Mock(spec=ContextTypes.DEFAULT_TYPE)
        context.user_data = {'waiting_for_symbol': True}

        # Mock database
        with patch('bot.telegram_bot.db') as mock_db:
            mock_db.is_admin_async = AsyncMock(return_value=True)
            mock_db.get_watchlist_async = AsyncMock(return_value=[])
            mock_db.add_to_watchlist_async = AsyncMock(return_value=True)

            import asyncio
            # Should not crash even without bot_app
            asyncio.run(bot.handle_symbol_input(message_update, context))

            # Verify message still sent
            message.reply_text.assert_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
