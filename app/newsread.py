"""📖 Đọc tin bằng tiếng Việt: bấm tiêu đề tin (ở cả 2 bot) -> Bot Tin tức gửi bản tóm tắt tiếng Việt + nút mở bài gốc.

Mỗi tin được lưu theo mã ngắn (kv "nw:<mã>"); tiêu đề là link t.me/<Bot Tin tức>?start=nw_<mã>.
Tóm tắt do AI viết từ nội dung bài (tải trang gốc; trang chặn thì dùng đoạn mô tả trong RSS), lưu lại để không gọi AI lặp.
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from datetime import datetime

from app import ai, storage
from app.config import VN_TZ
from app.data.http import get_text

log = logging.getLogger(__name__)
MAX_CHARS = 6000


def _id(h) -> str:
    return hashlib.sha1((h.link or h.title).encode()).hexdigest()[:10]


async def ref(h) -> str:
    """Lưu tin (tiêu đề, link, mô tả, giờ) và trả mã ngắn."""
    nid = _id(h)
    if not await storage.kv_get(f"nw:{nid}"):
        await storage.kv_set(f"nw:{nid}", json.dumps({"t": h.title, "l": h.link, "s": getattr(h, "summary", ""),
                                                      "ts": h.time.isoformat()}, ensure_ascii=False))
    return nid


def link(nid: str, fallback: str = "") -> str:
    """Link mở bản tóm tắt trong Bot Tin tức (chưa biết tên bot thì dùng link bài gốc)."""
    from app import reports
    return f"https://t.me/{reports.NEWS_USERNAME}?start=nw_{nid}" if reports.NEWS_USERNAME else fallback


async def link_for(h) -> str:
    return link(await ref(h), h.link)


def _plain(raw: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


async def article_text(url: str) -> str:
    """Nội dung chính của bài (các đoạn <p> đủ dài). Trang chặn / lỗi -> chuỗi rỗng."""
    try:
        page = await get_text(url, ttl=3600)
    except Exception as exc:  # noqa: BLE001
        log.info("Không tải được bài %s: %s", url, exc)
        return ""
    paras = [_plain(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", page, flags=re.S | re.I)]
    out, size = [], 0
    for p in paras:
        if len(p) < 50 or re.search(r"cookie|subscribe|newsletter|all rights reserved|sign up", p, re.I):
            continue
        out.append(p)
        size += len(p)
        if size > MAX_CHARS:
            break
    return "\n".join(out)[:MAX_CHARS]


PROMPT = ("Tóm tắt bài báo crypto dưới đây cho người Việt KHÔNG biết tiếng Anh. Trả về ĐÚNG định dạng:\n"
          "TIÊU ĐỀ: <tiêu đề tiếng Việt>\n"
          "- <ý chính 1>\n- <ý chính 2>\n- <ý chính 3> (3 đến 5 ý, mỗi ý 1 câu ngắn: ai, làm gì, con số quan trọng)\n"
          "ẢNH HƯỞNG: <1 câu: tác động có thể tới thị trường crypto / coin liên quan; không rõ thì ghi 'Ảnh hưởng nhỏ'>\n"
          "Chỉ dùng thông tin trong bài, không bịa. Viết hoàn toàn bằng tiếng Việt, giữ nguyên tên riêng và mã coin.")


def _format(raw: str, when: str) -> str | None:
    title = re.search(r"TIÊU ĐỀ:\s*(.+)", raw)
    impact = re.search(r"ẢNH HƯỞNG:\s*(.+)", raw)
    bullets = [b.strip() for b in re.findall(r"^\s*[-•*]\s*(.+)$", raw, flags=re.M)][:5]
    if not title or not bullets:
        return None
    lines = [f"📰 <b>{html.escape(title.group(1).strip())}</b>", f"🕒 {when}", ""]
    lines += [f"• {html.escape(b)}" for b in bullets]
    if impact:
        lines += ["", f"💡 <b>Ảnh hưởng:</b> {html.escape(impact.group(1).strip())}"]
    return "\n".join(lines)


async def summary(nid: str, *, require_ai: bool = False) -> tuple[str, str] | None:
    """(bản tóm tắt HTML, link bài gốc) — None nếu không có tin này, hoặc AI chưa tóm tắt được khi `require_ai`."""
    raw = await storage.kv_get(f"nw:{nid}")
    if not raw:
        return None
    item = json.loads(raw)
    cached = await storage.kv_get(f"nws:{nid}")
    if cached:
        return cached, item["l"]
    when = datetime.fromisoformat(item["ts"]).astimezone(VN_TZ).strftime("%H:%M %d/%m")
    body = await article_text(item["l"]) if item["l"] else ""
    source = body if len(body) > 300 else _plain(item.get("s") or "")
    text = None
    if ai.enabled():
        ans, _ = await ai.ask(f"{PROMPT}\n\nTIÊU ĐỀ GỐC: {item['t']}", source or item["t"], "summary")
        if ans and ans not in (ai.OUT_OF_SCOPE, ai.OTHER_PLACE):
            text = _format(ans, when)
    if text is None and require_ai:
        return None
    if text is None:  # AI lỗi -> ít nhất có tiêu đề + mô tả đã dịch
        from app.assistant import vi_titles
        desc = _plain(item.get("s") or "")[:400]
        vi = await vi_titles([item["t"]] + ([desc] if desc else []))
        text = "\n".join([f"📰 <b>{html.escape(vi[0])}</b>", f"🕒 {when}"]
                         + ([f"\n{html.escape(vi[1])}"] if len(vi) > 1 and vi[1] != desc else [])
                         + ["\n<i>Chưa tóm tắt được nội dung, thử lại sau ít phút.</i>"])
        return text, item["l"]
    await storage.kv_set(f"nws:{nid}", text)
    return text, item["l"]
