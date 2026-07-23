# 알림 발송 이관 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** n8n `03-notifier`(Discord 공고 알림)를 career-agent로 이관하고, 전역 필터를 존중하며, 죽어 있던 기존 알림 경로를 되살린다.

**Architecture:** 웹훅 출처를 `app_settings`로 통일(모듈 캐시 + env 폴백)하고, 순수 로직(임베드 빌더·필터·청크)과 I/O(`notify_tick`)를 분리한다. 스케줄 5분 주기 + 수동 트리거, `run_log`에 `pipeline='notifier'`로 기록. `notify_enabled` 플래그 기본 false로 배포해 컷오버를 통제한다.

**Tech Stack:** FastAPI + asyncpg + Alembic + APScheduler(백엔드), React 18 + TypeScript + vitest(프론트).

## Global Constraints

- `jobs.notified_at`과 인덱스는 baseline(0001)에 **이미 존재** — 컬럼 마이그레이션 금지/불필요. 타입: `id`=`bigint`, `tech_stacks`=`TEXT[]`(asyncpg가 list 반환), `locations`=`text`.
- 전역 필터를 알림에 적용하고, **걸러진 공고는 발송 없이 `notified_at`을 찍어 소비**한다.
- 필터 규칙은 목록 쿼리와 동일: 기업=정확일치 제외, 지역=`locations`에 허용 지역 포함, **빈 배열이면 미적용**.
- **청크 단위 마킹**: 임베드 10개 묶음을 보낼 때마다 그 청크의 id만 마킹한다(중간 실패 시 중복 발송 방지).
- `push_embeds`는 실패 시 **예외를 던진다**(기존 `push`는 조용히 무시 — 시그니처·동작 유지).
- 웹훅 출처는 설정(모듈 캐시) → env 폴백. `discord.py` 파일은 **이동하지 않는다**(임포트 3곳 변경은 컷오버 후 별도 정리).
- 배치 30, 청크 10, 색상 5814783, 주기 5분은 원본 값 그대로 상수.
- `notify_enabled` 기본 **false**. 수동 트리거는 이 플래그와 무관하게 동작.
- pytest `asyncio_mode=auto`(평범한 `async def`, 데코레이터 없음), 실 DB 대신 fake conn. 백엔드 `cd backend && python -m pytest`, 프론트 `cd frontend && npx vitest run` + `npx tsc --noEmit`.

---

### Task 1: 마이그레이션 0006 + `notify_enabled` 설정

**Files:**
- Create: `backend/migrations/versions/0006_notify_enabled.py`
- Modify: `backend/app/settings_repo.py`
- Test: `backend/tests/test_settings_repo.py`

**Interfaces:**
- Produces: `app_settings.notify_enabled boolean NOT NULL DEFAULT false`; `Settings.notify_enabled: bool = False`; `_COLUMNS`/`SETTINGS_DEFAULTS`에 동일 포함.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_settings_repo.py` 끝에 추가:

```python
def test_notify_enabled_defaults_false_and_is_persisted():
    from app.settings_repo import Settings, SETTINGS_DEFAULTS, build_upsert
    s = Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"]))
    assert s.notify_enabled is False
    sql, params = build_upsert(Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], notify_enabled=True)))
    assert "notify_enabled" in sql
    assert True in params
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_settings_repo.py -q`
Expected: FAIL — `Settings`에 `notify_enabled` 없음.

- [ ] **Step 3: settings_repo.py 확장**

`SETTINGS_DEFAULTS`의 `hidden_companies=[],` 뒤에 추가:

```python
    notify_enabled=False,
```

`_COLUMNS` 끝(`"allowed_regions", "hidden_companies",` 뒤)에 추가:

```python
    "notify_enabled",
```

`Settings` 클래스의 `hidden_companies` 필드 뒤에 추가:

```python
    # 알림 발송 마스터 스위치 — 컷오버 통제를 위해 기본 false
    notify_enabled: bool = False
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_settings_repo.py -q`
Expected: PASS

- [ ] **Step 5: 마이그레이션 작성**

`backend/migrations/versions/0006_notify_enabled.py`:

```python
"""알림 발송 마스터 스위치

Revision ID: 0006_notify_enabled
Revises: 0005_global_filter
Create Date: 2026-07-23
"""
from alembic import op

revision = "0006_notify_enabled"
down_revision = "0005_global_filter"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE app_settings "
        "ADD COLUMN IF NOT EXISTS notify_enabled boolean NOT NULL DEFAULT false;"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE app_settings DROP COLUMN IF EXISTS notify_enabled;")
```

- [ ] **Step 6: 리비전 체인 + 전체 스위트**

Run: `cd backend && python -m alembic history | head -3 && python -m pytest -q`
Expected: `0005_global_filter -> 0006_notify_enabled (head)`, 전체 PASS.

- [ ] **Step 7: 커밋**

```bash
git add backend/migrations/versions/0006_notify_enabled.py backend/app/settings_repo.py backend/tests/test_settings_repo.py
git commit -m "feat(notify): notify_enabled 설정 추가(마이그 0006)"
```

---

### Task 2: 웹훅 출처 통일 — `set_webhook`·`push_embeds` + 배선

**Files:**
- Modify: `backend/app/research/discord.py`
- Modify: `backend/app/main.py` (lifespan)
- Modify: `backend/app/routers/settings.py` (저장 직후 갱신)
- Test: `backend/tests/test_research_discord.py`

**Interfaces:**
- Produces: `set_webhook(url: str) -> None`, `_url() -> str`(캐시→env 폴백), `async push_embeds(content: str | None, embeds: list[dict]) -> None`(실패 시 예외). `push(content)`의 시그니처·"조용히 무시" 동작은 **불변**.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_research_discord.py` 끝에 추가:

```python
async def test_set_webhook_overrides_env(monkeypatch):
    from app.research import discord
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://env.example/hook")
    discord.set_webhook("https://settings.example/hook")
    try:
        assert discord._url() == "https://settings.example/hook"
    finally:
        discord.set_webhook("")


async def test_url_falls_back_to_env_when_unset(monkeypatch):
    from app.research import discord
    discord.set_webhook("")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://env.example/hook")
    assert discord._url() == "https://env.example/hook"


async def test_push_embeds_raises_when_not_configured(monkeypatch):
    import pytest
    from app.research import discord
    discord.set_webhook("")
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    with pytest.raises(RuntimeError):
        await discord.push_embeds("hi", [{"title": "t"}])


async def test_push_embeds_posts_content_and_embeds(monkeypatch):
    from app.research import discord
    sent = {}

    class FakeResp:
        def raise_for_status(self): return None

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None):
            sent.update(url=url, json=json)
            return FakeResp()

    monkeypatch.setattr(discord.httpx, "AsyncClient", lambda **kw: FakeClient())
    discord.set_webhook("https://settings.example/hook")
    try:
        await discord.push_embeds("헤더", [{"title": "t"}])
    finally:
        discord.set_webhook("")
    assert sent["url"] == "https://settings.example/hook"
    assert sent["json"]["content"] == "헤더"
    assert sent["json"]["embeds"] == [{"title": "t"}]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_research_discord.py -q`
Expected: FAIL — `set_webhook`/`push_embeds` 없음.

- [ ] **Step 3: `discord.py` 확장**

`backend/app/research/discord.py`를 아래로 교체(기존 `push` 동작 유지):

```python
import logging
import os

import httpx

log = logging.getLogger("notify.discord")

# 웹훅 출처는 설정(app_settings.discord_webhook_url). 앱 시작·설정 저장 시 갱신하고,
# 미설정이면 env로 폴백한다. (env만 읽던 시절엔 컨테이너에 env가 없어 알림이 전부 죽어 있었다.)
_webhook = ""


def set_webhook(url: str) -> None:
    global _webhook
    _webhook = (url or "").strip()


def _url() -> str:
    return _webhook or os.environ.get("DISCORD_WEBHOOK_URL", "")


async def push(content: str) -> None:
    """Discord 웹훅으로 알림. 웹훅 미설정/실패는 조용히 무시(호출 흐름 비차단)."""
    url = _url()
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(
                url,
                json={"content": content},
                headers={"User-Agent": "career-agent"},
            )
    except Exception as e:  # noqa: BLE001 — 알림 실패는 무시
        log.warning("discord push failed: %s", e)


async def push_embeds(content: str | None, embeds: list[dict]) -> None:
    """임베드 카드 발송. push와 달리 실패 시 예외를 던진다 —
    알림기가 성공 여부로 notified_at 마킹을 결정하므로 삼키면 안 된다."""
    url = _url()
    if not url:
        raise RuntimeError("discord webhook not configured")
    payload: dict = {"embeds": embeds}
    if content:
        payload["content"] = content
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, json=payload, headers={"User-Agent": "career-agent"})
        r.raise_for_status()
```

- [ ] **Step 4: lifespan 배선 (main.py)**

import 블록에 추가:

```python
from app.research import discord
```

lifespan에서 `settings = await get_settings(conn)` 바로 다음 줄에 추가:

```python
    discord.set_webhook(settings.discord_webhook_url)  # 웹훅 출처=설정(env는 폴백)
```

- [ ] **Step 5: 설정 저장 시 갱신 (routers/settings.py)**

import에 추가:

```python
from app.research import discord
```

`write_settings`의 `saved = await put_settings(conn, body)` 다음 줄에 추가:

```python
    discord.set_webhook(saved.discord_webhook_url)  # 저장 즉시 반영
```

- [ ] **Step 6: 테스트 + 전체 스위트**

Run: `cd backend && python -m pytest tests/test_research_discord.py -q && python -m pytest -q`
Expected: 신규 4건 PASS, 전체 PASS.

- [ ] **Step 7: 커밋**

```bash
git add backend/app/research/discord.py backend/app/main.py backend/app/routers/settings.py backend/tests/test_research_discord.py
git commit -m "fix(notify): 웹훅 출처를 설정으로 통일 + 임베드 발송 추가(죽어있던 알림 부활)"
```

---

### Task 3: 알림기 순수 로직 — 임베드·필터·청크

**Files:**
- Create: `backend/app/notify/__init__.py` (빈 파일)
- Create: `backend/app/notify/notifier.py`
- Test: `backend/tests/test_notifier_pure.py`

**Interfaces:**
- Produces: 상수 `NOTIFY_BATCH=30`, `EMBED_CHUNK=10`, `EMBED_COLOR=5814783`; `build_embed(row) -> dict`, `passes_filter(row, allowed_regions, hidden_companies) -> bool`, `chunk(items, size=EMBED_CHUNK) -> list[list]`.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_notifier_pure.py`:

```python
from app.notify.notifier import (
    EMBED_COLOR, build_embed, chunk, passes_filter,
)


def _row(**kw):
    base = dict(id=1, source="wanted", job_id="1", company="미스릴", title="백엔드",
                url="https://x/1", locations="서울 강남구", min_career=1, max_career=3,
                tech_stacks=["python", "fastapi"], summary="좋은 회사\n기술스택: python, fastapi")
    base.update(kw)
    return base


def test_build_embed_strips_stack_line_from_description():
    e = build_embed(_row())
    assert "기술스택" not in e["description"]
    assert e["description"] == "좋은 회사"


def test_build_embed_fields_and_shape():
    e = build_embed(_row())
    assert e["title"] == "미스릴 — 백엔드"
    assert e["url"] == "https://x/1" and e["color"] == EMBED_COLOR
    names = [f["name"] for f in e["fields"]]
    assert names == ["경력", "기술스택", "출처"]
    assert e["fields"][0]["value"] == "1~3"
    assert e["fields"][1]["value"] == "python, fastapi"
    assert e["fields"][2]["value"] == "wanted"


def test_build_embed_career_unknown_and_empty_summary():
    e = build_embed(_row(min_career=None, max_career=None, summary=""))
    assert e["fields"][0]["value"] == "무관"
    assert e["description"] == "(요약 없음)"


def test_build_embed_truncates_long_description_and_title():
    e = build_embed(_row(summary="가" * 500, company="회" * 200, title="사" * 200))
    assert len(e["description"]) == 401 and e["description"].endswith("…")
    assert len(e["title"]) == 250


def test_passes_filter_hidden_company_excluded():
    assert passes_filter(_row(), [], ["미스릴"]) is False
    assert passes_filter(_row(), [], ["다른곳"]) is True


def test_passes_filter_region_allowlist():
    assert passes_filter(_row(), ["서울"], []) is True
    assert passes_filter(_row(), ["부산"], []) is False


def test_passes_filter_empty_arrays_pass_everything():
    assert passes_filter(_row(), [], []) is True


def test_chunk_splits_on_boundary():
    assert chunk(list(range(25)), 10) == [list(range(10)), list(range(10, 20)), [20, 21, 22, 23, 24]]
    assert chunk([], 10) == []
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_notifier_pure.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.notify'`

- [ ] **Step 3: 모듈 작성**

`backend/app/notify/__init__.py`: 빈 파일.

`backend/app/notify/notifier.py`:

```python
"""공고 알림 — n8n 03-notifier에서 이관. 순수 로직(임베드·필터·청크) + notify_tick."""
import re

NOTIFY_BATCH = 30       # 한 틱에 다룰 공고 수(원본 값)
EMBED_CHUNK = 10        # Discord 한 메시지당 임베드 상한
EMBED_COLOR = 5814783   # 원본 값

# 요약 본문 끝의 "기술스택: ..." 줄은 별도 필드로 보여주므로 설명에서 제거.
_STACK_LINE = re.compile(r"\n?기술스택\s*[:：].*$", re.M)


def build_embed(row: dict) -> dict:
    company = (row.get("company") or "").strip()
    title = (row.get("title") or "").strip()
    desc = _STACK_LINE.sub("", row.get("summary") or "").strip()
    if len(desc) > 400:
        desc = desc[:400] + "…"
    stacks = row.get("tech_stacks") or []
    stacks_s = ", ".join(stacks) if isinstance(stacks, (list, tuple)) else str(stacks)
    career = "~".join(
        str(v) for v in (row.get("min_career"), row.get("max_career")) if v is not None
    ) or "무관"
    return {
        "title": f"{company} — {title}"[:250],
        "url": row.get("url"),
        "color": EMBED_COLOR,
        "description": desc or "(요약 없음)",
        "fields": [
            {"name": "경력", "value": career, "inline": True},
            {"name": "기술스택", "value": (stacks_s or "-")[:1000], "inline": True},
            {"name": "출처", "value": str(row.get("source") or ""), "inline": True},
        ],
    }


def passes_filter(row: dict, allowed_regions, hidden_companies) -> bool:
    """전역 필터를 알림에도 적용. 빈 배열이면 해당 조건 미적용(목록 쿼리와 동일 규칙)."""
    if hidden_companies and (row.get("company") or "").strip() in set(hidden_companies):
        return False
    if allowed_regions:
        locs = row.get("locations") or ""
        if not any(r in locs for r in allowed_regions):
            return False
    return True


def chunk(items: list, size: int = EMBED_CHUNK) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_notifier_pure.py -q`
Expected: PASS (8건)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/notify/__init__.py backend/app/notify/notifier.py backend/tests/test_notifier_pure.py
git commit -m "feat(notify): 임베드 빌더·전역 필터·청크 순수 로직"
```

---

### Task 4: `notify_tick` — 조회·분류·발송·청크별 마킹

**Files:**
- Modify: `backend/app/notify/notifier.py`
- Test: `backend/tests/test_notify_tick.py`

**Interfaces:**
- Consumes: `push_embeds`(Task 2), 순수 로직(Task 3), `Settings.allowed_regions`/`hidden_companies`.
- Produces: `SELECT_SQL`, `MARK_SQL`, `async notify_tick(conn, settings, *, sender=push_embeds, on_stage=None) -> {"picked","sent","skipped"}`.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_notify_tick.py`:

```python
import pytest

from app.notify.notifier import notify_tick
from app.settings_repo import SETTINGS_DEFAULTS, Settings


def _settings(**kw):
    return Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], **kw))


def _row(i, company="미스릴", locations="서울 강남구"):
    return dict(id=i, source="wanted", job_id=str(i), company=company, title=f"t{i}",
                url=f"https://x/{i}", locations=locations, min_career=1, max_career=3,
                tech_stacks=["python"], summary="요약")


class FakeConn:
    def __init__(self, rows):
        self._rows = rows
        self.marked = []          # 마킹된 id 묶음(호출 단위)

    async def fetch(self, sql, *args):
        return self._rows

    async def execute(self, sql, *args):
        if "notified_at=now()" in sql:
            self.marked.append(list(args[0]))


async def test_no_rows_sends_and_marks_nothing():
    conn = FakeConn([])
    sent = []
    out = await notify_tick(conn, _settings(), sender=lambda c, e: sent.append(e))
    assert out == {"picked": 0, "sent": 0, "skipped": 0}
    assert sent == [] and conn.marked == []


async def test_filtered_rows_are_marked_without_sending():
    conn = FakeConn([_row(1, company="미스릴"), _row(2, company="토스")])
    sent = []

    async def sender(content, embeds):
        sent.append([e["title"] for e in embeds])

    out = await notify_tick(conn, _settings(hidden_companies=["미스릴"]), sender=sender)
    assert out == {"picked": 2, "sent": 1, "skipped": 1}
    # 걸러진 1번은 발송 없이 소비, 통과한 2번은 발송 후 마킹
    assert conn.marked[0] == [1]
    assert any(2 in m for m in conn.marked[1:])
    assert len(sent) == 1 and "토스" in sent[0][0]


async def test_chunks_are_marked_per_chunk():
    conn = FakeConn([_row(i) for i in range(1, 26)])  # 25건 → 10/10/5
    async def sender(content, embeds):
        return None
    out = await notify_tick(conn, _settings(), sender=sender)
    assert out == {"picked": 25, "sent": 25, "skipped": 0}
    assert [len(m) for m in conn.marked] == [10, 10, 5]


async def test_mid_chunk_failure_marks_only_successful_chunks():
    """중간 청크가 실패하면 성공분만 소비되고 예외가 전파된다 — 재발송(중복) 방지."""
    conn = FakeConn([_row(i) for i in range(1, 26)])
    calls = {"n": 0}

    async def flaky(content, embeds):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("discord 5xx")

    with pytest.raises(RuntimeError):
        await notify_tick(conn, _settings(), sender=flaky)
    assert [len(m) for m in conn.marked] == [10]   # 1번 청크만 마킹


async def test_first_chunk_carries_header_content():
    conn = FakeConn([_row(i) for i in range(1, 13)])  # 12건 → 10/2
    contents = []

    async def sender(content, embeds):
        contents.append(content)

    await notify_tick(conn, _settings(), sender=sender)
    assert "새 채용 공고 12건" in contents[0]
    assert contents[1] is None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_notify_tick.py -q`
Expected: FAIL — `cannot import name 'notify_tick'`

- [ ] **Step 3: `notify_tick` 추가**

`backend/app/notify/notifier.py`의 import에 추가:

```python
from datetime import datetime

from app.research.discord import push_embeds
```

파일 끝에 추가:

```python
SELECT_SQL = (
    "SELECT id, source, job_id, company, title, url, locations, "
    "min_career, max_career, tech_stacks, summary "
    "FROM jobs WHERE status='done' AND notified_at IS NULL "
    "ORDER BY collected_at LIMIT $1"
)
MARK_SQL = "UPDATE jobs SET notified_at=now() WHERE id = ANY($1::bigint[])"


async def notify_tick(conn, settings, *, sender=push_embeds, on_stage=None) -> dict:
    rows = [dict(r) for r in await conn.fetch(SELECT_SQL, NOTIFY_BATCH)]
    if not rows:
        return {"picked": 0, "sent": 0, "skipped": 0}

    keep, drop = [], []
    for r in rows:
        target = keep if passes_filter(
            r, settings.allowed_regions, settings.hidden_companies
        ) else drop
        target.append(r)

    # 전역 필터로 걸러진 공고는 발송 없이 소비 — 나중에 숨김을 풀어도 밀린 알림이 쏟아지지 않는다.
    if drop:
        await conn.execute(MARK_SQL, [r["id"] for r in drop])

    groups = chunk(keep)
    today = datetime.now().strftime("%Y-%m-%d")
    sent = 0
    for i, g in enumerate(groups):
        if on_stage:
            on_stage("알림 발송", f"{len(g)}건", f"{i + 1}/{len(groups)}")
        content = f"📋 **새 채용 공고 {len(keep)}건** ({today})" if i == 0 else None
        await sender(content, [build_embed(r) for r in g])
        # 청크 단위 마킹 — 중간 실패 시 성공분만 소비되어 재발송(중복)이 없다.
        await conn.execute(MARK_SQL, [r["id"] for r in g])
        sent += len(g)

    return {"picked": len(rows), "sent": sent, "skipped": len(drop)}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_notify_tick.py -q`
Expected: PASS (5건)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/notify/notifier.py backend/tests/test_notify_tick.py
git commit -m "feat(notify): notify_tick — 필터 소비·청크별 발송/마킹"
```

---

### Task 5: 스케줄러 배선 + `POST /api/notify/run`

**Files:**
- Modify: `backend/app/collect_scheduler.py`
- Create: `backend/app/routers/notify.py`
- Modify: `backend/app/main.py` (라우터 include)
- Test: `backend/tests/test_collect_scheduler.py`, `backend/tests/test_notify_router.py`

**Interfaces:**
- Consumes: `notify_tick`(Task 4), `logged_run`, `get_settings`, `Settings.notify_enabled`(Task 1).
- Produces: `notifier_job(get_ctx)` 5분 주기 잡(id `"notifier"`), `POST /api/notify/run`. 둘 다 `run_log`에 `pipeline='notifier'` 기록(스케줄=`scheduled`, 수동=`manual`).

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_collect_scheduler.py`의 `test_start_registers_two_jobs`를 아래로 교체(잡이 3개가 됨):

```python
def test_start_registers_three_jobs(monkeypatch):
    monkeypatch.setattr(cs, "AsyncIOScheduler", FakeSched)
    app = _app()
    cs.start_collect_scheduler(app)
    sched = app.state.collect_scheduler
    assert set(sched.jobs) == {"collector", "worker", "notifier"}
    assert sched.started is True
```

같은 파일 끝에 추가:

```python
def _notify_ctx(monkeypatch, *, enabled, has_unsent):
    from app.settings_repo import Settings, SETTINGS_DEFAULTS
    calls = {"logged_run": 0, "notify_tick": 0}

    class _C:
        async def fetchval(self, sql, *args):
            return 1 if ("notified_at IS NULL" in sql and has_unsent) else None

    conn = _C()

    async def fake_get_settings(c):
        return Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], notify_enabled=enabled))
    monkeypatch.setattr(cs, "get_settings", fake_get_settings)

    async def fake_notify_tick(*a, **kw):
        calls["notify_tick"] += 1
        return {"picked": 0, "sent": 0, "skipped": 0}
    monkeypatch.setattr(cs, "notify_tick", fake_notify_tick)

    async def fake_logged_run(c, *, pipeline, trigger, run, **kw):
        calls["logged_run"] += 1
        calls["pipeline"], calls["trigger"] = pipeline, trigger
        return await run()
    monkeypatch.setattr(cs, "logged_run", fake_logged_run)

    return calls, (lambda: (_Pool(conn), object(), Activity()))


async def test_notifier_job_noop_when_disabled(monkeypatch):
    calls, get_ctx = _notify_ctx(monkeypatch, enabled=False, has_unsent=True)
    await cs.notifier_job(get_ctx)
    assert calls["notify_tick"] == 0 and calls["logged_run"] == 0


async def test_notifier_job_skips_when_nothing_unsent(monkeypatch):
    calls, get_ctx = _notify_ctx(monkeypatch, enabled=True, has_unsent=False)
    await cs.notifier_job(get_ctx)
    assert calls["notify_tick"] == 0, "미전송 0건인데 발송 시도됨"
    assert calls["logged_run"] == 0, "미전송 0건인데 run_log 행이 기록됨"


async def test_notifier_job_runs_when_enabled_and_unsent(monkeypatch):
    calls, get_ctx = _notify_ctx(monkeypatch, enabled=True, has_unsent=True)
    await cs.notifier_job(get_ctx)
    assert calls["notify_tick"] == 1 and calls["logged_run"] == 1
    assert calls["pipeline"] == "notifier" and calls["trigger"] == "scheduled"
```

`backend/tests/test_notify_router.py`:

```python
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.routers import notify as notify_router


async def test_manual_notify_runs_regardless_of_enabled_flag(monkeypatch):
    from app.settings_repo import Settings, SETTINGS_DEFAULTS
    app = FastAPI()
    app.include_router(notify_router.router)

    class _Conn: pass

    async def _get_conn():
        yield _Conn()
    app.dependency_overrides[notify_router.get_conn] = _get_conn

    async def fake_get_settings(conn):
        # 수동 실행은 마스터 스위치가 꺼져 있어도 동작해야 한다(컷오버 검증용).
        return Settings(**dict(SETTINGS_DEFAULTS, keywords=["x"], notify_enabled=False))
    monkeypatch.setattr(notify_router, "get_settings", fake_get_settings)

    seen = {}

    async def fake_logged_run(conn, *, pipeline, trigger, run, **kw):
        seen.update(pipeline=pipeline, trigger=trigger)
        return await run()
    monkeypatch.setattr(notify_router, "logged_run", fake_logged_run)

    async def fake_notify_tick(conn, settings, **kw):
        return {"picked": 3, "sent": 2, "skipped": 1}
    monkeypatch.setattr(notify_router, "notify_tick", fake_notify_tick)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/notify/run")
    assert r.status_code == 202
    assert r.json() == {"picked": 3, "sent": 2, "skipped": 1}
    assert seen == {"pipeline": "notifier", "trigger": "manual"}
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_collect_scheduler.py tests/test_notify_router.py -q`
Expected: FAIL — `cs.notifier_job` 없음, `app.routers.notify` 모듈 없음.

- [ ] **Step 3: 스케줄러 배선**

`backend/app/collect_scheduler.py`의 import에 추가:

```python
from app.notify.notifier import notify_tick
```

`log = logging.getLogger(...)` 아래에 상수 추가:

```python
NOTIFY_INTERVAL_MIN = 5  # 원본(n8n) 주기
```

`worker_job` 다음에 추가:

```python
async def notifier_job(get_ctx) -> None:
    pool, _http, _activity = get_ctx()
    async with pool.acquire() as conn:
        settings = await get_settings(conn)
        if not settings.notify_enabled:
            return
        # 미전송이 없으면 아무것도 하지 않는다 — 발송 시도도, run_log 행도 없음(워커와 동일 패턴).
        if not await conn.fetchval(
            "SELECT 1 FROM jobs WHERE status='done' AND notified_at IS NULL LIMIT 1"
        ):
            return
        await logged_run(
            conn, pipeline="notifier", trigger="scheduled",
            run=lambda: notify_tick(conn, settings),
        )
```

`start_collect_scheduler`의 worker 잡 등록 다음 줄에 추가:

```python
    sched.add_job(notifier_job, "interval", id="notifier",
                  minutes=NOTIFY_INTERVAL_MIN, args=[get_ctx])
```

`reschedule`는 **수정하지 않는다**(알림 주기는 상수).

- [ ] **Step 4: 라우터 작성**

`backend/app/routers/notify.py`:

```python
from typing import Any

from fastapi import APIRouter, Depends

from app.db import get_conn
from app.notify.notifier import notify_tick
from app.run_log import logged_run
from app.settings_repo import get_settings

router = APIRouter(prefix="/api", tags=["notify"])


@router.post("/notify/run", status_code=202)
async def run_notify(conn: Any = Depends(get_conn)):
    settings = await get_settings(conn)
    # 수동 실행은 notify_enabled와 무관 — 명시적 행동이므로 항상 동작(컷오버 검증용).
    return await logged_run(
        conn, pipeline="notifier", trigger="manual",
        run=lambda: notify_tick(conn, settings),
    )
```

- [ ] **Step 5: main.py include**

import 블록에 추가:

```python
from app.routers import notify as notify_router
```

`app.include_router(facets_router.router)` 다음 줄에 추가:

```python
app.include_router(notify_router.router)
```

- [ ] **Step 6: 테스트 + 전체 스위트**

Run: `cd backend && python -m pytest tests/test_collect_scheduler.py tests/test_notify_router.py -q && python -m pytest -q`
Expected: 신규 PASS, 전체 PASS.

- [ ] **Step 7: 커밋**

```bash
git add backend/app/collect_scheduler.py backend/app/routers/notify.py backend/app/main.py backend/tests/test_collect_scheduler.py backend/tests/test_notify_router.py
git commit -m "feat(notify): 5분 주기 스케줄 잡 + POST /api/notify/run(run_log 연동)"
```

---

### Task 6: Ops 알림 카드 — 활성화 토글 + 수동 발송

**Files:**
- Modify: `frontend/src/settingsApi.ts` (Settings 타입 + runNotify)
- Modify: `frontend/src/pages/Ops.tsx` (알림 카드)
- Test: `frontend/src/pages/Ops.test.tsx`

**Interfaces:**
- Consumes: `POST /api/notify/run`(Task 5), `Settings.notify_enabled`(Task 1).
- Produces: `Settings.notify_enabled: boolean`, `runNotify(): Promise<{picked;sent;skipped}>`, Ops 알림 카드의 토글 + `지금 알림 발송` 버튼.

- [ ] **Step 1: 실패하는 테스트 작성**

`frontend/src/pages/Ops.test.tsx`의 `SETTINGS` 상수에 `notify_enabled: false,`를 추가하고, `mockFetch`의 `/api/settings` 분기 앞에 추가:

```typescript
    else if (u.includes("/api/notify/run")) body = { picked: 3, sent: 2, skipped: 1 };
```

파일 끝에 추가:

```typescript
test("알림 활성화 토글이 저장 페이로드에 담긴다", async () => {
  render(<Ops />);
  await waitFor(() => expect(screen.getByLabelText("알림 활성화")).toBeTruthy());
  fireEvent.click(screen.getByLabelText("알림 활성화"));
  fireEvent.click(screen.getByRole("button", { name: "저장" }));
  await waitFor(() => expect(putBody).not.toBeNull());
  expect(putBody!.notify_enabled).toBe(true);
});

test("지금 알림 발송 결과를 문구로 보여준다", async () => {
  render(<Ops />);
  await waitFor(() => expect(screen.getByText("지금 알림 발송")).toBeTruthy());
  fireEvent.click(screen.getByText("지금 알림 발송"));
  await waitFor(() => expect(screen.getByText(/발송 2건/)).toBeTruthy());
});
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd frontend && npx vitest run src/pages/Ops.test.tsx`
Expected: FAIL — "알림 활성화"/"지금 알림 발송" 없음.

- [ ] **Step 3: settingsApi.ts 확장**

`Settings` 인터페이스의 `hidden_companies: string[];` 뒤에 추가:

```typescript
  notify_enabled: boolean;
```

파일 끝에 추가:

```typescript
export async function runNotify(): Promise<{ picked: number; sent: number; skipped: number }> {
  const r = await fetch("/api/notify/run", { method: "POST" });
  if (!r.ok) throw new Error("notify run failed");
  return r.json();
}
```

- [ ] **Step 4: Ops.tsx 알림 카드 확장**

import에서 `runWorker` 옆에 `runNotify`를 추가:

```typescript
  getSettings, putSettings, runCollect, runNotify, runWorker, type Settings as S,
} from "../settingsApi";
```

알림 카드의 Discord 웹훅 `<label>` 다음(닫는 `</motion.section>` 앞)에 추가:

```tsx
            <div className="form-row">
              <span className="rl">알림 활성화</span>
              <div className="control">
                <input className="switch" type="checkbox" aria-label="알림 활성화"
                  checked={form.notify_enabled} onChange={(e) => set("notify_enabled", e.target.checked)} />
              </div>
            </div>
            <div className="run-bar">
              <button
                onClick={() => doRun(runNotify, (r) => `발송 ${r.sent}건${r.skipped ? ` · 건너뜀 ${r.skipped}` : ""}`)}
                disabled={dirty || busy}
              >지금 알림 발송</button>
              <span className="caption">{dirty ? "먼저 저장하세요" : ""}</span>
            </div>
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `cd frontend && npx vitest run src/pages/Ops.test.tsx`
Expected: PASS

- [ ] **Step 6: 전체 프론트 + 타입체크**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: 전부 PASS, 타입 0. (`Settings`에 필수 필드가 늘었으므로 다른 픽스처가 깨지면 `notify_enabled: false`를 추가하되 기존 단언은 유지.)

- [ ] **Step 7: 커밋**

```bash
git add frontend/src/settingsApi.ts frontend/src/pages/Ops.tsx frontend/src/pages/Ops.test.tsx
git commit -m "feat(notify): Ops 알림 활성화 토글 + 지금 알림 발송"
```

---

## 최종 검증

- [ ] `cd backend && python -m pytest -q` → 전부 PASS
- [ ] `cd frontend && npx vitest run && npx tsc --noEmit` → 전부 PASS, 타입 0
- [ ] 배포 후 컷오버: ① `notify_enabled=false`로 배포(무동작) → ② Ops "지금 알림 발송"으로 검증 → ③ **n8n `03-notifier` 비활성화** → ④ Ops에서 토글 ON

## 자기 검토 결과

**스펙 커버리지:** 설정 플래그(T1) · 웹훅 통일+임베드(T2) · 순수 로직(T3) · notify_tick(T4) · 스케줄/수동 트리거(T5) · Ops UI(T6). 스펙의 모든 항목이 매핑됨. "걸러진 공고 소비"는 T4 구현·테스트로, "청크별 마킹(중복 방지)"은 T4의 중간 실패 회귀 테스트로 고정. 컷오버 절차는 최종 검증에 명시.

**플레이스홀더:** 없음 — 모든 코드 단계에 실제 코드 포함.

**타입 일관성:** `notify_enabled`가 T1(파이썬)·T5(스케줄러 게이트)·T6(TS)에서 동일. `{picked,sent,skipped}` 형태가 T4 반환·T5 라우터 응답·T6 문구에서 일치. `sender(content, embeds)` 시그니처가 T2 `push_embeds`와 T4 기본 인자·테스트 페이크에서 일치. `MARK_SQL`의 `$1::bigint[]`가 실제 `id` 타입(bigint)과 일치.
