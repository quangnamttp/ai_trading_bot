"""
Module Breakout Engine cho AI Trading Signal Bot
Phát hiện coin đang/sắp "bùng nổ" (breakout) - khác hẳn logic trend-following của
signal_engine.py. Không quan tâm R:R chuẩn xác hay TP/SL cố định, mục tiêu là bắt được
điểm vào lệnh sớm khi có dấu hiệu bùng nổ giá thật (volume đột biến + phá vỡ cấu trúc giá +
nến mạnh liên tiếp), có thể do tin tức hoặc dòng tiền lớn.

LƯU Ý QUAN TRỌNG - GIỚI HẠN THỰC TẾ:
Không có hệ thống nào có thể "dự đoán trước" khi nào giá sẽ bùng nổ một cách đáng tin cậy.
Module này phát hiện bùng nổ NGAY KHI NÓ BẮT ĐẦU XẢY RA (volume + giá đã thực sự di chuyển),
không phải dự đoán trước khi nó xảy ra. Đây là cách duy nhất trung thực và khả thi để "vào sớm"
một con sóng - phản ứng nhanh với dữ liệu thật, không phải bói tương lai.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Ngưỡng phát hiện - có thể tinh chỉnh qua backtest thực tế sau này
VOLUME_SURGE_RATIO = 2.2       # Volume nến hiện tại phải >= 2.2x trung bình 20 nến gần nhất
STRUCTURE_BREAK_LOOKBACK = 20  # Số nến nhìn lại để xác định đỉnh/đáy cấu trúc gần nhất
CONSECUTIVE_CANDLES_MIN = 3    # Số nến cùng chiều liên tiếp tối thiểu để tính là "nến mạnh liên tiếp"
CANDLE_STRENGTH_ATR_MULT = 1.5  # Nến hiện tại phải có biên độ >= 1.5x ATR mới coi là "nến mạnh"
COOLDOWN_MINUTES = 45          # Không cảnh báo lại cùng 1 coin trong X phút, tránh spam khi sóng kéo dài


class BreakoutEngine:
    """Phát hiện breakout/momentum ignition - bổ sung cho signal_engine.py (trend-following),
    không thay thế. Chạy song song, độc lập với bộ lọc đa khung thời gian của signal_engine."""

    def __init__(self):
        self.last_alert_time = {}  # {symbol: datetime} - cooldown chống spam

    def _is_in_cooldown(self, symbol: str) -> bool:
        last = self.last_alert_time.get(symbol)
        if not last:
            return False
        return (datetime.now() - last).total_seconds() < COOLDOWN_MINUTES * 60

    async def detect_breakout(self, symbol: str, market_data, news_engine=None) -> Optional[Dict]:
        """Kiểm tra 1 coin có đang breakout hay không. Trả về dict cảnh báo nếu có, None nếu không.

        Điều kiện BẮT BUỘC (cả 2, để giảm tín hiệu giả - chỉ volume hoặc chỉ nến mạnh riêng lẻ
        rất dễ nhiễu trong crypto):
        1. Volume đột biến (>= VOLUME_SURGE_RATIO lần trung bình)
        2. VÀ (phá vỡ đỉnh/đáy N nến gần nhất HOẶC có >= CONSECUTIVE_CANDLES_MIN nến mạnh cùng chiều)
        """
        try:
            if self._is_in_cooldown(symbol):
                return None

            df = await market_data.get_ohlcv(symbol, '15m', limit=STRUCTURE_BREAK_LOOKBACK + 20)
            if df is None or len(df) < STRUCTURE_BREAK_LOOKBACK + 5:
                return None

            latest = df.iloc[-1]
            current_volume = latest['volume']
            volume_window = df['volume'].iloc[-21:-1]  # 20 nến trước đó, không tính nến hiện tại
            avg_volume = volume_window.mean()
            if not avg_volume or avg_volume <= 0:
                return None
            volume_ratio = current_volume / avg_volume

            if volume_ratio < VOLUME_SURGE_RATIO:
                return None  # Không đủ volume đột biến -> loại ngay, đỡ tốn công tính tiếp

            # ATR đơn giản (14 nến) để chuẩn hoá độ mạnh của nến, không phụ thuộc module khác
            high_low = df['high'] - df['low']
            atr14 = high_low.tail(14).mean()
            if not atr14 or atr14 <= 0:
                return None

            candle_range = latest['high'] - latest['low']
            candle_body = latest['close'] - latest['open']
            is_bullish_candle = candle_body > 0

            # Phá vỡ cấu trúc: so với đỉnh/đáy của N nến TRƯỚC đó (không tính nến hiện tại)
            structure_window = df.iloc[-(STRUCTURE_BREAK_LOOKBACK + 1):-1]
            recent_high = structure_window['high'].max()
            recent_low = structure_window['low'].min()
            breaks_up = latest['close'] > recent_high
            breaks_down = latest['close'] < recent_low

            # Đếm số nến cùng chiều liên tiếp gần nhất (kể cả nến hiện tại)
            consecutive = 0
            direction = None
            for i in range(len(df) - 1, -1, -1):
                row = df.iloc[i]
                row_dir = 'up' if row['close'] > row['open'] else ('down' if row['close'] < row['open'] else None)
                if row_dir is None:
                    break
                if direction is None:
                    direction = row_dir
                    consecutive = 1
                elif row_dir == direction:
                    consecutive += 1
                else:
                    break

            strong_consecutive = consecutive >= CONSECUTIVE_CANDLES_MIN

            action = None
            reasons = []

            if is_bullish_candle and (breaks_up or (strong_consecutive and direction == 'up')):
                action = 'LONG'
                if breaks_up:
                    reasons.append(f"Phá vỡ đỉnh {STRUCTURE_BREAK_LOOKBACK} nến gần nhất")
                if strong_consecutive and direction == 'up':
                    reasons.append(f"{consecutive} nến xanh liên tiếp")
            elif (not is_bullish_candle) and (breaks_down or (strong_consecutive and direction == 'down')):
                action = 'SHORT'
                if breaks_down:
                    reasons.append(f"Phá vỡ đáy {STRUCTURE_BREAK_LOOKBACK} nến gần nhất")
                if strong_consecutive and direction == 'down':
                    reasons.append(f"{consecutive} nến đỏ liên tiếp")

            if not action:
                return None

            reasons.append(f"Volume đột biến {volume_ratio:.1f}x trung bình")
            if candle_range >= atr14 * CANDLE_STRENGTH_ATR_MULT:
                reasons.append("Nến biên độ mạnh")

            # Tham khảo tin tức gần đây có nhắc tới coin này không (chỉ để tham khảo thêm bối cảnh,
            # không phải điều kiện bắt buộc - vì không phải breakout nào cũng có tin tức rõ ràng)
            news_hits = []
            if news_engine:
                try:
                    base_symbol = symbol.split('/')[0]
                    cutoff = datetime.now() - timedelta(hours=6)
                    for news in news_engine.news_cache:
                        title = news.get('title', '')
                        if base_symbol.lower() in title.lower():
                            published_at = news.get('published_at')
                            try:
                                pub_time = datetime.fromisoformat(published_at.replace('Z', '+00:00')).replace(tzinfo=None)
                            except Exception:
                                pub_time = None
                            if pub_time is None or pub_time > cutoff:
                                news_hits.append(title)
                except Exception as e:
                    logger.debug(f"[BREAKOUT] Lỗi khi tham chiếu tin tức cho {symbol}: {e}")

            self.last_alert_time[symbol] = datetime.now()

            return {
                'symbol': symbol,
                'action': action,
                'price': latest['close'],
                'volume_ratio': round(volume_ratio, 2),
                'reasons': reasons,
                'news_hits': news_hits[:2],  # tối đa 2 tin liên quan để tránh spam message
                'reference_atr': atr14
            }
        except Exception as e:
            logger.error(f"[BREAKOUT] Lỗi khi kiểm tra breakout cho {symbol}: {e}")
            return None


# Singleton instance
breakout_engine = BreakoutEngine()


def format_breakout_message(breakout: Dict) -> str:
    """Định dạng tin nhắn cảnh báo breakout - KHÁC hẳn tin nhắn tín hiệu trend-following thường,
    không có TP1/TP2/TP3 chi tiết vì mục đích là vào lệnh nhanh, chốt tay theo diễn biến thực tế."""
    from core.config import clean_symbol
    display_symbol = clean_symbol(breakout['symbol'])
    action = breakout['action']
    emoji = "🚀" if action == 'LONG' else "🔻"
    action_text = "LONG (mua)" if action == 'LONG' else "SHORT (bán)"

    msg = f"{emoji} <b>CẢNH BÁO BÙNG NỔ - {display_symbol}</b>\n\n"
    msg += f"Hướng: <b>{action_text}</b>\n"
    msg += f"Giá hiện tại: <b>{breakout['price']:.6f}</b>\n\n"
    msg += "<b>Lý do phát hiện:</b>\n"
    for r in breakout['reasons']:
        msg += f"• {r}\n"

    if breakout.get('news_hits'):
        msg += "\n<b>📰 Tin liên quan gần đây:</b>\n"
        for title in breakout['news_hits']:
            msg += f"• {title}\n"

    ref_atr = breakout.get('reference_atr', 0)
    if ref_atr:
        if action == 'LONG':
            ref_sl = breakout['price'] - ref_atr * 1.5
        else:
            ref_sl = breakout['price'] + ref_atr * 1.5
        msg += f"\n<i>Mức tham khảo nếu cần dừng lỗ: ~{ref_sl:.6f} (chỉ để tham khảo, không phải khuyến nghị cứng)</i>\n"

    msg += "\n⚠️ <i>Đây là cảnh báo bùng nổ (momentum), không phải tín hiệu trend-following chuẩn. " \
           "Không có TP/SL cố định - phù hợp cho việc tự quản lý lệnh theo diễn biến thực tế.</i>"

    return msg

