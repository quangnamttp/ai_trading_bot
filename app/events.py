"""Lịch sự kiện kinh tế Mỹ: giải thích tiếng Việt + thống kê BTC phản ứng thế nào trong 24h sau tin (dữ liệu thật)."""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from html import escape

import pandas as pd
import sqlalchemy as sa

from app import storage
from app.config import VN_TZ
from app.data import binance, macro

log = logging.getLogger(__name__)

# (mẫu tên tin, loại, giải thích: là gì · cao hơn dự báo · thấp hơn dự báo)
EXPLAIN: list[tuple[str, str, str]] = [
    (r"core pce|pce price", "pce",
     "Chỉ số giá chi tiêu cá nhân — thước đo lạm phát Fed ưa dùng nhất.\n"
     "• Cao hơn dự báo: lạm phát dai dẳng → Fed khó giảm lãi suất → USD mạnh, crypto thường GIẢM.\n"
     "• Thấp hơn dự báo: mở đường giảm lãi suất → thường TỐT cho crypto."),
    (r"\bcpi\b", "cpi",
     "Chỉ số giá tiêu dùng — đo lạm phát, là tin làm crypto biến động mạnh nhất trong tháng.\n"
     "• Cao hơn dự báo: Fed có thể giữ lãi suất cao lâu hơn → USD tăng, crypto thường GIẢM mạnh ngay sau tin.\n"
     "• Thấp hơn dự báo: kỳ vọng giảm lãi suất → crypto thường TĂNG.\n"
     "• Bản 'Core' (bỏ thực phẩm, năng lượng) được thị trường chú ý hơn."),
    (r"\bppi\b", "ppi",
     "Chỉ số giá sản xuất — lạm phát ở đầu vào, thường báo trước CPI.\n"
     "• Cao hơn dự báo: lo ngại lạm phát → thường XẤU cho crypto.\n• Thấp hơn: thường TỐT."),
    (r"non-farm|nonfarm", "nfp",
     "Bảng lương phi nông nghiệp (NFP) — số việc làm mới của Mỹ, ra thứ Sáu đầu tháng.\n"
     "• Cao hơn nhiều so với dự báo: kinh tế nóng → Fed chưa vội giảm lãi suất → crypto thường GIẢM ngắn hạn.\n"
     "• Thấp hơn nhiều: kỳ vọng giảm lãi suất → thường TỐT, trừ khi quá thấp gây lo suy thoái."),
    (r"unemployment rate", "unemp",
     "Tỉ lệ thất nghiệp.\n• Cao hơn dự báo: thị trường lao động yếu → kỳ vọng giảm lãi suất → thường TỐT cho crypto "
     "(nhưng tăng quá mạnh gây lo suy thoái).\n• Thấp hơn: thường hơi XẤU."),
    (r"unemployment claims|jobless", "claims",
     "Số đơn xin trợ cấp thất nghiệp hằng tuần — tác động nhỏ hơn NFP.\n• Cao hơn dự báo: lao động yếu → thường hơi TỐT.\n"
     "• Thấp hơn: thường hơi XẤU."),
    (r"federal funds rate|fomc statement|rate decision", "fomc",
     "Quyết định lãi suất của Fed (FOMC) — sự kiện quan trọng nhất.\n"
     "• Giảm lãi suất / giọng mềm mỏng (dovish): thường TỐT cho crypto.\n"
     "• Giữ nguyên nhưng giọng cứng rắn (hawkish) / tăng lãi suất: thường XẤU.\n"
     "• Giá hay giật 2 chiều trong 1–2 giờ sau tin và buổi họp báo."),
    (r"press conference|powell|fed chair", "powell",
     "Chủ tịch Fed phát biểu / họp báo.\n• Nói về giảm lãi suất, lo kinh tế yếu: thường TỐT cho crypto.\n"
     "• Nhấn mạnh lạm phát, chưa vội giảm lãi suất: thường XẤU."),
    (r"fomc.*minutes|meeting minutes", "minutes",
     "Biên bản cuộc họp Fed trước — cho biết các thành viên nghĩ gì.\n• Nghiêng về giảm lãi suất: TỐT · nghiêng cứng rắn: XẤU."),
    (r"\bgdp\b", "gdp",
     "Tăng trưởng GDP.\n• Cao hơn dự báo: kinh tế mạnh, nhưng giảm kỳ vọng hạ lãi suất → tác động lẫn lộn.\n"
     "• Thấp hơn nhiều: lo suy thoái → ngắn hạn thường XẤU cho tài sản rủi ro."),
    (r"retail sales", "retail",
     "Doanh số bán lẻ — sức chi tiêu của người Mỹ.\n• Cao hơn dự báo: kinh tế mạnh → lãi suất cao lâu hơn → hơi XẤU.\n"
     "• Thấp hơn: hơi TỐT (kỳ vọng hạ lãi suất)."),
    (r"\bism\b|pmi", "pmi",
     "Chỉ số quản lý mua hàng (PMI) — sức khỏe sản xuất/dịch vụ. Trên 50 = mở rộng.\n"
     "• Cao hơn dự báo: kinh tế mạnh, lãi suất khó giảm → hơi XẤU.\n• Thấp hơn: hơi TỐT."),
    (r"jolts|job openings", "jolts",
     "Số việc làm còn trống (JOLTS).\n• Cao hơn dự báo: lao động thiếu → lương tăng → lạm phát → hơi XẤU.\n• Thấp hơn: hơi TỐT."),
    (r"consumer (confidence|sentiment)|inflation expectations", "sentiment",
     "Niềm tin / kỳ vọng lạm phát của người tiêu dùng.\n• Kỳ vọng lạm phát cao hơn: XẤU cho crypto.\n"
     "• Niềm tin giảm mạnh: lo suy thoái, tác động lẫn lộn."),
]

# số thực tế CAO hơn dự báo thì thường thế nào với crypto (thấp hơn thì ngược lại); None = không có số dự báo rõ ràng
HIGHER_IS = {"pce": "XẤU", "cpi": "XẤU", "ppi": "XẤU", "nfp": "XẤU (ngắn hạn)", "unemp": "TỐT", "claims": "hơi TỐT",
             "gdp": "lẫn lộn", "retail": "hơi XẤU", "pmi": "hơi XẤU", "jolts": "hơi XẤU", "sentiment": "lẫn lộn"}
OPPOSITE = {"XẤU": "TỐT", "TỐT": "XẤU", "hơi XẤU": "hơi TỐT", "hơi TỐT": "hơi XẤU", "XẤU (ngắn hạn)": "TỐT",
            "lẫn lộn": "lẫn lộn"}


def brief(kind: str, explain: str) -> tuple[str, str]:
    """(1 dòng: tin này là gì, 1 dòng: cao/thấp hơn dự báo thì tốt/xấu) cho tin nhắn ngắn."""
    what = explain.split("\n")[0]
    hi = HIGHER_IS.get(kind)
    if hi:
        return what, f"Cao hơn dự báo → thường {hi} cho crypto · thấp hơn → thường {OPPOSITE[hi]}"
    bullets = [b.strip("• ").strip() for b in explain.split("\n")[1:3]]
    return what, " · ".join(bullets)


# Ngày FOMC công bố lãi suất (lịch Fed công bố trước) — dùng để thống kê phản ứng trong quá khứ
FOMC_DATES = [
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12", "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
]

macro_events = sa.Table(
    "macro_events", storage.meta,
    sa.Column("key", sa.String(64), primary_key=True),
    sa.Column("kind", sa.String(16), nullable=False),
    sa.Column("title", sa.String(128), nullable=False),
    sa.Column("time", sa.DateTime(timezone=True), nullable=False),
)


def classify(title: str) -> tuple[str, str]:
    t = title.lower()
    for pattern, kind, text in EXPLAIN:
        if re.search(pattern, t):
            return kind, text
    return "other", "Tin kinh tế Mỹ tác động mạnh — giá có thể biến động mạnh 2 chiều quanh giờ ra tin."


async def remember(events: list[dict]) -> None:
    """Lưu lại tin đã/ sắp diễn ra để tích lũy thống kê phản ứng (CPI, PPI... không có lịch sử miễn phí)."""
    async with storage.engine().begin() as c:
        for e in events:
            kind, _ = classify(e["title"])
            key = f"{kind}:{e['time']:%Y%m%d%H%M}"
            if not (await c.execute(sa.select(macro_events.c.key).where(macro_events.c.key == key))).first():
                await c.execute(macro_events.insert().values(key=key, kind=kind, title=e["title"][:128], time=e["time"]))


def _nfp_dates(start: datetime, end: datetime) -> list[datetime]:
    """Thứ Sáu đầu tiên mỗi tháng, 12:30 UTC (lịch thông thường của NFP)."""
    out, d = [], start.replace(day=1, hour=12, minute=30, second=0, microsecond=0)
    while d < end:
        first = d + timedelta(days=(4 - d.weekday()) % 7)
        out.append(first)
        d = (d + timedelta(days=32)).replace(day=1)
    return out


_btc: tuple[float, pd.DataFrame] | None = None


async def _btc_hourly() -> pd.DataFrame:
    global _btc
    if _btc and _btc[0] > time.time():
        return _btc[1]
    start = int((datetime.now(timezone.utc) - timedelta(days=760)).timestamp() * 1000)
    df = await binance.klines_since("BTCUSDT", "1h", start)
    _btc = (time.time() + 6 * 3600, df)
    return df


async def reaction_stats(kind: str) -> dict | None:
    """BTC trong 24h sau các lần tin loại `kind` ra: biến động TB, số lần tăng/giảm, so với ngày thường."""
    now = datetime.now(timezone.utc)
    times: list[datetime] = []
    if kind == "fomc":
        times = [datetime.fromisoformat(d).replace(hour=18, tzinfo=timezone.utc) for d in FOMC_DATES]
    elif kind == "nfp":
        times = _nfp_dates(now - timedelta(days=740), now)
    async with storage.engine().connect() as c:
        rows = (await c.execute(sa.select(macro_events.c.time).where(macro_events.c.kind == kind))).all()
    times += [storage._aware(r.time) for r in rows]
    times = sorted({t for t in times if t < now - timedelta(hours=24)})
    if len(times) < 3:
        return None
    df = await _btc_hourly()
    close = df["close"]
    moves = []
    for t in times:
        before = close[close.index <= pd.Timestamp(t)]
        after = close[close.index <= pd.Timestamp(t + timedelta(hours=24))]
        if len(before) and len(after) and after.index[-1] > before.index[-1]:
            moves.append(after.iloc[-1] / before.iloc[-1] - 1)
    if len(moves) < 3:
        return None
    base = (close.pct_change(24).abs()).mean()
    s = pd.Series(moves)
    return {"n": len(s), "avg_abs": float(s.abs().mean()), "up": int((s > 0).sum()), "down": int((s < 0).sum()),
            "max_up": float(s.max()), "max_down": float(s.min()), "normal_abs": float(base)}


def stats_text(st: dict | None) -> str:
    if not st:
        return "📊 Chưa đủ dữ liệu lịch sử cho loại tin này (bot đang tự thu thập dần)."
    return (f"📊 <b>BTC 24h sau {st['n']} lần tin này gần đây</b>: biến động TB ±{st['avg_abs']:.1%} "
            f"(ngày thường ±{st['normal_abs']:.1%}) · tăng {st['up']} lần, giảm {st['down']} lần · "
            f"mạnh nhất {st['max_up']:+.1%} / {st['max_down']:+.1%}.\n"
            "<i>Thống kê quá khứ, không phải dự đoán.</i>")


async def week_events() -> list[dict]:
    """Tin Mỹ mức High + Medium trong tuần (lưu lại tin High để tích lũy thống kê)."""
    evs = await macro.us_calendar(("High", "Medium"))
    await remember([e for e in evs if e["impact"] == "High"])
    return evs


async def detail_text(e: dict) -> str:
    kind, explain = classify(e["title"])
    extra = []
    if e.get("forecast"):
        extra.append(f"Dự báo: <b>{escape(str(e['forecast']))}</b>")
    if e.get("previous"):
        extra.append(f"Kỳ trước: {escape(str(e['previous']))}")
    level = "🔴 Tác động mạnh" if e.get("impact") == "High" else "🟠 Tác động vừa"
    return (f"📌 <b>{escape(vi_title(e['title']))}</b> · {e['time'].astimezone(VN_TZ):%H:%M %d/%m} (giờ VN) · {level}\n"
            + (" · ".join(extra) + "\n" if extra else "") + f"\n{escape(explain)}\n\n{stats_text(await reaction_stats(kind))}\n\n"
            + ("⏸ Bot tạm dừng tín hiệu mới từ 3 giờ trước đến 1 giờ sau tin." if e.get("impact") == "High" else ""))


async def recent_events(days: int = 7) -> list[dict]:
    """Tin tác động mạnh đã diễn ra trong `days` ngày (bot tự lưu khi đọc lịch)."""
    now = datetime.now(timezone.utc)
    async with storage.engine().connect() as c:
        rows = (await c.execute(sa.select(macro_events).where(macro_events.c.time >= now - timedelta(days=days),
                                                              macro_events.c.time <= now)
                                .order_by(macro_events.c.time))).all()
    return [{"title": r.title, "kind": r.kind, "time": storage._aware(r.time)} for r in rows]


# ---------------------------------------------------------------- tên tin tiếng Việt
# (mẫu tên tin ForexFactory, tên tiếng Việt) — mẫu cụ thể đặt trước mẫu chung
VI_TITLES: list[tuple[str, str]] = [
    (r"^core pce price index", "Lạm phát lõi PCE"),
    (r"^pce price index", "Lạm phát PCE"),
    (r"^core cpi", "Lạm phát lõi CPI"),
    (r"^cpi", "Lạm phát CPI"),
    (r"^core ppi", "Giá sản xuất lõi PPI"),
    (r"^ppi", "Giá sản xuất PPI"),
    (r"^adp non-farm employment change", "Việc làm tư nhân ADP"),
    (r"^non-farm employment change", "Bảng lương phi nông nghiệp NFP"),
    (r"^unemployment rate", "Tỉ lệ thất nghiệp"),
    (r"^unemployment claims", "Đơn trợ cấp thất nghiệp"),
    (r"^average hourly earnings", "Thu nhập bình quân theo giờ"),
    (r"^federal funds rate", "Quyết định lãi suất Fed"),
    (r"^fomc statement", "Tuyên bố của Fed (FOMC)"),
    (r"^fomc press conference", "Họp báo của Fed"),
    (r"^fomc meeting minutes", "Biên bản họp Fed"),
    (r"^fomc economic projections", "Dự báo kinh tế của Fed"),
    (r"^fomc member (\w+) speaks", r"Thành viên Fed \1 phát biểu"),
    (r"^fed chair (\w+) (speaks|testifies)", r"Chủ tịch Fed \1 phát biểu"),
    (r"gdp price index", "Chỉ số giá GDP"),
    (r"^beige book", "Báo cáo kinh tế Beige Book của Fed"),
    (r"^challenger job cuts", "Số việc làm bị cắt giảm (Challenger)"),
    (r"^(advance|prelim|final) gdp", "Tăng trưởng GDP"),
    (r"^gdp", "Tăng trưởng GDP"),
    (r"^core retail sales", "Doanh số bán lẻ lõi"),
    (r"^retail sales", "Doanh số bán lẻ"),
    (r"^ism manufacturing pmi", "PMI sản xuất ISM"),
    (r"^ism services pmi", "PMI dịch vụ ISM"),
    (r"^(flash|final) manufacturing pmi", "PMI sản xuất"),
    (r"^(flash|final) services pmi", "PMI dịch vụ"),
    (r"^jolts job openings", "Việc làm còn trống JOLTS"),
    (r"^cb consumer confidence", "Niềm tin tiêu dùng CB"),
    (r"^(prelim|revised) uom consumer sentiment", "Tâm lý tiêu dùng (ĐH Michigan)"),
    (r"^(prelim|revised) uom inflation expectations", "Kỳ vọng lạm phát (ĐH Michigan)"),
    (r"^core durable goods orders", "Đơn hàng lâu bền lõi"),
    (r"^durable goods orders", "Đơn hàng lâu bền"),
    (r"^personal spending", "Chi tiêu cá nhân"),
    (r"^personal income", "Thu nhập cá nhân"),
    (r"^employment cost index", "Chỉ số chi phí lao động"),
    (r"^(prelim |revised )?unit labor costs", "Chi phí lao động đơn vị"),
    (r"^(prelim |revised )?nonfarm productivity", "Năng suất lao động"),
    (r"^empire state manufacturing index", "Chỉ số sản xuất New York"),
    (r"^philly fed manufacturing index", "Chỉ số sản xuất Philadelphia"),
    (r"^industrial production", "Sản xuất công nghiệp"),
    (r"^import prices", "Giá nhập khẩu"),
    (r"^trade balance", "Cán cân thương mại"),
    (r"^pending home sales", "Nhà chờ bán"),
    (r"^new home sales", "Doanh số nhà mới"),
    (r"^existing home sales", "Doanh số nhà cũ"),
    (r"^building permits", "Giấy phép xây dựng"),
    (r"^housing starts", "Nhà khởi công"),
    (r"^crude oil inventories", "Tồn kho dầu thô"),
    (r"^(\d+)-y bond auction", r"Đấu giá trái phiếu \1 năm"),
    (r"^treasury currency report", "Báo cáo tiền tệ Bộ Tài chính"),
    (r"^president \w+ speaks", "Tổng thống Mỹ phát biểu"),
    (r"^bank holiday", "Ngày nghỉ lễ ngân hàng"),
]
VI_SUFFIX = {"m/m": "(so tháng trước)", "y/y": "(so năm trước)", "q/q": "(so quý trước)"}


def vi_title(title: str) -> str:
    """'Core CPI m/m' -> 'Lạm phát lõi CPI (so tháng trước)'. Tên chưa có trong từ điển -> giữ nguyên."""
    t = title.strip()
    low = t.lower()
    for pattern, vi in VI_TITLES:
        m = re.search(pattern, low)
        if m:
            name = m.expand(vi)
            # giữ chữ hoa tên riêng (vd thành viên Fed)
            for w in t.split():
                if w.lower() in name.lower().split() and w[:1].isupper() and w.lower() not in ("fed", "cpi", "ppi"):
                    name = re.sub(rf"\b{re.escape(w.lower())}\b", w, name)
            suffix = next((v for k, v in VI_SUFFIX.items() if low.endswith(k)), "")
            return f"{name} {suffix}".strip()
    return t
