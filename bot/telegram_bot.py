"""
Module Telegram Bot cho AI Trading Signal Bot
Xử lý tất cả các lệnh và tin nhắn từ người dùng
"""
import logging
import os
from datetime import datetime
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeAllPrivateChats, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    TypeHandler
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
/news - Tin tức Crypto & Forex mới nhất

🔹 <b>Quản trị (Chỉ Admin):</b>
/adduser <user_id> - Thêm người nhận tín hiệu
/removeuser <user_id> - Xóa người nhận
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
    
    async def adduser_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /adduser - Thêm người nhận (Admin only) - Single-line parsing"""
        user_id = update.effective_user.id

        if not db.is_admin(user_id):
            await update.message.reply_text("❌ Chỉ Admin mới sử dụng lệnh này.")
            return

        if not context.args or len(context.args) < 1:
            await update.message.reply_text("❌ Sử dụng: /adduser <tên> <telegram_id> [username]\n\nVí dụ:\n/adduser Anh Trương 5335165612 anhtruong\n/adduser VIP 01 6021458788")
            return

        try:
            # Parse single-line input
            input_str = " ".join(context.args)

            # Find the Telegram ID (numeric string)
            import re
            numbers = re.findall(r'\d+', input_str)

            if not numbers:
                await update.message.reply_text("❌ Không tìm thấy Telegram ID trong đầu vào.")
                return

            target_user_id = int(numbers[0])
            if target_user_id <= 0:
                await update.message.reply_text("❌ Telegram ID phải là số dương.")
                return

            # Check if user already exists
            existing_user = db.get_user(target_user_id)
            if existing_user:
                await update.message.reply_text(f"❌ Người dùng với ID {target_user_id} đã tồn tại trong danh sách.")
                return

            # Extract display_name (everything before the ID)
            id_str = str(target_user_id)
            id_index = input_str.find(id_str)
            if id_index > 0:
                display_name = input_str[:id_index].strip()
            else:
                display_name = "Người dùng"

            # Extract username (everything after the ID)
            if id_index + len(id_str) < len(input_str):
                username_part = input_str[id_index + len(id_str):].strip()
                # Remove @ if present
                if username_part.startswith('@'):
                    username = username_part[1:]
                else:
                    username = username_part if username_part else None
            else:
                username = None

            # Add user to database
            db.add_user(
                telegram_id=target_user_id,
                username=username,
                display_name=display_name,
                is_active=True
            )

            # Display added user info
            added_message = f"""
✅ <b>Đã thêm người nhận thành công!</b>

👤 <b>Tên:</b> {display_name}
🆔 <b>Telegram ID:</b> {target_user_id}
📛 <b>Username:</b> @{username if username else '-'}
📅 <b>Ngày thêm:</b> {datetime.now().strftime('%d/%m/%Y')}
🟢 <b>Trạng thái:</b> Đang nhận tín hiệu
            """

            await update.message.reply_text(added_message, parse_mode='HTML')
            logger.info(f"Admin {user_id} added user {target_user_id} with display_name '{display_name}' and username '{username}'")
        except Exception as e:
            logger.error(f"Error adding user: {e}")
            await update.message.reply_text(f"❌ Lỗi: {str(e)}")
    
    async def removeuser_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /removeuser - Xóa người nhận (Admin only)"""
        user_id = update.effective_user.id

        if not db.is_admin(user_id):
            await update.message.reply_text("❌ Chỉ Admin mới sử dụng lệnh này.")
            return

        if not context.args or len(context.args) < 1:
            await update.message.reply_text("❌ Sử dụng: /removeuser <telegram_id>")
            return

        try:
            target_user_id = int(context.args[0])
            if target_user_id <= 0:
                await update.message.reply_text("❌ Telegram ID phải là số dương.")
                return

            db.remove_user(target_user_id)
            await update.message.reply_text(f"✅ Đã xóa người nhận {target_user_id} khỏi danh sách.")
            logger.info(f"Admin {user_id} removed user {target_user_id}")
        except ValueError:
            await update.message.reply_text("❌ Telegram ID phải là số.")
        except Exception as e:
            logger.error(f"Error removing user: {e}")
            await update.message.reply_text(f"❌ Lỗi: {str(e)}")
    
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

    async def editname_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /editname - Sửa tên người nhận (Admin only)"""
        user_id = update.effective_user.id

        if not db.is_admin(user_id):
            await update.message.reply_text("❌ Chỉ Admin mới sử dụng lệnh này.")
            return

        if not context.args or len(context.args) < 2:
            await update.message.reply_text("❌ Sử dụng: /editname <telegram_id> <tên mới>")
            return

        try:
            target_user_id = int(context.args[0])
            if target_user_id <= 0:
                await update.message.reply_text("❌ Telegram ID phải là số dương.")
                return

            new_name = " ".join(context.args[1:])

            db.update_display_name(target_user_id, new_name)
            await update.message.reply_text(f"✅ Đã sửa tên người nhận {target_user_id} thành: {new_name}")
            logger.info(f"Admin {user_id} edited name for user {target_user_id} to '{new_name}'")
        except ValueError:
            await update.message.reply_text("❌ Telegram ID phải là số.")
        except Exception as e:
            logger.error(f"Error editing name: {e}")
            await update.message.reply_text(f"❌ Lỗi: {str(e)}")

    async def disable_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /disable - Tắt nhận tín hiệu (Admin only)"""
        user_id = update.effective_user.id

        if not db.is_admin(user_id):
            await update.message.reply_text("❌ Chỉ Admin mới sử dụng lệnh này.")
            return

        if not context.args or len(context.args) < 1:
            await update.message.reply_text("❌ Sử dụng: /disable <telegram_id>")
            return

        try:
            target_user_id = int(context.args[0])
            if target_user_id <= 0:
                await update.message.reply_text("❌ Telegram ID phải là số dương.")
                return

            db.toggle_user_status(target_user_id)
            await update.message.reply_text(f"✅ Đã thay đổi trạng thái nhận tín hiệu cho người dùng {target_user_id}")
            logger.info(f"Admin {user_id} toggled status for user {target_user_id}")
        except ValueError:
            await update.message.reply_text("❌ Telegram ID phải là số.")
        except Exception as e:
            logger.error(f"Error toggling status: {e}")
            await update.message.reply_text(f"❌ Lỗi: {str(e)}")

    async def enable_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /enable - Bật nhận tín hiệu (Admin only)"""
        user_id = update.effective_user.id

        if not db.is_admin(user_id):
            await update.message.reply_text("❌ Chỉ Admin mới sử dụng lệnh này.")
            return

        if not context.args or len(context.args) < 1:
            await update.message.reply_text("❌ Sử dụng: /enable <telegram_id>")
            return

        try:
            target_user_id = int(context.args[0])
            if target_user_id <= 0:
                await update.message.reply_text("❌ Telegram ID phải là số dương.")
                return

            db.toggle_user_status(target_user_id)
            await update.message.reply_text(f"✅ Đã thay đổi trạng thái nhận tín hiệu cho người dùng {target_user_id}")
            logger.info(f"Admin {user_id} toggled status for user {target_user_id}")
        except ValueError:
            await update.message.reply_text("❌ Telegram ID phải là số.")
        except Exception as e:
            logger.error(f"Error toggling status: {e}")
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
    
    # ==================== CALLBACK HANDLERS ====================

    def get_reply_keyboard(self, is_admin: bool = False):
        """Tạo Reply Keyboard cho menu chính - tùy theo quyền Admin/User"""
        if is_admin:
            keyboard = [
                [KeyboardButton("📊 Phân tích"), KeyboardButton("📨 Tín hiệu")],
                [KeyboardButton("📈 Thị trường"), KeyboardButton("📰 Tin tức")],
                [KeyboardButton("👤 Tài khoản"), KeyboardButton("⚙️ Cài đặt")],
                [KeyboardButton("👥 Quản lý người nhận"), KeyboardButton("📋 Danh sách lệnh")],
                [KeyboardButton("❓ Trợ giúp")]
            ]
        else:
            # User menu - chỉ các chức năng cơ bản
            keyboard = [
                [KeyboardButton("📨 Tín hiệu"), KeyboardButton("📈 Thị trường")],
                [KeyboardButton("📰 Tin tức"), KeyboardButton("❓ Trợ giúp")]
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
        """Xử lý tin nhắn văn bản từ Reply Keyboard"""
        user = update.effective_user
        text = update.message.text

        logger.info(f"Received message from user {user.id}: '{text}'")

        # Kiểm tra xem user có bị ban không
        if db.is_banned(user.id):
            await update.message.reply_text("❌ Bạn đã bị ban khỏi bot.")
            return

        is_admin = db.is_admin(user.id)
        logger.info(f"User {user.id} is_admin: {is_admin}")

        # Xử lý các nút menu
        if text == "📊 Phân tích":
            logger.info(f"Processing: Phân tích")
            await self.show_analysis(update, is_admin)
        elif text == "📨 Tín hiệu":
            logger.info(f"Processing: Tín hiệu")
            await self.show_signals(update, is_admin)
        elif text == "📈 Thị trường":
            logger.info(f"Processing: Thị trường")
            await self.show_market(update, is_admin)
        elif text == "📰 Tin tức":
            logger.info(f"Processing: Tin tức")
            await self.show_news(update, is_admin)
        elif text == "👤 Tài khoản":
            logger.info(f"Processing: Tài khoản")
            await self.show_account(update, is_admin)
        elif text == "⚙️ Cài đặt":
            logger.info(f"Processing: Cài đặt")
            if is_admin:
                await self.show_settings(update, is_admin)
            else:
                await update.message.reply_text("⛔ Bạn không có quyền sử dụng chức năng này.")
        elif text == "👥 Quản lý người nhận":
            logger.info(f"Processing: Quản lý người nhận")
            if is_admin:
                await self.show_recipient_management(update)
            else:
                await update.message.reply_text("⛔ Bạn không có quyền sử dụng chức năng này.")
        elif text == "📋 Danh sách lệnh":
            logger.info(f"Processing: Danh sách lệnh")
            await self.show_commands(update, is_admin)
        elif text == "❓ Trợ giúp":
            logger.info(f"Processing: Trợ giúp")
            await self.show_help(update, is_admin)
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

    async def show_recipient_management(self, update: Update):
        """Hiển thị quản lý người nhận (Admin only)"""
        keyboard = [
            [InlineKeyboardButton("➕ Thêm người nhận", callback_data="recipient_add")],
            [InlineKeyboardButton("✏️ Sửa tên", callback_data="recipient_edit")],
            [InlineKeyboardButton("🗑 Xóa người nhận", callback_data="recipient_remove")],
            [InlineKeyboardButton("📋 Danh sách người nhận", callback_data="recipient_list")],
            [InlineKeyboardButton("🔕 Tắt nhận tín hiệu", callback_data="recipient_disable")],
            [InlineKeyboardButton("🔔 Bật nhận tín hiệu", callback_data="recipient_enable")],
            [InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "👥 <b>Quản lý người nhận tín hiệu</b>\n\nChọn chức năng:",
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
                [InlineKeyboardButton("👥 Quản lý người nhận", callback_data="manage_recipients")],
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

        # Quản lý người nhận tín hiệu (Admin)
        elif query.data == "manage_recipients":
            if not is_admin:
                await query.edit_message_text("⛔ Bạn không có quyền sử dụng chức năng này.")
                return

            keyboard = [
                [InlineKeyboardButton("➕ Thêm người nhận", callback_data="recipient_add")],
                [InlineKeyboardButton("✏️ Sửa tên", callback_data="recipient_edit")],
                [InlineKeyboardButton("🗑 Xóa người nhận", callback_data="recipient_remove")],
                [InlineKeyboardButton("📋 Danh sách người nhận", callback_data="recipient_list")],
                [InlineKeyboardButton("🔕 Tắt nhận tín hiệu", callback_data="recipient_disable")],
                [InlineKeyboardButton("🔔 Bật nhận tín hiệu", callback_data="recipient_enable")],
                [InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_settings")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "👥 <b>Quản lý người nhận tín hiệu</b>\n\nChọn chức năng:",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )

        # Thêm người nhận
        elif query.data == "recipient_add":
            if not is_admin:
                await query.edit_message_text("⛔ Bạn không có quyền sử dụng chức năng này.")
                return

            keyboard = [
                [InlineKeyboardButton("⬅️ Quay lại", callback_data="manage_recipients")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "➕ <b>Thêm người nhận</b>\n\n"
                "Sử dụng lệnh: /adduser <tên> <telegram_id> [username]\n\n"
                "Ví dụ: /adduser Anh Trương 5335165612 anhtruong",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )

        # Xóa người nhận
        elif query.data == "recipient_remove":
            if not is_admin:
                await query.edit_message_text("⛔ Bạn không có quyền sử dụng chức năng này.")
                return

            keyboard = [
                [InlineKeyboardButton("⬅️ Quay lại", callback_data="manage_recipients")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "➖ <b>Xóa người nhận</b>\n\n"
                "Sử dụng lệnh: /removeuser <telegram_id>\n\n"
                "Ví dụ: /removeuser 123456789",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )

        # Danh sách người nhận
        elif query.data == "recipient_list":
            if not is_admin:
                await query.edit_message_text("⛔ Bạn không có quyền sử dụng chức năng này.")
                return

            users = db.get_all_users()

            if not users:
                users_list = "📋 <b>Danh sách người nhận</b>\n\nKhông có người nhận nào."
            else:
                users_list = "👥 <b>Danh sách người nhận</b>\n\n"
                for idx, user in enumerate(users, 1):
                    display_name = user.get('display_name') or user.get('first_name') or 'Người dùng'
                    username = user.get('username')
                    username_display = f"@{username}" if username else "-"
                    status_emoji = "🟢" if user['is_active'] else "🔴"
                    status_text = "Đang nhận tín hiệu" if user['is_active'] else "Không nhận tín hiệu"

                    users_list += f"{idx}️⃣ {display_name}\n"
                    users_list += f"🆔 ID: {user['telegram_id']}\n"
                    users_list += f"📛 Username: {username_display}\n"
                    users_list += f"{status_emoji} {status_text}\n"
                    users_list += "----------------------\n\n"

            keyboard = [
                [InlineKeyboardButton("⬅️ Quay lại", callback_data="manage_recipients")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(users_list, reply_markup=reply_markup, parse_mode='HTML')

        # Sửa tên người nhận
        elif query.data == "recipient_edit":
            if not is_admin:
                await query.edit_message_text("⛔ Bạn không có quyền sử dụng chức năng này.")
                return

            keyboard = [
                [InlineKeyboardButton("⬅️ Quay lại", callback_data="manage_recipients")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "✏️ <b>Sửa tên người nhận</b>\n\n"
                "Sử dụng lệnh: /editname <telegram_id> <tên mới>\n\n"
                "Ví dụ: /editname 5335165612 Anh Trương VIP",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )

        # Tắt nhận tín hiệu
        elif query.data == "recipient_disable":
            if not is_admin:
                await query.edit_message_text("⛔ Bạn không có quyền sử dụng chức năng này.")
                return

            keyboard = [
                [InlineKeyboardButton("⬅️ Quay lại", callback_data="manage_recipients")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "🔕 <b>Tắt nhận tín hiệu</b>\n\n"
                "Sử dụng lệnh: /disable <telegram_id>\n\n"
                "Ví dụ: /disable 5335165612",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )

        # Bật nhận tín hiệu
        elif query.data == "recipient_enable":
            if not is_admin:
                await query.edit_message_text("⛔ Bạn không có quyền sử dụng chức năng này.")
                return

            keyboard = [
                [InlineKeyboardButton("⬅️ Quay lại", callback_data="manage_recipients")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "🔔 <b>Bật nhận tín hiệu</b>\n\n"
                "Sử dụng lệnh: /enable <telegram_id>\n\n"
                "Ví dụ: /enable 5335165612",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )

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
                        [InlineKeyboardButton("👥 Quản lý người nhận", callback_data="manage_recipients")],
                        [InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_main")]
                    ]),
                    parse_mode='HTML'
                )
            elif target == "manage_recipients":
                # Navigate back to manage recipients
                await query.edit_message_text(
                    "👥 <b>Quản lý người nhận tín hiệu</b>\n\nChọn chức năng:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("➕ Thêm người nhận", callback_data="recipient_add")],
                        [InlineKeyboardButton("✏️ Sửa tên", callback_data="recipient_edit")],
                        [InlineKeyboardButton("🗑 Xóa người nhận", callback_data="recipient_remove")],
                        [InlineKeyboardButton("📋 Danh sách người nhận", callback_data="recipient_list")],
                        [InlineKeyboardButton("🔕 Tắt nhận tín hiệu", callback_data="recipient_disable")],
                        [InlineKeyboardButton("🔔 Bật nhận tín hiệu", callback_data="recipient_enable")],
                        [InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_settings")]
                    ]),
                    parse_mode='HTML'
                )
    
    async def setup_menu_button(self):
        """Set up Telegram Menu Button"""
        try:
            commands = [
                BotCommand("start", "Bắt đầu sử dụng bot"),
                BotCommand("help", "Trợ giúp"),
                BotCommand("status", "Trạng thái bot"),
                BotCommand("market", "Thông tin thị trường"),
                BotCommand("news", "Tin tức"),
                BotCommand("stats", "Thống kê tín hiệu")
            ]
            await self.application.bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats())
            logger.info("Telegram Menu Button set up successfully")
        except Exception as e:
            logger.error(f"Error setting up menu button: {e}")

    # ==================== BOT STARTUP ====================

    async def start(self):
        """Khởi động bot - tạo Application và setup webhook"""
        try:
            if self.application is not None:
                logger.warning("Telegram bot application already initialized")
                return self.application

            self.application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

            # Đăng ký handlers
            self.application.add_handler(CommandHandler("start", self.start_command))
            self.application.add_handler(CommandHandler("menu", self.menu_command))
            self.application.add_handler(CommandHandler("help", self.help_command))
            self.application.add_handler(CommandHandler("status", self.status_command))
            self.application.add_handler(CommandHandler("market", self.market_command))
            self.application.add_handler(CommandHandler("news", self.news_command))
            self.application.add_handler(CommandHandler("settings", self.settings_command))
            self.application.add_handler(CommandHandler("id", self.id_command))
            self.application.add_handler(CommandHandler("adduser", self.adduser_command))
            self.application.add_handler(CommandHandler("removeuser", self.removeuser_command))
            self.application.add_handler(CommandHandler("ban", self.ban_command))
            self.application.add_handler(CommandHandler("unban", self.unban_command))
            self.application.add_handler(CommandHandler("users", self.users_command))
            self.application.add_handler(CommandHandler("broadcast", self.broadcast_command))
            self.application.add_handler(CommandHandler("stats", self.stats_command))
            self.application.add_handler(CommandHandler("editname", self.editname_command))
            self.application.add_handler(CommandHandler("disable", self.disable_command))
            self.application.add_handler(CommandHandler("enable", self.enable_command))
            self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
            self.application.add_handler(CallbackQueryHandler(self.button_callback))

            # Initialize the application
            await self.application.initialize()
            logger.info("Telegram bot application initialized successfully")

            # Set up Telegram Menu Button
            await self.setup_menu_button()

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
        """Gửi tín hiệu đến tất cả users được phép với chart"""
        users = db.get_all_users()

        success_count = 0
        for user in users:
            try:
                # Send chart with signal as caption if available
                if chart_path:
                    try:
                        with open(chart_path, 'rb') as photo:
                            await self.application.bot.send_photo(
                                chat_id=user['telegram_id'],
                                photo=photo,
                                caption=signal_text,
                                parse_mode='HTML'
                            )
                        success_count += 1
                    except Exception as e:
                        error_str = str(e)
                        if "Chat not found" in error_str or "chat not found" in error_str.lower():
                            logger.warning(f"Chat {user['telegram_id']} not found, deactivating user")
                            db.remove_user(user['telegram_id'])
                        else:
                            logger.error(f"Error sending chart to {user['telegram_id']}: {e}")
                        # Fallback to text message if chart fails
                        try:
                            await self.application.bot.send_message(
                                chat_id=user['telegram_id'],
                                text=signal_text,
                                parse_mode='HTML'
                            )
                            success_count += 1
                        except Exception as e2:
                            error_str2 = str(e2)
                            if "Chat not found" in error_str2 or "chat not found" in error_str2.lower():
                                logger.warning(f"Chat {user['telegram_id']} not found, deactivating user")
                                db.remove_user(user['telegram_id'])
                            else:
                                logger.error(f"Error sending fallback message to {user['telegram_id']}: {e2}")
                else:
                    # Send text message only if no chart
                    try:
                        await self.application.bot.send_message(
                            chat_id=user['telegram_id'],
                            text=signal_text,
                            parse_mode='HTML'
                        )
                        success_count += 1
                    except Exception as e:
                        error_str = str(e)
                        if "Chat not found" in error_str or "chat not found" in error_str.lower():
                            logger.warning(f"Chat {user['telegram_id']} not found, deactivating user")
                            db.remove_user(user['telegram_id'])
                        else:
                            logger.error(f"Error sending signal to {user['telegram_id']}: {e}")
            except Exception as e:
                error_str = str(e)
                if "Chat not found" in error_str or "chat not found" in error_str.lower():
                    logger.warning(f"Chat {user['telegram_id']} not found, deactivating user")
                    db.remove_user(user['telegram_id'])
                else:
                    logger.error(f"Error sending signal to {user['telegram_id']}: {e}")

        logger.info(f"Signal sent to {success_count}/{len(users)} users")

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
