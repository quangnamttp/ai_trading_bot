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
    
    def set_dependencies(self, signal_engine, market_data):
        """Set dependencies cho bot"""
        self.signal_engine = signal_engine
        self.market_data = market_data
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /start - Khởi động bot"""
        user = update.effective_user

        # Kiểm tra xem user có bị ban không
        if db.is_banned(user.id):
            await update.message.reply_text("❌ Bạn đã bị ban khỏi bot.")
            return

        # Lưu user vào database
        is_admin = db.is_admin(user.id)
        db.add_user(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            is_admin=is_admin
        )
        logger.info(f"Registered chat: {user.id}, is_admin: {is_admin}")

        # Hiển thị menu chính với Reply Keyboard - tùy theo quyền
        reply_markup = self.get_reply_keyboard(is_admin)

        welcome_message = f"""
🤖 <b>AI Trading Signal Bot</b>

👤 Xin chào, {user.first_name}!

Bot phân tích thị trường 24/7 và gửi tín hiệu giao dịch với độ chính xác cao.

⚠️ <b>Lưu ý:</b> Bot chỉ cung cấp tín hiệu phân tích, không tự động giao dịch. Bạn tự quyết định vào lệnh thủ công.
        """

        await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode='HTML')
        logger.info(f"User {user.id} started the bot, is_admin: {is_admin}")
    
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
        total_users = len(db.get_all_users())
        recent_signals = db.get_recent_signals(limit=5)
        recent_ai_logs = db.get_recent_ai_logs(limit=5)

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
        user_id = update.effective_user.id

        if not db.is_authorized(user_id):
            await update.message.reply_text("❌ Bạn không có quyền sử dụng bot này.")
            return

        try:
            if self.market_data:
                market_info = await self.market_data.get_market_overview()
                if market_info:
                    await update.message.reply_text(market_info, parse_mode='Markdown')
                else:
                    logger.error("Market data not available")
                    await update.message.reply_text("📊 Dữ liệu thị trường không khả dụng lúc này.")
            else:
                logger.error("Market data engine not initialized")
                await update.message.reply_text("📊 Dữ liệu thị trường không khả dụng lúc này.")
        except Exception as e:
            logger.error(f"Error in market_command: {e}")
            await update.message.reply_text("📊 Dữ liệu thị trường không khả dụng lúc này.")
    
    async def news_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /news - Tin tức"""
        user_id = update.effective_user.id

        if not db.is_authorized(user_id):
            await update.message.reply_text("❌ Bạn không có quyền sử dụng bot này.")
            return

        try:
            from data.news_engine import news_engine

            # Get real news summary from news engine
            news_summary = await news_engine.get_news_summary()

            if news_summary:
                await update.message.reply_text(news_summary, parse_mode='Markdown')
            else:
                logger.error("News summary not available")
                await update.message.reply_text("📰 Tin tức không khả dụng lúc này.")
        except Exception as e:
            logger.error(f"Error in news_command: {e}")
            await update.message.reply_text("📰 Tin tức không khả dụng lúc này.")
    
    async def settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /settings - Cấu hình (Admin only)"""
        user_id = update.effective_user.id
        
        if not db.is_admin(user_id):
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

        if not db.is_admin(user_id):
            await update.message.reply_text("❌ Chỉ Admin mới sử dụng lệnh này.")
            return

        users = db.get_all_users()

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

        if not db.is_admin(user_id):
            await update.message.reply_text("❌ Chỉ Admin mới sử dụng lệnh này.")
            return

        if not context.args:
            await update.message.reply_text("❌ Sử dụng: /broadcast <message>")
            return

        message = " ".join(context.args)
        users = db.get_all_users()

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

        if not db.is_admin(user_id):
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

            db.ban_user(target_user_id, banned_by=user_id, reason=reason)
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

        if not db.is_admin(user_id):
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

            db.unban_user(target_user_id)
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
        if db.is_banned(user_id):
            await update.message.reply_text("❌ Bạn đã bị cấm sử dụng bot.")
            return

        # Kiểm tra xem user có được phép sử dụng không
        if not db.is_authorized(user_id):
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
        user_id = update.effective_user.id

        if not db.is_authorized(user_id):
            await update.message.reply_text("❌ Bạn không có quyền sử dụng bot này.")
            return

        is_admin = db.is_admin(user_id)
        await self.show_signals(update, is_admin)
    
    async def analyze_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /analyze - Hiển thị phân tích"""
        user_id = update.effective_user.id

        if not db.is_authorized(user_id):
            await update.message.reply_text("❌ Bạn không có quyền sử dụng bot này.")
            return

        is_admin = db.is_admin(user_id)
        await self.show_analysis(update, is_admin)
    
    # ==================== CALLBACK HANDLERS ====================

    def get_reply_keyboard(self, is_admin: bool = False):
        """Tạo Reply Keyboard với 6 nút chính"""
        keyboard = [
            [KeyboardButton("📰 Tin tức"), KeyboardButton("📈 Thị trường")],
            [KeyboardButton("📨 Tín hiệu"), KeyboardButton("📊 Phân tích")],
            [KeyboardButton("⚙️ Cài đặt"), KeyboardButton("📋 Danh sách lệnh")]
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
        if db.is_banned(user.id):
            await update.message.reply_text("❌ Bạn đã bị ban khỏi bot.")
            return

        # Hiển thị menu với Reply Keyboard
        is_admin = db.is_admin(user.id)
        reply_markup = self.get_reply_keyboard(is_admin)

        await update.message.reply_text(
            "🤖 <b>Menu chính</b>\n\nChọn chức năng từ menu bên dưới:",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        logger.info(f"User {user.id} requested menu")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Xử lý tin nhắn văn bản từ Reply Keyboard - gọi trực tiếp các handler"""
        user = update.effective_user
        text = update.message.text

        logger.info(f"Received message from user {user.id}: '{text}'")

        # Kiểm tra xem user có bị ban không
        if db.is_banned(user.id):
            await update.message.reply_text("❌ Bạn đã bị ban khỏi bot.")
            return

        is_admin = db.is_admin(user.id)

        # Xử lý các nút menu - gọi trực tiếp các command handlers
        if text == "📰 Tin tức":
            logger.info(f"Processing: Tin tức - calling news_command")
            await self.news_command(update, context)
        elif text == "📈 Thị trường":
            logger.info(f"Processing: Thị trường - calling market_command")
            await self.market_command(update, context)
        elif text == "📨 Tín hiệu":
            logger.info(f"Processing: Tín hiệu - calling signals_command")
            await self.signals_command(update, context)
        elif text == "📊 Phân tích":
            logger.info(f"Processing: Phân tích - calling analyze_command")
            await self.analyze_command(update, context)
        elif text == "⚙️ Cài đặt":
            logger.info(f"Processing: Cài đặt")
            if is_admin:
                await self.show_settings(update, is_admin)
            else:
                await update.message.reply_text("⛔ Bạn không có quyền sử dụng chức năng này.")
        elif text == "📋 Danh sách lệnh":
            logger.info(f"Processing: Danh sách lệnh")
            await self.show_commands(update, is_admin)
        else:
            # Tin nhắn không phải menu - có thể xử lý khác hoặc bỏ qua
            logger.info(f"Unknown message: '{text}'")
            pass

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
        if self.market_data:
            market_info = self.market_data.get_market_summary()
            await update.message.reply_text(market_info, parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Dữ liệu thị trường chưa sẵn sàng.")

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

🔹 <b>Lệnh quản trị (Chỉ Admin):</b>
/ban <id> - Cấm người dùng
/unban <id> - Bỏ cấm người dùng
/users - Danh sách người dùng
/broadcast <message> - Gửi thông báo

🔹 <b>Lệnh cơ bản:</b>
/start - Bắt đầu sử dụng bot
            """
        else:
            commands_message = """
📋 <b>Danh sách lệnh</b>

🔹 <b>Lệnh cơ bản:</b>
/start - Bắt đầu sử dụng bot
            """

        await update.message.reply_text(commands_message, parse_mode='HTML')

    async def show_news(self, update: Update, is_admin: bool):
        """Hiển thị tin tức"""
        if self.market_data:
            news = self.market_data.get_latest_news()
            await update.message.reply_text(news, parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Tin tức chưa sẵn sàng.")

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

    async def show_settings(self, update: Update, is_admin: bool):
        """Hiển thị cài đặt (Admin only)"""
        keyboard = [
            [InlineKeyboardButton("📊 Xem cấu hình", callback_data="config_view")],
            [InlineKeyboardButton("👥 Quản lý người nhận", callback_data="manage_recipients")],
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
        is_admin = db.is_admin(user_id)

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
                    market_info = self.market_data.get_market_summary()
                    await query.edit_message_text(market_info, reply_markup=reply_markup, parse_mode='HTML')
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
            if self.market_data:
                try:
                    news = self.market_data.get_latest_news()
                    await query.edit_message_text(news, reply_markup=reply_markup, parse_mode='HTML')
                except Exception as e:
                    logger.error(f"Error in menu_news: {e}")
                    await query.edit_message_text(
                        "📰 <b>Tin tức</b>\n\n❌ Lỗi khi tải tin tức.",
                        reply_markup=reply_markup,
                        parse_mode='HTML'
                    )
            else:
                await query.edit_message_text(
                    "📰 <b>Tin tức</b>\n\n❌ Tin tức chưa sẵn sàng.",
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
                SYMBOLS, EXCHANGE, clean_symbol
            )
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
            clean_symbols = [clean_symbol(s) for s in SYMBOLS]
            config_text += f"• Cặp tiền giao dịch: {', '.join(clean_symbols)}\n"
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
        """Khởi động bot - tạo Application và setup webhook"""
        try:
            if self.application is not None:
                logger.warning("Telegram bot application already initialized")
                return self.application

            self.application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

            # Đăng ký handlers - chỉ giữ admin commands cần thiết
            self.application.add_handler(CommandHandler("start", self.start_command))
            self.application.add_handler(CommandHandler("ban", self.ban_command))
            self.application.add_handler(CommandHandler("unban", self.unban_command))
            self.application.add_handler(CommandHandler("users", self.users_command))
            self.application.add_handler(CommandHandler("broadcast", self.broadcast_command))
            self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
            self.application.add_handler(CallbackQueryHandler(self.button_callback))

            # Initialize the application
            await self.application.initialize()
            logger.info("Telegram bot application initialized successfully")

            # Delete all bot commands from Telegram
            await self.application.bot.delete_my_commands()
            logger.info("Deleted all bot commands from Telegram")

            # Try to remove menu button by setting to default without commands
            from telegram import BotCommandScopeAllPrivateChats
            await self.application.bot.set_chat_menu_button(menu_button=MenuButtonDefault())
            await self.application.bot.set_my_commands(commands=[], scope=BotCommandScopeAllPrivateChats())
            logger.info("Reset Telegram Menu Button and cleared commands")

            # Start the application (without polling)
            await self.application.start()
            logger.info("Telegram bot application started successfully")
            self.running = True

            # Setup webhook if TELEGRAM_WEBHOOK_URL is configured
            if TELEGRAM_WEBHOOK_URL:
                # Auto-append /webhook if not present
                webhook_url = TELEGRAM_WEBHOOK_URL
                if not webhook_url.endswith('/webhook'):
                    webhook_url = webhook_url.rstrip('/') + '/webhook'
                await self.application.bot.set_webhook(url=webhook_url)
                logger.info(f"Telegram webhook set to: {webhook_url}")
            else:
                logger.warning("TELEGRAM_WEBHOOK_URL not configured, webhook not set")

            return self.application
        except Exception as e:
            logger.error(f"Error starting Telegram bot: {e}")
            raise

    async def stop(self):
        """Stop the bot"""
        try:
            if not self.running:
                logger.info("Telegram bot not running, skipping stop")
                return

            self.running = False

            if self.application:
                # Delete webhook on shutdown
                try:
                    await self.application.bot.delete_webhook()
                    logger.info("Telegram webhook deleted successfully")
                except Exception as e:
                    logger.warning(f"Could not delete webhook: {e}")

                try:
                    await self.application.stop()
                    logger.info("Telegram bot application stopped")
                except Exception as e:
                    logger.error(f"Error stopping application: {e}")

                try:
                    await self.application.shutdown()
                    logger.info("Telegram bot application shut down")
                except Exception as e:
                    logger.error(f"Error shutting down application: {e}")

                self.application = None
                logger.info("Telegram bot stopped successfully")
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
