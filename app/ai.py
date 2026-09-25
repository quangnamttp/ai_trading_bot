"""AI hỏi đáp (tùy chọn): Gemini -> Groq -> OpenRouter, lỗi hết thì trả lời bằng dữ liệu có sẵn.

- Tự dò model đang dùng được của từng nhà cung cấp (lưu 12 giờ), chỉ dùng model đủ mạnh (bỏ model nhỏ hay lặp/bịa).
- Kiểm tra câu trả lời: lặp câu, quá nhiều con số không có trong dữ liệu -> bỏ, thử nhà cung cấp kế tiếp.
- Phạm vi (đều trong chat riêng): "spot" (danh mục Spot), "futures" (tín hiệu đã gửi), "market" (thị trường chung),
  "news" (tóm tắt tin), "translate" (dịch tiêu đề tin).
  Câu hỏi ngoài phạm vi -> AI trả về mã OUT_OF_SCOPE / OTHER_PLACE để bot trả lời cố định.
"""
from __future__ import annotations

import logging
import re
import time

import httpx

from app.config import settings

log = logging.getLogger(__name__)

OUT_OF_SCOPE = "OUT_OF_SCOPE"
OTHER_PLACE = "OTHER_PLACE"

BASE = (
    "Bạn trả lời bằng TIẾNG VIỆT, ngắn gọn, dễ hiểu cho người mới (tối đa khoảng 180 từ, gạch đầu dòng khi hợp lý, "
    "không dùng markdown ** hay #). CHỈ dùng số liệu có trong DỮ LIỆU CỦA BOT; không có thì nói là không có. "
    "KHÔNG bịa số, KHÔNG khẳng định giá chắc chắn tăng/giảm — chỉ nêu kịch bản 'nếu... thì thường...'. "
)
SCOPES = {
    "spot": BASE + (
        "Bạn là TRỢ LÝ SPOT trong chat riêng, chỉ lo DANH MỤC SPOT của người hỏi (chỉ mua bán thật, không short, "
        "không đòn bẩy). Phạm vi: coin trong danh mục của họ — giá vốn, lời/lỗ, nên DCA bao nhiêu tiền ở mốc nào, "
        "khi nào dừng DCA, chốt lời từng phần theo kịch bản, rủi ro. Mốc giá và số tiền CHỈ lấy từ 'VỊ THẾ SPOT' và "
        "'KẾ HOẠCH DO BOT TÍNH'. "
        f"Nếu câu hỏi là tin tức / thị trường chung, không gắn với coin trong danh mục -> chỉ trả lời đúng: {OTHER_PLACE}. "
        f"Nếu câu hỏi không liên quan crypto / giao dịch (thời tiết, đời sống...) -> chỉ trả lời đúng: {OUT_OF_SCOPE}."
    ),
    "futures": BASE + (
        "Bạn là TRỢ LÝ TÍN HIỆU FUTURES trong chat riêng, chỉ trả lời về TÍN HIỆU BOT ĐÃ GỬI có trong dữ liệu. "
        "Phạm vi: vì sao bot LONG/SHORT (dựa vào 'Lý do bot'), khi nào về bờ (chỉ nêu giá cần quay lại mức nào, cách "
        "bao nhiêu %, KHÔNG hứa thời gian), SL/TP/trailing đang ở đâu, quy tắc quản lý lệnh của bot (chốt 50% ở TP1, "
        "trailing kích hoạt ở +1R), rủi ro cần theo dõi. Không khuyên gồng lỗ, không khuyên dời SL xa hơn. "
        f"Nếu câu hỏi là tin tức / thị trường chung -> chỉ trả lời đúng: {OTHER_PLACE}. "
        f"Nếu câu hỏi không liên quan crypto / giao dịch -> chỉ trả lời đúng: {OUT_OF_SCOPE}."
    ),
    "market": BASE + (
        "Bạn là TRỢ LÝ THỊ TRƯỜNG CHUNG trong chat riêng. Phạm vi: thị trường crypto nói chung, mọi coin, tin tức, "
        "lịch sự kiện kinh tế và ảnh hưởng tới crypto, xu hướng, dòng tiền. "
        f"Nếu câu hỏi về lệnh / danh mục / vốn cá nhân của người hỏi -> chỉ trả lời đúng: {OTHER_PLACE}. "
        f"Nếu câu hỏi không liên quan crypto / tài chính (thời tiết, đời sống...) -> chỉ trả lời đúng: {OUT_OF_SCOPE}."
    ),
    "news": BASE + "Bạn viết tóm tắt tin tức thị trường cực ngắn (tối đa 3 gạch đầu dòng, mỗi dòng dưới 20 từ).",
    "translate": ("Dịch từng tiêu đề tin tức crypto sang TIẾNG VIỆT tự nhiên, ngắn gọn. Giữ nguyên tên riêng, mã coin, "
                  "con số. Trả về đúng số dòng, mỗi dòng dạng 'số. bản dịch', không thêm gì khác."),
}

# thứ tự ưu tiên model đủ mạnh; model nhỏ (hay lặp, bịa) bị loại
PREFER = {
    "gemini": ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest", "gemini-1.5-flash"],
    "groq": ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "moonshotai/kimi-k2-instruct", "qwen/qwen3-32b",
             "llama-3.1-70b-versatile"],
    "openrouter": ["meta-llama/llama-3.3-70b-instruct:free", "deepseek/deepseek-chat-v3-0324:free",
                   "deepseek/deepseek-chat-v3.1:free", "qwen/qwen-2.5-72b-instruct:free", "google/gemini-2.0-flash-exp:free"],
}
WEAK = re.compile(r"(\b|-)(1b|2b|3b|7b|8b|9b|mini|nano|instant|tiny|small|lite|gemma-3n|whisper|guard|tts|vision|image|embed)",
                  re.I)
_models: dict[str, tuple[float, list[str]]] = {}
_down_until: dict[str, float] = {}


def enabled() -> bool:
    return bool(settings.gemini_key or settings.groq_key or settings.openrouter_key)


async def _discover(provider: str, client: httpx.AsyncClient) -> list[str]:
    cached = _models.get(provider)
    if cached and cached[0] > time.time():
        return cached[1]
    names: list[str] = []
    try:
        if provider == "gemini":
            r = await client.get("https://generativelanguage.googleapis.com/v1beta/models",
                                 params={"key": settings.gemini_key, "pageSize": 200})
            r.raise_for_status()
            names = [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
                     if "generateContent" in m.get("supportedGenerationMethods", [])]
            names = [n for n in names if re.search(r"gemini-[\d.]+-(flash|pro)", n) and not WEAK.search(n.replace("flash-lite", "lite"))]
        elif provider == "groq":
            r = await client.get("https://api.groq.com/openai/v1/models",
                                 headers={"Authorization": f"Bearer {settings.groq_key}"})
            r.raise_for_status()
            names = [m["id"] for m in r.json().get("data", []) if m.get("active", True) and not WEAK.search(m["id"])]
        else:
            r = await client.get("https://openrouter.ai/api/v1/models")
            r.raise_for_status()
            names = [m["id"] for m in r.json().get("data", []) if m["id"].endswith(":free") and not WEAK.search(m["id"])]
    except Exception as exc:  # noqa: BLE001
        log.warning("AI: không lấy được danh sách model %s: %s", provider, exc)
    ordered = [m for m in PREFER[provider] if m in names] + [m for m in names if m not in PREFER[provider]]
    if not names:
        ordered = PREFER[provider]
    _models[provider] = (time.time() + 12 * 3600, ordered[:3])
    return ordered[:3]


async def _call(provider: str, model: str, system: str, prompt: str, client: httpx.AsyncClient) -> str:
    if provider == "gemini":
        r = await client.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                              params={"key": settings.gemini_key},
                              json={"systemInstruction": {"parts": [{"text": system}]},
                                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                                    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 700}})
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts if not p.get("thought"))
    url = ("https://api.groq.com/openai/v1/chat/completions" if provider == "groq"
           else "https://openrouter.ai/api/v1/chat/completions")
    key = settings.groq_key if provider == "groq" else settings.openrouter_key
    r = await client.post(url, headers={"Authorization": f"Bearer {key}"},
                          json={"model": model, "temperature": 0.2, "max_tokens": 700, "frequency_penalty": 0.5,
                                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _clean(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = text.replace("**", "").replace("__", "")
    return re.sub(r"^#+\s*", "", text, flags=re.M).strip()


def degenerate(text: str) -> bool:
    """Câu trả lời lặp lại (model yếu hay bị) -> bỏ."""
    words = text.lower().split()
    if len(words) < 12:
        return False
    grams = [" ".join(words[i:i + 6]) for i in range(len(words) - 5)]
    top = max(grams.count(g) for g in set(grams))
    return top >= 3 or len(set(words)) / len(words) < 0.3


def invented_numbers(text: str, context: str) -> int:
    """Số lượng con số (≥ 2 chữ số) trong câu trả lời mà dữ liệu không có — nhiều = đang bịa."""
    def numbers(s: str) -> set[float]:
        out = set()
        for n in re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", s):
            try:
                out.add(float(n.replace(",", "")))
            except ValueError:
                pass
        return out

    known = numbers(context)
    # số làm tròn (64,123 -> 64,100) vẫn tính là có trong dữ liệu: lệch <= 1%
    return sum(1 for n in numbers(text)
               if n >= 10 and not any(abs(n - k) <= 0.01 * max(k, 1) for k in known))


async def ask(question: str, context: str, scope: str = "market") -> tuple[str | None, str]:
    """Trả (câu trả lời | OUT_OF_SCOPE | OTHER_PLACE, nguồn). (None, lý do) nếu không nhà cung cấp nào trả lời tốt."""
    keys = {"gemini": settings.gemini_key, "groq": settings.groq_key, "openrouter": settings.openrouter_key}
    system = SCOPES.get(scope, SCOPES["market"])
    prompt = f"DỮ LIỆU CỦA BOT (thời gian thực):\n{context}\n\nCÂU HỎI: {question}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        for provider, key in keys.items():
            if not key or _down_until.get(provider, 0) > time.time():
                continue
            for model in await _discover(provider, client):
                try:
                    text = _clean(await _call(provider, model, system, prompt, client))
                except httpx.HTTPStatusError as exc:
                    code = exc.response.status_code
                    log.warning("AI %s/%s lỗi HTTP %s", provider, model, code)
                    if code in (401, 403):
                        break
                    if code == 429:
                        _down_until[provider] = time.time() + 300
                        break
                    if code == 404:
                        _models.pop(provider, None)
                    continue
                except Exception as exc:  # noqa: BLE001
                    log.warning("AI %s/%s lỗi: %s", provider, model, exc)
                    continue
                for code in (OUT_OF_SCOPE, OTHER_PLACE):
                    if code in text[:40]:
                        return code, f"{provider}:{model}"
                if scope == "translate" and text:
                    return text, f"{provider}:{model}"
                if not text or degenerate(text):
                    log.warning("AI %s/%s trả lời lặp/rỗng -> bỏ", provider, model)
                    continue
                if invented_numbers(text, context + question) > 3:
                    log.warning("AI %s/%s có nhiều số không có trong dữ liệu -> bỏ", provider, model)
                    continue
                return text, f"{provider}:{model}"
    return None, "không có nhà cung cấp AI nào trả lời được" if enabled() else "chưa cấu hình key AI"
