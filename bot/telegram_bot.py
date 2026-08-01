"""
Module Telegram Bot cho AI Trading Signal Bot
Xử lý tất cả các lệnh và tin nhắn từ người dùng
"""
import logging
import os
from datetime import datetime
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from core.config import TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_ID
from core.database import db
from core.statistics import statistics_manager

logger = logging.getLogger(__name__)
logger.info(f"IMPORT telegram_bot - PID: {os.getpid()}")

# PID lock file to prevent multiple polling instances
POLLING_LOCK_FILE = "temp/telegram_polling.lock"


def acquire_polling_lock() -> bool:
    """Acquire polling lock using PID file. Returns True if lock acquired."""
    try:
        # Ensure temp directory exists
        os.makedirs("temp", exist_ok=True)

        # Check if lock file exists
        if os.path.exists(POLLING_LOCK_FILE):
            try:
                with open(POLLING_LOCK_FILE, 'r') as f:
                    old_pid = int(f.read().strip())

                # Check if process with that PID is still running
                try:
                    os.kill(old_pid, 0)  # Signal 0 checks if process exists
                    logger.warning(f"Polling lock held by process {old_pid}, skipping")
                    return False
                except OSError:
                    # Process not running, stale lock
                    logger.info(f"Stale lock from process {old_pid}, removing")
                    os.remove(POLLING_LOCK_FILE)
            except (ValueError, IOError) as e:
                logger.warning(f"Error reading lock file: {e}, removing")
                try:
                    os.remove(POLLING_LOCK_FILE)
                except:
                    pass

        # Write current PID to lock file
        current_pid = os.getpid()
        with open(POLLING_LOCK_FILE, 'w') as f:
            f.write(str(current_pid))

        logger.info(f"Polling lock acquired for PID {current_pid}")
        return True
    except Exception as e:
        logger.error(f"Error acquiring polling lock: {e}")
        return False


def release_polling_lock():
    """Release polling lock by removing PID file."""
    try:
        if os.path.exists(POLLING_LOCK_FILE):
            os.remove(POLLING_LOCK_FILE)
            logger.info("Polling lock released")
    except Exception as e:
        logger.error(f"Error releasing polling lock: {e}")


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
        db.add_user(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            is_admin=(str(user.id) == TELEGRAM_ADMIN_ID)
        )
        logger.info(f"Registered chat: {user.id}")
        
        welcome_message = f"""
🤖 *Chào mừng bạn đến với AI Trading Signal Bot!*

👤 Xin chào {user.first_name}!

Bot này sẽ giúp bạn:
• 📊 Phân tích thị trường 24/7
• 🎯 Gửi tín hiệu giao dịch BTC và Vàng
• 🤖 AI phân tích với độ chính xác cao
• 📰 Cập nhật tin tức thị trường

📋 *Các lệnh có sẵn:*
/start - Khởi động bot
/help - Xem trợ giúp
/status - Trạng thái bot
/btc - Phân tích BTC
/gold - Phân tích Vàng
/market - Thông tin thị trường
/news - Tin tức mới nhất
/settings - Cấu hình
/id - Xem Telegram ID của bạn

⚠️ *Lưu ý:* Bot chỉ cung cấp tín hiệu phân tích, không tự động giao dịch. Bạn tự quyết định vào lệnh thủ công.
        """
        
        await update.message.reply_text(welcome_message, parse_mode='HTML')
        logger.info(f"User {user.id} started the bot")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /help - Hiển thị trợ giúp"""
        help_message = f"""
🤖 <b>AI Trading Signal Bot - Hướng dẫn sử dụng</b>

🔹 <b>Lệnh cơ bản:</b>
/start - Bắt đầu sử dụng bot
/help - Hiển thị trợ giúp này
/status - Trạng thái bot
/market - Thông tin thị trường
/news - Tin tức Crypto & Forex mới nhất

🔹 <b>Quản trị (Chỉ Admin):</b>
/adduser <user_id> - Thêm user nhận tín hiệu
/removeuser <user_id> - Xóa user
/ban <user_id> - Ban user
/unban <user_id> - Unban user
/users - Danh sách users
/settings - Cấu hình bot
/broadcast <message> - Gửi thông báo đến tất cả users

📊 <b>Thống kê:</b>
/stats - Xem thống kê tín hiệu

🤖 <b>Bot hoạt động 24/7 quét dữ liệu thị trường và gửi tín hiệu khi AI Score > {AI_SCORE_THRESHOLD}%</b>

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

👥 Users: {total_users}
📈 Tín hiệu gần đây: {len(recent_signals)}
🤖 AI Logs: {len(recent_ai_logs)}

✅ Bot đang hoạt động 24/7
🔄 Quét dữ liệu thị trường liên tục
🎯 Gửi tín hiệu khi AI Score > {AI_SCORE_THRESHOLD}%
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
        """Lệnh /adduser - Thêm user (Admin only)"""
        user_id = update.effective_user.id
        
        if not db.is_admin(user_id):
            await update.message.reply_text("❌ Chỉ Admin mới sử dụng lệnh này.")
            return
        
        if not context.args or len(context.args) < 1:
            await update.message.reply_text("❌ Sử dụng: /adduser <telegram_id>")
            return
        
        try:
            target_user_id = int(context.args[0])
            if target_user_id <= 0:
                await update.message.reply_text("❌ Telegram ID phải là số dương.")
                return
            
            db.add_user(target_user_id, is_active=True)
            await update.message.reply_text(f"✅ Đã thêm user {target_user_id} vào danh sách.")
            logger.info(f"Admin {user_id} added user {target_user_id}")
        except ValueError:
            await update.message.reply_text("❌ Telegram ID phải là số.")
        except Exception as e:
            logger.error(f"Error adding user: {e}")
            await update.message.reply_text(f"❌ Lỗi: {str(e)}")
    
    async def removeuser_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /removeuser - Xóa user (Admin only)"""
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
            await update.message.reply_text(f"✅ Đã xóa user {target_user_id} khỏi danh sách.")
            logger.info(f"Admin {user_id} removed user {target_user_id}")
        except ValueError:
            await update.message.reply_text("❌ Telegram ID phải là số.")
        except Exception as e:
            logger.error(f"Error removing user: {e}")
            await update.message.reply_text(f"❌ Lỗi: {str(e)}")
    
    async def users_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /users - Danh sách users (Admin only)"""
        user_id = update.effective_user.id
        
        if not db.is_admin(user_id):
            await update.message.reply_text("❌ Chỉ Admin mới sử dụng lệnh này.")
            return
        
        users = db.get_all_users()
        
        if not users:
            await update.message.reply_text("📋 Không có user nào.")
            return
        
        users_list = "📋 *Danh sách Users:*\n\n"
        for user in users:
            admin_badge = " 👑" if user['is_admin'] else ""
            users_list += f"• ID: `{user['telegram_id']}`{admin_badge}\n"
            users_list += f"  Username: @{user['username'] or 'N/A'}\n"
            users_list += f"  Name: {user['first_name'] or 'N/A'}\n\n"
        
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
        
        await update.message.reply_text(f"✅ Đã gửi thông báo đến {success_count}/{len(users)} users.")
        logger.info(f"Admin {user_id} broadcasted message to {success_count} users")
    
    async def ban_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /ban - Ban user (Admin only)"""
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
            await update.message.reply_text(f"✅ Đã ban user {target_user_id}")
            logger.info(f"Admin {user_id} banned user {target_user_id}")
        except ValueError:
            await update.message.reply_text("❌ Telegram ID phải là số.")
        except Exception as e:
            logger.error(f"Error banning user: {e}")
            await update.message.reply_text(f"❌ Lỗi: {str(e)}")
    
    async def unban_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /unban - Unban user (Admin only)"""
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
            await update.message.reply_text(f"✅ Đã unban user {target_user_id}")
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
            await update.message.reply_text("❌ Bạn đã bị ban khỏi bot.")
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
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Xử lý callback từ inline keyboard"""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id

        if not db.is_admin(user_id):
            await query.edit_message_text("❌ Chỉ Admin mới sử dụng chức năng này.")
            return

        if query.data == "config_view":
            from core.config import (
                AI_SCORE_THRESHOLD, MIN_CONFIDENCE, MAX_RISK_PER_TRADE,
                MAX_POSITIONS, SIGNAL_COOLDOWN_MINUTES, MAX_SIGNALS_PER_HOUR,
                MARKET_DATA_INTERVAL, NEWS_CHECK_INTERVAL, AI_UPDATE_INTERVAL,
                SYMBOLS, EXCHANGE, clean_symbol
            )
            config_text = "📊 <b>Cấu hình hiện tại:</b>\n\n"
            config_text += f"• AI Score Threshold: {AI_SCORE_THRESHOLD}\n"
            config_text += f"• Min Confidence: {MIN_CONFIDENCE}\n"
            config_text += f"• Max Risk Per Trade: {MAX_RISK_PER_TRADE}\n"
            config_text += f"• Max Positions: {MAX_POSITIONS}\n"
            config_text += f"• Signal Cooldown: {SIGNAL_COOLDOWN_MINUTES} minutes\n"
            config_text += f"• Max Signals Per Hour: {MAX_SIGNALS_PER_HOUR}\n"
            config_text += f"• Market Data Interval: {MARKET_DATA_INTERVAL}s\n"
            config_text += f"• News Check Interval: {NEWS_CHECK_INTERVAL}s\n"
            config_text += f"• AI Update Interval: {AI_UPDATE_INTERVAL}s\n"
            clean_symbols = [clean_symbol(s) for s in SYMBOLS]
            config_text += f"• Trading Symbols: {', '.join(clean_symbols)}\n"
            config_text += f"• Exchange: {EXCHANGE}\n"

            keyboard = [
                [InlineKeyboardButton("🔙 Quay lại", callback_data="config_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(config_text, reply_markup=reply_markup, parse_mode='HTML')

        elif query.data == "config_ai_threshold":
            from core.config import AI_SCORE_THRESHOLD
            keyboard = [
                [InlineKeyboardButton("🔙 Quay lại", callback_data="config_view")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"🔧 <b>Đổi ngưỡng AI Score</b>\n\n"
                f"Ngưỡng hiện tại: {AI_SCORE_THRESHOLD}\n"
                "Để đổi, sử dụng lệnh: /set_ai_threshold <value>\n"
                "Ví dụ: /set_ai_threshold 90",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )

        elif query.data == "config_back":
            keyboard = [
                [InlineKeyboardButton("📊 Xem cấu hình", callback_data="config_view")],
                [InlineKeyboardButton("🔧 Đổi ngưỡng AI Score", callback_data="config_ai_threshold")],
                [InlineKeyboardButton("🔙 Quay lại", callback_data="config_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("⚙️ <b>Cấu hình Bot</b>", reply_markup=reply_markup, parse_mode='HTML')
    
    # ==================== BOT STARTUP ====================

    async def start(self):
        """Khởi động bot - chỉ tạo Application, không start polling"""
        try:
            if self.application is not None:
                logger.warning("Telegram bot application already initialized")
                return self.application

            self.application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

            # Đăng ký handlers
            self.application.add_handler(CommandHandler("start", self.start_command))
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
            self.application.add_handler(CallbackQueryHandler(self.button_callback))

            # Initialize the application (không start polling ở đây)
            logger.info(f"ENTER application.initialize() - PID: {os.getpid()}")
            await self.application.initialize()
            logger.info(f"EXIT application.initialize() - PID: {os.getpid()}")
            logger.info("Telegram bot application initialized successfully")
            return self.application
        except Exception as e:
            logger.error(f"Error starting Telegram bot: {e}")
            raise

    async def run_polling(self):
        """Chạy polling trong background task"""
        try:
            logger.info(f"ENTER run_polling() - PID: {os.getpid()}")

            # Print stack trace to see who called this
            import traceback
            logger.info(f"CALL STACK for run_polling() - PID: {os.getpid()}")
            traceback.print_stack()

            if self.running:
                logger.warning("Telegram bot polling already running")
                return

            # Acquire PID lock to prevent race condition during deployment
            if not acquire_polling_lock():
                logger.error("Could not acquire polling lock, skipping")
                return

            logger.info(f"PID: {os.getpid()}")
            logger.info(f"Process ID: {os.getpid()}")
            logger.info("START TELEGRAM POLLING")

            # Delete webhook before starting polling to avoid conflicts
            try:
                await self.application.bot.delete_webhook(drop_pending_updates=True)
                logger.info("Telegram webhook deleted successfully")
            except Exception as e:
                logger.warning(f"Could not delete webhook (may not exist): {e}")

            self.running = True

            # Use manual async lifecycle to avoid event loop conflicts
            # The application is already running in an existing event loop
            # application.run_polling() creates its own event loop, which causes conflicts
            logger.info(f"ENTER application.start() - PID: {os.getpid()}")
            await self.application.start()
            logger.info(f"EXIT application.start() - PID: {os.getpid()}")

            logger.info(f"START updater.start_polling() - PID: {os.getpid()}")
            await self.application.updater.start_polling(drop_pending_updates=True)
            logger.info(f"EXIT updater.start_polling() - PID: {os.getpid()}")

            logger.info("Telegram polling started")
            logger.info(f"EXIT run_polling() - PID: {os.getpid()}")
        except Exception as e:
            logger.error(f"Error starting Telegram bot polling: {e}")
            self.running = False
            release_polling_lock()
            raise

    async def stop(self):
        """Stop the bot"""
        try:
            if not self.running:
                logger.info("Telegram bot not running, skipping stop")
                return

            self.running = False

            # Release polling lock
            release_polling_lock()

            if self.application:
                # Manual async lifecycle: stop updater, then application, then shutdown
                if hasattr(self.application, 'updater') and self.application.updater:
                    try:
                        await self.application.updater.stop()
                        logger.info("Telegram bot updater stopped")
                    except Exception as e:
                        logger.error(f"Error stopping updater: {e}")

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
