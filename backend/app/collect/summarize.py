import re

from app.claude_client import run_claude
from app.collect.config import LLM_BASE_URL, SUMMARY_TIMEOUT

SUMMARY_SYSTEM_PROMPT = (
    "너는 채용공고를 3줄로 요약하고 핵심 자격요건을 뽑는 도우미다. "
    "답변의 맨 마지막 줄에 반드시 '기술스택: 키워드1, 키워드2' 형식으로 "
    "공고에 등장한 기술 스택을 쉼표로 구분해 나열하라."
)

_STACK_RE = re.compile(r"기술스택\s*[:：]\s*(.+)")


def extract_stacks(content: str) -> list[str]:
    m = _STACK_RE.search(content or "")
    if not m:
        return []
    return [s.strip() for s in re.split(r"[,·]", m.group(1)) if s.strip()]


async def summarize(prompt, settings, *, http, model="", runner=run_claude, on_step=None) -> str | None:
    if settings.summary_backend == "claude":
        full = f"{SUMMARY_SYSTEM_PROMPT}\n\n{prompt}"
        text = await runner(full, model=model, timeout=SUMMARY_TIMEOUT, on_step=on_step)
        return text or None
    # local: LM Studio OpenAI 호환 chat completions.
    # settings.model은 LM Studio 로컬 모델명 — claude 티어(model 인자)와 무관하다.
    body = {
        "model": settings.model,
        "messages": [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3, "max_tokens": 800, "tools": [],
    }
    r = await http.post(
        f"{LLM_BASE_URL}/v1/chat/completions", json=body, timeout=SUMMARY_TIMEOUT
    )
    content = (r.json().get("choices") or [{}])[0].get("message", {}).get("content")
    return content or None
