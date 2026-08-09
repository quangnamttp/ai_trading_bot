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
        """Loop theo dõi tín hiệu (TP/SL) with event loop trace"""
        import asyncio
        from datetime import datetime

        try:
            event_loop = asyncio.get_event_loop()
            event_loop_id = id(event_loop)
        except RuntimeError:
            event_loop = None
            event_loop_id = "NO_LOOP"

        logger.info(f"[TASK START] task_name=signal_tracking_loop, event_loop_id={event_loop_id}, timestamp={datetime.now().isoformat()}")

        while self.running:
            try:
                loop_start = datetime.now().isoformat()
                logger.info(f"[TASK ITERATION] task_name=signal_tracking_loop, timestamp={loop_start}, event_loop_id={event_loop_id}")
                await signal_tracker.monitoring_loop()
                loop_end = datetime.now().isoformat()
                duration_ms = (datetime.fromisoformat(loop_end) - datetime.fromisoformat(loop_start)).total_seconds() * 1000
                logger.info(f"[TASK ITERATION COMPLETE] task_name=signal_tracking_loop, duration_ms={duration_ms:.2f}, event_loop_id={event_loop_id}")
                if duration_ms > 1000:
                    logger.warning(f"[SLOW TASK] task_name=signal_tracking_loop, duration_ms={duration_ms:.2f}, event_loop_id={event_loop_id}")
                await async_sleep(60)
            except Exception as e:
                logger.error(f"Error in signal tracking loop: {e}")
                await async_sleep(30)
    
    async def cache_cleanup_loop(self):
        """Loop cleanup cache with event loop trace"""
        import asyncio
        from datetime import datetime

        try:
            event_loop = asyncio.get_event_loop()
            event_loop_id = id(event_loop)
        except RuntimeError:
            event_loop = None
            event_loop_id = "NO_LOOP"

        logger.info(f"[TASK START] task_name=cache_cleanup_loop, event_loop_id={event_loop_id}, timestamp={datetime.now().isoformat()}")

        while self.running:
            try:
                loop_start = datetime.now().isoformat()
                logger.info(f"[TASK ITERATION] task_name=cache_cleanup_loop, timestamp={loop_start}, event_loop_id={event_loop_id}")
                cache_manager.cleanup_expired()
                loop_end = datetime.now().isoformat()
                duration_ms = (datetime.fromisoformat(loop_end) - datetime.fromisoformat(loop_start)).total_seconds() * 1000
                logger.info(f"[TASK ITERATION COMPLETE] task_name=cache_cleanup_loop, duration_ms={duration_ms:.2f}, event_loop_id={event_loop_id}")
                if duration_ms > 1000:
                    logger.warning(f"[SLOW TASK] task_name=cache_cleanup_loop, duration_ms={duration_ms:.2f}, event_loop_id={event_loop_id}")
                await async_sleep(300)  # Every 5 minutes
            except Exception as e:
                logger.error(f"Error in cache cleanup loop: {e}")
                await async_sleep(60)

    async def health_monitor_loop(self):
        """Loop giám sát health của background tasks with event loop trace"""
        import asyncio
        from datetime import datetime

        try:
            event_loop = asyncio.get_event_loop()
            event_loop_id = id(event_loop)
        except RuntimeError:
            event_loop = None
            event_loop_id = "NO_LOOP"

        logger.info(f"[TASK START] task_name=health_monitor_loop, event_loop_id={event_loop_id}, timestamp={datetime.now().isoformat()}")

        last_signal_time = datetime.now()
        last_market_update_time = datetime.now()

        while not self.shutdown_event.is_set():
            try:
                loop_start = datetime.now().isoformat()
                logger.info(f"[TASK ITERATION] task_name=health_monitor_loop, timestamp={loop_start}, event_loop_id={event_loop_id}")
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

                loop_end = datetime.now().isoformat()
                duration_ms = (datetime.fromisoformat(loop_end) - datetime.fromisoformat(loop_start)).total_seconds() * 1000
                logger.info(f"[TASK ITERATION COMPLETE] task_name=health_monitor_loop, duration_ms={duration_ms:.2f}, event_loop_id={event_loop_id}")
                if duration_ms > 1000:
                    logger.warning(f"[SLOW TASK] task_name=health_monitor_loop, duration_ms={duration_ms:.2f}, event_loop_id={event_loop_id}")

                await async_sleep(3600)  # Check every hour
            except Exception as e:
                logger.error(f"Error in health monitor loop: {e}")
                await async_sleep(30)

    async def reporting_loop(self):
        """Loop báo cáo tự động with event loop trace"""
        import asyncio
        from datetime import datetime

        try:
            event_loop = asyncio.get_event_loop()
            event_loop_id = id(event_loop)
        except RuntimeError:
            event_loop = None
            event_loop_id = "NO_LOOP"

        logger.info(f"[TASK START] task_name=reporting_loop, event_loop_id={event_loop_id}, timestamp={datetime.now().isoformat()}")

        await reporting_manager.reporting_loop(telegram_bot)
    
    async def market_data_loop(self):
        """Loop quét dữ liệu thị trường with event loop trace"""
        import asyncio
        from datetime import datetime

        try:
            event_loop = asyncio.get_event_loop()
            event_loop_id = id(event_loop)
        except RuntimeError:
            event_loop = None
            event_loop_id = "NO_LOOP"

        logger.info(f"[TASK START] task_name=market_data_loop, event_loop_id={event_loop_id}, timestamp={datetime.now().isoformat()}")

        while not self.shutdown_event.is_set():
            try:
                loop_start = datetime.now().isoformat()
                logger.info(f"[TASK ITERATION] task_name=market_data_loop, timestamp={loop_start}, event_loop_id={event_loop_id}")
                for symbol in SYMBOLS:
                    try:
                        # Lấy dữ liệu thị trường (sử dụng cache để tránh spam API)
                        await market_data_engine.get_symbol_data(symbol)

                        # Lưu vào database (ticker đã được cache trong get_symbol_data)
                        ticker = await market_data_engine.get_ticker(symbol)
                        if ticker:
                            await db.save_market_data_async(
                                symbol=symbol,
                                data_type='ticker',
                                data_value=ticker
                            )

                        logger.debug(f"Market data updated for {symbol}")
                    except Exception as e:
                        logger.error(f"Error updating market data for {symbol}: {e}")

                loop_end = datetime.now().isoformat()
                duration_ms = (datetime.fromisoformat(loop_end) - datetime.fromisoformat(loop_start)).total_seconds() * 1000
                logger.info(f"[TASK ITERATION COMPLETE] task_name=market_data_loop, duration_ms={duration_ms:.2f}, event_loop_id={event_loop_id}")
                if duration_ms > 1000:
                    logger.warning(f"[SLOW TASK] task_name=market_data_loop, duration_ms={duration_ms:.2f}, event_loop_id={event_loop_id}")
                if duration_ms > 5000:
                    logger.error(f"[BLOCKING WARNING] task_name=market_data_loop, duration_ms={duration_ms:.2f}, event_loop_id={event_loop_id}")

                await async_sleep(MARKET_DATA_INTERVAL)
            except Exception as e:
                logger.error(f"Error in market data loop: {e}")
                await async_sleep(10)  # Wait before retry
    
    async def news_loop(self):
        """Loop cập nhật tin tức with event loop trace"""
        import asyncio
        from datetime import datetime

        try:
            event_loop = asyncio.get_event_loop()
            event_loop_id = id(event_loop)
        except RuntimeError:
            event_loop = None
            event_loop_id = "NO_LOOP"

        logger.info(f"[TASK START] task_name=news_loop, event_loop_id={event_loop_id}, timestamp={datetime.now().isoformat()}")

        while not self.shutdown_event.is_set():
            try:
                loop_start = datetime.now().isoformat()
                logger.info(f"[TASK ITERATION] task_name=news_loop, timestamp={loop_start}, event_loop_id={event_loop_id}")
                await news_engine.update_news()
                await news_engine.fetch_economic_calendar()
                logger.info("News updated")

                loop_end = datetime.now().isoformat()
                duration_ms = (datetime.fromisoformat(loop_end) - datetime.fromisoformat(loop_start)).total_seconds() * 1000
                logger.info(f"[TASK ITERATION COMPLETE] task_name=news_loop, duration_ms={duration_ms:.2f}, event_loop_id={event_loop_id}")
                if duration_ms > 1000:
                    logger.warning(f"[SLOW TASK] task_name=news_loop, duration_ms={duration_ms:.2f}, event_loop_id={event_loop_id}")
                if duration_ms > 5000:
                    logger.error(f"[BLOCKING WARNING] task_name=news_loop, duration_ms={duration_ms:.2f}, event_loop_id={event_loop_id}")

                await async_sleep(NEWS_CHECK_INTERVAL)
            except Exception as e:
                logger.error(f"Error in news loop: {e}")
                await async_sleep(30)
    
    async def analysis_loop(self):
        """Loop phân tích AI with event loop trace"""
        import asyncio
        from datetime import datetime

        try:
            event_loop = asyncio.get_event_loop()
            event_loop_id = id(event_loop)
        except RuntimeError:
            event_loop = None
            event_loop_id = "NO_LOOP"

        logger.info(f"[TASK START] task_name=analysis_loop, event_loop_id={event_loop_id}, timestamp={datetime.now().isoformat()}")

        signals_generated_this_cycle = 0

        while not self.shutdown_event.is_set():
            try:
                loop_start = datetime.now().isoformat()
                logger.info(f"[TASK ITERATION] task_name=analysis_loop, timestamp={loop_start}, event_loop_id={event_loop_id}")
                signals_generated_this_cycle = 0
                for symbol in SYMBOLS:
                    try:
                        symbol_start = datetime.now().isoformat()
                        logger.info(f"[ANALYSIS SYMBOL START] symbol={symbol}, timestamp={symbol_start}, event_loop_id={event_loop_id}")

                        # Phân tích AI
                        analyze_start = datetime.now().isoformat()
                        logger.info(f"[AI ANALYZE START] symbol={symbol}, timestamp={analyze_start}, event_loop_id={event_loop_id}")
                        analysis = await ai_engine.analyze(
                            symbol,
                            market_data_engine,
                            smart_money_tracker,
                            news_engine
                        )
                        analyze_end = datetime.now().isoformat()
                        analyze_duration_ms = (datetime.fromisoformat(analyze_end) - datetime.fromisoformat(analyze_start)).total_seconds() * 1000
                        logger.info(f"[AI ANALYZE COMPLETE] symbol={symbol}, duration_ms={analyze_duration_ms:.2f}, event_loop_id={event_loop_id}")
                        if analyze_duration_ms > 1000:
                            logger.warning(f"[SLOW AI ANALYZE] symbol={symbol}, duration_ms={analyze_duration_ms:.2f}, event_loop_id={event_loop_id}")

                        # Lưu AI log
                        db_save_start = datetime.now().isoformat()
                        await db.save_ai_log_async(
                            symbol=symbol,
                            analysis_data=analysis,
                            decision=analysis.get('action'),
                            ai_score=analysis.get('ai_score'),
                            confidence=analysis.get('confidence')
                        )
                        db_save_end = datetime.now().isoformat()
                        db_save_duration_ms = (datetime.fromisoformat(db_save_end) - datetime.fromisoformat(db_save_start)).total_seconds() * 1000
                        logger.info(f"[DB SAVE AI LOG] symbol={symbol}, duration_ms={db_save_duration_ms:.2f}, event_loop_id={event_loop_id}")
                        if db_save_duration_ms > 1000:
                            logger.warning(f"[SLOW DB SAVE] symbol={symbol}, duration_ms={db_save_duration_ms:.2f}, event_loop_id={event_loop_id}")

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
                            signal_create_start = datetime.now().isoformat()
                            logger.info(f"[SIGNAL CREATE START] symbol={symbol}, timestamp={signal_create_start}, event_loop_id={event_loop_id}")
                            signal = await signal_engine.create_signal(analysis)
                            signal_create_end = datetime.now().isoformat()
                            signal_create_duration_ms = (datetime.fromisoformat(signal_create_end) - datetime.fromisoformat(signal_create_start)).total_seconds() * 1000
                            logger.info(f"[SIGNAL CREATE COMPLETE] symbol={symbol}, duration_ms={signal_create_duration_ms:.2f}, event_loop_id={event_loop_id}")
                            if signal_create_duration_ms > 1000:
                                logger.warning(f"[SLOW SIGNAL CREATE] symbol={symbol}, duration_ms={signal_create_duration_ms:.2f}, event_loop_id={event_loop_id}")

                            if signal and signal.get('message'):
                                # Gửi tín hiệu qua Telegram với chart
                                chart_path = signal.get('chart_path')
                                signal_send_start = datetime.now().isoformat()
                                logger.info(f"[SIGNAL SEND START] symbol={symbol}, timestamp={signal_send_start}, event_loop_id={event_loop_id}")
                                await telegram_bot.send_signal(signal['message'], chart_path)
                                signal_send_end = datetime.now().isoformat()
                                signal_send_duration_ms = (datetime.fromisoformat(signal_send_end) - datetime.fromisoformat(signal_send_start)).total_seconds() * 1000
                                logger.info(f"[SIGNAL SEND COMPLETE] symbol={symbol}, duration_ms={signal_send_duration_ms:.2f}, event_loop_id={event_loop_id}")
                                if signal_send_duration_ms > 1000:
                                    logger.warning(f"[SLOW SIGNAL SEND] symbol={symbol}, duration_ms={signal_send_duration_ms:.2f}, event_loop_id={event_loop_id}")
                                logger.info(f"Signal sent for {symbol}")
                                signals_generated_this_cycle += 1
                            else:
                                logger.warning(f"Signal creation failed for {symbol} despite valid analysis")

                        symbol_end = datetime.now().isoformat()
                        symbol_duration_ms = (datetime.fromisoformat(symbol_end) - datetime.fromisoformat(symbol_start)).total_seconds() * 1000
                        logger.info(f"[ANALYSIS SYMBOL COMPLETE] symbol={symbol}, duration_ms={symbol_duration_ms:.2f}, event_loop_id={event_loop_id}")
                        if symbol_duration_ms > 1000:
                            logger.warning(f"[SLOW SYMBOL ANALYSIS] symbol={symbol}, duration_ms={symbol_duration_ms:.2f}, event_loop_id={event_loop_id}")

                        logger.debug(f"AI analysis completed for {symbol}")
                    except Exception as e:
                        logger.error(f"Error analyzing {symbol}: {e}")

                # Log if no signals were generated in this cycle
                if signals_generated_this_cycle == 0:
                    logger.info("No high-quality trading setup found in this analysis cycle")

                loop_end = datetime.now().isoformat()
                duration_ms = (datetime.fromisoformat(loop_end) - datetime.fromisoformat(loop_start)).total_seconds() * 1000
                logger.info(f"[TASK ITERATION COMPLETE] task_name=analysis_loop, duration_ms={duration_ms:.2f}, event_loop_id={event_loop_id}")
                if duration_ms > 1000:
                    logger.warning(f"[SLOW TASK] task_name=analysis_loop, duration_ms={duration_ms:.2f}, event_loop_id={event_loop_id}")
                if duration_ms > 5000:
                    logger.error(f"[BLOCKING WARNING] task_name=analysis_loop, duration_ms={duration_ms:.2f}, event_loop_id={event_loop_id}")

                await async_sleep(AI_UPDATE_INTERVAL)
            except Exception as e:
                logger.error(f"Error in analysis loop: {e}")
                await async_sleep(30)
    
    async def smart_money_loop(self):
        """Loop theo dõi Smart Money with event loop trace"""
        import asyncio
        from datetime import datetime

        try:
            event_loop = asyncio.get_event_loop()
            event_loop_id = id(event_loop)
        except RuntimeError:
            event_loop = None
            event_loop_id = "NO_LOOP"

        logger.info(f"[TASK START] task_name=smart_money_loop, event_loop_id={event_loop_id}, timestamp={datetime.now().isoformat()}")

        while not self.shutdown_event.is_set():
            try:
                loop_start = datetime.now().isoformat()
                logger.info(f"[TASK ITERATION] task_name=smart_money_loop, timestamp={loop_start}, event_loop_id={event_loop_id}")
                for symbol in SYMBOLS:
                    try:
                        await smart_money_tracker.analyze_smart_money_confluence(
                            symbol,
                            market_data_engine
                        )
                        logger.debug(f"Smart money analysis completed for {symbol}")
                    except Exception as e:
                        logger.error(f"Error in smart money analysis for {symbol}: {e}")

                loop_end = datetime.now().isoformat()
                duration_ms = (datetime.fromisoformat(loop_end) - datetime.fromisoformat(loop_start)).total_seconds() * 1000
                logger.info(f"[TASK ITERATION COMPLETE] task_name=smart_money_loop, duration_ms={duration_ms:.2f}, event_loop_id={event_loop_id}")
                if duration_ms > 1000:
                    logger.warning(f"[SLOW TASK] task_name=smart_money_loop, duration_ms={duration_ms:.2f}, event_loop_id={event_loop_id}")
                if duration_ms > 5000:
                    logger.error(f"[BLOCKING WARNING] task_name=smart_money_loop, duration_ms={duration_ms:.2f}, event_loop_id={event_loop_id}")

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

                # Log webhook receiving update IMMEDIATELY
                webhook_timestamp = datetime.now().isoformat()
                print(f"[WEBHOOK RECEIVED] timestamp={webhook_timestamp}, method=POST, path=/webhook, event_loop_id={event_loop_id}")
                logger.info(f"[WEBHOOK RECEIVED] timestamp={webhook_timestamp}, method=POST, path=/webhook, event_loop_id={event_loop_id}")

                if telegram_bot.application:
                    try:
                        # Get update from request
                        update_json = request.get_json(force=True)
                        update_id = update_json.get('update_id') if update_json else None

                        print(f"[WEBHOOK] Update JSON: {update_json}")
                        logger.info(f"[WEBHOOK] Full update JSON: {update_json}")

                        # Log update parsing
                        parse_timestamp = datetime.now().isoformat()
                        message = update_json.get('message', {}) if update_json else {}
                        user_id = message.get('from', {}).get('id')
                        chat_id = message.get('chat', {}).get('id')
                        message_type = 'message' if 'message' in update_json else 'unknown'
                        text = message.get('text')

                        print(f"[UPDATE PARSED] timestamp={parse_timestamp}, update_id={update_id}, user_id={user_id}, chat_id={chat_id}, message_type={message_type}, text={text}, event_loop_id={event_loop_id}")
                        logger.info(f"[UPDATE PARSED] timestamp={parse_timestamp}, update_id={update_id}, user_id={user_id}, chat_id={chat_id}, message_type={message_type}, text={text}, event_loop_id={event_loop_id}")

                        # Log dispatcher start
                        dispatch_start_timestamp = datetime.now().isoformat()
                        print(f"[DISPATCH START] timestamp={dispatch_start_timestamp}, update_id={update_id}, event_loop_id={event_loop_id}")
                        logger.info(f"[DISPATCH START] timestamp={dispatch_start_timestamp}, update_id={update_id}, event_loop_id={event_loop_id}")

                        # Put update into application's update_queue
                        try:
                            queue_put_timestamp = datetime.now().isoformat()
                            update = Update.de_json(update_json, telegram_bot.application.bot)
                            telegram_bot.application.update_queue.put_nowait(update)
                            print(f"[QUEUE PUT] timestamp={queue_put_timestamp}, update_id={update_id}, event_loop_id={event_loop_id}")
                            logger.info(f"[QUEUE PUT] timestamp={queue_put_timestamp}, update_id={update_id}, event_loop_id={event_loop_id}")
                            print(f"[WEBHOOK] Update put into queue successfully: update_id={update_id}")
                            logger.info(f"[WEBHOOK] Update put into queue successfully: update_id={update_id}")
                        except Exception as e:
                            print(f"[WEBHOOK ERROR] update_id={update_id}, error={e}")
                            logger.error(f"[WEBHOOK ERROR] update_id={update_id}, error={e}", exc_info=True)
                            print(f"[TELEGRAM UPDATE ERROR] timestamp={datetime.now().isoformat()}, update_id={update_id}, error={e}")
                            logger.error(f"[TELEGRAM UPDATE ERROR] timestamp={datetime.now().isoformat()}, update_id={update_id}, error={e}", exc_info=True)
                            return 'Error', 500

                        # Log dispatcher end
                        dispatch_end_timestamp = datetime.now().isoformat()
                        dispatch_duration_ms = (datetime.fromisoformat(dispatch_end_timestamp) - datetime.fromisoformat(dispatch_start_timestamp)).total_seconds() * 1000
                        print(f"[DISPATCH END] timestamp={dispatch_end_timestamp}, update_id={update_id}, duration_ms={dispatch_duration_ms:.2f}, event_loop_id={event_loop_id}")
                        logger.info(f"[DISPATCH END] timestamp={dispatch_end_timestamp}, update_id={update_id}, duration_ms={dispatch_duration_ms:.2f}, event_loop_id={event_loop_id}")

                        return 'OK', 200

                    except Exception as e:
                        error_timestamp = datetime.now().isoformat()
                        print(f"[TELEGRAM UPDATE ERROR] timestamp={error_timestamp}, error={e}")
                        print(f"[FULL TRACEBACK]: {traceback.format_exc()}")
                        logger.error(f"[TELEGRAM UPDATE ERROR] timestamp={error_timestamp}, error={e}", exc_info=True)
                        return 'Error', 500
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
