"""
BACKTEST TOOL - Kiểm chứng chiến lược bằng dữ liệu lịch sử THẬT trước khi tin dùng tín hiệu thật.

QUAN TRỌNG - ĐỌC TRƯỚC KHI DÙNG:
- Script này KHÔNG chạy được trong môi trường sandbox của Claude (không có internet ra sàn
  giao dịch). Nó được thiết kế để chạy trên máy có internet: máy cá nhân của bạn, GitHub
  Actions, hoặc Render Shell.
- Script tái sử dụng TRỰC TIẾP các hàm tính toán thật trong code (GannEngine, AIEngine,
  SignalEngine.calculate_take_profit/stop_loss, MarketDataEngine._calculate_indicators_sync)
  - không phải bản viết lại riêng - để đảm bảo kết quả backtest phản ánh đúng logic đang
  chạy thật trong bot, tránh trường hợp "backtest đẹp nhưng bot thật khác".
- GIỚI HẠN TRUNG THỰC (đọc kỹ):
  1. Dùng khung 1H làm khung "entry timing" trong backtest thay vì 15M như bot thật
     (vì tải toàn bộ lịch sử 15M nhiều tháng tốn quá nhiều API calls). Đây là 1 sự đơn giản
     hoá - kết quả backtest có thể lạc quan hoặc bi quan hơn thực tế đôi chút.
  2. KHÔNG mô phỏng được Funding Rate và Open Interest lịch sử (sàn không cung cấp API
     lịch sử miễn phí đầy đủ cho việc này) - 2 bộ lọc này được bỏ qua trong backtest.
     Nghĩa là bot thật có thể chặt chẽ hơn (ít tín hiệu hơn) backtest cho thấy.
  3. KHÔNG mô phỏng Smart Money / News - 2 yếu tố này trong bot thật chỉ mang tính bổ trợ,
     không phải điều kiện chặn cứng, nên ảnh hưởng không lớn tới kết quả.
  4. Backtest giả định lệnh luôn khớp đúng giá đóng nến tín hiệu (không tính slippage,
     phí giao dịch, hoặc thanh khoản thực tế khi vào lệnh).
  5. Kết quả quá khứ KHÔNG đảm bảo kết quả tương lai. Đây là công cụ để phát hiện lỗi
     logic rõ ràng (ví dụ: quá ít tín hiệu, hoặc win rate quá thấp bất thường) - không phải
     lời hứa lợi nhuận.

CÁCH CHẠY:
    cd ai_trading_bot
    pip install -r requirements.txt
    python tools/backtest.py --symbols "BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT,XRP/USDT:USDT" --days 150

KẾT QUẢ: in ra console + lưu file tools/backtest_report.json và tools/backtest_report.csv
"""
import sys
import os
import asyncio
import argparse
import json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
import ccxt.async_support as ccxt

from data.market_data import MarketDataEngine
from analysis.gann_engine import GannEngine
from analysis.ai_engine import AIEngine
from analysis.signal_engine import SignalEngine
from core.config import (
    AI_SCORE_THRESHOLD, GANN_MIN_CONFIDENCE, ATR_REGIME_MIN, ATR_REGIME_MAX,
    VOLUME_MULTIPLIER
)

# Cửa sổ phát hiện EMA cross (số nến gần nhất) - khớp với data/market_data.py hiện tại
EMA_CROSS_LOOKBACK = 5
# Khoảng cách tối đa tới vùng Gann để coi là "đủ gần" để vào lệnh - khớp với signal_engine.py
GANN_PROXIMITY_ATR_MULT = 0.6
# Số nến tối đa chờ 1 tín hiệu chốt TP3/SL trước khi coi là timeout (đóng theo giá hiện tại)
MAX_HOLD_BARS = 200  # 200 nến 1H = ~8.3 ngày


async def fetch_full_history(exchange, symbol: str, timeframe: str, days: int) -> pd.DataFrame:
    """Tải toàn bộ lịch sử OHLCV, tự động phân trang (MEXC giới hạn số nến mỗi lần gọi)"""
    since = exchange.milliseconds() - days * 24 * 60 * 60 * 1000
    all_candles = []
    while True:
        batch = await exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
        if not batch:
            break
        all_candles.extend(batch)
        last_ts = batch[-1][0]
        if last_ts <= since:
            break
        since = last_ts + 1
        if len(batch) < 2:
            break
        await asyncio.sleep(exchange.rateLimit / 1000)
        if since >= exchange.milliseconds():
            break

    if not all_candles:
        return pd.DataFrame()

    df = pd.DataFrame(all_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df.drop_duplicates(subset='timestamp', inplace=True)
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df.sort_index(inplace=True)
    return df


def resample_4h(df_1h: pd.DataFrame) -> pd.DataFrame:
    """Tổng hợp nến 4H từ nến 1H"""
    return df_1h.resample('4h').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna()


def detect_ema_cross(df_slice: pd.DataFrame, lookback: int = EMA_CROSS_LOOKBACK):
    """Trả về (bullish_cross, bearish_cross) trong N nến gần nhất - dùng chung logic với production"""
    n = min(lookback, len(df_slice) - 1)
    if n < 1:
        return False, False
    window = df_slice.iloc[-(n + 1):]
    e20 = window['ema_20'].values
    e50 = window['ema_50'].values
    bullish = bearish = False
    for i in range(1, len(e20)):
        if e20[i - 1] <= e50[i - 1] and e20[i] > e50[i]:
            bullish = True
        if e20[i - 1] >= e50[i - 1] and e20[i] < e50[i]:
            bearish = True
    return bullish, bearish


def macro_trend_from_indicators(ind: dict) -> str:
    price, ema50, ema200 = ind.get('price', 0), ind.get('ema_50', 0), ind.get('ema_200', 0)
    if not ema50 or not ema200 or pd.isna(ema50) or pd.isna(ema200):
        return 'neutral'
    if price > ema50 > ema200:
        return 'bullish'
    if price < ema50 < ema200:
        return 'bearish'
    return 'neutral'


async def backtest_symbol(symbol: str, days: int, mde: MarketDataEngine, gann: GannEngine,
                           ai: AIEngine, se: SignalEngine, exchange) -> dict:
    print(f"\n=== Đang tải dữ liệu lịch sử cho {symbol} ({days} ngày, khung 1H) ===")
    df_1h_raw = await fetch_full_history(exchange, symbol, '1h', days)
    if df_1h_raw.empty or len(df_1h_raw) < 350:
        print(f"[{symbol}] Không đủ dữ liệu lịch sử, bỏ qua.")
        return {'symbol': symbol, 'error': 'insufficient_data', 'candles': len(df_1h_raw)}

    print(f"[{symbol}] Tải được {len(df_1h_raw)} nến 1H. Bắt đầu mô phỏng...")
    trades = run_simulation(df_1h_raw, mde, gann, ai, se)
    return summarize(symbol, trades, days)


def run_simulation(df_1h_raw: pd.DataFrame, mde: MarketDataEngine, gann: GannEngine,
                    ai: AIEngine, se: SignalEngine) -> list:
    """Chạy mô phỏng walk-forward trên dữ liệu 1H đã có sẵn (không gọi mạng).
    Tách riêng khỏi backtest_symbol() để có thể unit-test bằng dữ liệu giả lập."""

    trades = []
    active_trade = None  # {'action','entry','tp1','tp2','tp3','sl','entry_idx','tp1_hit','tp2_hit'}

    warmup = 300  # cần đủ nến cho EMA200 hội tụ (khớp production)
    for i in range(warmup, len(df_1h_raw)):
        bar_time = df_1h_raw.index[i]
        window_1h = df_1h_raw.iloc[max(0, i - 400):i + 1].copy()  # không nhìn trước tương lai
        price = window_1h.iloc[-1]['close']

        # --- Nếu đang có lệnh mở, kiểm tra TP/SL trước ---
        if active_trade:
            high, low = df_1h_raw.iloc[i]['high'], df_1h_raw.iloc[i]['low']
            a = active_trade
            bars_held = i - a['entry_idx']
            closed = False
            if a['action'] == 'LONG':
                if low <= a['sl']:
                    a['exit'] = a['sl']; a['result'] = 'SL'; closed = True
                elif high >= a['tp3']:
                    a['exit'] = a['tp3']; a['result'] = 'TP3'; closed = True
                elif high >= a['tp2']:
                    a['tp2_hit'] = True
                elif high >= a['tp1']:
                    a['tp1_hit'] = True
            else:  # SHORT
                if high >= a['sl']:
                    a['exit'] = a['sl']; a['result'] = 'SL'; closed = True
                elif low <= a['tp3']:
                    a['exit'] = a['tp3']; a['result'] = 'TP3'; closed = True
                elif low <= a['tp2']:
                    a['tp2_hit'] = True
                elif low <= a['tp1']:
                    a['tp1_hit'] = True

            if not closed and bars_held >= MAX_HOLD_BARS:
                a['exit'] = price; a['result'] = 'TIMEOUT'; closed = True

            if closed:
                if a['action'] == 'LONG':
                    a['pnl_pct'] = (a['exit'] - a['entry']) / a['entry'] * 100
                else:
                    a['pnl_pct'] = (a['entry'] - a['exit']) / a['entry'] * 100
                a['exit_time'] = str(bar_time)
                a['bars_held'] = bars_held
                trades.append(a)
                active_trade = None
            else:
                continue  # đang giữ lệnh -> không tìm tín hiệu mới (đúng luật "1 lệnh/coin")

        # --- Không có lệnh mở -> tìm tín hiệu mới, đúng thứ tự filter_signal() thật ---
        window_4h = resample_4h(window_1h)
        if len(window_4h) < 60:
            continue

        # Không .copy() nữa - để hàm mutate trực tiếp lên window_1h/window_4h (thêm cột ema_20,
        # ema_50...) vì detect_ema_cross() bên dưới cần đọc lại các cột này từ window_1h.
        # window_1h/window_4h đã là bản sao độc lập với df_1h_raw (từ .iloc[].copy() và
        # resample().agg() ở trên) nên mutate ở đây an toàn, không ảnh hưởng dữ liệu gốc.
        ind_1h = mde._calculate_indicators_sync(window_1h)
        ind_4h = mde._calculate_indicators_sync(window_4h)
        if not ind_1h or not ind_4h:
            continue

        macro_trend = macro_trend_from_indicators(ind_4h)
        if macro_trend == 'neutral':
            continue

        # Xu hướng "1H" trong bot thật; ở đây dùng lại ind_1h cho cả 2 vai trò 1H/15M
        # (giới hạn đã ghi rõ ở đầu file)
        trend_1h = macro_trend_from_indicators(ind_1h)
        if trend_1h != macro_trend:
            continue

        angles = gann.calculate_gann_angles(window_1h)
        levels = gann.identify_gann_levels(window_1h, angles)
        gann_trend = gann.determine_gann_trend(window_1h, levels)
        gann_conf = gann.calculate_gann_confidence(window_1h, gann_trend)
        if gann_trend != macro_trend or gann_conf < GANN_MIN_CONFIDENCE:
            continue

        ema20, ema50 = ind_1h.get('ema_20', 0), ind_1h.get('ema_50', 0)
        if not ema20 or not ema50 or pd.isna(ema20) or pd.isna(ema50):
            continue
        entry_trend = 'bullish' if ema20 > ema50 else ('bearish' if ema20 < ema50 else 'neutral')
        if entry_trend != macro_trend:
            continue
        # Cú cắt EMA gần đây không còn là điều kiện chặn cứng (khớp với thay đổi trong
        # signal_engine.py) - chỉ giữ lại làm thông tin tham khảo, không dùng để loại bỏ
        # candidate trong backtest này.
        bull_cross, bear_cross = detect_ema_cross(window_1h)
        ema_cross_recent = bull_cross if macro_trend == 'bullish' else bear_cross

        atr = ind_1h.get('atr', 0)
        atr_ma50 = ind_1h.get('atr_ma50', 0)
        if not atr or not atr_ma50 or pd.isna(atr) or pd.isna(atr_ma50):
            continue

        support, resistance = levels.get('nearest_support'), levels.get('nearest_resistance')
        proximity_threshold = atr * GANN_PROXIMITY_ATR_MULT
        if macro_trend == 'bullish' and resistance:
            if abs(price - resistance) > proximity_threshold:
                continue
        elif macro_trend == 'bearish' and support:
            if abs(price - support) > proximity_threshold:
                continue

        atr_ratio = atr / atr_ma50
        if atr_ratio < ATR_REGIME_MIN or atr_ratio > ATR_REGIME_MAX:
            continue

        volume = ind_1h.get('volume', 0)
        volume_ma20 = ind_1h.get('volume_ma20', 0)
        if not volume_ma20 or pd.isna(volume_ma20) or volume < volume_ma20 * VOLUME_MULTIPLIER:
            continue

        # AI Score - dùng lại đúng hàm chấm điểm thật, smart_money mặc định trung lập
        # vì không có dữ liệu funding/OI lịch sử (đã ghi rõ giới hạn ở đầu file)
        trend_analysis = ai.analyze_trend(ind_1h)
        neutral_smart_money = {'trend': 'neutral', 'cascade_risk': 'low', 'signals': []}
        probabilities = ai.calculate_probabilities(trend_analysis, neutral_smart_money, 'neutral')
        risk_level = ai.calculate_risk_level(trend_analysis, neutral_smart_money)
        decision = ai.generate_ai_decision(probabilities, risk_level, trend_analysis)

        if decision['ai_score'] < AI_SCORE_THRESHOLD:
            continue
        action = 'LONG' if macro_trend == 'bullish' else 'SHORT'

        # Vào lệnh - dùng đúng công thức TP/SL thật (ATR-based)
        tps = se.calculate_take_profit(price, action, atr, resistance if action == 'LONG' else support)
        sl = se.calculate_stop_loss(price, action, atr)

        active_trade = {
            'action': action, 'entry': price,
            'tp1': tps['TP1'], 'tp2': tps['TP2'], 'tp3': tps['TP3'], 'sl': sl,
            'ai_score': decision['ai_score'], 'entry_idx': i, 'entry_time': str(bar_time),
            'ema_cross_recent': ema_cross_recent,
            'tp1_hit': False, 'tp2_hit': False
        }

    # Đóng lệnh còn treo ở cuối kỳ backtest theo giá cuối cùng (không tính là thắng/thua thật)
    if active_trade:
        a = active_trade
        a['exit'] = df_1h_raw.iloc[-1]['close']
        a['result'] = 'OPEN_AT_END'
        if a['action'] == 'LONG':
            a['pnl_pct'] = (a['exit'] - a['entry']) / a['entry'] * 100
        else:
            a['pnl_pct'] = (a['entry'] - a['exit']) / a['entry'] * 100
        a['exit_time'] = str(df_1h_raw.index[-1])
        a['bars_held'] = len(df_1h_raw) - 1 - a['entry_idx']
        trades.append(a)

    return trades


def summarize(symbol: str, trades: list, days: int) -> dict:
    for t in trades:
        t['symbol'] = symbol
    total = len(trades)
    wins = [t for t in trades if t['result'] in ('TP1', 'TP2', 'TP3') or (t['result'] in ('SL', 'TIMEOUT', 'OPEN_AT_END') and t.get('tp1_hit'))]
    full_tp3 = [t for t in trades if t['result'] == 'TP3']
    sl_hits = [t for t in trades if t['result'] == 'SL']
    timeouts = [t for t in trades if t['result'] in ('TIMEOUT', 'OPEN_AT_END')]
    avg_pnl = float(np.mean([t['pnl_pct'] for t in trades])) if trades else 0.0
    win_rate = (len(wins) / total * 100) if total else 0.0

    print(f"\n--- KẾT QUẢ {symbol} ({days} ngày) ---")
    print(f"Tổng số tín hiệu: {total} (~{total / max(days,1)*7:.1f} tín hiệu/tuần)")
    print(f"Đạt ít nhất TP1: {len(wins)} ({win_rate:.1f}%)")
    print(f"Đạt full TP3: {len(full_tp3)} ({len(full_tp3)/total*100 if total else 0:.1f}%)")
    print(f"Dính Stop Loss (không chạm TP nào): {len([t for t in sl_hits if not t.get('tp1_hit')])}")
    print(f"Timeout/còn mở cuối kỳ: {len(timeouts)}")
    print(f"PnL trung bình mỗi lệnh: {avg_pnl:+.2f}%")

    return {
        'symbol': symbol, 'days': days, 'total_signals': total,
        'signals_per_week': round(total / max(days, 1) * 7, 2),
        'win_rate_pct': round(win_rate, 1),
        'full_tp3_count': len(full_tp3),
        'sl_only_count': len([t for t in sl_hits if not t.get('tp1_hit')]),
        'timeout_count': len(timeouts),
        'avg_pnl_pct': round(avg_pnl, 2),
        'trades': trades
    }


async def main():
    parser = argparse.ArgumentParser(description="Backtest chiến lược giao dịch bằng dữ liệu MEXC thật")
    parser.add_argument('--symbols', type=str, default="BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT,XRP/USDT:USDT")
    parser.add_argument('--days', type=int, default=150)
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(',') if s.strip()]

    exchange = ccxt.mexc({'enableRateLimit': True, 'timeout': 15000, 'options': {'defaultType': 'swap'}})
    mde = MarketDataEngine()
    gann = GannEngine()
    ai = AIEngine()
    se = SignalEngine()

    results = []
    try:
        await exchange.load_markets()
        for symbol in symbols:
            try:
                result = await backtest_symbol(symbol, args.days, mde, gann, ai, se, exchange)
                results.append(result)
            except Exception as e:
                print(f"[{symbol}] Lỗi khi backtest: {e}")
                results.append({'symbol': symbol, 'error': str(e)})
    finally:
        await exchange.close()

    # Tổng hợp toàn bộ watchlist
    print("\n" + "=" * 60)
    print("TỔNG HỢP TOÀN BỘ WATCHLIST BACKTEST")
    print("=" * 60)
    valid = [r for r in results if 'error' not in r]
    total_signals = sum(r['total_signals'] for r in valid)
    print(f"Tổng số coin test: {len(symbols)} | Số coin đủ dữ liệu: {len(valid)}")
    print(f"Tổng số tín hiệu toàn watchlist: {total_signals} trong {args.days} ngày")
    print(f"Trung bình: {total_signals / args.days:.2f} tín hiệu/ngày toàn watchlist")
    if valid:
        overall_win_rate = np.mean([r['win_rate_pct'] for r in valid])
        print(f"Win rate trung bình (đạt ít nhất TP1): {overall_win_rate:.1f}%")

    out_dir = os.path.dirname(os.path.abspath(__file__))
    report_path = os.path.join(out_dir, 'backtest_report.json')
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump({
            'run_at': datetime.now().isoformat(),
            'days': args.days,
            'symbols': symbols,
            'total_signals_all_symbols': total_signals,
            'signals_per_day_all_symbols': round(total_signals / args.days, 2),
            'results': results
        }, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nĐã lưu báo cáo chi tiết: {report_path}")

    # CSV gọn cho từng lệnh (dễ mở bằng Excel/Google Sheets để soi thủ công)
    csv_path = os.path.join(out_dir, 'backtest_report.csv')
    rows = []
    for r in results:
        if 'trades' not in r:
            continue
        for t in r['trades']:
            rows.append(t)
    if rows:
        pd.DataFrame(rows).to_csv(csv_path, index=False)
        print(f"Đã lưu chi tiết từng lệnh: {csv_path}")


if __name__ == '__main__':
    asyncio.run(main())
