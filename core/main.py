"""
Main Application cho AI Trading Signal Bot
Khởi động và quản lý toàn bộ hệ thống
"""
import asyncio
import logging
import signal
import sys
import os
from datetime import datetime
from core.config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_ID,
    MARKET_DATA_INTERVAL, NEWS_CHECK_INTERVAL, AI_UPDATE_INTERVAL,
    validate_config, PORT, SYMBOLS, AI_SCORE_THRESHOLD, MIN_CONFIDENCE
)

logger = logging.getLogger(__name__)
from core.database import db
from core.signal_tracker import signal_tracker
from core.statistics import statistics_manager
from core.reporting import reporting_manager
from bot.telegram_bot import telegram_bot
from data.market_data import market_data_engine
from data.news_engine import news_engine
from data.smart_money import smart_money_tracker
from analysis.ai_engine import ai_engine
from analysis.signal_engine import signal_engine
from analysis.risk_manager import risk_manager
from analysis.chart_generator import chart_generator
from utils.utils import setup_logging, async_sleep
from utils.message_queue import message_queue
from utils.anti_duplicate import anti_duplicate
from utils.cache_manager import cache_manager
from utils.auto_cleanup import auto_cleanup


class TradingBotApp:
    """Main Application class"""
    
    def __init__(self):
        self.running = False
        self.tasks = []
        self.shutdown_event = asyncio.Event()
        self.bot_application = None
    
    async def initialize(self):
        """Khởi tạo tất cả các components"""
        try:
            logger.info("Initializing AI Trading Signal Bot...")
            
            # Validate config
            try:
                validate_config()
                logger.info("Configuration validated")
            except ValueError as e:
                logger.error(f"Configuration validation failed: {e}")
                raise
            
            # Initialize database
            try:
                logger.info("Database initialized")
            except Exception as e:
                logger.error(f"Database initialization failed: {e}")
                raise
            
            # Initialize market data engine
            try:
                await market_data_engine.initialize_exchanges()
                logger.info("Market data engine initialized")
            except Exception as e:
                logger.error(f"Market data engine initialization failed: {e}")
                logger.warning("Continuing with limited market data functionality")
            
            # Initialize telegram bot
            try:
                telegram_bot.set_dependencies(signal_engine, market_data_engine)
                bot_app = await telegram_bot.start()
                self.bot_application = bot_app
                logger.info("Telegram bot application initialized")

                # Set telegram bot for message queue
                message_queue.set_telegram_bot(telegram_bot)
                signal_tracker.set_telegram_bot(telegram_bot)
            except Exception as e:
                logger.error(f"Telegram bot initialization failed: {e}")
                raise
            
            # Add admin to database
            try:
                db.add_user(
                    telegram_id=int(TELEGRAM_ADMIN_ID),
                    is_admin=True
                )
                logger.info(f"Admin {TELEGRAM_ADMIN_ID} added to database")
            except Exception as e:
                logger.error(f"Failed to add admin to database: {e}")
            
            logger.info("All components initialized successfully")
            return bot_app
        except Exception as e:
            logger.error(f"Error during initialization: {e}")
            raise
    
    async def signal_tracking_loop(self):
        """Loop theo dõi tín hiệu (TP/SL)"""
        logger.info("Starting signal tracking loop")
        while self.running:
            try:
                await signal_tracker.monitoring_loop()
                await async_sleep(60)
            except Exception as e:
                logger.error(f"Error in signal tracking loop: {e}")
                await async_sleep(30)
    
    async def cache_cleanup_loop(self):
        """Loop cleanup cache"""
        logger.info("Starting cache cleanup loop")
        while self.running:
            try:
                cache_manager.cleanup_expired()
                await async_sleep(300)  # Every 5 minutes
            except Exception as e:
                logger.error(f"Error in cache cleanup loop: {e}")
                await async_sleep(60)

    async def health_monitor_loop(self):
        """Loop giám sát health của background tasks"""
        logger.info("Starting health monitor loop")

        last_signal_time = datetime.now()
        last_market_update_time = datetime.now()

        while not self.shutdown_event.is_set():
            try:
                current_time = datetime.now()

                # Check if market data is updating
                try:
                    test_symbol = SYMBOLS[0] if SYMBOLS else None
                    if test_symbol:
                        await market_data_engine.get_symbol_data(test_symbol)
                        last_market_update_time = current_time
                        logger.debug("Market data health check passed")
                except Exception as e:
                    logger.error(f"Market data health check failed: {e}")

                # Check time since last signal
                time_since_last_signal = (current_time - last_signal_time).total_seconds()
                if time_since_last_signal > 43200:  # 12 hours
                    logger.warning(f"No signal generated for {time_since_last_signal/3600:.1f} hours. Diagnosing...")

                    # Check for active signals
                    active_signals = []
                    for symbol in SYMBOLS:
                        active = db.get_active_signal(symbol)
                        if active:
                            active_signals.append(symbol)

                    if active_signals:
                        logger.info(f"Active signals locked for: {active_signals}. No new signals due to signal lock.")
                    else:
                        logger.warning("No active signals but no new signals generated. Checking AI analysis...")

                        # Test AI analysis
                        try:
                            test_symbol = SYMBOLS[0] if SYMBOLS else None
                            if test_symbol:
                                test_analysis = await ai_engine.analyze(
                                    test_symbol,
                                    market_data_engine,
                                    smart_money_tracker,
                                    news_engine
                                )
                                logger.info(f"AI analysis test for {test_symbol}: Action={test_analysis.get('action')}, Score={test_analysis.get('ai_score')}")
                        except Exception as e:
                            logger.error(f"AI analysis test failed: {e}")

                # Update last signal time if a signal was sent
                recent_signals = db.get_recent_signals(limit=1)
                if recent_signals:
                    last_signal_time = datetime.now()

                await async_sleep(3600)  # Check every hour
            except Exception as e:
                logger.error(f"Error in health monitor loop: {e}")
                await async_sleep(30)

    async def reporting_loop(self):
        """Loop báo cáo tự động"""
        logger.info("Starting reporting loop")
        await reporting_manager.reporting_loop(telegram_bot)
    
    async def market_data_loop(self):
        """Loop quét dữ liệu thị trường"""
        logger.info("Starting market data loop")

        while not self.shutdown_event.is_set():
            try:
                for symbol in SYMBOLS:
                    try:
                        # Lấy dữ liệu thị trường (sử dụng cache để tránh spam API)
                        await market_data_engine.get_symbol_data(symbol)

                        # Lưu vào database (ticker đã được cache trong get_symbol_data)
                        ticker = await market_data_engine.get_ticker(symbol)
                        if ticker:
                            db.save_market_data(
                                symbol=symbol,
                                data_type='ticker',
                                data_value=ticker
                            )

                        logger.debug(f"Market data updated for {symbol}")
                    except Exception as e:
                        logger.error(f"Error updating market data for {symbol}: {e}")

                await async_sleep(MARKET_DATA_INTERVAL)
            except Exception as e:
                logger.error(f"Error in market data loop: {e}")
                await async_sleep(10)  # Wait before retry
    
    async def news_loop(self):
        """Loop cập nhật tin tức"""
        logger.info("Starting news loop")
        
        while not self.shutdown_event.is_set():
            try:
                await news_engine.update_news()
                await news_engine.fetch_economic_calendar()
                logger.info("News updated")
                
                await async_sleep(NEWS_CHECK_INTERVAL)
            except Exception as e:
                logger.error(f"Error in news loop: {e}")
                await async_sleep(30)
    
    async def analysis_loop(self):
        """Loop phân tích AI"""
        logger.info("Starting AI analysis loop")

        signals_generated_this_cycle = 0

        while not self.shutdown_event.is_set():
            try:
                signals_generated_this_cycle = 0
                for symbol in SYMBOLS:
                    try:
                        # Phân tích AI
                        analysis = await ai_engine.analyze(
                            symbol,
                            market_data_engine,
                            smart_money_tracker,
                            news_engine
                        )

                        # Lưu AI log
                        db.save_ai_log(
                            symbol=symbol,
                            analysis_data=analysis,
                            decision=analysis.get('action'),
                            ai_score=analysis.get('ai_score'),
                            confidence=analysis.get('confidence')
                        )

                        # Log diagnostics for why signal was not generated
                        action = analysis.get('action')
                        ai_score = analysis.get('ai_score', 0)
                        confidence = analysis.get('confidence', 0)

                        if action == 'WAIT':
                            from core.config import clean_symbol
                            display_symbol = clean_symbol(symbol)
                            logger.info(f"No signal for {display_symbol}: AI Score {ai_score} < threshold (reason: {analysis.get('reasons', ['Unknown'])})")

                        # Nếu có tín hiệu, tạo và gửi
                        if analysis.get('action') in ['LONG', 'SHORT']:
                            signal = await signal_engine.create_signal(analysis)
                            if signal and signal.get('message'):
                                # Gửi tín hiệu qua Telegram với chart
                                chart_path = signal.get('chart_path')
                                await telegram_bot.send_signal(signal['message'], chart_path)
                                logger.info(f"Signal sent for {symbol}")
                                signals_generated_this_cycle += 1
                            else:
                                logger.warning(f"Signal creation failed for {symbol} despite valid analysis")

                        logger.debug(f"AI analysis completed for {symbol}")
                    except Exception as e:
                        logger.error(f"Error analyzing {symbol}: {e}")

                # Log if no signals were generated in this cycle
                if signals_generated_this_cycle == 0:
                    logger.info("No high-quality trading setup found in this analysis cycle")

                await async_sleep(AI_UPDATE_INTERVAL)
            except Exception as e:
                logger.error(f"Error in analysis loop: {e}")
                await async_sleep(30)
    
    async def smart_money_loop(self):
        """Loop theo dõi Smart Money"""
        logger.info("Starting smart money loop")

        while not self.shutdown_event.is_set():
            try:
                for symbol in SYMBOLS:
                    try:
                        await smart_money_tracker.analyze_smart_money_confluence(
                            symbol,
                            market_data_engine
                        )
                        logger.debug(f"Smart money analysis completed for {symbol}")
                    except Exception as e:
                        logger.error(f"Error in smart money analysis for {symbol}: {e}")

                await async_sleep(120)  # Every 2 minutes
            except Exception as e:
                logger.error(f"Error in smart money loop: {e}")
                await async_sleep(30)
    
    def run_flask_server(self):
        """Chạy Flask server cho health check và Telegram webhook"""
        try:
            # Create Flask app locally to avoid module-level import issues
            from flask import Flask, request
            app = Flask(__name__)

            @app.route('/')
            def health_check():
                """Health check endpoint cho Render"""
                return {
                    'status': 'running',
                    'timestamp': datetime.now().isoformat(),
                    'bot_status': 'active'
                }

            @app.route('/health')
            def health():
                """Simple health endpoint"""
                return 'OK', 200

            @app.route('/webhook', methods=['POST'])
            def webhook():
                """Telegram webhook endpoint - Use proper python-telegram-bot v22 webhook handling"""
                print(f"[WEBHOOK] Request received at {datetime.now().isoformat()}")

                if telegram_bot.application:
                    from telegram import Update
                    import asyncio
                    import logging

                    logger = logging.getLogger(__name__)
                    timestamp = datetime.now().isoformat()

                    # Get update from request
                    update_json = request.get_json(force=True)
                    print(f"[WEBHOOK] Update JSON: {update_json}")

                    # Extract update_id, user_id and text for logging
                    update_id = None
                    user_id = None
                    text = None
                    if update_json:
                        update_id = update_json.get('update_id')
                        message = update_json.get('message', {})
                        user_id = message.get('from', {}).get('id')
                        text = message.get('text')

                    print(f"[WEBHOOK RECEIVED] update_id={update_id}, user_id={user_id}, text={text}, timestamp={timestamp}")
                    logger.info(f"[WEBHOOK RECEIVED] update_id={update_id}, user_id={user_id}, text={text}, timestamp={timestamp}")
                    logger.info(f"[WEBHOOK] Full update JSON: {update_json}")

                    # Put update into application's update_queue
                    # This ensures proper handler routing through the dispatcher
                    try:
                        update = Update.de_json(update_json, telegram_bot.application.bot)
                        telegram_bot.application.update_queue.put_nowait(update)
                        print(f"[WEBHOOK] Update put into queue successfully: update_id={update_id}")
                        logger.info(f"[WEBHOOK] Update put into queue successfully: update_id={update_id}")
                    except Exception as e:
                        print(f"[WEBHOOK ERROR] update_id={update_id}, error={e}")
                        logger.error(f"[WEBHOOK ERROR] update_id={update_id}, error={e}", exc_info=True)

                    return 'OK', 200
                else:
                    print("[WEBHOOK ERROR] Bot not initialized")
                    logger.error("[WEBHOOK ERROR] Bot not initialized")
                    return 'Bot not initialized', 503

            # Run Flask in a separate thread
            import threading

            def run_flask():
                app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False, threaded=True)

            flask_thread = threading.Thread(target=run_flask, daemon=True)
            flask_thread.start()
            logger.info(f"Flask server started on port {PORT}")
        except Exception as e:
            logger.error(f"Error starting Flask server: {e}")
    
    async def run(self):
        """Chạy toàn bộ ứng dụng"""
        try:
            logger.info("=" * 50)
            logger.info("AI Trading Signal Bot Starting...")
            logger.info("=" * 50)
            logger.info(f"AI Score Threshold: {AI_SCORE_THRESHOLD}")
            logger.info(f"Min Confidence: {MIN_CONFIDENCE}")
            logger.info(f"Trading Symbols: {', '.join(SYMBOLS)}")

            # Initialize components
            bot_app = await self.initialize()

            # Start Flask server
            self.run_flask_server()

            # Start Telegram bot
            self.running = True
            logger.info("Telegram bot started with webhook")

            # Create tasks
            self.tasks = [
                asyncio.create_task(self.market_data_loop()),
                asyncio.create_task(self.news_loop()),
                asyncio.create_task(self.analysis_loop()),
                asyncio.create_task(self.smart_money_loop()),
                asyncio.create_task(self.signal_tracking_loop()),
                asyncio.create_task(self.cache_cleanup_loop()),
                asyncio.create_task(self.health_monitor_loop()),
                asyncio.create_task(self.reporting_loop())
            ]

            logger.info("All loops started successfully")
            logger.info("Bot is now running 24/7")

            # Wait for shutdown
            await self.shutdown_event.wait()

        except Exception as e:
            logger.error(f"Error in main run loop: {e}")
            raise
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """Tắt ứng dụng"""
        logger.info("Shutting down AI Trading Signal Bot...")
        self.running = False
        self.shutdown_event.set()

        # Cancel all tasks
        for task in self.tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"Error cancelling task: {e}")

        # Stop and shutdown Telegram bot application
        try:
            await telegram_bot.stop()
            logger.info("Telegram bot stopped")
        except Exception as e:
            logger.error(f"Error stopping Telegram bot: {e}")

        # Close market data connections
        try:
            await market_data_engine.close()
        except Exception as e:
            logger.error(f"Error closing market data connections: {e}")

        logger.info("Bot shutdown complete")


def signal_handler(signum, frame):
    """Xử lý signal shutdown"""
    logger.info(f"Received signal {signum}, shutting down...")
    sys.exit(0)


async def main():
    """Main entry point"""
    # Setup logging
    setup_logging()
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create and run app
    bot_app = TradingBotApp()
    
    try:
        await bot_app.run()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise
    finally:
        await bot_app.shutdown()


if __name__ == "__main__":
    # Run the bot
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        sys.exit(1)
