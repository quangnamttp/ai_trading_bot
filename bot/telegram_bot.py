"""
Module Telegram Bot cho AI Trading Signal Bot
Xử lý tất cả các lệnh và tin nhắn từ người dùng
"""
import logging
import os
from datetime import datetime
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, MenuButtonDefault
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from core.config import TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_ID, TELEGRAM_WEBHOOK_URL
from core.database import db
from core.statistics import statistics_manager

logger = logging.getLogger(__name__)


class TelegramBot:
    """Quản lý Telegram Bot"""

    def __init__(self):
        self.application = None
        self.signal_engine = None
        self.market_data = None
        self.running = False
        self.queue_timestamps = None  # Safe timing tracking dictionary
        self.bot_app = None  # Reference to TradingBotApp for watchlist sync

    def set_dependencies(self, signal_engine, market_data):
        """Set dependencies cho bot"""
        self.signal_engine = signal_engine
        self.market_data = market_data

    def set_queue_timestamps(self, queue_timestamps):
        """Set the safe timing tracking dictionary"""
        self.queue_timestamps = queue_timestamps

    def set_queue_stack_traces(self, queue_stack_traces):
        """Set the stack trace tracking dictionary for blocking detection"""
        self.queue_stack_traces = queue_stack_traces

    def set_bot_app(self, bot_app):
        """Set reference to TradingBotApp for watchlist synchronization"""
        self.bot_app = bot_app
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /start - Khởi động bot"""
        import time
        handler_start = time.time()
        user = update.effective_user
        update_id = update.update_id

        # Calculate queue wait duration (from webhook queue put to consumer start)
        queue_wait_duration_ms = 0
        if self.queue_timestamps and update_id in self.queue_timestamps:
            queue_put_timestamp = self.queue_timestamps[update_id]
            queue_consumer_start = time.time()
            queue_wait_duration_ms = (queue_consumer_start - datetime.fromisoformat(queue_put_timestamp).timestamp()) * 1000
            logger.info(f"[QUEUE WAIT] duration_ms={queue_wait_duration_ms:.2f}, update_id={update_id}")
            if queue_wait_duration_ms > 1000:
                logger.warning(f"[SLOW QUEUE WAIT] duration_ms={queue_wait_duration_ms:.2f}, update_id={update_id}")
                # Log stack trace from queue put time to identify blocking operation
                if self.queue_stack_traces and update_id in self.queue_stack_traces:
                    stack_trace = self.queue_stack_traces[update_id]
                    logger.error(f"[BLOCKING STACK TRACE at queue put time] update_id={update_id}:\n{stack_trace}")
            # Clean up the timestamp after use
            del self.queue_timestamps[update_id]
            if self.queue_stack_traces and update_id in self.queue_stack_traces:
                del self.queue_stack_traces[update_id]

        # Kiểm tra xem user có bị ban không
        is_banned = await db.is_banned_async(user.id)
        if is_banned:
            await update.message.reply_text("❌ Bạn đã bị ban khỏi bot.")
            return

        # Lưu user vào database
        is_admin = await db.is_admin_async(user.id)
        await db.add_user_async(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            is_admin=is_admin
        )

        # Hiển thị menu chính với Reply Keyboard - tùy theo quyền
        reply_markup = self.get_reply_keyboard(is_admin)

        welcome_message = f"""
🤖 <b>AI Trading Signal Bot</b>

👤 Xin chào, {user.first_name}!

Bot phân tích thị trường 24/7 và gửi tín hiệu giao dịch với độ chính xác cao.

⚠️ <b>Lưu ý:</b> Bot chỉ cung cấp tín hiệu phân tích, không tự động giao dịch. Bạn tự quyết định vào lệnh thủ công.
        """

        try:
            await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error sending start message: {e}", exc_info=True)
            raise

        handler_duration_ms = (time.time() - handler_start) * 1000
        logger.info(f"[HANDLER DURATION] duration_ms={handler_duration_ms:.2f}, update_id={update_id}")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /help - Hiển thị trợ giúp"""
        from core.config import AI_SCORE_THRESHOLD
        help_message = f"""
🤖 <b>AI Trading Signal Bot - Hướng dẫn sử dụng</b>

🔹 <b>Lệnh cơ bản:</b>
/start - Bắt đầu sử dụng bot
/help - Hiển thị trợ giúp này
/status - Trạng thái bot
/market - Thông tin thị trường
/news - Tin tức Crypto & Forex mới

🔹 <b>Quản trị (Chỉ Admin):</b>
/ban <user_id> - Cấm người dùng
/unban <user_id> - Bỏ cấm người dùng
/users - Danh sách người dùng
/settings - Cấu hình bot
/broadcast <message> - Gửi thông báo đến tất cả

📊 <b>Thống kê:</b>
/stats - Xem thống kê tín hiệu

🤖 <b>Bot hoạt động 24/7 quét dữ liệu thị trường và gửi tín hiệu khi Điểm AI > {AI_SCORE_THRESHOLD}%</b>

⚠️ <b>Bot không tự động giao dịch. Tín hiệu chỉ để tham khảo.</b>
        """

        await update.message.reply_text(help_message, parse_mode='HTML')
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /status - Trạng thái bot"""
        from core.config import AI_SCORE_THRESHOLD
        user_id = update.effective_user.id

        # Kiểm tra quyền truy cập
        if not db.is_authorized(user_id):
            await update.message.reply_text("❌ Bạn không có quyền sử dụng bot này.")
            return

        # Lấy thống kê
        total_users = len(await db.get_all_users_async())
        recent_signals = await db.get_recent_signals_async(limit=5)
        recent_ai_logs = await db.get_recent_ai_logs_async(limit=5)

        status_message = f"""
📊 <b>Trạng thái Bot</b>

🕒 Thời gian: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

👥 Người dùng: {total_users}
📈 Tín hiệu gần đây: {len(recent_signals)}
🤖 Nhật ký AI: {len(recent_ai_logs)}

✅ Bot đang hoạt động 24/7
🔄 Quét dữ liệu thị trường liên tục
🎯 Gửi tín hiệu khi Điểm AI > {AI_SCORE_THRESHOLD}%
        """

        await update.message.reply_text(status_message, parse_mode='HTML')
    
    async def market_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /market - Thông tin thị trường"""
        from datetime import datetime
        timestamp = datetime.now().isoformat()
        user_id = update.effective_user.id

        logger.info(f"[MARKET COMMAND ENTER] user_id={user_id}, timestamp={timestamp}")

        if not await db.is_authorized_async(user_id):
            logger.info(f"[MARKET COMMAND DENIED] user_id={user_id}, reason=NOT_AUTHORIZED")
            await update.message.reply_text("❌ Bạn không có quyền sử dụng bot này.")
            return

        logger.info(f"[MARKET COMMAND PROCESSING] user_id={user_id}, timestamp={datetime.now().isoformat()}")

        try:
            if self.market_data:
                market_info = await self.market_data.get_market_overview()
                if market_info:
                    logger.info(f"[MARKET COMMAND SENDING RESPONSE] user_id={user_id}, timestamp={datetime.now().isoformat()}")
                    await update.message.reply_text(market_info, parse_mode='Markdown')
                    logger.info(f"[MARKET COMMAND RESPONSE SENT] user_id={user_id}, timestamp={datetime.now().isoformat()}")
                else:
                    logger.error("[MARKET COMMAND ERROR] Market data not available")
                    await update.message.reply_text("📊 Dữ liệu thị trường không khả dụng lúc này.")
            else:
                logger.error("[MARKET COMMAND ERROR] Market data engine not initialized")
                await update.message.reply_text("📊 Dữ liệu thị trường không khả dụng lúc này.")
        except Exception as e:
            logger.error(f"[MARKET COMMAND ERROR] user_id={user_id}, error={e}", exc_info=True)
            await update.message.reply_text("📊 Dữ liệu thị trường không khả dụng lúc này.")

        logger.info(f"[MARKET COMMAND EXIT] user_id={user_id}, timestamp={datetime.now().isoformat()}")
    
    async def news_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /news - Tin tức"""
        from datetime import datetime
        timestamp = datetime.now().isoformat()
        user_id = update.effective_user.id

        logger.info(f"[NEWS COMMAND ENTER] user_id={user_id}, timestamp={timestamp}")

        if not await db.is_authorized_async(user_id):
            logger.info(f"[NEWS COMMAND DENIED] user_id={user_id}, reason=NOT_AUTHORIZED")
            await update.message.reply_text("❌ Bạn không có quyền sử dụng bot này.")
            return

        logger.info(f"[NEWS COMMAND PROCESSING] user_id={user_id}, timestamp={datetime.now().isoformat()}")

        try:
            from data.news_engine import news_engine

            # Get real news summary from news engine
            news_summary = await news_engine.get_news_summary()

            if news_summary:
                logger.info(f"[NEWS COMMAND SENDING RESPONSE] user_id={user_id}, timestamp={datetime.now().isoformat()}")
                await update.message.reply_text(news_summary, parse_mode='Markdown')
                logger.info(f"[NEWS COMMAND RESPONSE SENT] user_id={user_id}, timestamp={datetime.now().isoformat()}")
            else:
                logger.error("[NEWS COMMAND ERROR] News summary not available")
                await update.message.reply_text("📰 Tin tức không khả dụng lúc này.")
        except Exception as e:
            logger.error(f"[NEWS COMMAND ERROR] user_id={user_id}, error={e}", exc_info=True)
            await update.message.reply_text("📰 Tin tức không khả dụng lúc này.")

        logger.info(f"[NEWS COMMAND EXIT] user_id={user_id}, timestamp={datetime.now().isoformat()}")
    
    async def settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /settings - Cấu hình (Admin only)"""
        user_id = update.effective_user.id
        
        if not await db.is_admin_async(user_id):
            await update.message.reply_text("❌ Chỉ Admin mới sử dụng lệnh này.")
            return
        
        # Hiển thị menu cấu hình
        keyboard = [
            [InlineKeyboardButton("📊 Xem cấu hình", callback_data="config_view")],
            [InlineKeyboardButton("🔧 Đổi ngưỡng AI Score", callback_data="config_ai_threshold")],
            [InlineKeyboardButton("🔙 Quay lại", callback_data="config_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text("⚙️ *Cấu hình Bot*", reply_markup=reply_markup, parse_mode='Markdown')
    
    async def id_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /id - Xem Telegram ID"""
        user_id = update.effective_user.id
        username = update.effective_user.username or "N/A"
        
        id_message = f"""
🆔 *Thông tin của bạn:*

👤 Telegram ID: `{user_id}`
📛 Username: @{username}

📌 Sử dụng ID này để Admin thêm bạn vào danh sách nhận tín hiệu.
        """
        
        await update.message.reply_text(id_message, parse_mode='Markdown')
    
    # ==================== ADMIN COMMANDS ====================
    
    
    
    async def users_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /users - Danh sách người dùng (Admin only)"""
        user_id = update.effective_user.id

        if not await db.is_admin_async(user_id):
            await update.message.reply_text("❌ Chỉ Admin mới sử dụng lệnh này.")
            return

        users = await db.get_all_users_async()

        if not users:
            await update.message.reply_text("📋 Không có người dùng nào.")
            return

        users_list = "📋 *Danh sách người dùng:*\n\n"
        for user in users:
            admin_badge = " 👑" if user['is_admin'] else ""
            users_list += f"• ID: `{user['telegram_id']}`{admin_badge}\n"
            users_list += f"  Username: @{user['username'] or 'N/A'}\n"
            users_list += f"  Tên: {user['first_name'] or 'N/A'}\n\n"

        await update.message.reply_text(users_list, parse_mode='Markdown')
    
    async def broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /broadcast - Gửi thông báo (Admin only)"""
        user_id = update.effective_user.id

        if not await db.is_admin_async(user_id):
            await update.message.reply_text("❌ Chỉ Admin mới sử dụng lệnh này.")
            return

        if not context.args:
            await update.message.reply_text("❌ Sử dụng: /broadcast <message>")
            return

        message = " ".join(context.args)
        users = await db.get_all_users_async()

        success_count = 0
        for user in users:
            try:
                await context.bot.send_message(chat_id=user['telegram_id'], text=message)
                success_count += 1
            except Exception as e:
                logger.error(f"Error sending broadcast to {user['telegram_id']}: {e}")

        await update.message.reply_text(f"✅ Đã gửi thông báo đến {success_count}/{len(users)} người dùng.")
        logger.info(f"Admin {user_id} broadcasted message to {success_count} users")
    
    async def ban_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /ban - Cấm người dùng (Admin only)"""
        user_id = update.effective_user.id

        if not await db.is_admin_async(user_id):
            await update.message.reply_text("❌ Chỉ Admin mới sử dụng lệnh này.")
            return

        if not context.args or len(context.args) < 1:
            await update.message.reply_text("❌ Sử dụng: /ban <telegram_id> [reason]")
            return

        try:
            target_user_id = int(context.args[0])
            if target_user_id <= 0:
                await update.message.reply_text("❌ Telegram ID phải là số dương.")
                return

            reason = " ".join(context.args[1:]) if len(context.args) > 1 else None

            await db.ban_user_async(target_user_id, banned_by=user_id, reason=reason)
            await update.message.reply_text(f"✅ Đã cấm người dùng {target_user_id}")
            logger.info(f"Admin {user_id} banned user {target_user_id}")
        except ValueError:
            await update.message.reply_text("❌ Telegram ID phải là số.")
        except Exception as e:
            logger.error(f"Error banning user: {e}")
            await update.message.reply_text(f"❌ Lỗi: {str(e)}")
    
    async def unban_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /unban - Bỏ cấm người dùng (Admin only)"""
        user_id = update.effective_user.id

        if not await db.is_admin_async(user_id):
            await update.message.reply_text("❌ Chỉ Admin mới sử dụng lệnh này.")
            return

        if not context.args or len(context.args) < 1:
            await update.message.reply_text("❌ Sử dụng: /unban <telegram_id>")
            return

        try:
            target_user_id = int(context.args[0])
            if target_user_id <= 0:
                await update.message.reply_text("❌ Telegram ID phải là số dương.")
                return

            await db.unban_user_async(target_user_id)
            await update.message.reply_text(f"✅ Đã bỏ cấm người dùng {target_user_id}")
            logger.info(f"Admin {user_id} unbanned user {target_user_id}")
        except ValueError:
            await update.message.reply_text("❌ Telegram ID phải là số.")
        except Exception as e:
            logger.error(f"Error unbanning user: {e}")
            await update.message.reply_text(f"❌ Lỗi: {str(e)}")



    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /stats - Xem thống kê tín hiệu"""
        user_id = update.effective_user.id

        # Kiểm tra xem user có bị ban không
        if await db.is_banned_async(user_id):
            await update.message.reply_text("❌ Bạn đã bị cấm sử dụng bot.")
            return

        # Kiểm tra xem user có được phép sử dụng không
        if not await db.is_authorized_async(user_id):
            await update.message.reply_text("❌ Bạn chưa được phép sử dụng bot.")
            return

        try:
            # Lấy tham số period (default: all)
            period = 'all'
            if context.args and len(context.args) > 0:
                period_arg = context.args[0].lower()
                if period_arg in ['day', 'week', 'month']:
                    period = period_arg

            stats_message = statistics_manager.format_stats_message(period)
            await update.message.reply_text(stats_message, parse_mode='HTML')
            logger.info(f"User {user_id} requested stats (period: {period})")
        except Exception as e:
            logger.error(f"Error in stats command: {e}")
            await update.message.reply_text("❌ Không thể lấy thống kê.")
    
    async def signals_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /signals - Hiển thị tín hiệu"""
        from datetime import datetime
        timestamp = datetime.now().isoformat()
        user_id = update.effective_user.id

        logger.info(f"[SIGNALS COMMAND ENTER] user_id={user_id}, timestamp={timestamp}")

        if not await db.is_authorized_async(user_id):
            logger.info(f"[SIGNALS COMMAND DENIED] user_id={user_id}, reason=NOT_AUTHORIZED")
            await update.message.reply_text("❌ Bạn không có quyền sử dụng bot này.")
            return

        is_admin = await db.is_admin_async(user_id)
        logger.info(f"[SIGNALS COMMAND PROCESSING] user_id={user_id}, is_admin={is_admin}, timestamp={datetime.now().isoformat()}")
        await self.show_signals(update, is_admin)
        logger.info(f"[SIGNALS COMMAND EXIT] user_id={user_id}, timestamp={datetime.now().isoformat()}")
    
    async def analyze_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /analyze - Hiển thị phân tích"""
        from datetime import datetime
        timestamp = datetime.now().isoformat()
        user_id = update.effective_user.id

        logger.info(f"[ANALYZE COMMAND ENTER] user_id={user_id}, timestamp={timestamp}")

        if not await db.is_authorized_async(user_id):
            logger.info(f"[ANALYZE COMMAND DENIED] user_id={user_id}, reason=NOT_AUTHORIZED")
            await update.message.reply_text("❌ Bạn không có quyền sử dụng bot này.")
            return

        is_admin = await db.is_admin_async(user_id)
        logger.info(f"[ANALYZE COMMAND PROCESSING] user_id={user_id}, is_admin={is_admin}, timestamp={datetime.now().isoformat()}")
        await self.show_analysis(update, is_admin)
        logger.info(f"[ANALYZE COMMAND EXIT] user_id={user_id}, timestamp={datetime.now().isoformat()}")
    
    # ==================== CALLBACK HANDLERS ====================

    def get_reply_keyboard(self, is_admin: bool = False):
        """Tạo Reply Keyboard với 6 nút chính"""
        keyboard = [
            [KeyboardButton("📰 Tin tức"), KeyboardButton("📈 Thị trường")],
            [KeyboardButton("📨 Tín hiệu"), KeyboardButton("📊 Phân tích")],
            [KeyboardButton("⚙️ Cài đặt"), KeyboardButton("🪙 Danh sách coin")]
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False, is_persistent=True)

    def get_main_menu_keyboard(self, is_admin: bool = False):
        """Tạo keyboard cho menu chính - tùy theo quyền Admin/User (Inline Keyboard for submenus)"""
        if is_admin:
            return [
                [InlineKeyboardButton("📊 Phân tích", callback_data="menu_analysis")],
                [InlineKeyboardButton("📨 Tín hiệu", callback_data="menu_signals")],
                [InlineKeyboardButton("👤 Tài khoản", callback_data="menu_account")],
                [InlineKeyboardButton("⚙️ Cài đặt", callback_data="menu_settings")],
                [InlineKeyboardButton("📈 Thị trường", callback_data="menu_market")],
                [InlineKeyboardButton("📰 Tin tức", callback_data="menu_news")],
                [InlineKeyboardButton("📋 Danh sách lệnh", callback_data="menu_commands")],
                [InlineKeyboardButton("❓ Trợ giúp", callback_data="menu_help")]
            ]
        else:
            # User menu - không có Cài đặt (quản trị)
            return [
                [InlineKeyboardButton("📊 Phân tích", callback_data="menu_analysis")],
                [InlineKeyboardButton("📨 Tín hiệu", callback_data="menu_signals")],
                [InlineKeyboardButton("👤 Tài khoản", callback_data="menu_account")],
                [InlineKeyboardButton("📈 Thị trường", callback_data="menu_market")],
                [InlineKeyboardButton("📰 Tin tức", callback_data="menu_news")],
                [InlineKeyboardButton("📋 Danh sách lệnh", callback_data="menu_commands")],
                [InlineKeyboardButton("❓ Trợ giúp", callback_data="menu_help")]
            ]

    async def menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /menu - Hiển thị menu"""
        user = update.effective_user

        # Kiểm tra xem user có bị ban không
        is_banned = await db.is_banned_async(user.id)
        if is_banned:
            await update.message.reply_text("❌ Bạn đã bị ban khỏi bot.")
            return

        # Hiển thị menu với Reply Keyboard
        is_admin = await db.is_admin_async(user.id)
        reply_markup = self.get_reply_keyboard(is_admin)

        await update.message.reply_text(
            "🤖 <b>Menu chính</b>\n\nChọn chức năng từ menu bên dưới:",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        logger.info(f"User {user.id} requested menu")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Xử lý tin nhắn văn bản từ Reply Keyboard - comprehensive trace logging"""
        import asyncio
        import traceback
        from datetime import datetime

        # Get current event loop ID
        try:
            event_loop = asyncio.get_event_loop()
            event_loop_id = id(event_loop)
        except RuntimeError:
            event_loop = None
            event_loop_id = "NO_LOOP"

        queue_consumer_start_timestamp = datetime.now().isoformat()
        user = update.effective_user
        text = update.message.text
        update_id = update.update_id

        print(f"[QUEUE CONSUMER START] timestamp={queue_consumer_start_timestamp}, update_id={update_id}, event_loop_id={event_loop_id}")
        logger.info(f"[QUEUE CONSUMER START] timestamp={queue_consumer_start_timestamp}, update_id={update_id}, event_loop_id={event_loop_id}")

        # Calculate queue wait duration (from webhook queue put to consumer start)
        queue_wait_duration_ms = 0
        if self.queue_timestamps and update_id in self.queue_timestamps:
            queue_put_timestamp = self.queue_timestamps[update_id]
            queue_wait_duration_ms = (datetime.fromisoformat(queue_consumer_start_timestamp) - datetime.fromisoformat(queue_put_timestamp)).total_seconds() * 1000
            print(f"[QUEUE WAIT DURATION] duration_ms={queue_wait_duration_ms:.2f}, update_id={update_id}, event_loop_id={event_loop_id}")
            logger.info(f"[QUEUE WAIT DURATION] duration_ms={queue_wait_duration_ms:.2f}, update_id={update_id}, event_loop_id={event_loop_id}")
            if queue_wait_duration_ms > 1000:
                print(f"[SLOW QUEUE WAIT] duration_ms={queue_wait_duration_ms:.2f}, update_id={update_id}, event_loop_id={event_loop_id}")
                logger.warning(f"[SLOW QUEUE WAIT] duration_ms={queue_wait_duration_ms:.2f}, update_id={update_id}, event_loop_id={event_loop_id}")
            # Clean up the timestamp after use
            del self.queue_timestamps[update_id]

        print(f"[QUEUE WAIT START] timestamp={queue_consumer_start_timestamp}, update_id={update_id}, event_loop_id={event_loop_id}")
        logger.info(f"[QUEUE WAIT START] timestamp={queue_consumer_start_timestamp}, update_id={update_id}, event_loop_id={event_loop_id}")

        handler_enter_timestamp = datetime.now().isoformat()
        print(f"[HANDLER ENTER] timestamp={handler_enter_timestamp}, update_id={update_id}, user_id={user.id}, text={text}, event_loop_id={event_loop_id}")
        logger.info(f"[HANDLER ENTER] timestamp={handler_enter_timestamp}, update_id={update_id}, user_id={user.id}, text={text}, event_loop_id={event_loop_id}")

        # Kiểm tra xem user có bị ban không
        is_banned = await db.is_banned_async(user.id)
        if is_banned:
            print(f"[HANDLER BANNED] timestamp={datetime.now().isoformat()}, user_id={user.id}, event_loop_id={event_loop_id}")
            logger.info(f"[HANDLER BANNED] user_id={user.id}")
            await update.message.reply_text("❌ Bạn đã bị ban khỏi bot.")
            handler_exit_timestamp = datetime.now().isoformat()
            handler_duration_ms = (datetime.fromisoformat(handler_exit_timestamp) - datetime.fromisoformat(handler_enter_timestamp)).total_seconds() * 1000
            print(f"[HANDLER EXIT] timestamp={handler_exit_timestamp}, update_id={update_id}, user_id={user.id}, text={text}, reason=BANNED, duration_ms={handler_duration_ms:.2f}, event_loop_id={event_loop_id}")
            logger.info(f"[HANDLER EXIT] timestamp={handler_exit_timestamp}, update_id={update_id}, user_id={user.id}, text={text}, reason=BANNED, duration_ms={handler_duration_ms:.2f}, event_loop_id={event_loop_id}")
            return

        is_admin = await db.is_admin_async(user.id)
        print(f"[HANDLER AUTH] timestamp={datetime.now().isoformat()}, user_id={user.id}, is_admin={is_admin}, event_loop_id={event_loop_id}")
        logger.info(f"[HANDLER AUTH] user_id={user.id}, is_admin={is_admin}")

        # Check if waiting for symbol input
        if context.user_data.get('waiting_for_symbol'):
            await self.handle_symbol_input(update, context)
            return

        # Xử lý các nút menu - gọi trực tiếp các command handlers
        try:
            if text == "📰 Tin tức":
                button_received_timestamp = datetime.now().isoformat()
                print(f"[BUTTON RECEIVED] timestamp={button_received_timestamp}, text=📰 Tin tức, user_id={user.id}, update_id={update_id}, event_loop_id={event_loop_id}")
                logger.info(f"[BUTTON RECEIVED] timestamp={button_received_timestamp}, text=📰 Tin tức, user_id={user.id}, update_id={update_id}, event_loop_id={event_loop_id}")
                await self.news_command(update, context)
                button_completed_timestamp = datetime.now().isoformat()
                button_duration_ms = (datetime.fromisoformat(button_completed_timestamp) - datetime.fromisoformat(button_received_timestamp)).total_seconds() * 1000
                print(f"[BUTTON COMPLETED] timestamp={button_completed_timestamp}, text=📰 Tin tức, user_id={user.id}, update_id={update_id}, duration_ms={button_duration_ms:.2f}, event_loop_id={event_loop_id}")
                logger.info(f"[BUTTON COMPLETED] timestamp={button_completed_timestamp}, text=📰 Tin tức, user_id={user.id}, update_id={update_id}, duration_ms={button_duration_ms:.2f}, event_loop_id={event_loop_id}")
            elif text == "📈 Thị trường":
                button_received_timestamp = datetime.now().isoformat()
                print(f"[BUTTON RECEIVED] timestamp={button_received_timestamp}, text=📈 Thị trường, user_id={user.id}, update_id={update_id}, event_loop_id={event_loop_id}")
                logger.info(f"[BUTTON RECEIVED] timestamp={button_received_timestamp}, text=📈 Thị trường, user_id={user.id}, update_id={update_id}, event_loop_id={event_loop_id}")
                await self.market_command(update, context)
                button_completed_timestamp = datetime.now().isoformat()
                button_duration_ms = (datetime.fromisoformat(button_completed_timestamp) - datetime.fromisoformat(button_received_timestamp)).total_seconds() * 1000
                print(f"[BUTTON COMPLETED] timestamp={button_completed_timestamp}, text=📈 Thị trường, user_id={user.id}, update_id={update_id}, duration_ms={button_duration_ms:.2f}, event_loop_id={event_loop_id}")
                logger.info(f"[BUTTON COMPLETED] timestamp={button_completed_timestamp}, text=📈 Thị trường, user_id={user.id}, update_id={update_id}, duration_ms={button_duration_ms:.2f}, event_loop_id={event_loop_id}")
            elif text == "📨 Tín hiệu":
                button_received_timestamp = datetime.now().isoformat()
                print(f"[BUTTON RECEIVED] timestamp={button_received_timestamp}, text=📨 Tín hiệu, user_id={user.id}, update_id={update_id}, event_loop_id={event_loop_id}")
                logger.info(f"[BUTTON RECEIVED] timestamp={button_received_timestamp}, text=📨 Tín hiệu, user_id={user.id}, update_id={update_id}, event_loop_id={event_loop_id}")
                await self.signals_command(update, context)
                button_completed_timestamp = datetime.now().isoformat()
                button_duration_ms = (datetime.fromisoformat(button_completed_timestamp) - datetime.fromisoformat(button_received_timestamp)).total_seconds() * 1000
                print(f"[BUTTON COMPLETED] timestamp={button_completed_timestamp}, text=📨 Tín hiệu, user_id={user.id}, update_id={update_id}, duration_ms={button_duration_ms:.2f}, event_loop_id={event_loop_id}")
                logger.info(f"[BUTTON COMPLETED] timestamp={button_completed_timestamp}, text=📨 Tín hiệu, user_id={user.id}, update_id={update_id}, duration_ms={button_duration_ms:.2f}, event_loop_id={event_loop_id}")
            elif text == "📊 Phân tích":
                button_received_timestamp = datetime.now().isoformat()
                print(f"[BUTTON RECEIVED] timestamp={button_received_timestamp}, text=📊 Phân tích, user_id={user.id}, update_id={update_id}, event_loop_id={event_loop_id}")
                logger.info(f"[BUTTON RECEIVED] timestamp={button_received_timestamp}, text=📊 Phân tích, user_id={user.id}, update_id={update_id}, event_loop_id={event_loop_id}")
                await self.analyze_command(update, context)
                button_completed_timestamp = datetime.now().isoformat()
                button_duration_ms = (datetime.fromisoformat(button_completed_timestamp) - datetime.fromisoformat(button_received_timestamp)).total_seconds() * 1000
                print(f"[BUTTON COMPLETED] timestamp={button_completed_timestamp}, text=📊 Phân tích, user_id={user.id}, update_id={update_id}, duration_ms={button_duration_ms:.2f}, event_loop_id={event_loop_id}")
                logger.info(f"[BUTTON COMPLETED] timestamp={button_completed_timestamp}, text=📊 Phân tích, user_id={user.id}, update_id={update_id}, duration_ms={button_duration_ms:.2f}, event_loop_id={event_loop_id}")
            elif text == "⚙️ Cài đặt":
                button_received_timestamp = datetime.now().isoformat()
                print(f"[BUTTON RECEIVED] timestamp={button_received_timestamp}, text=⚙️ Cài đặt, user_id={user.id}, update_id={update_id}, event_loop_id={event_loop_id}")
                logger.info(f"[BUTTON RECEIVED] timestamp={button_received_timestamp}, text=⚙️ Cài đặt, user_id={user.id}, update_id={update_id}, event_loop_id={event_loop_id}")
                if is_admin:
                    await self.show_settings(update, is_admin)
                    button_completed_timestamp = datetime.now().isoformat()
                    button_duration_ms = (datetime.fromisoformat(button_completed_timestamp) - datetime.fromisoformat(button_received_timestamp)).total_seconds() * 1000
                    print(f"[BUTTON COMPLETED] timestamp={button_completed_timestamp}, text=⚙️ Cài đặt, user_id={user.id}, update_id={update_id}, duration_ms={button_duration_ms:.2f}, event_loop_id={event_loop_id}")
                    logger.info(f"[BUTTON COMPLETED] timestamp={button_completed_timestamp}, text=⚙️ Cài đặt, user_id={user.id}, update_id={update_id}, duration_ms={button_duration_ms:.2f}, event_loop_id={event_loop_id}")
                else:
                    await update.message.reply_text("⛔ Bạn không có quyền sử dụng chức năng này.")
                    button_denied_timestamp = datetime.now().isoformat()
                    print(f"[BUTTON DENIED] timestamp={button_denied_timestamp}, text=⚙️ Cài đặt, user_id={user.id}, reason=NOT_ADMIN, event_loop_id={event_loop_id}")
                    logger.info(f"[BUTTON DENIED] timestamp={button_denied_timestamp}, text=⚙️ Cài đặt, user_id={user.id}, reason=NOT_ADMIN, event_loop_id={event_loop_id}")
            elif text == "🪙 Danh sách coin":
                button_received_timestamp = datetime.now().isoformat()
                print(f"[BUTTON RECEIVED] timestamp={button_received_timestamp}, text=🪙 Danh sách coin, user_id={user.id}, update_id={update_id}, event_loop_id={event_loop_id}")
                logger.info(f"[BUTTON RECEIVED] timestamp={button_received_timestamp}, text=🪙 Danh sách coin, user_id={user.id}, update_id={update_id}, event_loop_id={event_loop_id}")
                await self.show_watchlist_manager(update, is_admin)
                button_completed_timestamp = datetime.now().isoformat()
                button_duration_ms = (datetime.fromisoformat(button_completed_timestamp) - datetime.fromisoformat(button_received_timestamp)).total_seconds() * 1000
                print(f"[BUTTON COMPLETED] timestamp={button_completed_timestamp}, text=🪙 Danh sách coin, user_id={user.id}, update_id={update_id}, duration_ms={button_duration_ms:.2f}, event_loop_id={event_loop_id}")
                logger.info(f"[BUTTON COMPLETED] timestamp={button_completed_timestamp}, text=🪙 Danh sách coin, user_id={user.id}, update_id={update_id}, duration_ms={button_duration_ms:.2f}, event_loop_id={event_loop_id}")
            else:
                # Tin nhắn không phải menu - có thể xử lý khác hoặc bỏ qua
                print(f"[HANDLER UNKNOWN] timestamp={datetime.now().isoformat()}, user_id={user.id}, text={text}, event_loop_id={event_loop_id}")
                logger.info(f"[HANDLER UNKNOWN] user_id={user.id}, text={text}, timestamp={datetime.now().isoformat()}")
                pass
        except Exception as e:
            error_timestamp = datetime.now().isoformat()
            print(f"[HANDLER ERROR] timestamp={error_timestamp}, user_id={user.id}, text={text}, error={e}")
            print(f"[FULL TRACEBACK]: {traceback.format_exc()}")
            logger.error(f"[HANDLER ERROR] user_id={user.id}, text={text}, error={e}", exc_info=True)
            await update.message.reply_text("❌ Có lỗi xảy ra khi xử lý tin nhắn.")

        handler_exit_timestamp = datetime.now().isoformat()
        handler_duration_ms = (datetime.fromisoformat(handler_exit_timestamp) - datetime.fromisoformat(handler_enter_timestamp)).total_seconds() * 1000
        print(f"[HANDLER EXIT] timestamp={handler_exit_timestamp}, update_id={update_id}, user_id={user.id}, text={text}, duration_ms={handler_duration_ms:.2f}, event_loop_id={event_loop_id}")
        logger.info(f"[HANDLER EXIT] timestamp={handler_exit_timestamp}, update_id={update_id}, user_id={user.id}, text={text}, duration_ms={handler_duration_ms:.2f}, event_loop_id={event_loop_id}")

    async def show_analysis(self, update: Update, is_admin: bool):
        """Hiển thị phân tích"""
        await update.message.reply_text(
            "📊 <b>Phân tích</b>\n\n"
            "Bot phân tích thị trường 24/7 sử dụng AI để phát hiện tín hiệu giao dịch.\n\n"
            "🤖 <b>AI Engine:</b>\n"
            "• Phân tích xu hướng thị trường\n"
            "• Phát hiện vùng vào lệnh tối ưu\n"
            "• Tính toán điểm tin cậy\n\n"
            "📈 <b>Cặp tiền giao dịch:</b>\n"
            "• BTC/USDT\n"
            "• XAU/USD (Vàng)",
            parse_mode='HTML'
        )

    async def show_signals(self, update: Update, is_admin: bool):
        """Hiển thị tín hiệu"""
        await update.message.reply_text(
            "📨 <b>Tín hiệu</b>\n\n"
            "Bot gửi tín hiệu giao dịch tự động khi:\n\n"
            "🎯 <b>Điều kiện:</b>\n"
            "• Điểm AI vượt ngưỡng cấu hình\n"
            "• Độ tin cậy cao\n"
            "• Xu hướng thị trường rõ ràng\n\n"
            "📊 <b>Thông tin tín hiệu bao gồm:</b>\n"
            "• Hành động (MUA/BÁN)\n"
            "• Vùng vào lệnh\n"
            "• Giá chốt lời\n"
            "• Giá cắt lỗ\n"
            "• Độ tin cậy AI\n"
            "• Xu hướng thị trường",
            parse_mode='HTML'
        )

    async def show_market(self, update: Update, is_admin: bool):
        """Hiển thị thị trường"""
        await self.market_command(update, None)

    async def show_news(self, update: Update, is_admin: bool):
        """Hiển thị tin tức"""
        await self.news_command(update, None)

    async def show_account(self, update: Update, is_admin: bool):
        """Hiển thị tài khoản"""
        user = update.effective_user

        account_message = f"""
👤 <b>Tài khoản</b>

🆔 <b>Telegram ID:</b> {user.id}
📛 <b>Username:</b> @{user.username if user.username else 'N/A'}
👤 <b>Tên:</b> {user.first_name}
{'👑 <b>Quyền:</b> Admin' if is_admin else '👤 <b>Quyền:</b> Người dùng'}
        """

        await update.message.reply_text(account_message, parse_mode='HTML')

    async def show_watchlist_manager(self, update: Update, is_admin: bool):
        """Hiển thị Watchlist Manager"""
        try:
            watchlist = await db.get_watchlist_async()

            if not watchlist:
                message = "🪙 <b>DANH SÁCH COIN</b>\n\n"
                message += "Chưa có coin nào trong watchlist.\n\n"
                if is_admin:
                    keyboard = [
                        [InlineKeyboardButton("➕ Thêm coin", callback_data="watchlist_add")],
                        [InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_back")]
                    ]
                else:
                    keyboard = [
                        [InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_back")]
                    ]
            else:
                message = "🪙 <b>DANH SÁCH COIN</b>\n\n"
                message += "<b>Danh sách ACTIVE:</b>\n\n"
                for symbol in watchlist:
                    message += f"• {symbol}\n"
                message += f"\nTổng: {len(watchlist)} coin\n\n"

                if is_admin:
                    keyboard = [
                        [InlineKeyboardButton("➕ Thêm coin", callback_data="watchlist_add")],
                        [InlineKeyboardButton("➖ Xóa coin", callback_data="watchlist_remove")],
                        [InlineKeyboardButton("🔄 Làm mới", callback_data="watchlist_refresh")],
                        [InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_back")]
                    ]
                else:
                    keyboard = [
                        [InlineKeyboardButton("🔄 Làm mới", callback_data="watchlist_refresh")],
                        [InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_back")]
                    ]

            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error showing watchlist manager: {e}")
            await update.message.reply_text("❌ Có lỗi xảy ra khi hiển thị watchlist.")

    async def handle_watchlist_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Xử lý callback từ Watchlist Manager"""
        query = update.callback_query
        callback_data = query.data
        user_id = query.from_user.id

        logger.info(f"[WATCHLIST CALLBACK] user_id={user_id}, callback_data={callback_data}")

        # Acknowledge callback immediately to prevent loading
        try:
            await query.answer()
            logger.info(f"[WATCHLIST CALLBACK] acknowledged for user_id={user_id}")
        except Exception as e:
            logger.error(f"[WATCHLIST CALLBACK ERROR] failed to acknowledge: {e}")
            return

        try:
            is_admin = await db.is_admin_async(user_id)

            if callback_data == "watchlist_add":
                logger.info(f"[WATCHLIST ADD] clicked by user_id={user_id}, is_admin={is_admin}")
                if not is_admin:
                    await query.edit_message_text("⛔ Chỉ Admin mới có thể thêm coin.")
                    logger.warning(f"[WATCHLIST ADD] denied for non-admin user_id={user_id}")
                    return
                try:
                    await query.edit_message_text("➕ <b>Thêm coin</b>\n\nNhập symbol muốn thêm.\nVí dụ: BTC ETH SUI DOGE XRP", parse_mode='HTML')
                    # Set state to wait for symbol input
                    context.user_data['waiting_for_symbol'] = True
                    logger.info(f"[WATCHLIST ADD] state set waiting_for_symbol=True for user_id={user_id}")
                except Exception as e:
                    logger.error(f"[WATCHLIST ADD ERROR] user_id={user_id}: {e}", exc_info=True)
                    await query.edit_message_text("❌ Có lỗi xảy ra. Vui lòng thử lại.")

            elif callback_data == "watchlist_remove":
                if not is_admin:
                    await query.edit_message_text("⛔ Chỉ Admin mới có thể xóa coin.")
                    return
                watchlist = await db.get_watchlist_async()
                if not watchlist:
                    await query.edit_message_text("❌ Chưa có coin nào trong watchlist.")
                    return

                keyboard = []
                for symbol in watchlist:
                    keyboard.append([InlineKeyboardButton(symbol, callback_data=f"watchlist_remove_{symbol}")])
                keyboard.append([InlineKeyboardButton("⬅️ Quay lại", callback_data="watchlist_back")])

                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text("➖ <b>Xóa coin</b>\n\nChọn coin để xóa:", reply_markup=reply_markup, parse_mode='HTML')

            elif callback_data.startswith("watchlist_remove_"):
                if not is_admin:
                    await query.edit_message_text("⛔ Chỉ Admin mới có thể xóa coin.")
                    return
                symbol = callback_data.replace("watchlist_remove_", "")
                success = await db.remove_from_watchlist_async(symbol)
                if success:
                    logger.info(f"[WATCHLIST] Removed symbol={symbol}")
                    await query.edit_message_text(f"✅ Đã xóa {symbol} khỏi watchlist.")
                    # Reload watchlist in main app immediately
                    if self.bot_app:
                        await self.bot_app.reload_watchlist()
                        logger.info(f"[WATCHLIST] Active symbols updated={self.bot_app.active_symbols}")
                    else:
                        logger.warning("[WATCHLIST] bot_app reference not available for immediate sync")
                else:
                    await query.edit_message_text(f"❌ Không thể xóa {symbol}.")

            elif callback_data == "watchlist_refresh":
                await self.show_watchlist_manager(update, is_admin)

            elif callback_data == "watchlist_back":
                await self.show_watchlist_manager(update, is_admin)

            elif callback_data == "menu_back":
                # Return to main menu
                is_admin = await db.is_admin_async(user_id)
                reply_markup = self.get_reply_keyboard(is_admin)
                await query.edit_message_text("🏠 Quay lại menu chính.", reply_markup=reply_markup)

        except Exception as e:
            logger.error(f"[WATCHLIST CALLBACK ERROR] user_id={user_id}, callback_data={callback_data}: {e}", exc_info=True)
            try:
                await query.edit_message_text("❌ Có lỗi xảy ra. Vui lòng thử lại.")
            except:
                pass

    async def handle_symbol_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Xử lý input symbol từ admin"""
        user_id = update.effective_user.id
        symbol_input = update.message.text.strip().upper()

        logger.info(f"[WATCHLIST SYMBOL INPUT] user_id={user_id}, symbol={symbol_input}, waiting_state={context.user_data.get('waiting_for_symbol')}")

        is_admin = await db.is_admin_async(user_id)

        if not is_admin:
            logger.warning(f"[WATCHLIST SYMBOL INPUT] denied for non-admin user_id={user_id}")
            await update.message.reply_text("⛔ Chỉ Admin mới có thể thêm coin.")
            return

        if not context.user_data.get('waiting_for_symbol'):
            logger.warning(f"[WATCHLIST SYMBOL INPUT] user_id={user_id} not in waiting state")
            return

        context.user_data['waiting_for_symbol'] = False
        logger.info(f"[WATCHLIST SYMBOL INPUT] state cleared for user_id={user_id}")

        # Normalize symbol
        if not '/' in symbol_input:
            # Add exchange suffix
            symbol_normalized = f"{symbol_input}/USDT:USDT"
        else:
            symbol_normalized = symbol_input

        logger.info(f"[WATCHLIST SYMBOL INPUT] normalized: {symbol_input} -> {symbol_normalized}")

        # Validate symbol exists on exchange
        try:
            if self.market_data:
                # Check if symbol exists by fetching ticker
                logger.info(f"[WATCHLIST SYMBOL INPUT] validating symbol {symbol_normalized} on exchange")
                ticker = await self.market_data.get_ticker(symbol_normalized)
                if not ticker:
                    logger.warning(f"[WATCHLIST SYMBOL INPUT] symbol {symbol_normalized} not found on exchange")
                    await update.message.reply_text(f"❌ Symbol {symbol_normalized} không tồn tại trên exchange.")
                    return
                logger.info(f"[WATCHLIST SYMBOL INPUT] symbol {symbol_normalized} validated successfully")
            else:
                logger.error(f"[WATCHLIST SYMBOL INPUT] market_data engine not available")
                await update.message.reply_text("❌ Market data engine không khả dụng.")
                return
        except Exception as e:
            logger.error(f"[WATCHLIST SYMBOL INPUT ERROR] validation failed for {symbol_normalized}: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Không thể kiểm tra symbol {symbol_normalized}.")
            return

        # Check if already in watchlist
        watchlist = await db.get_watchlist_async()
        if symbol_normalized in watchlist:
            logger.info(f"[WATCHLIST SYMBOL INPUT] symbol {symbol_normalized} already in watchlist")
            await update.message.reply_text(f"⚠️ {symbol_normalized} đã có trong watchlist.")
            return

        # Add to watchlist
        try:
            logger.info(f"[WATCHLIST SYMBOL INPUT] adding {symbol_normalized} to watchlist by user_id={user_id}")
            success = await db.add_to_watchlist_async(symbol_normalized, added_by=user_id)
            if success:
                logger.info(f"[WATCHLIST SYMBOL INPUT] successfully added {symbol_normalized}")
                await update.message.reply_text(f"✅ Đã thêm {symbol_normalized} vào watchlist.")
                # Reload watchlist in main app immediately
                if self.bot_app:
                    await self.bot_app.reload_watchlist()
                    logger.info(f"[WATCHLIST] Active symbols updated={self.bot_app.active_symbols}")
                else:
                    logger.warning("[WATCHLIST] bot_app reference not available for immediate sync")
            else:
                logger.error(f"[WATCHLIST SYMBOL INPUT] failed to add {symbol_normalized}")
                await update.message.reply_text(f"❌ Không thể thêm {symbol_normalized} vào watchlist.")
        except Exception as e:
            logger.error(f"[WATCHLIST SYMBOL INPUT ERROR] add failed for {symbol_normalized}: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Không thể thêm {symbol_normalized} vào watchlist.")

    async def show_settings(self, update: Update, is_admin: bool):
        """Hiển thị cài đặt (Admin only)"""
        keyboard = [
            [InlineKeyboardButton("📊 Xem cấu hình", callback_data="config_view")],
            [InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "⚙️ <b>Cài đặt</b>\n\nChọn chức năng quản trị:",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )


    async def show_commands(self, update: Update, is_admin: bool):
        """Hiển thị danh sách lệnh"""
        if is_admin:
            commands_message = """
📋 <b>Danh sách lệnh</b>

🔹 <b>Lệnh cơ bản:</b>
/start - Bắt đầu sử dụng bot
/menu - Hiển thị menu
/help - Hiển thị trợ giúp
/status - Trạng thái bot
/market - Thông tin thị trường
/news - Tin tức Crypto & Forex
/stats - Xem thống kê tín hiệu

🔹 <b>Quản trị (Chỉ Admin):</b>
/ban <id> - Cấm người dùng
/unban <id> - Bỏ cấm người dùng
/users - Danh sách người dùng
/broadcast <message> - Gửi thông báo
            """
        else:
            commands_message = """
📋 <b>Danh sách lệnh</b>

🔹 <b>Lệnh cơ bản:</b>
/start - Bắt đầu sử dụng bot
/menu - Hiển thị menu
/help - Hiển thị trợ giúp
/status - Trạng thái bot
/market - Thông tin thị trường
/news - Tin tức Crypto & Forex
/stats - Xem thống kê tín hiệu
            """

        await update.message.reply_text(commands_message, parse_mode='HTML')

    async def show_help(self, update: Update, is_admin: bool):
        """Hiển thị trợ giúp"""
        from core.config import AI_SCORE_THRESHOLD

        help_message = f"""
❓ <b>Trợ giúp</b>

🤖 <b>Bot hoạt động như thế nào?</b>
• Phân tích thị trường 24/7
• Gửi tín hiệu khi AI Score vượt ngưỡng
• Không tự động giao dịch

📊 <b>Cách sử dụng:</b>
1. Sử dụng menu để điều hướng
2. Nhận tín hiệu tự động nếu được cấp quyền
3. Tự quyết định vào lệnh thủ công

⚠️ <b>Lưu ý quan trọng:</b>
• Tín hiệu chỉ để tham khảo
• Không tự động giao dịch
• Quản lý rủi ro cẩn thận
• Không đầu tư quá khả năng

🤖 <b>Bot hoạt động 24/7 quét dữ liệu thị trường và gửi tín hiệu khi Điểm AI > {AI_SCORE_THRESHOLD}%</b>

⚠️ <b>Bot không tự động giao dịch. Tín hiệu chỉ để tham khảo.</b>
        """

        await update.message.reply_text(help_message, parse_mode='HTML')

    # ==================== CALLBACK HANDLERS ====================

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Xử lý callback từ inline keyboard"""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        is_admin = await db.is_admin_async(user_id)

        # Menu chính
        if query.data == "menu_main":
            keyboard = self.get_main_menu_keyboard(is_admin)
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "🤖 <b>AI Trading Signal Bot</b>\n\nChọn chức năng từ menu bên dưới:",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )

        # Menu Phân tích
        elif query.data == "menu_analysis":
            keyboard = self.get_navigation_keyboard("menu_main")
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "📊 <b>Phân tích</b>\n\n"
                "Bot phân tích thị trường 24/7 sử dụng AI để phát hiện tín hiệu giao dịch.\n\n"
                "🤖 <b>AI Engine:</b>\n"
                "• Phân tích xu hướng thị trường\n"
                "• Phát hiện vùng vào lệnh tối ưu\n"
                "• Tính toán điểm tin cậy\n\n"
                "📈 <b>Cặp tiền giao dịch:</b>\n"
                "• BTC/USDT\n"
                "• XAU/USD (Vàng)",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )

        # Menu Tín hiệu
        elif query.data == "menu_signals":
            keyboard = self.get_navigation_keyboard("menu_main")
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "📨 <b>Tín hiệu</b>\n\n"
                "Bot gửi tín hiệu giao dịch tự động khi:\n\n"
                "🎯 <b>Điều kiện:</b>\n"
                "• Điểm AI vượt ngưỡng cấu hình\n"
                "• Độ tin cậy cao\n"
                "• Xu hướng thị trường rõ ràng\n\n"
                "📊 <b>Thông tin tín hiệu bao gồm:</b>\n"
                "• Hành động (MUA/BÁN)\n"
                "• Vùng vào lệnh\n"
                "• Giá chốt lời\n"
                "• Giá cắt lỗ\n"
                "• Độ tin cậy AI\n"
                "• Xu hướng thị trường",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )

        # Menu Tài khoản
        elif query.data == "menu_account":
            keyboard = self.get_navigation_keyboard("menu_main")
            reply_markup = InlineKeyboardMarkup(keyboard)
            user = query.from_user
            account_message = f"""
👤 <b>Tài khoản</b>

🆔 <b>Telegram ID:</b> {user.id}
📛 <b>Username:</b> @{user.username if user.username else 'N/A'}
👤 <b>Tên:</b> {user.first_name}
{'👑 <b>Quyền:</b> Admin' if is_admin else '👤 <b>Quyền:</b> Người dùng'}
            """
            await query.edit_message_text(account_message, reply_markup=reply_markup, parse_mode='HTML')

        # Menu Cài đặt (Admin only)
        elif query.data == "menu_settings":
            if not is_admin:
                await query.edit_message_text("⛔ Bạn không có quyền sử dụng chức năng này.")
                return

            keyboard = [
                [InlineKeyboardButton("📊 Xem cấu hình", callback_data="config_view")],
                [InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "⚙️ <b>Cài đặt</b>\n\nChọn chức năng quản trị:",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )

        # Menu Thị trường
        elif query.data == "menu_market":
            keyboard = self.get_navigation_keyboard("menu_main")
            reply_markup = InlineKeyboardMarkup(keyboard)
            if self.market_data:
                try:
                    market_info = await self.market_data.get_market_overview()
                    await query.edit_message_text(market_info, reply_markup=reply_markup, parse_mode='Markdown')
                except Exception as e:
                    logger.error(f"Error in menu_market: {e}")
                    await query.edit_message_text(
                        "📈 <b>Thị trường</b>\n\n❌ Lỗi khi tải dữ liệu thị trường.",
                        reply_markup=reply_markup,
                        parse_mode='HTML'
                    )
            else:
                await query.edit_message_text(
                    "📈 <b>Thị trường</b>\n\n❌ Dữ liệu thị trường chưa sẵn sàng.",
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )

        # Menu Tin tức
        elif query.data == "menu_news":
            keyboard = self.get_navigation_keyboard("menu_main")
            reply_markup = InlineKeyboardMarkup(keyboard)
            try:
                from data.news_engine import news_engine
                news_summary = await news_engine.get_news_summary()
                if news_summary:
                    await query.edit_message_text(news_summary, reply_markup=reply_markup, parse_mode='Markdown')
                else:
                    await query.edit_message_text(
                        "📰 <b>Tin tức</b>\n\n❌ Tin tức không khả dụng lúc này.",
                        reply_markup=reply_markup,
                        parse_mode='HTML'
                    )
            except Exception as e:
                logger.error(f"Error in menu_news: {e}")
                await query.edit_message_text(
                    "📰 <b>Tin tức</b>\n\n❌ Lỗi khi tải tin tức.",
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )

        # Menu Danh sách lệnh
        elif query.data == "menu_commands":
            keyboard = self.get_navigation_keyboard("menu_main")
            reply_markup = InlineKeyboardMarkup(keyboard)
            if is_admin:
                commands_message = """
📋 <b>Danh sách lệnh</b>

🔹 <b>Lệnh cơ bản:</b>
/start - Bắt đầu sử dụng bot
/menu - Hiển thị menu
/help - Hiển thị trợ giúp
/status - Trạng thái bot
/market - Thông tin thị trường
/news - Tin tức Crypto & Forex
/stats - Xem thống kê tín hiệu

🔹 <b>Quản trị (Chỉ Admin):</b>
/adduser <tên> <id> [username] - Thêm người nhận
/removeuser <id> - Xóa người nhận
/ban <id> - Cấm người dùng
/unban <id> - Bỏ cấm người dùng
/users - Danh sách người dùng
/broadcast <message> - Gửi thông báo
/editname <id> <tên mới> - Sửa tên
/disable <id> - Tắt nhận tín hiệu
/enable <id> - Bật nhận tín hiệu
                """
            else:
                commands_message = """
📋 <b>Danh sách lệnh</b>

🔹 <b>Lệnh cơ bản:</b>
/start - Bắt đầu sử dụng bot
/menu - Hiển thị menu
/help - Hiển thị trợ giúp
/status - Trạng thái bot
/market - Thông tin thị trường
/news - Tin tức Crypto & Forex
/stats - Xem thống kê tín hiệu
                """
            await query.edit_message_text(commands_message, reply_markup=reply_markup, parse_mode='HTML')

        # Menu Trợ giúp
        elif query.data == "menu_help":
            from core.config import AI_SCORE_THRESHOLD
            keyboard = self.get_navigation_keyboard("menu_main")
            reply_markup = InlineKeyboardMarkup(keyboard)
            help_message = f"""
❓ <b>Trợ giúp</b>

🤖 <b>Bot hoạt động như thế nào?</b>
• Phân tích thị trường 24/7
• Gửi tín hiệu khi AI Score vượt ngưỡng
• Không tự động giao dịch

📊 <b>Cách sử dụng:</b>
1. Sử dụng menu để điều hướng
2. Nhận tín hiệu tự động nếu được cấp quyền
3. Tự quyết định vào lệnh thủ công

⚠️ <b>Lưu ý quan trọng:</b>
• Tín hiệu chỉ để tham khảo
• Không tự động giao dịch
• Quản lý rủi ro cẩn thận
• Không đầu tư quá khả năng

🤖 <b>Bot hoạt động 24/7 quét dữ liệu thị trường và gửi tín hiệu khi Điểm AI > {AI_SCORE_THRESHOLD}%</b>

⚠️ <b>Bot không tự động giao dịch. Tín hiệu chỉ để tham khảo.</b>
            """
            await query.edit_message_text(help_message, reply_markup=reply_markup, parse_mode='HTML')








        # Xem cấu hình (Admin)
        elif query.data == "config_view":
            if not is_admin:
                await query.edit_message_text("⛔ Bạn không có quyền sử dụng chức năng này.")
                return

            from core.config import (
                AI_SCORE_THRESHOLD, MIN_CONFIDENCE, MAX_RISK_PER_TRADE,
                MAX_POSITIONS, SIGNAL_COOLDOWN_MINUTES, MAX_SIGNALS_PER_HOUR,
                MARKET_DATA_INTERVAL, NEWS_CHECK_INTERVAL, AI_UPDATE_INTERVAL,
                EXCHANGE
            )
            # Get watchlist from database
            watchlist = await db.get_watchlist_async()
            from core.config import clean_symbol
            clean_symbols = [clean_symbol(s) for s in watchlist]

            config_text = "📊 <b>Cấu hình hiện tại:</b>\n\n"
            config_text += f"• Ngưỡng điểm AI: {AI_SCORE_THRESHOLD}\n"
            config_text += f"• Độ tin cậy tối thiểu: {MIN_CONFIDENCE}\n"
            config_text += f"• Rủi ro tối đa mỗi lệnh: {MAX_RISK_PER_TRADE}\n"
            config_text += f"• Số vị thế tối đa: {MAX_POSITIONS}\n"
            config_text += f"• Thời gian chờ tín hiệu: {SIGNAL_COOLDOWN_MINUTES} phút\n"
            config_text += f"• Số tín hiệu tối đa mỗi giờ: {MAX_SIGNALS_PER_HOUR}\n"
            config_text += f"• Cập nhật dữ liệu thị trường: {MARKET_DATA_INTERVAL} giây\n"
            config_text += f"• Kiểm tra tin tức: {NEWS_CHECK_INTERVAL} giây\n"
            config_text += f"• Cập nhật AI: {AI_UPDATE_INTERVAL} giây\n"
            config_text += f"• Cặp tiền giao dịch: {', '.join(clean_symbols) if clean_symbols else 'Chưa có'}\n"
            config_text += f"• Sàn giao dịch: {EXCHANGE}\n"

            keyboard = [
                [InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_settings")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(config_text, reply_markup=reply_markup, parse_mode='HTML')

        # Quay lại
        elif query.data.startswith("back_"):
            target = query.data.replace("back_", "")
            if target == "menu_main":
                keyboard = self.get_main_menu_keyboard(is_admin)
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    "🤖 <b>AI Trading Signal Bot</b>\n\nChọn chức năng từ menu bên dưới:",
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
            elif target == "menu_settings":
                # Navigate back to settings
                await query.edit_message_text(
                    "⚙️ <b>Cài đặt</b>\n\nChọn chức năng quản trị:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📊 Xem cấu hình", callback_data="config_view")],
                        [InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_main")]
                    ]),
                    parse_mode='HTML'
                )
    

    # ==================== BOT STARTUP ====================

    async def start(self):
        """Khởi động bot with comprehensive trace logging"""
        import asyncio
        import traceback
        from datetime import datetime

        # Get current event loop ID
        try:
            event_loop = asyncio.get_event_loop()
            event_loop_id = id(event_loop)
        except RuntimeError:
            event_loop = None
            event_loop_id = "NO_LOOP"

        start_timestamp = datetime.now().isoformat()
        print(f"[TELEGRAM APPLICATION START] timestamp={start_timestamp}, event_loop_id={event_loop_id}")
        logger.info(f"[TELEGRAM APPLICATION START] timestamp={start_timestamp}, event_loop_id={event_loop_id}")

        try:
            if self.application is not None:
                print(f"[DUPLICATE APPLICATION WARNING] timestamp={datetime.now().isoformat()}, event_loop_id={event_loop_id}")
                logger.warning("[DUPLICATE APPLICATION WARNING] Application already initialized")
                return self.application

            creating_timestamp = datetime.now().isoformat()
            print(f"[TELEGRAM APPLICATION CREATING] timestamp={creating_timestamp}, event_loop_id={event_loop_id}")
            logger.info(f"[TELEGRAM APPLICATION CREATING] timestamp={creating_timestamp}, event_loop_id={event_loop_id}")
            self.application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
            created_timestamp = datetime.now().isoformat()
            app_object_id = id(self.application)
            print(f"[TELEGRAM APPLICATION CREATED] timestamp={created_timestamp}, object_id={app_object_id}, event_loop_id={event_loop_id}")
            logger.info(f"[TELEGRAM APPLICATION CREATED] timestamp={created_timestamp}, object_id={app_object_id}, event_loop_id={event_loop_id}")

            # Đăng ký handlers - đăng ký tất cả commands
            adding_handlers_timestamp = datetime.now().isoformat()
            print(f"[TELEGRAM APPLICATION ADDING HANDLERS] timestamp={adding_handlers_timestamp}, event_loop_id={event_loop_id}")
            logger.info(f"[TELEGRAM APPLICATION ADDING HANDLERS] timestamp={adding_handlers_timestamp}, event_loop_id={event_loop_id}")
            self.application.add_handler(CommandHandler("start", self.start_command))
            self.application.add_handler(CommandHandler("help", self.help_command))
            self.application.add_handler(CommandHandler("status", self.status_command))
            self.application.add_handler(CommandHandler("market", self.market_command))
            self.application.add_handler(CommandHandler("news", self.news_command))
            self.application.add_handler(CommandHandler("settings", self.settings_command))
            self.application.add_handler(CommandHandler("id", self.id_command))
            self.application.add_handler(CommandHandler("users", self.users_command))
            self.application.add_handler(CommandHandler("broadcast", self.broadcast_command))
            self.application.add_handler(CommandHandler("ban", self.ban_command))
            self.application.add_handler(CommandHandler("unban", self.unban_command))
            self.application.add_handler(CommandHandler("stats", self.stats_command))
            self.application.add_handler(CommandHandler("signals", self.signals_command))
            self.application.add_handler(CommandHandler("analyze", self.analyze_command))
            self.application.add_handler(CommandHandler("menu", self.menu_command))
            self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
            # Register watchlist callback BEFORE general button_callback to ensure it's processed first
            self.application.add_handler(CallbackQueryHandler(self.handle_watchlist_callback, pattern='^watchlist_'))
            self.application.add_handler(CallbackQueryHandler(self.button_callback))
            handlers_added_timestamp = datetime.now().isoformat()
            print(f"[TELEGRAM APPLICATION HANDLERS ADDED] timestamp={handlers_added_timestamp}, event_loop_id={event_loop_id}")
            logger.info(f"[TELEGRAM APPLICATION HANDLERS ADDED] timestamp={handlers_added_timestamp}, event_loop_id={event_loop_id}")

            # Initialize the application
            initializing_timestamp = datetime.now().isoformat()
            print(f"[TELEGRAM APPLICATION INITIALIZING] timestamp={initializing_timestamp}, event_loop_id={event_loop_id}")
            logger.info(f"[TELEGRAM APPLICATION INITIALIZING] timestamp={initializing_timestamp}, event_loop_id={event_loop_id}")
            await self.application.initialize()
            initialized_timestamp = datetime.now().isoformat()
            print(f"[TELEGRAM APPLICATION INITIALIZED] timestamp={initialized_timestamp}, event_loop_id={event_loop_id}")
            logger.info(f"[TELEGRAM APPLICATION INITIALIZED] timestamp={initialized_timestamp}, event_loop_id={event_loop_id}")

            # REMOVED: Telegram menu registration (setChatMenuButton, setMyCommands)
            # Only Reply Keyboard is used, no Telegram Command Menu

            # Start the application (without polling)
            starting_timestamp = datetime.now().isoformat()
            print(f"[TELEGRAM APPLICATION STARTING] timestamp={starting_timestamp}, event_loop_id={event_loop_id}")
            logger.info(f"[TELEGRAM APPLICATION STARTING] timestamp={starting_timestamp}, event_loop_id={event_loop_id}")
            await self.application.start()
            started_timestamp = datetime.now().isoformat()
            print(f"[TELEGRAM APPLICATION STARTED] timestamp={started_timestamp}, event_loop_id={event_loop_id}")
            logger.info(f"[TELEGRAM APPLICATION STARTED] timestamp={started_timestamp}, event_loop_id={event_loop_id}")
            self.running = True

            # Setup webhook if TELEGRAM_WEBHOOK_URL is configured
            if TELEGRAM_WEBHOOK_URL:
                # Auto-append /webhook if not present
                webhook_url = TELEGRAM_WEBHOOK_URL
                if not webhook_url.endswith('/webhook'):
                    webhook_url = webhook_url.rstrip('/') + '/webhook'
                setting_webhook_timestamp = datetime.now().isoformat()
                print(f"[TELEGRAM APPLICATION SETTING WEBHOOK] url={webhook_url}, timestamp={setting_webhook_timestamp}, event_loop_id={event_loop_id}")
                logger.info(f"[TELEGRAM APPLICATION SETTING WEBHOOK] url={webhook_url}, timestamp={setting_webhook_timestamp}, event_loop_id={event_loop_id}")
                await self.application.bot.set_webhook(url=webhook_url)
                webhook_set_timestamp = datetime.now().isoformat()
                print(f"[TELEGRAM APPLICATION WEBHOOK SET] url={webhook_url}, timestamp={webhook_set_timestamp}, event_loop_id={event_loop_id}")
                logger.info(f"[TELEGRAM APPLICATION WEBHOOK SET] url={webhook_url}, timestamp={webhook_set_timestamp}, event_loop_id={event_loop_id}")
            else:
                print(f"[TELEGRAM APPLICATION ERROR] timestamp={datetime.now().isoformat()}, error=TELEGRAM_WEBHOOK_URL not configured, event_loop_id={event_loop_id}")
                logger.error("[TELEGRAM APPLICATION ERROR] TELEGRAM_WEBHOOK_URL not configured - bot cannot receive updates!")
                logger.error("Please set TELEGRAM_WEBHOOK_URL in Render environment variables")

            start_completed_timestamp = datetime.now().isoformat()
            start_duration_ms = (datetime.fromisoformat(start_completed_timestamp) - datetime.fromisoformat(start_timestamp)).total_seconds() * 1000
            print(f"[TELEGRAM APPLICATION START COMPLETED] timestamp={start_completed_timestamp}, duration_ms={start_duration_ms:.2f}, event_loop_id={event_loop_id}")
            logger.info(f"[TELEGRAM APPLICATION START COMPLETED] timestamp={start_completed_timestamp}, duration_ms={start_duration_ms:.2f}, event_loop_id={event_loop_id}")
        except Exception as e:
            error_timestamp = datetime.now().isoformat()
            print(f"[TELEGRAM APPLICATION ERROR] timestamp={error_timestamp}, error={e}")
            print(f"[FULL TRACEBACK]: {traceback.format_exc()}")
            logger.error(f"[TELEGRAM APPLICATION ERROR] error={e}", exc_info=True)
            raise

    async def stop(self):
        """Stop the bot"""
        from datetime import datetime
        timestamp = datetime.now().isoformat()
        logger.info(f"[TELEGRAM APPLICATION STOP] timestamp={timestamp}")

        try:
            if not self.running:
                logger.info("[TELEGRAM APPLICATION STOP] Bot not running, skipping stop")
                return

            self.running = False

            if self.application:
                # DO NOT delete webhook - keep it active for next startup
                logger.info(f"[TELEGRAM APPLICATION STOPPING] timestamp={datetime.now().isoformat()}")
                try:
                    await self.application.stop()
                    logger.info(f"[TELEGRAM APPLICATION STOPPED] timestamp={datetime.now().isoformat()}")
                except Exception as e:
                    logger.error(f"[TELEGRAM APPLICATION STOP ERROR] error={e}", exc_info=True)

                logger.info(f"[TELEGRAM APPLICATION SHUTTING DOWN] timestamp={datetime.now().isoformat()}")
                try:
                    await self.application.shutdown()
                    logger.info(f"[TELEGRAM APPLICATION SHUTDOWN COMPLETE] timestamp={datetime.now().isoformat()}")
                except Exception as e:
                    logger.error(f"[TELEGRAM APPLICATION SHUTDOWN ERROR] error={e}", exc_info=True)

                self.application = None
                logger.info(f"[TELEGRAM APPLICATION STOP COMPLETED] timestamp={datetime.now().isoformat()}")
        except Exception as e:
            logger.error(f"Error stopping Telegram bot: {e}")
    
    async def send_signal(self, signal_text: str, chart_path: str = None):
        """Gửi tín hiệu đến tất cả người nhận từ SIGNAL_RECEIVER_IDS config"""
        from core.config import SIGNAL_RECEIVER_IDS

        receiver_ids = SIGNAL_RECEIVER_IDS
        logger.info(f"Sending signal to {len(receiver_ids)} receivers: {receiver_ids}")

        success_count = 0
        for user_id in receiver_ids:
            try:
                # Send chart with signal as caption if available
                if chart_path:
                    try:
                        with open(chart_path, 'rb') as photo:
                            await self.application.bot.send_photo(
                                chat_id=user_id,
                                photo=photo,
                                caption=signal_text,
                                parse_mode='HTML'
                            )
                        success_count += 1
                        logger.info(f"Signal sent to {user_id} with chart")
                    except Exception as e:
                        error_str = str(e)
                        if "Chat not found" in error_str or "chat not found" in error_str.lower():
                            logger.warning(f"Chat {user_id} not found")
                        else:
                            logger.error(f"Error sending chart to {user_id}: {e}")
                        # Fallback to text message if chart fails
                        try:
                            await self.application.bot.send_message(
                                chat_id=user_id,
                                text=signal_text,
                                parse_mode='HTML'
                            )
                            success_count += 1
                            logger.info(f"Signal sent to {user_id} as text fallback")
                        except Exception as e2:
                            error_str2 = str(e2)
                            if "Chat not found" in error_str2 or "chat not found" in error_str2.lower():
                                logger.warning(f"Chat {user_id} not found")
                            else:
                                logger.error(f"Error sending fallback message to {user_id}: {e2}")
                else:
                    # Send text message only if no chart
                    try:
                        await self.application.bot.send_message(
                            chat_id=user_id,
                            text=signal_text,
                            parse_mode='HTML'
                        )
                        success_count += 1
                        logger.info(f"Signal sent to {user_id} as text")
                    except Exception as e:
                        error_str = str(e)
                        if "Chat not found" in error_str or "chat not found" in error_str.lower():
                            logger.warning(f"Chat {user_id} not found")
                        else:
                            logger.error(f"Error sending signal to {user_id}: {e}")
            except Exception as e:
                error_str = str(e)
                if "Chat not found" in error_str or "chat not found" in error_str.lower():
                    logger.warning(f"Chat {user_id} not found")
                else:
                    logger.error(f"Error sending signal to {user_id}: {e}")

        logger.info(f"Signal sent to {success_count}/{len(receiver_ids)} receivers")

        # Delete chart file after sending to all users
        if chart_path:
            try:
                import os
                if os.path.exists(chart_path):
                    os.remove(chart_path)
                    logger.info(f"Chart file deleted: {chart_path}")
            except Exception as e:
                logger.warning(f"Could not delete chart file {chart_path}: {e}")

        return success_count


# Singleton instance
telegram_bot = TelegramBot()
