"""claude -p 호출의 작업별 모델 티어.

정책만 담는다 — 프로세스 실행은 app.claude_client, 저장은 app.settings_repo.
소비자가 collect/summarize.py와 research/runner.py 둘이라, 어느 한쪽에 두면
다른 패키지를 끌어온다.
"""

# 싼 것 → 유능한 것 순. 승급은 이 순서로 한 칸씩 올라간다.
LADDER = ("haiku", "sonnet", "opus")

# 작업 종류별 기본 티어. 설정 오버라이드가 비어 있을 때 쓰인다.
TASK_MODEL = {"summary": "haiku", "research": "sonnet"}


def escalate(model: str) -> str:
    """한 단계 위 티어. 상한이거나 사다리 밖 값이면 그대로 반환.

    상한에서 예외를 던지지 않는 이유: 설정으로 opus를 고정한 사용자의
    재시도가 크래시하면 안 된다. 상한에서의 승급 = 같은 모델로 재시도.
    """
    try:
        i = LADDER.index(model)
    except ValueError:
        return model
    return LADDER[min(i + 1, len(LADDER) - 1)]


def resolve(task: str, override: str = "", *, escalated: bool = False) -> str:
    """override(설정) → 비어 있으면 TASK_MODEL[task]. escalated면 한 단계 승급.

    알 수 없는 task는 KeyError — 오타를 조용히 기본 티어로 넘기지 않는다.
    """
    model = (override or "").strip() or TASK_MODEL[task]
    return escalate(model) if escalated else model
