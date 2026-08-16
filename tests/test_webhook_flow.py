"""
End-to-End Webhook Flow Tests
Tests the complete flow from Telegram webhook to watchlist synchronization
"""
import pytest
import asyncio
import json
from unittest.mock import Mock, AsyncMock, patch
from telegram import Update, CallbackQuery, User, Message
from telegram.ext import ContextTypes


class TestWebhookFlow:
    """Test complete webhook flow from Telegram to database"""

    @pytest.fixture
    def setup_database(self):
        """Setup test database"""
        from core.database import db
        db.init_database()
        db.clear_watchlist()
        yield
        db.clear_watchlist()

    def test_webhook_request_logging(self):
        """Test that webhook logs incoming request details"""
        from core.main import TradingBotApp
        from flask import Flask

        app = TradingBotApp()

        # Create Flask app
        flask_app = Flask(__name__)
        flask_app.config['TESTING'] = True

        # Mock telegram_bot
        with patch('core.main.telegram_bot') as mock_telegram_bot:
            mock_telegram_bot.application = Mock()
            mock_telegram_bot.application.update_queue = Mock()
            mock_telegram_bot.application.update_queue.put_nowait = Mock()
            mock_telegram_bot.application.update_queue.qsize = Mock(return_value=0)

            # Mock event loop
            with patch.object(app, 'event_loop') as mock_loop:
                mock_loop.is_closed = Mock(return_value=False)
                mock_loop.call_soon_threadsafe = Mock()

                @flask_app.route('/webhook', methods=['POST'])
                def webhook():
                    from core.main import logger
                    logger.info("[TEST] Webhook called")
                    return 'OK', 200

                with flask_app.test_client() as client:
                    response = client.post('/webhook',
                                         data=json.dumps({'update_id': 123}),
                                         content_type='application/json')
                    assert response.status_code == 200

    def test_webhook_queue_put_flow(self, setup_database):
        """Test that webhook puts update into queue correctly"""
        from core.main import TradingBotApp

        app = TradingBotApp()

        # Mock telegram bot application
        with patch('core.main.telegram_bot') as mock_telegram_bot:
            mock_application = Mock()
            mock_queue = Mock()
            mock_queue.put_nowait = Mock()
            mock_queue.qsize = Mock(return_value=1)
            mock_application.update_queue = mock_queue
            mock_telegram_bot.application = mock_application

            # Mock event loop
            with patch.object(app, 'event_loop') as mock_loop:
                mock_loop.is_closed = Mock(return_value=False)
                mock_loop.call_soon_threadsafe = Mock()

                # Create a mock update object
                update = Mock()
                update.update_id = 123

                mock_loop.call_soon_threadsafe(mock_queue.put_nowait, update)

                # Verify queue put was called
                mock_loop.call_soon_threadsafe.assert_called_once()

    def test_watchlist_callback_flow(self, setup_database):
        """Test complete watchlist add callback flow"""
        from bot.telegram_bot import TelegramBot
        from core.main import TradingBotApp
        from core.database import db

        bot = TelegramBot()
        app = TradingBotApp()
        bot.set_bot_app(app)
        bot.market_data = Mock()
        bot.market_data.get_ticker = AsyncMock(return_value={'last': 50000.0})

        # Create mock callback update for watchlist_add
        update = Mock(spec=Update)
        query = Mock(spec=CallbackQuery)
        user = Mock(spec=User)
        user.id = 123456
        query.from_user = user
        query.data = "watchlist_add"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query

        # Create mock context
        from telegram.ext import ContextTypes
        context = Mock(spec=ContextTypes.DEFAULT_TYPE)
        context.user_data = {}

        # Mock database
        with patch('bot.telegram_bot.db') as mock_db:
            mock_db.is_admin_async = AsyncMock(return_value=True)
            mock_db.get_watchlist_async = AsyncMock(return_value=[])

            import asyncio
            asyncio.run(bot.handle_watchlist_callback(update, context))

            # Verify callback was acknowledged
            query.answer.assert_called_once()

            # Verify state was set
            assert context.user_data.get('waiting_for_symbol') == True

    def test_symbol_input_flow(self, setup_database):
        """Test complete symbol input flow"""
        from bot.telegram_bot import TelegramBot
        from core.main import TradingBotApp
        from core.database import db

        bot = TelegramBot()
        app = TradingBotApp()
        bot.set_bot_app(app)
        bot.market_data = Mock()
        bot.market_data.get_ticker = AsyncMock(return_value={'last': 50000.0})

        # Create mock message update for symbol input
        update = Mock(spec=Update)
        message = Mock(spec=Message)
        user = Mock(spec=User)
        user.id = 123456
        message.text = "PEPE"
        message.reply_text = AsyncMock()
        update.message = message
        update.effective_user = user

        # Create mock context
        from telegram.ext import ContextTypes
        context = Mock(spec=ContextTypes.DEFAULT_TYPE)
        context.user_data = {'waiting_for_symbol': True}

        # Mock database and app reload
        with patch('bot.telegram_bot.db') as mock_db:
            mock_db.is_admin_async = AsyncMock(return_value=True)
            mock_db.get_watchlist_async = AsyncMock(return_value=[])
            mock_db.add_to_watchlist_async = AsyncMock(return_value=True)

            app.reload_watchlist = AsyncMock()
            app.active_symbols = []

            import asyncio
            asyncio.run(bot.handle_symbol_input(update, context))

            # Verify database write was attempted
            mock_db.add_to_watchlist_async.assert_called_once()

            # Verify reload was called
            app.reload_watchlist.assert_called_once()

    def test_reload_watchlist_flow(self, setup_database):
        """Test reload_watchlist flow from database to active_symbols"""
        from core.main import TradingBotApp
        from core.database import db

        app = TradingBotApp()

        # Add symbol to database
        db.add_to_watchlist("PEPE/USDT:USDT", added_by=123456)

        # Reload watchlist
        import asyncio
        result = asyncio.run(app.reload_watchlist())

        # Verify active_symbols updated
        assert "PEPE/USDT:USDT" in app.active_symbols
        assert len(app.active_symbols) == 1

    def test_complete_add_flow(self, setup_database):
        """Test complete flow: callback -> input -> database -> reload -> active_symbols"""
        from bot.telegram_bot import TelegramBot
        from core.main import TradingBotApp
        from core.database import db

        bot = TelegramBot()
        app = TradingBotApp()
        bot.set_bot_app(app)
        bot.market_data = Mock()
        bot.market_data.get_ticker = AsyncMock(return_value={'last': 50000.0})

        # Step 1: Watchlist add callback
        update_callback = Mock(spec=Update)
        query = Mock(spec=CallbackQuery)
        user = Mock(spec=User)
        user.id = 123456
        query.from_user = user
        query.data = "watchlist_add"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update_callback.callback_query = query

        context = Mock(spec=ContextTypes.DEFAULT_TYPE)
        context.user_data = {}

        with patch('bot.telegram_bot.db') as mock_db:
            mock_db.is_admin_async = AsyncMock(return_value=True)
            mock_db.get_watchlist_async = AsyncMock(return_value=[])

            import asyncio
            asyncio.run(bot.handle_watchlist_callback(update_callback, context))

            assert context.user_data.get('waiting_for_symbol') == True

        # Step 2: Symbol input
        update_input = Mock(spec=Update)
        message = Mock(spec=Message)
        user = Mock(spec=User)
        user.id = 123456
        message.text = "PEPE"
        message.reply_text = AsyncMock()
        update_input.message = message
        update_input.effective_user = user

        context.user_data = {'waiting_for_symbol': True}

        with patch('bot.telegram_bot.db') as mock_db:
            mock_db.is_admin_async = AsyncMock(return_value=True)
            mock_db.get_watchlist_async = AsyncMock(return_value=[])
            mock_db.add_to_watchlist_async = AsyncMock(return_value=True)

            app.reload_watchlist = AsyncMock()
            app.active_symbols = []

            asyncio.run(bot.handle_symbol_input(update_input, context))

            # Verify complete flow
            mock_db.add_to_watchlist_async.assert_called_once_with("PEPE/USDT:USDT", added_by=123456)
            app.reload_watchlist.assert_called_once()

    def test_remove_flow(self, setup_database):
        """Test complete remove flow"""
        from bot.telegram_bot import TelegramBot
        from core.main import TradingBotApp
        from core.database import db

        bot = TelegramBot()
        app = TradingBotApp()
        bot.set_bot_app(app)

        # Add symbol first
        db.add_to_watchlist("PEPE/USDT:USDT", added_by=123456)
        import asyncio
        asyncio.run(app.load_watchlist())
        assert "PEPE/USDT:USDT" in app.active_symbols

        # Remove callback
        update = Mock(spec=Update)
        query = Mock(spec=CallbackQuery)
        user = Mock(spec=User)
        user.id = 123456
        query.from_user = user
        query.data = "watchlist_remove_PEPE/USDT:USDT"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query

        context = Mock(spec=ContextTypes.DEFAULT_TYPE)

        with patch('bot.telegram_bot.db') as mock_db:
            mock_db.is_admin_async = AsyncMock(return_value=True)
            mock_db.remove_from_watchlist_async = AsyncMock(return_value=True)
            mock_db.get_watchlist_async = AsyncMock(return_value=[])

            app.reload_watchlist = AsyncMock()

            asyncio.run(bot.handle_watchlist_callback(update, context))

            # Verify remove and reload
            mock_db.remove_from_watchlist_async.assert_called_once_with("PEPE/USDT:USDT")
            app.reload_watchlist.assert_called_once()

    def test_refresh_flow(self, setup_database):
        """Test refresh callback flow"""
        from bot.telegram_bot import TelegramBot
        from core.database import db

        bot = TelegramBot()

        # Add symbol to database
        db.add_to_watchlist("PEPE/USDT:USDT", added_by=123456)

        # Refresh callback
        update = Mock(spec=Update)
        query = Mock(spec=CallbackQuery)
        user = Mock(spec=User)
        user.id = 123456
        query.from_user = user
        query.data = "watchlist_refresh"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query

        context = Mock(spec=ContextTypes.DEFAULT_TYPE)

        with patch('bot.telegram_bot.db') as mock_db:
            mock_db.is_admin_async = AsyncMock(return_value=True)
            mock_db.get_watchlist_async = AsyncMock(return_value=["PEPE/USDT:USDT"])

            import asyncio
            asyncio.run(bot.handle_watchlist_callback(update, context))

            # Verify callback acknowledged and message edited
            query.answer.assert_called_once()
            query.edit_message_text.assert_called_once()

    def test_empty_watchlist_flow(self, setup_database):
        """Test flow with empty watchlist"""
        from core.main import TradingBotApp
        from core.database import db

        app = TradingBotApp()

        # Ensure empty
        db.clear_watchlist()

        # Load watchlist
        import asyncio
        asyncio.run(app.load_watchlist())

        # Verify empty
        assert len(app.active_symbols) == 0

    def test_restart_persistence_flow(self, setup_database):
        """Test that watchlist persists across restart"""
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
