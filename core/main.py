"""
Main Application cho AI Trading Signal Bot
Khởi động và quản lý toàn bộ hệ thống
"""
import asyncio
import logging
import signal
import sys
import os
import threading
import traceback
import faulthandler
from datetime import datetime
from core.config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_ID,
    MARKET_DATA_INTERVAL, NEWS_CHECK_INTERVAL, AI_UPDATE_INTERVAL,
    validate_config, PORT, AI_SCORE_THRESHOLD, MIN_CONFIDENCE
)

logger = logging.getLogger(__name__)

# Enable faulthandler to capture stack traces on crashes
faulthandler.enable()
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
        # Store reference to the main event loop for thread-safe webhook calls
        self.event_loop = None
        # Safe timing tracking - dictionary keyed by update_id
        self.queue_put_timestamps = {}
        # Stack trace tracking for blocking detection
        self.queue_put_stack_traces = {}
        # Dynamic watchlist loaded from database
        self.active_symbols = []

    def set_queue_timestamps(self, queue_timestamps):
        """Set the safe timing tracking dictionary"""
        self.queue_put_timestamps = queue_timestamps

    def set_queue_stack_traces(self, queue_stack_traces):
        """Set the stack trace tracking dictionary for blocking detection"""
        self.queue_put_stack_traces = queue_stack_traces

    def capture_event_loop_stack(self):
        """Capture current stack trace of event loop thread for blocking detection"""
        import sys
        import traceback
        stack = []
        for frame in sys._current_frames().values():
            stack_trace = traceback.format_stack(frame)
            stack.extend(stack_trace)
        return ''.join(stack)

    async def load_watchlist(self):
        """Load watchlist from database"""
        try:
            self.active_symbols = await db.get_watchlist_async()
            logger.info(f"[WATCHLIST] Loaded {len(self.active_symbols)} symbols from database: {self.active_symbols}")
            return self.active_symbols
        except Exception as e:
            logger.error(f"[WATCHLIST] Error loading watchlist: {e}")
            self.active_symbols = []
            return []

    async def reload_watchlist(self):
        """Reload watchlist from database immediately (called after add/remove)"""
        try:
            old_symbols = list(self.active_symbols)
            self.active_symbols = await db.get_watchlist_async()
            logger.info(f"[WATCHLIST] Reloaded watchlist: {old_symbols} -> {self.active_symbols}")
            return self.active_symbols
        except Exception as e:
            logger.error(f"[WATCHLIST] Error reloading watchlist: {e}")
            return self.active_symbols
    
    async def initialize(self):
        """Khởi tạo tất cả các components"""
        try:
            logger.info("Initializing AI Trading Signal Bot...")

            # Store reference to the current event loop for thread-safe webhook calls
            self.event_loop = asyncio.get_event_loop()
            logger.info(f"Event loop reference stored: {id(self.event_loop)}")

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
                # Pass timing tracking dictionary to telegram bot
                telegram_bot.set_queue_timestamps(self.queue_put_timestamps)
                # Pass stack trace tracking dictionary to telegram bot
                telegram_bot.set_queue_stack_traces(self.queue_put_stack_traces)
                # Pass TradingBotApp reference for watchlist synchronization
                telegram_bot.set_bot_app(self)
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
                await db.add_user_async(
                    telegram_id=int(TELEGRAM_ADMIN_ID),
                    is_admin=True
                )
                logger.info(f"Admin {TELEGRAM_ADMIN_ID} added to database")
            except Exception as e:
                logger.error(f"Failed to add admin to database: {e}")

            # Load watchlist from database
            await self.load_watchlist()

            logger.info("All components initialized successfully")
            return bot_app
        except Exception as e:
            logger.error(f"Error during initialization: {e}")
            raise
    
    async def signal_tracking_loop(self):
        """Loop theo dõi tín hiệu (TP/SL)"""
        while self.running:
            try:
                await signal_tracker.monitoring_loop()
                await async_sleep(60)
            except Exception as e:
                logger.error(f"Error in signal tracking loop: {e}")
                await async_sleep(30)
    
    async def cache_cleanup_loop(self):
        """Loop cleanup cache"""
        while self.running:
            try:
                cache_manager.cleanup_expired()
                await async_sleep(300)  # Every 5 minutes
            except Exception as e:
                logger.error(f"Error in cache cleanup loop: {e}")
                await async_sleep(60)

    async def health_monitor_loop(self):
        """Loop giám sát health của background tasks"""
        import time
        last_signal_time = datetime.now()
        last_market_update_time = datetime.now()

        while not self.shutdown_event.is_set():
            try:
                loop_start = time.time()
                current_time = datetime.now()

                # Check if market data is updating - use lightweight ticker check instead of full symbol data
                try:
                    test_symbol = self.active_symbols[0] if self.active_symbols else None
                    if test_symbol:
                        # Use lightweight ticker check instead of full symbol data to reduce blocking
                        ticker = await market_data_engine.get_ticker(test_symbol)
                        if ticker:
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
                    for symbol in self.active_symbols:
                        active = await db.get_active_signal_async(symbol) if hasattr(db, 'get_active_signal_async') else db.get_active_signal(symbol)
                        if active:
                            active_signals.append(symbol)

                    if active_signals:
                        logger.info(f"Active signals locked for: {active_signals}. No new signals due to signal lock.")
                    else:
                        logger.warning("No active signals but no new signals generated. Checking AI analysis...")

                        # Test AI analysis - skip full analysis to avoid blocking
                        try:
                            test_symbol = self.active_symbols[0] if self.active_symbols else None
                            if test_symbol:
                                # Use lightweight ticker check instead of full AI analysis
                                ticker = await market_data_engine.get_ticker(test_symbol)
                                if ticker:
                                    logger.info(f"AI analysis test for {test_symbol}: ticker available, price={ticker.get('last')}")
                                else:
                                    logger.warning(f"AI analysis test for {test_symbol}: ticker unavailable")
                        except Exception as e:
                            logger.error(f"AI analysis test failed: {e}")

                # Update last signal time if a signal was sent
                recent_signals = await db.get_recent_signals_async(limit=1) if hasattr(db, 'get_recent_signals_async') else db.get_recent_signals(limit=1)
                if recent_signals:
                    last_signal_time = datetime.now()

                loop_duration_ms = (time.time() - loop_start) * 1000
                logger.info(f"[HEALTH MONITOR] duration_ms={loop_duration_ms:.2f}")
                await async_sleep(3600)  # Check every hour
            except Exception as e:
                logger.error(f"Error in health monitor loop: {e}")
                await async_sleep(30)

    async def reporting_loop(self):
        """Loop báo cáo tự động"""
        await reporting_manager.reporting_loop(telegram_bot)
    
    async def market_data_loop(self):
        """Loop quét dữ liệu thị trường"""
        import time
        while not self.shutdown_event.is_set():
            try:
                loop_start = time.time()
                for symbol in self.active_symbols:
                    try:
                        # Lấy dữ liệu thị trường (sử dụng cache để tránh spam API)
                        symbol_data = await market_data_engine.get_symbol_data(symbol)

                        # Lưu vào database (ticker đã được cache trong get_symbol_data, không cần gọi lại)
                        ticker = symbol_data.get('ticker')
                        if ticker:
                            await db.save_market_data_async(
                                symbol=symbol,
                                data_type='ticker',
                                data_value=ticker
                            )

                        logger.debug(f"Market data updated for {symbol}")
                    except Exception as e:
                        logger.error(f"Error updating market data for {symbol}: {e}")

                loop_duration_ms = (time.time() - loop_start) * 1000
                logger.info(f"[MARKET DATA LOOP] duration_ms={loop_duration_ms:.2f}")
                await async_sleep(MARKET_DATA_INTERVAL)
            except Exception as e:
                logger.error(f"Error in market data loop: {e}")
                await async_sleep(10)  # Wait before retry

    async def news_loop(self):
        """Loop cập nhật tin tức"""
        import time
        while not self.shutdown_event.is_set():
            try:
                loop_start = time.time()
                await news_engine.update_news()
                await news_engine.fetch_economic_calendar()
                logger.info("News updated")

                loop_duration_ms = (time.time() - loop_start) * 1000
                logger.info(f"[NEWS LOOP] duration_ms={loop_duration_ms:.2f}")
                await async_sleep(NEWS_CHECK_INTERVAL)
            except Exception as e:
                logger.error(f"Error in news loop: {e}")
                await async_sleep(30)

    async def analysis_loop(self):
        """Loop phân tích AI"""
        import time
        signals_generated_this_cycle = 0

        logger.info("[ANALYSIS LOOP] started")
        logger.info(f"[ANALYSIS LOOP] active_symbols={self.active_symbols}")

        if not self.active_symbols:
            logger.warning("[WATCHLIST] No active symbols - analysis loop will run but process nothing")

        cycle_count = 0
        while not self.shutdown_event.is_set():
            try:
                loop_start = time.time()
                signals_generated_this_cycle = 0

                # Reload watchlist every 10 cycles (30 minutes) to pick up Telegram changes
                cycle_count += 1
                if cycle_count % 10 == 0:
                    await self.load_watchlist()
                    logger.info(f"[ANALYSIS LOOP] reloaded watchlist at cycle {cycle_count}")

                logger.info(f"[ANALYSIS LOOP] cycle_start, active_symbols={self.active_symbols}")
                for symbol in self.active_symbols:
                    try:
                        symbol_start = time.time()
                        # Phân tích AI
                        analysis = await ai_engine.analyze(
                            symbol,
                            market_data_engine,
                            smart_money_tracker,
                            news_engine
                        )

                        # Lưu AI log
                        await db.save_ai_log_async(
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

                        # Nếu AI có tín hiệu, áp dụng bộ lọc Gann + EMA + ATR
                        if analysis.get('action') in ['LONG', 'SHORT']:
                            from analysis.gann_engine import gann_engine
                            filter_result = await signal_engine.filter_signal(analysis, market_data_engine, gann_engine)
                            filtered_action = filter_result.get('action')
                            filter_reason = filter_result.get('reason')

                            # Chỉ tạo signal nếu filter cho phép LONG hoặc SHORT
                            if filtered_action in ['LONG', 'SHORT']:
                                # Update analysis with filtered action
                                analysis['action'] = filtered_action
                                analysis['reasons'] = analysis.get('reasons', []) + [f'Filter: {filter_reason}']

                                # Pass pre-fetched data to avoid duplicate fetches
                                symbol_data = filter_result.get('symbol_data')
                                gann_analysis = filter_result.get('gann_analysis')
                                signal = await signal_engine.create_signal(analysis, symbol_data, gann_analysis)

                                if signal and signal.get('message'):
                                    # Gửi tín hiệu qua Telegram với chart
                                    chart_path = signal.get('chart_path')
                                    await telegram_bot.send_signal(signal['message'], chart_path)
                                    logger.info(f"Signal sent for {symbol}")
                                    signals_generated_this_cycle += 1
                                else:
                                    logger.warning(f"Signal creation failed for {symbol} despite valid filter")
                            else:
                                logger.info(f"Signal filtered for {symbol}: {filter_reason}")

                        symbol_duration_ms = (time.time() - symbol_start) * 1000
                        logger.info(f"[ANALYSIS SYMBOL] symbol={symbol}, duration_ms={symbol_duration_ms:.2f}")
                        logger.debug(f"AI analysis completed for {symbol}")
                    except Exception as e:
                        logger.error(f"Error analyzing {symbol}: {e}")

                # Log if no signals were generated in this cycle
                if signals_generated_this_cycle == 0:
                    logger.info("No high-quality trading setup found in this analysis cycle")

                loop_duration_ms = (time.time() - loop_start) * 1000
                logger.info(f"[ANALYSIS LOOP] cycle_complete, duration_ms={loop_duration_ms:.2f}")
                await async_sleep(AI_UPDATE_INTERVAL)
            except Exception as e:
                logger.error(f"[ANALYSIS LOOP ERROR] {e}", exc_info=True)
                await async_sleep(30)

    async def smart_money_loop(self):
        """Loop theo dõi Smart Money"""
        import time
        while not self.shutdown_event.is_set():
            try:
                loop_start = time.time()
                for symbol in self.active_symbols:
                    try:
                        symbol_start = time.time()
                        await smart_money_tracker.analyze_smart_money_confluence(
                            symbol,
                            market_data_engine
                        )
                        symbol_duration_ms = (time.time() - symbol_start) * 1000
                        logger.info(f"[SMART MONEY SYMBOL] symbol={symbol}, duration_ms={symbol_duration_ms:.2f}")
                        logger.debug(f"Smart money analysis completed for {symbol}")
                    except Exception as e:
                        logger.error(f"Error in smart money analysis for {symbol}: {e}")

                loop_duration_ms = (time.time() - loop_start) * 1000
                logger.info(f"[SMART MONEY LOOP] duration_ms={loop_duration_ms:.2f}")
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
                """Telegram webhook endpoint - Comprehensive trace logging"""
                import asyncio
                import logging
                import traceback
                from telegram import Update

                # Get current event loop ID
                try:
                    event_loop = asyncio.get_event_loop()
                    event_loop_id = id(event_loop)
                except RuntimeError:
                    event_loop = None
                    event_loop_id = "NO_LOOP"

                if telegram_bot.application:
                    try:
                        # Get update from request
                        update_json = request.get_json(force=True)
                        update_id = update_json.get('update_id') if update_json else None

                        # Put update into application's update_queue using thread-safe method
                        try:
                            queue_put_timestamp = datetime.now().isoformat()
                            update = Update.de_json(update_json, telegram_bot.application.bot)
                            # Store queue put timestamp in safe dictionary keyed by update_id
                            self.queue_put_timestamps[update_id] = queue_put_timestamp
                            # Capture stack trace at queue put time for blocking detection
                            self.queue_put_stack_traces[update_id] = self.capture_event_loop_stack()
                            # Clean up old entries (keep last 1000 to prevent memory leaks)
                            if len(self.queue_put_timestamps) > 1000:
                                # Remove oldest entries
                                oldest_keys = list(self.queue_put_timestamps.keys())[:100]
                                for key in oldest_keys:
                                    del self.queue_put_timestamps[key]
                                    if key in self.queue_put_stack_traces:
                                        del self.queue_put_stack_traces[key]
                            # Use thread-safe method to put update into queue
                            # Use the stored event loop reference from the main application
                            loop = self.event_loop
                            if loop and not loop.is_closed():
                                # Schedule the queue put on the correct event loop
                                loop.call_soon_threadsafe(telegram_bot.application.update_queue.put_nowait, update)
                                logger.info(f"[WEBHOOK QUEUE PUT] update_id={update_id}")
                            else:
                                logger.error(f"[WEBHOOK QUEUE PUT] update_id={update_id}, error=Event loop not available")
                                return 'Error', 503
                        except Exception as e:
                            logger.error(f"Webhook queue put error: update_id={update_id}, error={e}", exc_info=True)
                            # Return 200 to prevent Telegram from retrying, even if queue put failed
                            # Handler errors will be logged separately by the Telegram Application
                            return 'OK', 200

                        return 'OK', 200

                    except Exception as e:
                        logger.error(f"Webhook error: {e}", exc_info=True)
                        return 'Error', 500
                else:
                    logger.error("Bot not initialized for webhook")
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
            logger.info(f"Trading Symbols: {', '.join(self.active_symbols) if self.active_symbols else 'None (empty watchlist)'}")

            # Initialize components
            bot_app = await self.initialize()

            # Enable asyncio debug mode for blocking detection
            loop = asyncio.get_event_loop()
            loop.set_debug(True)
            loop.slow_callback_duration = 0.1  # Log callbacks taking >100ms
            logger.info("Asyncio debug mode enabled - slow_callback_duration=0.1s")

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
