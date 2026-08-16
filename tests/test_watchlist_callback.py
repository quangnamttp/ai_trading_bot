"""
Tests for Telegram Watchlist Callback Flow
Tests the specific bug fix for "➕ Thêm coin" callback loading issue
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from telegram import Update, CallbackQuery, User, Message
from telegram.ext import ContextTypes


class TestWatchlistCallbackFlow:
    """Test watchlist callback flow to prevent loading bug"""

    @pytest.fixture
    def mock_update(self):
        """Create mock Update with callback query"""
        update = Mock(spec=Update)
        query = Mock(spec=CallbackQuery)
        user = Mock(spec=User)
        user.id = 123456
        query.from_user = user
        query.data = "watchlist_add"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        return update

    @pytest.fixture
    def mock_context(self):
        """Create mock Context"""
        context = Mock(spec=ContextTypes.DEFAULT_TYPE)
        context.user_data = {}
        return context

    @pytest.fixture
    def setup_database(self):
        """Setup test database"""
        from core.database import db
        db.init_database()
        db.clear_watchlist()
        yield
        db.clear_watchlist()

    def test_callback_acknowledged_immediately(self, mock_update, mock_context):
        """Test callback is acknowledged immediately to prevent loading"""
        from bot.telegram_bot import TelegramBot

        bot = TelegramBot()
        bot.market_data = None

        # Mock database
        with patch('bot.telegram_bot.db') as mock_db:
            mock_db.is_admin_async = AsyncMock(return_value=True)

            # Run callback handler
            import asyncio
            asyncio.run(bot.handle_watchlist_callback(mock_update, mock_context))

            # Verify callback was acknowledged
            mock_update.callback_query.answer.assert_called_once()

    def test_callback_sets_waiting_state(self, mock_update, mock_context):
        """Test callback sets waiting_for_symbol state"""
        from bot.telegram_bot import TelegramBot

        bot = TelegramBot()
        bot.market_data = None

        with patch('bot.telegram_bot.db') as mock_db:
            mock_db.is_admin_async = AsyncMock(return_value=True)

            import asyncio
            asyncio.run(bot.handle_watchlist_callback(mock_update, mock_context))

            # Verify state was set
            assert mock_context.user_data.get('waiting_for_symbol') is True

    def test_callback_sends_prompt_message(self, mock_update, mock_context):
        """Test callback sends prompt message for symbol input"""
        from bot.telegram_bot import TelegramBot

        bot = TelegramBot()
        bot.market_data = None

        with patch('bot.telegram_bot.db') as mock_db:
            mock_db.is_admin_async = AsyncMock(return_value=True)

            import asyncio
            asyncio.run(bot.handle_watchlist_callback(mock_update, mock_context))

            # Verify prompt was sent
            mock_update.callback_query.edit_message_text.assert_called_once()
            call_args = mock_update.callback_query.edit_message_text.call_args
            message = call_args[0][0]
            assert "Nhập symbol muốn thêm" in message
            assert "BTC ETH SUI DOGE XRP" in message

    def test_non_admin_denied(self, mock_update, mock_context):
        """Test non-admin is denied access"""
        from bot.telegram_bot import TelegramBot

        bot = TelegramBot()
        bot.market_data = None

        with patch('bot.telegram_bot.db') as mock_db:
            mock_db.is_admin_async = AsyncMock(return_value=False)

            import asyncio
            asyncio.run(bot.handle_watchlist_callback(mock_update, mock_context))

            # Verify denial message
            mock_update.callback_query.edit_message_text.assert_called_once()
            call_args = mock_update.callback_query.edit_message_text.call_args
            message = call_args[0][0]
            assert "Chỉ Admin" in message

            # Verify state was NOT set
            assert mock_context.user_data.get('waiting_for_symbol') is None

    def test_callback_exception_handling(self, mock_update, mock_context):
        """Test callback exception doesn't cause infinite loading"""
        from bot.telegram_bot import TelegramBot

        bot = TelegramBot()
        bot.market_data = None

        with patch('bot.telegram_bot.db') as mock_db:
            # Make admin check fail
            mock_db.is_admin_async = AsyncMock(side_effect=Exception("DB error"))

            import asyncio
            try:
                asyncio.run(bot.handle_watchlist_callback(mock_update, mock_context))
            except:
                pass  # Exception is expected

            # Callback should still be acknowledged even on error
            mock_update.callback_query.answer.assert_called_once()

    def test_symbol_input_handler_called(self, mock_update, mock_context):
        """Test symbol input handler is called when in waiting state"""
        from bot.telegram_bot import TelegramBot

        bot = TelegramBot()
        bot.market_data = Mock()
        bot.market_data.get_ticker = AsyncMock(return_value={'last': 50000.0})

        # Create message update
        message_update = Mock(spec=Update)
        message = Mock(spec=Message)
        user = Mock(spec=User)
        user.id = 123456
        message.text = "BTC"
        message.reply_text = AsyncMock()
        message_update.message = message
        message_update.effective_user = user

        # Set waiting state
        mock_context.user_data['waiting_for_symbol'] = True

        with patch('bot.telegram_bot.db') as mock_db:
            mock_db.is_admin_async = AsyncMock(return_value=True)
            mock_db.get_watchlist_async = AsyncMock(return_value=[])
            mock_db.add_to_watchlist_async = AsyncMock(return_value=True)

            import asyncio
            asyncio.run(bot.handle_symbol_input(message_update, mock_context))

            # Verify state was cleared
            assert mock_context.user_data.get('waiting_for_symbol') is False

            # Verify symbol was normalized
            mock_db.add_to_watchlist_async.assert_called_once()
            call_args = mock_db.add_to_watchlist_async.call_args
            symbol = call_args[0][0]
            assert symbol == "BTC/USDT:USDT"

    def test_symbol_input_denied_without_state(self, mock_update, mock_context):
        """Test symbol input is denied when not in waiting state"""
        from bot.telegram_bot import TelegramBot

        bot = TelegramBot()

        # Create message update
        message_update = Mock(spec=Update)
        message = Mock(spec=Message)
        user = Mock(spec=User)
        user.id = 123456
        message.text = "BTC"
        message.reply_text = AsyncMock()
        message_update.message = message
        message_update.effective_user = user

        # Don't set waiting state
        mock_context.user_data = {}

        with patch('bot.telegram_bot.db') as mock_db:
            mock_db.is_admin_async = AsyncMock(return_value=True)

            import asyncio
            asyncio.run(bot.handle_symbol_input(message_update, mock_context))

            # Verify no database operation was attempted
            mock_db.add_to_watchlist_async.assert_not_called()

    def test_symbol_normalization(self, mock_update, mock_context):
        """Test symbol is normalized correctly"""
        from bot.telegram_bot import TelegramBot

        bot = TelegramBot()
        bot.market_data = Mock()
        bot.market_data.get_ticker = AsyncMock(return_value={'last': 50000.0})

        # Create message update
        message_update = Mock(spec=Update)
        message = Mock(spec=Message)
        user = Mock(spec=User)
        user.id = 123456
        message.text = "ETH"
        message.reply_text = AsyncMock()
        message_update.message = message
        message_update.effective_user = user

        mock_context.user_data['waiting_for_symbol'] = True

        with patch('bot.telegram_bot.db') as mock_db:
            mock_db.is_admin_async = AsyncMock(return_value=True)
            mock_db.get_watchlist_async = AsyncMock(return_value=[])
            mock_db.add_to_watchlist_async = AsyncMock(return_value=True)

            import asyncio
            asyncio.run(bot.handle_symbol_input(message_update, mock_context))

            # Verify normalization
            call_args = mock_db.add_to_watchlist_async.call_args
            symbol = call_args[0][0]
            assert symbol == "ETH/USDT:USDT"

    def test_symbol_validation_exchange_check(self, mock_update, mock_context):
        """Test symbol is validated against exchange"""
        from bot.telegram_bot import TelegramBot

        bot = TelegramBot()
        bot.market_data = Mock()
        bot.market_data.get_ticker = AsyncMock(return_value=None)  # Symbol not found

        # Create message update
        message_update = Mock(spec=Update)
        message = Mock(spec=Message)
        user = Mock(spec=User)
        user.id = 123456
        message.text = "INVALID"
        message.reply_text = AsyncMock()
        message_update.message = message
        message_update.effective_user = user

        mock_context.user_data['waiting_for_symbol'] = True

        with patch('bot.telegram_bot.db') as mock_db:
            mock_db.is_admin_async = AsyncMock(return_value=True)

            import asyncio
            asyncio.run(bot.handle_symbol_input(message_update, mock_context))

            # Verify validation failed
            message.reply_text.assert_called_once()
            call_args = message.reply_text.call_args
            message_text = call_args[0][0]
            assert "không tồn tại" in message_text

            # Verify symbol was not added
            mock_db.add_to_watchlist_async.assert_not_called()

    def test_duplicate_symbol_detection(self, mock_update, mock_context):
        """Test duplicate symbol is detected"""
        from bot.telegram_bot import TelegramBot

        bot = TelegramBot()
        bot.market_data = Mock()
        bot.market_data.get_ticker = AsyncMock(return_value={'last': 50000.0})

        # Create message update
        message_update = Mock(spec=Update)
        message = Mock(spec=Message)
        user = Mock(spec=User)
        user.id = 123456
        message.text = "BTC"
        message.reply_text = AsyncMock()
        message_update.message = message
        message_update.effective_user = user

        mock_context.user_data['waiting_for_symbol'] = True

        with patch('bot.telegram_bot.db') as mock_db:
            mock_db.is_admin_async = AsyncMock(return_value=True)
            mock_db.get_watchlist_async = AsyncMock(return_value=["BTC/USDT:USDT"])  # Already exists

            import asyncio
            asyncio.run(bot.handle_symbol_input(message_update, mock_context))

            # Verify duplicate detected
            message.reply_text.assert_called_once()
            call_args = message.reply_text.call_args
            message_text = call_args[0][0]
            assert "đã có trong watchlist" in message_text

            # Verify symbol was not added again
            mock_db.add_to_watchlist_async.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
