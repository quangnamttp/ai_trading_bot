"""
Module Telegram Bot cho AI Trading Signal Bot
Xử lý tất cả các lệnh và tin nhắn từ người dùng
"""
import logging
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
        
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
        logger.info(f"User {user.id} started the bot")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /help - Trợ giúp"""
        help_message = """
📖 *Trợ giúp AI Trading Signal Bot*

🔹 *Các lệnh cơ bản:*
/start - Khởi động bot
/help - Xem trợ giúp này
/status - Trạng thái hệ thống
/id - Xem Telegram ID của bạn

🔹 *Phân tích thị trường:*
/btc - Phân tích Bitcoin (BTCUSDT)
/gold - Phân tích Vàng (XAUUSD)
/market - Tổng quan thị trường

🔹 *Tin tức:*
/news - Tin tức Crypto & Forex mới nhất

🔹 *Quản trị (Chỉ Admin):*
/adduser <user_id> - Thêm user nhận tín hiệu
/removeuser <user_id> - Xóa user
/ban <user_id> - Ban user
/unban <user_id> - Unban user
/users - Danh sách users
/settings - Cấu hình bot
/broadcast <message> - Gửi thông báo đến tất cả users

� *Thống kê:*
/stats - Xem thống kê tín hiệu

� *Bot hoạt động 24/7 quét dữ liệu thị trường và gửi tín hiệu khi AI Score > 85%*

⚠️ *Bot không tự động giao dịch. Tín hiệu chỉ để tham khảo.*
        """
        
        await update.message.reply_text(help_message, parse_mode='Markdown')
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /status - Trạng thái bot"""
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
📊 *Trạng thái Bot*

🕒 Thời gian: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

👥 Users: {total_users}
📈 Tín hiệu gần đây: {len(recent_signals)}
🤖 AI Logs: {len(recent_ai_logs)}

✅ Bot đang hoạt động 24/7
🔄 Quét dữ liệu thị trường liên tục
🎯 Gửi tín hiệu khi AI Score > 85%
        """
        
        await update.message.reply_text(status_message, parse_mode='Markdown')
    
    async def market_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /market - Thông tin thị trường"""
        user_id = update.effective_user.id
        
        if not db.is_authorized(user_id):
            await update.message.reply_text("❌ Bạn không có quyền sử dụng bot này.")
            return
        
        await update.message.reply_text("🔄 Đang lấy dữ liệu thị trường...")
        
        try:
            if self.market_data:
                market_info = await self.market_data.get_market_overview()
                if market_info:
                    await update.message.reply_text(market_info, parse_mode='Markdown')
                else:
                    await update.message.reply_text("❌ Không thể lấy dữ liệu thị trường.")
            else:
                await update.message.reply_text("❌ Market data engine chưa được khởi tạo.")
        except Exception as e:
            logger.error(f"Error in market_command: {e}")
            await update.message.reply_text(f"❌ Lỗi: {str(e)}")
    
    async def news_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lệnh /news - Tin tức"""
        user_id = update.effective_user.id

        if not db.is_authorized(user_id):
            await update.message.reply_text("❌ Bạn không có quyền sử dụng bot này.")
            return

        await update.message.reply_text("🔄 Đang lấy tin tức...")

        try:
            from data.news_engine import news_engine

            # Get real news summary from news engine
            news_summary = await news_engine.get_news_summary()

            if news_summary:
                await update.message.reply_text(news_summary, parse_mode='Markdown')
            else:
                await update.message.reply_text("❌ Không thể lấy tin tức lúc này.")
        except Exception as e:
            logger.error(f"Error in news_command: {e}")
            await update.message.reply_text(f"❌ Lỗi: {str(e)}")
    
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
            await update.message.reply_text(stats_message, parse_mode='Markdown')
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
                SYMBOLS, EXCHANGE
            )
            config_text = "📊 *Cấu hình hiện tại:*\n\n"
            config_text += f"• AI Score Threshold: {AI_SCORE_THRESHOLD}\n"
            config_text += f"• Min Confidence: {MIN_CONFIDENCE}\n"
            config_text += f"• Max Risk Per Trade: {MAX_RISK_PER_TRADE}\n"
            config_text += f"• Max Positions: {MAX_POSITIONS}\n"
            config_text += f"• Signal Cooldown: {SIGNAL_COOLDOWN_MINUTES} minutes\n"
            config_text += f"• Max Signals Per Hour: {MAX_SIGNALS_PER_HOUR}\n"
            config_text += f"• Market Data Interval: {MARKET_DATA_INTERVAL}s\n"
            config_text += f"• News Check Interval: {NEWS_CHECK_INTERVAL}s\n"
            config_text += f"• AI Update Interval: {AI_UPDATE_INTERVAL}s\n"
            config_text += f"• Trading Symbols: {', '.join(SYMBOLS)}\n"
            config_text += f"• Exchange: {EXCHANGE}\n"

            keyboard = [
                [InlineKeyboardButton("🔙 Quay lại", callback_data="config_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(config_text, reply_markup=reply_markup, parse_mode='Markdown')

        elif query.data == "config_ai_threshold":
            keyboard = [
                [InlineKeyboardButton("🔙 Quay lại", callback_data="config_view")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "🔧 *Đổi ngưỡng AI Score*\n\n"
                "Ngưỡng hiện tại: 85\n"
                "Để đổi, sử dụng lệnh: /set_ai_threshold <value>\n"
                "Ví dụ: /set_ai_threshold 90",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )

        elif query.data == "config_back":
            keyboard = [
                [InlineKeyboardButton("📊 Xem cấu hình", callback_data="config_view")],
                [InlineKeyboardButton("🔧 Đổi ngưỡng AI Score", callback_data="config_ai_threshold")],
                [InlineKeyboardButton("🔙 Quay lại", callback_data="config_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("⚙️ *Cấu hình Bot*", reply_markup=reply_markup, parse_mode='Markdown')
    
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
            await self.application.initialize()
            logger.info("Telegram bot application initialized successfully")
            return self.application
        except Exception as e:
            logger.error(f"Error starting Telegram bot: {e}")
            raise

    async def run_polling(self):
        """Chạy polling trong background task"""
        try:
            if self.running:
                logger.warning("Telegram bot polling already running")
                return

            self.running = True
            await self.application.start()
            await self.application.updater.start_polling(drop_pending_updates=True)
            logger.info("Telegram bot polling started successfully")
        except Exception as e:
            logger.error(f"Error starting Telegram bot polling: {e}")
            self.running = False
            raise

    async def stop(self):
        """Stop the bot"""
        try:
            if not self.running:
                logger.info("Telegram bot not running, skipping stop")
                return

            self.running = False

            if self.application:
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
                # Send chart first if available
                if chart_path:
                    try:
                        with open(chart_path, 'rb') as photo:
                            await self.application.bot.send_photo(
                                chat_id=user['telegram_id'],
                                photo=photo,
                                caption="📊 Chart Analysis"
                            )
                    except Exception as e:
                        logger.error(f"Error sending chart to {user['telegram_id']}: {e}")

                # Send signal message
                await self.application.bot.send_message(
                    chat_id=user['telegram_id'],
                    text=signal_text,
                    parse_mode='Markdown'
                )
                success_count += 1
            except Exception as e:
                logger.error(f"Error sending signal to {user['telegram_id']}: {e}")

        logger.info(f"Signal sent to {success_count}/{len(users)} users")
        return success_count


# Singleton instance
telegram_bot = TelegramBot()
