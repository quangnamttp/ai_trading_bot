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
        self.active_cashflow_refreshers = {}  # {(chat_id, message_id): asyncio.Task} cho nút Dòng tiền tự làm mới

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

        # Log queue consumer start and queue wait duration
        queue_wait_duration_ms = 0
        if self.queue_timestamps and update_id in self.queue_timestamps:
            queue_put_timestamp = self.queue_timestamps[update_id]
            queue_wait_duration = (datetime.now() - datetime.fromisoformat(queue_put_timestamp)).total_seconds() * 1000
            logger.info(f"[WEBHOOK QUEUE CONSUMED] update_id={update_id}, queue_wait_duration_ms={queue_wait_duration_ms:.2f}")
            # Clean up timestamp
            del self.queue_timestamps[update_id]
            if update_id in self.queue_put_stack_traces:
                del self.queue_put_stack_traces[update_id]
        else:
            logger.info(f"[WEBHOOK QUEUE CONSUMED] update_id={update_id}, queue_wait_duration_ms=unknown")

        logger.info(f"[TELEGRAM UPDATE HANDLER START] handler=start_command, update_id={update_id}, user_id={user.id}")

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
                await update.message.reply_text(news_summary, parse_mode='HTML')
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
                [InlineKeyboardButton("💰 Dòng tiền", callback_data="menu_cashflow")],
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
                [InlineKeyboardButton("💰 Dòng tiền", callback_data="menu_cashflow")],
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

        print(f"[WEBHOOK QUEUE CONSUMED] timestamp={queue_consumer_start_timestamp}, update_id={update_id}, event_loop_id={event_loop_id}")
        logger.info(f"[WEBHOOK QUEUE CONSUMED] timestamp={queue_consumer_start_timestamp}, update_id={update_id}, event_loop_id={event_loop_id}")

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
        watchlist = await db.get_watchlist_async()
        pairs_text = "\n".join(f"• {s}" for s in watchlist) if watchlist else "• Chưa cấu hình (xem biến TRADING_SYMBOLS trên Render)"
        await update.message.reply_text(
            "📊 <b>Phân tích</b>\n\n"
            "Bot phân tích thị trường 24/7 sử dụng AI để phát hiện tín hiệu giao dịch.\n\n"
            "🤖 <b>AI Engine:</b>\n"
            "• Phân tích xu hướng thị trường\n"
            "• Phát hiện vùng vào lệnh tối ưu\n"
            "• Tính toán điểm tin cậy\n\n"
            "📈 <b>Cặp tiền đang theo dõi:</b>\n"
            f"{pairs_text}",
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

    async def render_cashflow_message(self, is_admin: bool, autorefresh_on: bool = False) -> tuple:
        """Xây dựng nội dung + bàn phím cho màn hình Dòng tiền.
        Trả về (text, reply_markup)."""
        try:
            from data.smart_money import smart_money_tracker
            from core.economic_calendar import get_upcoming_macro_events
            from core.config import clean_symbol

            watchlist = await db.get_watchlist_async()
            now_str = datetime.now().strftime('%H:%M:%S')

            message = "💰 <b>DÒNG TIỀN THỊ TRƯỜNG</b>\n"
            message += f"<i>Cập nhật lúc {now_str} (giờ VN)</i>\n\n"

            if not watchlist:
                message += "Chưa có coin nào trong watchlist để theo dõi dòng tiền.\n"
            elif not self.market_data:
                message += "❌ Market data engine chưa sẵn sàng.\n"
            else:
                message += "<b>📊 Theo từng coin (Funding Rate + Open Interest):</b>\n\n"
                for symbol in watchlist:
                    display_symbol = clean_symbol(symbol)
                    try:
                        cf = await smart_money_tracker.get_cashflow_verdict(symbol, self.market_data)
                        message += f"<b>{display_symbol}</b>: {cf['verdict']}\n"
                        message += f"  Funding: {cf['funding_rate']*100:.4f}% | OI: {cf['oi_change_percent']:+.2f}% | Giá 24h: {cf['price_change_percent']:+.2f}%\n"
                        message += f"  <i>{cf['detail']}</i>\n\n"
                    except Exception as e:
                        logger.error(f"[CASHFLOW] error for {symbol}: {e}")
                        message += f"<b>{display_symbol}</b>: ❌ Không lấy được dữ liệu\n\n"

            # Lịch vĩ mô sắp tới (FOMC/CPI/NFP) - các mốc thường gây bơm/rút dòng tiền lớn
            events = get_upcoming_macro_events(limit=3)
            if events:
                message += "<b>📅 Sự kiện sắp gây biến động dòng tiền:</b>\n"
                for e in events:
                    tag = " (ước tính)" if e.get('is_estimate') else ""
                    message += f"• <b>{e['event']}</b>{tag} - còn {e['days_left']} ngày ({e['date_display']})\n"

            message += f"\n{'🔴 Đang tự làm mới mỗi 60 giây' if autorefresh_on else '⚪ Tự làm mới: đang tắt'}"

            keyboard = [
                [InlineKeyboardButton("🔄 Làm mới ngay", callback_data="cashflow_refresh")],
            ]
            if autorefresh_on:
                keyboard.append([InlineKeyboardButton("⏸ Dừng tự làm mới", callback_data="cashflow_autorefresh_stop")])
            else:
                keyboard.append([InlineKeyboardButton("▶️ Tự làm mới mỗi phút", callback_data="cashflow_autorefresh_start")])
            keyboard.append([InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_back")])

            return message, InlineKeyboardMarkup(keyboard)
        except Exception as e:
            logger.error(f"Error rendering cashflow message: {e}", exc_info=True)
            return "❌ Có lỗi khi lấy dữ liệu dòng tiền.", InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_back")]]
            )

    async def show_cashflow(self, update: Update, is_admin: bool):
        """Hiển thị màn hình Dòng tiền (message context, ví dụ /menu -> Dòng tiền lần đầu)"""
        message, reply_markup = await self.render_cashflow_message(is_admin, autorefresh_on=False)
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='HTML')

    async def _cashflow_autorefresh_loop(self, chat_id: int, message_id: int, is_admin: bool):
        """Vòng lặp tự động sửa (edit) tin nhắn Dòng tiền mỗi 60 giây.
        Tự dừng sau 30 lần lặp (~30 phút) để tránh chạy vô hạn nếu người dùng quên tắt."""
        import asyncio
        max_iterations = 30
        try:
            for _ in range(max_iterations):
                await asyncio.sleep(60)
                message, reply_markup = await self.render_cashflow_message(is_admin, autorefresh_on=True)
                try:
                    await self.application.bot.edit_message_text(
                        chat_id=chat_id, message_id=message_id,
                        text=message, reply_markup=reply_markup, parse_mode='HTML'
                    )
                except Exception as e:
                    # Tin nhắn có thể đã bị xoá hoặc nội dung không đổi - bỏ qua và tiếp tục
                    logger.debug(f"[CASHFLOW AUTOREFRESH] edit skipped: {e}")
        except asyncio.CancelledError:
            logger.info(f"[CASHFLOW AUTOREFRESH] cancelled for chat_id={chat_id}, message_id={message_id}")
            raise
        finally:
            self.active_cashflow_refreshers.pop((chat_id, message_id), None)

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

    async def render_watchlist_message(self, update: Update, is_admin: bool, is_callback: bool = False):
        """Render watchlist message - CHỈ HIỂN THỊ (read-only).
        Watchlist giờ được quản lý hoàn toàn qua biến môi trường TRADING_SYMBOLS trên Render
        (không quản lý qua nút Telegram nữa), vì Render gói Free xoá dữ liệu SQLite mỗi khi
        server ngủ/khởi động lại - chỉ biến môi trường mới bền vững qua các lần restart đó."""
        try:
            from core.config import MAX_WATCHLIST_COINS
            watchlist = await db.get_watchlist_async()

            message = "🪙 <b>DANH SÁCH COIN ĐANG THEO DÕI</b>\n\n"
            if not watchlist:
                message += "Chưa có coin nào (chưa cấu hình TRADING_SYMBOLS).\n\n"
            else:
                for symbol in watchlist:
                    message += f"• {symbol}\n"
                message += f"\nTổng: {len(watchlist)}/{MAX_WATCHLIST_COINS} coin\n\n"

            message += (
                "ℹ️ Danh sách này lấy từ biến môi trường <b>TRADING_SYMBOLS</b> trên Render.\n"
                "Muốn thêm/bớt coin: vào Render Dashboard → service → tab <b>Environment</b> → "
                "sửa giá trị TRADING_SYMBOLS (vd: <code>BTC/USDT:USDT,ETH/USDT:USDT</code>) → Render tự deploy lại."
            )

            keyboard = [
                [InlineKeyboardButton("🔄 Làm mới", callback_data="watchlist_refresh")],
                [InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            if is_callback and update.callback_query:
                await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
            else:
                await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error rendering watchlist message: {e}")
            if is_callback and update.callback_query:
                await update.callback_query.edit_message_text("❌ Có lỗi xảy ra khi hiển thị watchlist.")
            else:
                await update.message.reply_text("❌ Có lỗi xảy ra khi hiển thị watchlist.")

    async def show_watchlist_manager(self, update: Update, is_admin: bool):
        """Hiển thị Watchlist Manager (message context)"""
        await self.render_watchlist_message(update, is_admin, is_callback=False)

    async def handle_cashflow_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Xử lý callback từ màn hình Dòng tiền (làm mới / bật-tắt tự làm mới mỗi phút)"""
        import asyncio
        query = update.callback_query
        callback_data = query.data
        user_id = query.from_user.id
        chat_id = query.message.chat_id
        message_id = query.message.message_id

        try:
            await query.answer()
        except Exception:
            pass

        is_admin = await db.is_admin_async(user_id)
        key = (chat_id, message_id)

        try:
            if callback_data == "cashflow_refresh":
                is_running = key in self.active_cashflow_refreshers
                message, reply_markup = await self.render_cashflow_message(is_admin, autorefresh_on=is_running)
                await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')

            elif callback_data == "cashflow_autorefresh_start":
                # Huỷ task cũ nếu có, tránh chạy trùng
                old_task = self.active_cashflow_refreshers.pop(key, None)
                if old_task:
                    old_task.cancel()

                task = asyncio.create_task(self._cashflow_autorefresh_loop(chat_id, message_id, is_admin))
                self.active_cashflow_refreshers[key] = task

                message, reply_markup = await self.render_cashflow_message(is_admin, autorefresh_on=True)
                await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
                logger.info(f"[CASHFLOW AUTOREFRESH] started for chat_id={chat_id}, message_id={message_id}")

            elif callback_data == "cashflow_autorefresh_stop":
                task = self.active_cashflow_refreshers.pop(key, None)
                if task:
                    task.cancel()

                message, reply_markup = await self.render_cashflow_message(is_admin, autorefresh_on=False)
                await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
                logger.info(f"[CASHFLOW AUTOREFRESH] stopped for chat_id={chat_id}, message_id={message_id}")

        except Exception as e:
            logger.error(f"[CASHFLOW CALLBACK ERROR] callback_data={callback_data}: {e}", exc_info=True)

    async def handle_watchlist_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Xử lý callback từ Watchlist Manager"""
        query = update.callback_query
        callback_data = query.data
        user_id = query.from_user.id
        update_id = update.update_id if hasattr(update, 'update_id') else 'unknown'

        logger.info(f"[TELEGRAM UPDATE HANDLER START] handler=handle_watchlist_callback, update_id={update_id}, user_id={user_id}, callback_data={callback_data}")
        logger.info(f"[WATCHLIST CALLBACK] user_id={user_id}, callback_data={callback_data}")

        # Acknowledge callback immediately to prevent loading
        try:
            await query.answer()
            logger.info(f"[WATCHLIST CALLBACK ACK] user_id={user_id}, callback_data={callback_data}")
        except Exception as e:
            logger.error(f"[WATCHLIST CALLBACK ACK ERROR] user_id={user_id}, callback_data={callback_data}: {e}")
            return

        try:
            is_admin = await db.is_admin_async(user_id)
            logger.info(f"[WATCHLIST CALLBACK ADMIN CHECK] user_id={user_id}, is_admin={is_admin}")

            if callback_data == "watchlist_refresh":
                await self.render_watchlist_message(update, is_admin, is_callback=True)

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
            watchlist = await db.get_watchlist_async()
            pairs_text = "\n".join(f"• {s}" for s in watchlist) if watchlist else "• Chưa cấu hình (xem biến TRADING_SYMBOLS trên Render)"
            await query.edit_message_text(
                "📊 <b>Phân tích</b>\n\n"
                "Bot phân tích thị trường 24/7 sử dụng AI để phát hiện tín hiệu giao dịch.\n\n"
                "🤖 <b>AI Engine:</b>\n"
                "• Phân tích xu hướng thị trường\n"
                "• Phát hiện vùng vào lệnh tối ưu\n"
                "• Tính toán điểm tin cậy\n\n"
                "📈 <b>Cặp tiền đang theo dõi:</b>\n"
                f"{pairs_text}",
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
                    await query.edit_message_text(news_summary, reply_markup=reply_markup, parse_mode='HTML')
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

        # Menu Dòng tiền
        elif query.data == "menu_cashflow":
            try:
                message, reply_markup = await self.render_cashflow_message(is_admin, autorefresh_on=False)
                await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
            except Exception as e:
                logger.error(f"Error in menu_cashflow: {e}", exc_info=True)
                keyboard = self.get_navigation_keyboard("menu_main")
                await query.edit_message_text(
                    "💰 <b>Dòng tiền</b>\n\n❌ Lỗi khi tải dữ liệu dòng tiền.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
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
            self.application.add_handler(CallbackQueryHandler(self.handle_cashflow_callback, pattern='^cashflow_'))
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
