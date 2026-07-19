"""
Module Signal Tracker cho AI Trading Signal Bot V2.0
Theo dõi trạng thái tín hiệu (TP/SL) và gửi thông báo
"""
import logging
import asyncio
from datetime import datetime
from typing import Dict, Optional
from .database import db
from ..data.market_data import market_data_engine

logger = logging.getLogger(__name__)


class SignalTracker:
    """Theo dõi trạng thái tín hiệu và thông báo TP/SL"""
    
    def __init__(self):
        self.active_signals = {}
        self.check_interval = 60  # Check every 60 seconds
    
    async def start_tracking(self, signal_id: int, symbol: str, signal_type: str,
                            entry_price: float, tp1: float, tp2: float, tp3: float,
                            stop_loss: float, telegram_bot):
        """Bắt đầu theo dõi tín hiệu"""
        try:
            # Lưu vào database
            tracking_id = db.save_signal_tracking(
                signal_id=signal_id,
                symbol=symbol,
                signal_type=signal_type,
                entry_price=entry_price,
                tp1=tp1,
                tp2=tp2,
                tp3=tp3,
                stop_loss=stop_loss,
                ai_score=0,  # Will be updated
                confidence=0,  # Will be updated
                reasons=[]
            )
            
            if tracking_id:
                self.active_signals[tracking_id] = {
                    'signal_id': signal_id,
                    'symbol': symbol,
                    'signal_type': signal_type,
                    'entry_price': entry_price,
                    'tp1': tp1,
                    'tp2': tp2,
                    'tp3': tp3,
                    'stop_loss': stop_loss,
                    'telegram_bot': telegram_bot,
                    'tp1_hit': False,
                    'tp2_hit': False,
                    'tp3_hit': False,
                    'sl_hit': False
                }
                logger.info(f"Started tracking signal {tracking_id}: {signal_type} {symbol}")
            
            return tracking_id
        except Exception as e:
            logger.error(f"Error starting signal tracking: {e}")
            return None
    
    async def check_signal_status(self, tracking_id: int) -> Optional[str]:
        """Kiểm tra trạng thái tín hiệu"""
        try:
            if tracking_id not in self.active_signals:
                return None
            
            signal = self.active_signals[tracking_id]
            symbol = signal['symbol']
            
            # Lấy giá hiện tại
            ticker = await market_data_engine.get_ticker(symbol)
            if not ticker:
                return None
            
            current_price = ticker.get('last', 0)
            signal_type = signal['signal_type']
            
            # Kiểm tra TP/SL
            status = None
            
            if signal_type == 'LONG':
                if not signal['tp1_hit'] and current_price >= signal['tp1']:
                    status = 'TP1'
                    signal['tp1_hit'] = True
                    db.update_signal_tracking(tracking_id, tp1_hit=True)
                elif not signal['tp2_hit'] and current_price >= signal['tp2']:
                    status = 'TP2'
                    signal['tp2_hit'] = True
                    db.update_signal_tracking(tracking_id, tp2_hit=True)
                elif not signal['tp3_hit'] and current_price >= signal['tp3']:
                    status = 'TP3'
                    signal['tp3_hit'] = True
                    db.update_signal_tracking(tracking_id, tp3_hit=True)
                elif not signal['sl_hit'] and current_price <= signal['stop_loss']:
                    status = 'SL'
                    signal['sl_hit'] = True
                    db.update_signal_tracking(tracking_id, sl_hit=True)
            
            elif signal_type == 'SHORT':
                if not signal['tp1_hit'] and current_price <= signal['tp1']:
                    status = 'TP1'
                    signal['tp1_hit'] = True
                    db.update_signal_tracking(tracking_id, tp1_hit=True)
                elif not signal['tp2_hit'] and current_price <= signal['tp2']:
                    status = 'TP2'
                    signal['tp2_hit'] = True
                    db.update_signal_tracking(tracking_id, tp2_hit=True)
                elif not signal['tp3_hit'] and current_price <= signal['tp3']:
                    status = 'TP3'
                    signal['tp3_hit'] = True
                    db.update_signal_tracking(tracking_id, tp3_hit=True)
                elif not signal['sl_hit'] and current_price >= signal['stop_loss']:
                    status = 'SL'
                    signal['sl_hit'] = True
                    db.update_signal_tracking(tracking_id, sl_hit=True)
            
            # Nếu hit SL hoặc TP3, đóng tín hiệu
            if status in ['SL', 'TP3']:
                await self.close_signal(tracking_id, current_price, status)
            
            return status
        except Exception as e:
            logger.error(f"Error checking signal status: {e}")
            return None
    
    async def send_notification(self, tracking_id: int, status: str, current_price: float):
        """Gửi thông báo TP/SL"""
        try:
            if tracking_id not in self.active_signals:
                return
            
            signal = self.active_signals[tracking_id]
            telegram_bot = signal['telegram_bot']
            symbol = signal['symbol']
            signal_type = signal['signal_type']
            
            if status == 'TP1':
                emoji = "🎯"
                message = f"{emoji} *TP1 ĐẠT!*\n\n"
                message += f"📊 {symbol}\n"
                message += f"📍 Giá hiện tại: {current_price:.2f}\n"
                message += f"✅ TP1: {signal['tp1']:.2f}\n"
                message += f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            
            elif status == 'TP2':
                emoji = "🎯🎯"
                message = f"{emoji} *TP2 ĐẠT!*\n\n"
                message += f"📊 {symbol}\n"
                message += f"📍 Giá hiện tại: {current_price:.2f}\n"
                message += f"✅ TP2: {signal['tp2']:.2f}\n"
                message += f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            
            elif status == 'TP3':
                emoji = "🎯🎯🎯"
                message = f"{emoji} *TP3 ĐẠT!*\n\n"
                message += f"📊 {symbol}\n"
                message += f"📍 Giá hiện tại: {current_price:.2f}\n"
                message += f"✅ TP3: {signal['tp3']:.2f}\n"
                message += f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                message += f"🎉 Tín hiệu đã hoàn thành!\n"
            
            elif status == 'SL':
                emoji = "🛑"
                message = f"{emoji} *STOP LOSS ĐẠT!*\n\n"
                message += f"📊 {symbol}\n"
                message += f"📍 Giá hiện tại: {current_price:.2f}\n"
                message += f"❌ SL: {signal['stop_loss']:.2f}\n"
                message += f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                message += f"⚠️ Tín hiệu đã kết thúc.\n"
            
            # Gửi đến tất cả users
            await telegram_bot.send_signal(message)
            logger.info(f"Sent {status} notification for {symbol}")
            
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
    
    async def close_signal(self, tracking_id: int, current_price: float, status: str):
        """Đóng tín hiệu theo dõi"""
        try:
            if tracking_id not in self.active_signals:
                return
            
            signal = self.active_signals[tracking_id]
            entry_price = signal['entry_price']
            signal_type = signal['signal_type']
            
            # Tính PNL
            if signal_type == 'LONG':
                pnl = (current_price - entry_price) / entry_price * 100
            else:
                pnl = (entry_price - current_price) / entry_price * 100
            
            # Cập nhật database
            db.close_signal_tracking(tracking_id, final_pnl=pnl)
            
            # Xóa khỏi active signals
            del self.active_signals[tracking_id]
            
            logger.info(f"Closed signal {tracking_id} with PNL: {pnl:.2f}%")
            
        except Exception as e:
            logger.error(f"Error closing signal: {e}")
    
    async def monitoring_loop(self):
        """Loop theo dõi tất cả tín hiệu active"""
        logger.info("Starting signal monitoring loop")
        
        while True:
            try:
                # Load active signals từ database
                active_signals = db.get_active_signals()
                
                for signal_data in active_signals:
                    tracking_id = signal_data['id']
                    
                    # Nếu chưa trong memory, thêm vào
                    if tracking_id not in self.active_signals:
                        # Cần telegram_bot reference - sẽ được set từ main
                        continue
                    
                    # Kiểm tra trạng thái
                    status = await self.check_signal_status(tracking_id)
                    
                    if status:
                        current_price = await self.get_current_price(signal_data['symbol'])
                        await self.send_notification(tracking_id, status, current_price)
                
                await asyncio.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(30)
    
    async def get_current_price(self, symbol: str) -> float:
        """Lấy giá hiện tại"""
        try:
            ticker = await market_data_engine.get_ticker(symbol)
            return ticker.get('last', 0) if ticker else 0
        except Exception as e:
            logger.error(f"Error getting current price: {e}")
            return 0
    
    def set_telegram_bot(self, telegram_bot):
        """Set telegram bot reference"""
        for tracking_id in self.active_signals:
            self.active_signals[tracking_id]['telegram_bot'] = telegram_bot


# Singleton instance
signal_tracker = SignalTracker()
