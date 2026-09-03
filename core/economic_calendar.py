"""
Module Lịch Kinh Tế Vĩ Mô cho AI Trading Signal Bot
Không cần API key - dùng lịch FOMC chính thức (Fed công bố công khai) +
lịch CPI/NFP ước tính theo quy luật công bố hàng tháng của Mỹ.

Đây là các sự kiện thường gây biến động mạnh cho thị trường Crypto vì
ảnh hưởng trực tiếp tới thanh khoản USD toàn cầu (dòng tiền vào/ra tài sản rủi ro).
"""
import logging
from datetime import datetime, date, timedelta
from typing import List, Dict

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
    ET_ZONE = ZoneInfo("America/New_York")
    VN_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
    _HAS_ZONEINFO = True
except Exception:
    _HAS_ZONEINFO = False

# Lịch họp FOMC chính thức năm 2026 (nguồn: federalreserve.gov, công bố công khai)
# Ngày công bố lãi suất luôn là ngày cuối của kỳ họp 2 ngày, 14:00 giờ Miền Đông Mỹ (ET)
FOMC_2026_DATES = [
    date(2026, 1, 28),
    date(2026, 3, 18),
    date(2026, 4, 29),
    date(2026, 6, 17),
    date(2026, 7, 29),
    date(2026, 9, 16),
    date(2026, 10, 28),
    date(2026, 12, 9),
]


def _fomc_announcement_vn_time(d: date) -> str:
    """Quy đổi giờ công bố FOMC (14:00 ET) sang giờ Việt Nam"""
    if _HAS_ZONEINFO:
        try:
            dt_et = datetime(d.year, d.month, d.day, 14, 0, tzinfo=ET_ZONE)
            dt_vn = dt_et.astimezone(VN_ZONE)
            return dt_vn.strftime("%H:%M ngày %d/%m (giờ VN)")
        except Exception:
            pass
    # Fallback: ET lệch VN khoảng 11-12 tiếng tùy giờ mùa hè/đông của Mỹ
    return "~01:00-02:00 sáng hôm sau (giờ VN, ước tính)"


def _first_friday(year: int, month: int) -> date:
    """Ngày thứ Sáu đầu tiên của tháng - dùng để ước tính ngày công bố NFP (Non-Farm Payrolls)"""
    d = date(year, month, 1)
    days_ahead = (4 - d.weekday()) % 7  # 4 = Friday
    return d + timedelta(days=days_ahead)


def get_upcoming_macro_events(limit: int = 5) -> List[Dict]:
    """Trả về danh sách sự kiện vĩ mô sắp tới, đã sắp xếp theo thời gian gần nhất.

    Gồm:
    - FOMC (ngày chính xác 100%, lấy từ lịch chính thức Fed)
    - NFP - Non-Farm Payrolls (ước tính: thứ Sáu đầu tiên mỗi tháng, giờ Mỹ công bố 8:30 ET)
    - CPI (ước tính: khoảng ngày 10-13 mỗi tháng, có thể lệch vài ngày so với công bố thật)
    """
    today = datetime.now().date()
    events = []

    # FOMC - chính xác
    for d in FOMC_2026_DATES:
        if d >= today:
            events.append({
                'event': 'FOMC - Quyết định lãi suất Fed',
                'date': d.isoformat(),
                'date_display': d.strftime('%d/%m/%Y'),
                'days_left': (d - today).days,
                'importance': 'CỰC CAO',
                'vn_time': _fomc_announcement_vn_time(d),
                'note': 'Ảnh hưởng trực tiếp đến thanh khoản USD toàn cầu, thường gây biến động mạnh nhất trong tháng cho BTC/Crypto.',
                'is_estimate': False
            })

    # NFP - ước tính (thứ 6 đầu tháng, hiện tại + 3 tháng tới)
    for i in range(0, 4):
        month = today.month + i
        year = today.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        d = _first_friday(year, month)
        if d >= today:
            events.append({
                'event': 'NFP - Báo cáo việc làm Mỹ',
                'date': d.isoformat(),
                'date_display': d.strftime('%d/%m/%Y'),
                'days_left': (d - today).days,
                'importance': 'CAO',
                'vn_time': '~19:30-20:30 tối (giờ VN, ước tính)',
                'note': 'Số liệu việc làm tốt/xấu ảnh hưởng kỳ vọng lãi suất Fed → tác động dòng tiền vào tài sản rủi ro.',
                'is_estimate': True
            })

    # CPI - ước tính (khoảng ngày 12 mỗi tháng, hiện tại + 3 tháng tới) - ngày thật có thể lệch 1-3 ngày
    for i in range(0, 4):
        month = today.month + i
        year = today.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        try:
            d = date(year, month, 12)
        except ValueError:
            continue
        if d >= today:
            events.append({
                'event': 'CPI - Chỉ số lạm phát Mỹ',
                'date': d.isoformat(),
                'date_display': d.strftime('%d/%m/%Y') + ' (±3 ngày)',
                'days_left': (d - today).days,
                'importance': 'CAO',
                'vn_time': '~19:30-20:30 tối (giờ VN, ước tính)',
                'note': 'Lạm phát cao hơn dự báo thường khiến dòng tiền rút khỏi Crypto do lo ngại Fed giữ lãi suất cao lâu hơn.',
                'is_estimate': True
            })

    events.sort(key=lambda e: e['date'])
    return events[:limit]
