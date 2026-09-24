"""AI hỏi đáp (tùy chọn): Gemini -> Groq -> OpenRouter, lỗi hết thì trả lời bằng dữ liệu có sẵn.

- Tự dò model đang dùng được của từng nhà cung cấp (lưu 12 giờ) -> nhà cung cấp đổi/ngừng model không phải sửa code.
- AI CHỈ giải thích dựa trên dữ liệu bot cung cấp (lịch sự kiện, thị trường, tín hiệu). Không tạo tín hiệu, không đoán giá.
"""
from __future__ import annotations

import logging
import re
import time

import httpx

from app.config import settings

log = logging.getLogger(__name__)

SYSTEM = (
    "Bạn là trợ lý phân tích thị trường crypto của một bot Telegram, trả lời bằng TIẾNG VIỆT, ngắn gọn, dễ hiểu cho "
    "người mới (tối đa khoảng 200 từ, dùng gạch đầu dòng khi hợp lý). "
    "Chỉ dựa vào DỮ LIỆU được cung cấp và kiến thức kinh tế phổ thông. Nếu dữ liệu không có thì nói rõ là không có. "
    "KHÔNG bịa số liệu, KHÔNG khẳng định giá sẽ tăng/giảm, KHÔNG đưa lời khuyên mua bán cụ thể; có thể nêu kịch bản "
    "'nếu... thì thường...' kèm mức độ chắc chắn. Không dùng markdown (** hay #); dùng văn bản thường."
)

# thứ tự ưu tiên model (nếu còn tồn tại); không có thì tự chọn model phù hợp trong danh sách nhà cung cấp trả về
PREFER = {
    "gemini": ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest", "gemini-1.5-flash"],
    "groq": ["llama-3.3-70b-versatile", "llama-3.1-70b-versatile", "llama-3.1-8b-instant"],
    "openrouter": ["meta-llama/llama-3.3-70b-instruct:free", "deepseek/deepseek-chat-v3-0324:free",
                   "google/gemini-2.0-flash-exp:free", "mistralai/mistral-7b-instruct:free"],
}
_models: dict[str, tuple[float, list[str]]] = {}
_down_until: dict[str, float] = {}   # tạm bỏ qua nhà cung cấp vừa lỗi hết lượt


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
            names = [n for n in names if "flash" in n and "vision" not in n and "tts" not in n and "image" not in n]
        elif provider == "groq":
            r = await client.get("https://api.groq.com/openai/v1/models",
                                 headers={"Authorization": f"Bearer {settings.groq_key}"})
            r.raise_for_status()
            names = [m["id"] for m in r.json().get("data", []) if m.get("active", True)
                     and not re.search(r"whisper|guard|tts|vision", m["id"])]
        else:
            r = await client.get("https://openrouter.ai/api/v1/models")
            r.raise_for_status()
            names = [m["id"] for m in r.json().get("data", []) if m["id"].endswith(":free")]
    except Exception as exc:  # noqa: BLE001
        log.warning("AI: không lấy được danh sách model %s: %s", provider, exc)
    ordered = [m for m in PREFER[provider] if m in names] + [m for m in names if m not in PREFER[provider]]
    if not ordered:
        ordered = PREFER[provider]
    _models[provider] = (time.time() + 12 * 3600, ordered[:3])
    return ordered[:3]


async def _call(provider: str, model: str, prompt: str, client: httpx.AsyncClient) -> str:
    if provider == "gemini":
        r = await client.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                              params={"key": settings.gemini_key},
                              json={"systemInstruction": {"parts": [{"text": SYSTEM}]},
                                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                                    "generationConfig": {"temperature": 0.3, "maxOutputTokens": 800}})
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    url = ("https://api.groq.com/openai/v1/chat/completions" if provider == "groq"
           else "https://openrouter.ai/api/v1/chat/completions")
    key = settings.groq_key if provider == "groq" else settings.openrouter_key
    r = await client.post(url, headers={"Authorization": f"Bearer {key}"},
                          json={"model": model, "temperature": 0.3, "max_tokens": 800,
                                "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _clean(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)   # model "suy nghĩ" in ra phần nháp
    text = text.replace("**", "").replace("__", "")
    return re.sub(r"^#+\s*", "", text, flags=re.M).strip()


async def ask(question: str, context: str) -> tuple[str | None, str]:
    """Trả (câu trả lời, nguồn). (None, lý do) nếu mọi nhà cung cấp đều lỗi / chưa cấu hình."""
    keys = {"gemini": settings.gemini_key, "groq": settings.groq_key, "openrouter": settings.openrouter_key}
    prompt = f"DỮ LIỆU CỦA BOT (thời gian thực):\n{context}\n\nCÂU HỎI: {question}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        for provider, key in keys.items():
            if not key or _down_until.get(provider, 0) > time.time():
                continue
            for model in await _discover(provider, client):
                try:
                    text = _clean(await _call(provider, model, prompt, client))
                    if text:
                        return text, f"{provider}:{model}"
                except httpx.HTTPStatusError as exc:
                    code = exc.response.status_code
                    log.warning("AI %s/%s lỗi HTTP %s", provider, model, code)
                    if code in (401, 403):
                        break                                   # sai key -> bỏ nhà cung cấp này
                    if code == 429:
                        _down_until[provider] = time.time() + 300   # hết lượt -> nghỉ 5 phút, chuyển nhà khác
                        break
                    if code == 404:
                        _models.pop(provider, None)              # model đã bị ngừng -> dò lại lần sau
                except Exception as exc:  # noqa: BLE001
                    log.warning("AI %s/%s lỗi: %s", provider, model, exc)
    return None, "không có nhà cung cấp AI nào trả lời được" if enabled() else "chưa cấu hình key AI"
