"""
Main Application cho AI Trading Signal Bot
Khởi động và quản lý toàn bộ hệ thống
"""
import asyncio
import logging
import signal
import sys
from datetime import datetime
from flask import Flask
from .config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_ID, 
    MARKET_DATA_INTERVAL, NEWS_CHECK_INTERVAL, AI_UPDATE_INTERVAL,
    validate_config, PORT
)
from .database import db
from ..telegram.telegram_bot import telegram_bot
from ..data.market_data import market_data_engine
from ..data.news_engine import news_engine
from ..data.smart_money import smart_money_tracker
from ..analysis.ai_engine import ai_engine
from ..analysis.signal_engine import signal_engine
from ..analysis.risk_manager import risk_manager
from ..utils.utils import setup_logging, async_sleep

# Flask app cho Render health check
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


class TradingBotApp:
    """Main Application class"""
    
    def __init__(self):
        self.running = False
        self.tasks = []
        self.shutdown_event = asyncio.Event()
    
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
                bot_app = telegram_bot.start()
                logger.info("Telegram bot initialized")
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
    
    async def market_data_loop(self):
        """Loop quét dữ liệu thị trường"""
        logger.info("Starting market data loop")
        
        while not self.shutdown_event.is_set():
            try:
                for symbol in ["BTCUSDT", "XAUUSD"]:
                    try:
                        # Lấy dữ liệu thị trường
                        await market_data_engine.get_symbol_data(symbol)
                        
                        # Lưu vào database
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
        
        while not self.shutdown_event.is_set():
            try:
                for symbol in ["BTCUSDT", "XAUUSD"]:
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
                        
                        # Nếu có tín hiệu, tạo và gửi
                        if analysis.get('action') in ['LONG', 'SHORT']:
                            signal = await signal_engine.create_signal(analysis)
                            if signal and signal.get('message'):
                                # Gửi tín hiệu qua Telegram
                                await telegram_bot.send_signal(signal['message'])
                                logger.info(f"Signal sent for {symbol}")
                        
                        logger.debug(f"AI analysis completed for {symbol}")
                    except Exception as e:
                        logger.error(f"Error analyzing {symbol}: {e}")
                
                await async_sleep(AI_UPDATE_INTERVAL)
            except Exception as e:
                logger.error(f"Error in analysis loop: {e}")
                await async_sleep(30)
    
    async def smart_money_loop(self):
        """Loop theo dõi Smart Money"""
        logger.info("Starting smart money loop")
        
        while not self.shutdown_event.is_set():
            try:
                for symbol in ["BTCUSDT", "XAUUSD"]:
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
    
    async def run_flask_server(self):
        """Chạy Flask server cho health check"""
        try:
            # Run Flask in a separate thread
            import threading
            
            def run_flask():
                app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
            
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
            
            # Initialize components
            bot_app = await self.initialize()
            
            # Start Flask server
            await self.run_flask_server()
            
            # Start Telegram bot
            self.running = True
            
            # Create tasks
            self.tasks = [
                asyncio.create_task(self.market_data_loop()),
                asyncio.create_task(self.news_loop()),
                asyncio.create_task(self.analysis_loop()),
                asyncio.create_task(self.smart_money_loop()),
                asyncio.create_task(bot_app.run_polling())
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
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        # Close market data connections
        await market_data_engine.close()
        
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
