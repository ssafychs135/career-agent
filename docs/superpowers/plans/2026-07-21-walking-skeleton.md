# career-agent Walking Skeleton — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `agent.chs135.com`이 실제로 뜨는 배포 가능한 골격을 만들고, 그 과정에서 **컨테이너 안 `claude -p`가 마운트된 구독 인증으로 동작함**과 **Jenkins→docker compose→cloudflared 배포 체인**을 end-to-end로 증명한다.

**Architecture:** FastAPI 백엔드(컨테이너, claude-code 설치+`~/.claude` 마운트) + React/Vite/TS 프론트(nginx가 정적 서빙) + nginx 리버스 프록시(`/`=프론트, `/api`=백엔드), 전부 docker compose. cloudflared 터널(`localhost:80`)로 노출, Cloudflare Access(Google). Jenkins가 빌드·배포. 이 플랜엔 **Postgres 없음**(DB는 플랜 ②).

**Tech Stack:** Python 3.12 · FastAPI · uvicorn · pytest / React 18 · Vite · TypeScript · vitest / nginx 1.27 · Docker Compose / Jenkins / cloudflared · Cloudflare Access

## Global Constraints

- 레포 루트: `/Users/sunny/career-agent` (GitHub에 신규 push 필요). 원격: `ssafychs135/career-agent`.
- 배포 대상: A1 서버(ssh alias `a1`), 경로 `/home/ubuntu/career-agent`. Docker/Jenkins 기존 스택 재사용.
- claude 인증 = **구독**(과금 0). 백엔드 컨테이너는 호스트 `/home/ubuntu/.claude`·`/home/ubuntu/.claude.json`를 **rw 마운트**, **컨테이너 uid = A1 ubuntu uid**(추정 1001, Task 1에서 검증)로 실행.
- claude 호출은 `claude -p ... --output-format json`, 툴은 `--allowedTools`로만 허용. 시크릿·자격증명은 화면 출력/커밋 금지.
- nginx는 **`127.0.0.1:80`에만 바인딩**(인터넷 직접 노출 없음, cloudflared만 접근). TLS·Access·WAF는 Cloudflare 엣지가 처리.
- 커밋 메시지 말미:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- 공개 리포에 개인 취업 결과(회사명·합불) 노출 금지.

---

## File Structure

```
career-agent/
├─ backend/
│  ├─ app/__init__.py
│  ├─ app/main.py              # FastAPI 앱: /api/health, /api/claude-check
│  ├─ app/claude_client.py     # claude -p 서브프로세스 래퍼
│  ├─ tests/test_claude_client.py
│  ├─ tests/test_routes.py
│  ├─ pyproject.toml
│  ├─ Dockerfile               # python + node + claude-code
│  └─ .dockerignore
├─ frontend/
│  ├─ src/main.tsx
│  ├─ src/App.tsx              # health·claude 상태 표시
│  ├─ src/api.ts               # fetch 클라이언트
│  ├─ src/App.test.tsx
│  ├─ index.html
│  ├─ package.json
│  ├─ tsconfig.json
│  ├─ tsconfig.node.json
│  ├─ vite.config.ts           # react + vitest(jsdom) + /api dev proxy
│  └─ .dockerignore
├─ nginx/
│  ├─ nginx.conf               # / = SPA, /api = proxy_pass backend:8000
│  └─ Dockerfile               # multi-stage: frontend 빌드 → nginx 서빙
├─ docker-compose.yml          # backend + nginx
├─ Jenkinsfile                 # CI(pytest·vitest·compose config) → CD(up -d) → smoke
├─ deploy/cloudflared-and-access.md  # 터널 ingress + Access 앱 셋업(수동 절차 기록)
└─ .gitignore                  # (이미 존재)
```

각 파일 1책임: `claude_client.py`=서브프로세스·파싱만, `main.py`=라우팅만, `api.ts`=HTTP만, `App.tsx`=표시만.

---

## Task 1: 백엔드 claude 래퍼 (`claude_client.py`)

**Files:**
- Create: `backend/pyproject.toml`, `backend/app/__init__.py`, `backend/app/claude_client.py`, `backend/tests/test_claude_client.py`

**Interfaces:**
- Produces: `async def run_claude(prompt: str, *, allowed_tools: str = "", timeout: int = 120, claude_bin: str = "claude") -> str` — `claude -p`의 JSON 엔벨로프에서 `result`(모델 텍스트)를 반환. 비정상 종료·타임아웃 시 `RuntimeError`.

- [ ] **Step 1: `pyproject.toml` 작성**

`backend/pyproject.toml`:
```toml
[project]
name = "career-agent-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["fastapi>=0.115", "uvicorn[standard]>=0.32"]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "httpx>=0.27"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["."]
```

- [ ] **Step 2: 실패하는 테스트 작성**

`backend/app/__init__.py`: (빈 파일)

`backend/tests/test_claude_client.py`:
```python
import asyncio
import json
import pytest
from app.claude_client import run_claude


class FakeProc:
    def __init__(self, out=b"", err=b"", rc=0):
        self._out, self._err, self.returncode = out, err, rc

    async def communicate(self):
        return self._out, self._err

    def kill(self):
        pass


async def test_run_claude_returns_result(monkeypatch):
    async def fake_exec(*args, **kwargs):
        assert args[0] == "claude" and "-p" in args
        return FakeProc(json.dumps({"result": "OK"}).encode())

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert await run_claude("hi") == "OK"


async def test_run_claude_passes_allowed_tools(monkeypatch):
    seen = {}

    async def fake_exec(*args, **kwargs):
        seen["args"] = args
        return FakeProc(json.dumps({"result": "x"}).encode())

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    await run_claude("hi", allowed_tools="WebSearch,WebFetch")
    assert "--allowedTools" in seen["args"]
    assert "WebSearch,WebFetch" in seen["args"]


async def test_run_claude_raises_on_nonzero(monkeypatch):
    async def fake_exec(*args, **kwargs):
        return FakeProc(b"", b"boom", rc=1)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(RuntimeError):
        await run_claude("hi")
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `cd backend && pip install -e ".[dev]" && python -m pytest tests/test_claude_client.py -q`
Expected: FAIL — `ModuleNotFoundError: app.claude_client` (아직 미구현)

- [ ] **Step 4: 구현**

`backend/app/claude_client.py`:
```python
import asyncio
import json


async def run_claude(
    prompt: str,
    *,
    allowed_tools: str = "",
    timeout: int = 120,
    claude_bin: str = "claude",
) -> str:
    """`claude -p`를 실행해 모델 텍스트(result)를 반환. 실패·타임아웃 시 RuntimeError."""
    args = [claude_bin, "-p", prompt, "--output-format", "json"]
    if allowed_tools:
        args += ["--allowedTools", allowed_tools]

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("claude timed out")

    if proc.returncode != 0:
        raise RuntimeError(f"claude failed ({proc.returncode}): {stderr.decode()[:500]}")

    envelope = json.loads(stdout.decode())
    return envelope["result"]
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_claude_client.py -q`
Expected: PASS (3 passed)

- [ ] **Step 6: 커밋**

```bash
cd /Users/sunny/career-agent
git add backend/pyproject.toml backend/app/__init__.py backend/app/claude_client.py backend/tests/test_claude_client.py
git commit -m "feat(backend): claude -p 서브프로세스 래퍼 run_claude"
```

---

## Task 2: 백엔드 라우트 (`main.py`)

**Files:**
- Create: `backend/app/main.py`, `backend/tests/test_routes.py`

**Interfaces:**
- Consumes: `run_claude` from Task 1.
- Produces: FastAPI 앱 `app`. `GET /api/health` → `{"status":"ok"}`. `GET /api/claude-check` → `{"ok":true,"reply":<text>}` (실패 시 503).

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_routes.py`:
```python
from fastapi.testclient import TestClient
from app import main


def test_health():
    client = TestClient(main.app)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_claude_check_ok(monkeypatch):
    async def fake_run_claude(prompt, **kw):
        return "OK"

    monkeypatch.setattr(main, "run_claude", fake_run_claude)
    r = TestClient(main.app).get("/api/claude-check")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "reply": "OK"}


def test_claude_check_failure(monkeypatch):
    async def boom(prompt, **kw):
        raise RuntimeError("down")

    monkeypatch.setattr(main, "run_claude", boom)
    r = TestClient(main.app).get("/api/claude-check")
    assert r.status_code == 503
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && python -m pytest tests/test_routes.py -q`
Expected: FAIL — `ImportError`/`ModuleNotFoundError: app.main`

- [ ] **Step 3: 구현**

`backend/app/main.py`:
```python
from fastapi import FastAPI, HTTPException
from app.claude_client import run_claude

app = FastAPI(title="career-agent")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/claude-check")
async def claude_check():
    try:
        text = await run_claude("Reply with exactly: OK")
    except Exception as e:  # noqa: BLE001 — 어떤 실패든 503로 표면화
        raise HTTPException(status_code=503, detail=str(e))
    return {"ok": True, "reply": text.strip()}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && python -m pytest -q`
Expected: PASS (5 passed — Task 1의 3 + 여기 2)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/main.py backend/tests/test_routes.py
git commit -m "feat(backend): /api/health·/api/claude-check 라우트"
```

---

## Task 3: 백엔드 Dockerfile (python + node + claude-code)

**Files:**
- Create: `backend/Dockerfile`, `backend/.dockerignore`

- [ ] **Step 1: `.dockerignore` 작성**

`backend/.dockerignore`:
```
__pycache__/
*.pyc
.pytest_cache/
tests/
.venv/
```

- [ ] **Step 2: Dockerfile 작성**

`backend/Dockerfile`:
```dockerfile
FROM python:3.12-slim

# Node.js(claude-code 런타임) + claude-code CLI
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && npm install -g @anthropic-ai/claude-code \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.32"
COPY app ./app

# 런타임에 호스트 ~/.claude 를 여기로 마운트. uid는 compose에서 ubuntu와 일치시킴.
ENV HOME=/home/appuser
RUN mkdir -p /home/appuser && chmod 777 /home/appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: 로컬 빌드 검증**

Run: `cd /Users/sunny/career-agent && docker build -t ca-backend-test ./backend && docker run --rm ca-backend-test claude --version`
Expected: 빌드 성공 + `claude` 버전 출력(예: `2.1.x (Claude Code)`). (인증은 마운트 없이 안 되지만, 바이너리 설치는 확인됨.)

- [ ] **Step 4: 커밋**

```bash
git add backend/Dockerfile backend/.dockerignore
git commit -m "feat(backend): Dockerfile(python+node+claude-code)"
```

---

## Task 4: 프론트엔드 스캐폴드 + 테스트

**Files:**
- Create: `frontend/package.json`, `frontend/tsconfig.json`, `frontend/tsconfig.node.json`, `frontend/vite.config.ts`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/api.ts`, `frontend/src/App.tsx`, `frontend/src/App.test.tsx`, `frontend/.dockerignore`

**Interfaces:**
- Produces: `getHealth(): Promise<{status:string}>`, `getClaudeCheck(): Promise<{ok:boolean;reply:string}>` in `src/api.ts`. `App` 컴포넌트가 두 값을 `data-testid="health"`·`data-testid="claude"`에 표시.

- [ ] **Step 1: 설정 파일 작성**

`frontend/package.json`:
```json
{
  "name": "career-agent-frontend",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@testing-library/react": "^16.0.1",
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.3",
    "jsdom": "^25.0.1",
    "typescript": "^5.6.3",
    "vite": "^5.4.10",
    "vitest": "^2.1.4"
  }
}
```

`frontend/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noEmit": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

`frontend/tsconfig.node.json`:
```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true
  },
  "include": ["vite.config.ts"]
}
```

`frontend/vite.config.ts`:
```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: { environment: "jsdom", globals: true },
  server: { proxy: { "/api": "http://localhost:8000" } },
});
```

`frontend/index.html`:
```html
<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>career-agent</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`frontend/.dockerignore`:
```
node_modules/
dist/
```

- [ ] **Step 2: 실패하는 테스트 작성**

`frontend/src/App.test.tsx`:
```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import App from "./App";

beforeEach(() => {
  global.fetch = vi.fn((url: RequestInfo | URL) =>
    Promise.resolve({
      ok: true,
      json: () =>
        Promise.resolve(
          String(url).includes("claude-check")
            ? { ok: true, reply: "OK" }
            : { status: "ok" },
        ),
    }),
  ) as unknown as typeof fetch;
});

test("renders health and claude status", async () => {
  render(<App />);
  await waitFor(() =>
    expect(screen.getByTestId("health").textContent).toBe("ok"),
  );
  expect(screen.getByTestId("claude").textContent).toBe("OK");
});
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `cd frontend && npm install && npm test`
Expected: FAIL — `Cannot find module './App'` (App/api 미작성)

- [ ] **Step 4: 구현**

`frontend/src/api.ts`:
```ts
export async function getHealth(): Promise<{ status: string }> {
  const r = await fetch("/api/health");
  if (!r.ok) throw new Error("health failed");
  return r.json();
}

export async function getClaudeCheck(): Promise<{ ok: boolean; reply: string }> {
  const r = await fetch("/api/claude-check");
  if (!r.ok) throw new Error("claude-check failed");
  return r.json();
}
```

`frontend/src/App.tsx`:
```tsx
import { useEffect, useState } from "react";
import { getHealth, getClaudeCheck } from "./api";

export default function App() {
  const [health, setHealth] = useState("…");
  const [claude, setClaude] = useState("…");

  useEffect(() => {
    getHealth()
      .then((r) => setHealth(r.status))
      .catch(() => setHealth("error"));
    getClaudeCheck()
      .then((r) => setClaude(r.reply))
      .catch(() => setClaude("error"));
  }, []);

  return (
    <main style={{ fontFamily: "sans-serif", padding: 24 }}>
      <h1>career-agent</h1>
      <p>
        API health: <span data-testid="health">{health}</span>
      </p>
      <p>
        claude: <span data-testid="claude">{claude}</span>
      </p>
    </main>
  );
}
```

`frontend/src/main.tsx`:
```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

- [ ] **Step 5: 테스트·빌드 통과 확인**

Run: `cd frontend && npm test && npm run build`
Expected: 테스트 PASS(1 passed) + `dist/` 생성

- [ ] **Step 6: 커밋**

```bash
git add frontend
git commit -m "feat(frontend): React/Vite 골격 — health·claude 상태 표시"
```

---

## Task 5: nginx (multi-stage 빌드 + 라우팅) & docker-compose

**Files:**
- Create: `nginx/nginx.conf`, `nginx/Dockerfile`, `docker-compose.yml`

**Interfaces:**
- Consumes: `frontend/`(빌드 대상), backend 서비스(`backend:8000`).
- Produces: `docker compose`가 `nginx`(127.0.0.1:80)·`backend`를 기동. nginx가 `/`=SPA, `/api/`=backend 프록시.

- [ ] **Step 1: nginx.conf 작성**

`nginx/nginx.conf`:
```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 180s;   # 향후 리서치 등 느린 응답 대비
    }

    location / {
        try_files $uri $uri/ /index.html;   # SPA fallback
    }
}
```

- [ ] **Step 2: nginx Dockerfile 작성 (multi-stage)**

`nginx/Dockerfile` (빌드 컨텍스트 = 레포 루트):
```dockerfile
# 1) 프론트 빌드
FROM node:22-slim AS build
WORKDIR /fe
COPY frontend/package.json ./
RUN npm install
COPY frontend/ .
RUN npm run build

# 2) nginx: dist 서빙 + /api 프록시
FROM nginx:1.27-alpine
COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /fe/dist /usr/share/nginx/html
```

- [ ] **Step 3: docker-compose.yml 작성**

`docker-compose.yml`:
```yaml
services:
  backend:
    build: ./backend
    user: "${HOST_UID:-1001}:${HOST_UID:-1001}"   # A1 ubuntu uid (Task 6에서 검증)
    volumes:
      - /home/ubuntu/.claude:/home/appuser/.claude:rw
      - /home/ubuntu/.claude.json:/home/appuser/.claude.json:rw
    expose:
      - "8000"
    restart: unless-stopped

  nginx:
    build:
      context: .
      dockerfile: nginx/Dockerfile
    ports:
      - "127.0.0.1:80:80"    # cloudflared만 접근(로컬 바인딩, 인터넷 직접노출 없음)
    depends_on:
      - backend
    restart: unless-stopped
```

- [ ] **Step 4: compose 설정 유효성 검증(로컬)**

Run: `cd /Users/sunny/career-agent && docker compose config -q && echo OK`
Expected: `OK` (문법 유효). *로컬 맥에는 `/home/ubuntu/.claude`가 없어 실행은 A1에서 검증(Task 6).*

- [ ] **Step 5: 커밋**

```bash
git add nginx docker-compose.yml
git commit -m "feat: nginx(멀티스테이지)+docker-compose(backend·nginx)"
```

---

## Task 6: A1 로컬 E2E — 컨테이너 안 claude 구독 인증 증명 ★핵심 게이트

이 태스크가 이 플랜의 **가장 중요한 리스크 해소**다: 컨테이너 안 `claude -p`가 마운트된 구독 자격증명으로 실제 응답하는지.

**Files:** (코드 변경 없음 — 배포·검증)

- [ ] **Step 1: 레포를 GitHub에 push**

```bash
cd /Users/sunny/career-agent
gh repo create ssafychs135/career-agent --public --source=. --remote=origin --push
```
Expected: 원격 생성 + main push 완료.
*public 선택 이유: A1·Jenkins가 인증 없이 클론/폴링(기존 n8n 레포와 동일 패턴). 코드만 담기고 취업 데이터는 Postgres에 있어 무방. private을 원하면 A1·Jenkins에 배포키/토큰 셋업 태스크가 추가로 필요(이 플랜 범위 밖). `.env`·시크릿은 `.gitignore`로 커밋 제외.*

- [ ] **Step 2: A1 ubuntu uid 확인 → `.env` 작성**

```bash
ssh a1 'id -u ubuntu'          # 예상 1001
```
A1에서 레포 클론 후 uid를 `.env`에 기록(값은 위 출력 사용):
```bash
ssh a1 'cd /home/ubuntu && git clone https://github.com/ssafychs135/career-agent.git && cd career-agent && printf "HOST_UID=%s\n" "$(id -u ubuntu)" > .env'
```
Expected: `/home/ubuntu/career-agent/.env`에 `HOST_UID=1001`(또는 실제값).

- [ ] **Step 3: A1에서 빌드·기동**

```bash
ssh a1 'cd /home/ubuntu/career-agent && sudo docker compose --env-file .env up -d --build'
```
Expected: `backend`·`nginx` 컨테이너 Up.

- [ ] **Step 4: health 검증**

```bash
ssh a1 'curl -s -o /dev/null -w "%{http_code}\n" http://localhost:80/api/health'
```
Expected: `200`

- [ ] **Step 5: ★ claude-in-container 검증 (구독 인증)**

```bash
ssh a1 'curl -s http://localhost:80/api/claude-check'
```
Expected: `{"ok":true,"reply":"OK"}` (또는 reply에 "OK" 포함).
**실패 시(503):** `ssh a1 'sudo docker compose -f /home/ubuntu/career-agent/docker-compose.yml logs backend | tail -30'`로 원인 확인 — 흔한 원인: (a) uid 불일치로 `~/.claude` 읽기 실패 → `.env`의 HOST_UID 재확인, (b) 토큰 만료 → 호스트에서 `claude login` 재실행(공유 마운트라 전파), (c) claude가 `HOME`을 못 찾음 → 컨테이너 `HOME=/home/appuser`와 마운트 경로 일치 확인. BLOCKED면 컨트롤러에 에스컬레이트.

- [ ] **Step 6: 프론트 정적 서빙 검증**

```bash
ssh a1 'curl -s http://localhost:80/ | grep -o "<title>career-agent</title>"'
```
Expected: `<title>career-agent</title>`

- [ ] **Step 7: 진행 기록(커밋 불필요, 원격 상태 확인)**

Run: `ssh a1 'cd /home/ubuntu/career-agent && git rev-parse --short HEAD'`
Expected: 로컬 main과 동일 커밋. (이 태스크는 배포·검증만 — 코드 커밋 없음.)

---

## Task 7: cloudflared 라우트 + Cloudflare Access (agent.chs135.com)

기존 n8n·Jenkins 노출과 동일 패턴을 미러링한다. 값(터널 ID·account ID·기존 Access 앱)은 하드코딩하지 말고 아래 명령으로 조회해 사용한다.

**Files:**
- Create: `deploy/cloudflared-and-access.md` (수행한 셋업의 기록)

- [ ] **Step 1: 현재 터널·계정 식별**

```bash
CF_TOKEN=$(cat ~/.cf_api_token)
# account id
curl -s -H "Authorization: Bearer $CF_TOKEN" https://api.cloudflare.com/client/v4/accounts \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"][0]["id"])'
# a1 터널이 붙는 방식 확인(기존 n8n.chs135.com이 어떤 터널/서비스로 가는지)
ssh a1 'sudo docker inspect a1-cloudflared-1 --format "{{json .Args}}"' 2>/dev/null || true
```
Expected: account id 획득 + 기존 터널 구성 파악. (원격관리 터널이면 CF API의 `cfd_tunnel` configurations로 ingress 확인.)

- [ ] **Step 2: DNS + 터널 ingress에 `agent.chs135.com → http://localhost:80` 추가**

기존 n8n/jenkins 호스트가 등록된 것과 **동일한 터널**에 라우트를 추가한다(원격관리면 CF API `PUT /accounts/{acct}/cfd_tunnel/{tunnelId}/configurations`의 ingress 배열에 항목 추가; 로컬 config.yml이면 A1 `~/.cloudflared/config.yml` ingress에 추가 후 `docker restart a1-cloudflared-1`). DNS는 `agent` CNAME → `<tunnelId>.cfargotunnel.com`(`POST /zones/{zoneId}/dns_records`, proxied=true).
검증:
```bash
ssh a1 'curl -s -o /dev/null -w "%{http_code}\n" -H "Host: agent.chs135.com" http://localhost:80/api/health'
```
Expected: 로컬 경유 `200`(nginx가 Host 무관 응답). 외부 도달은 Step 3 이후.

- [ ] **Step 3: Cloudflare Access 앱 생성(Google IdP)**

기존 n8n Access 앱을 템플릿으로 `agent.chs135.com`용 self-hosted Access application을 만들고, 정책을 **본인 이메일(ssafychs135@gmail.com) 허용 + Google IdP**로 설정(기존 앱의 `allowed_idps`·정책을 그대로 복제). CF API: `POST /accounts/{acct}/access/apps` (`domain: agent.chs135.com`, `type: self_hosted`) + `POST .../apps/{appId}/policies`.
검증(브라우저): `https://agent.chs135.com` 접속 → Google 로그인 요구 → 로그인 후 페이지 표시.

- [ ] **Step 4: 외부 E2E**

브라우저에서 `https://agent.chs135.com` → Google 로그인 → 페이지에 `API health: ok`, `claude: OK` 표시 확인.
Expected: 3개 다 정상(health ok, claude OK, 페이지 렌더).

- [ ] **Step 5: 셋업 기록 문서 작성 + 커밋**

`deploy/cloudflared-and-access.md`에 수행한 실제 절차(추가한 ingress 규칙, DNS 레코드, Access 앱/정책 ID — **시크릿·토큰 값은 제외**)를 기록.
```bash
git add deploy/cloudflared-and-access.md
git commit -m "docs(deploy): agent.chs135.com cloudflared ingress + Access 셋업 기록"
```

---

## Task 8: Jenkins 파이프라인 (CI → CD → smoke)

기존 A1 Jenkins(docker-out-of-docker, 경로동일 마운트)를 재사용한다. career-agent용 `Jenkinsfile`을 만들고, Jenkins에 career-agent 레포용 pipelineJob을 추가한다.

**Files:**
- Create: `Jenkinsfile`

**Interfaces:**
- Consumes: `docker-compose.yml`(Task 5), `.env`(HOST_UID, Task 6).

- [ ] **Step 1: Jenkinsfile 작성**

`Jenkinsfile`:
```groovy
// CI(pytest·vitest·compose config) → CD(main: git 동기화·up -d) → smoke → 실패시 Discord
pipeline {
  agent any
  environment { DEPLOY_DIR = '/home/ubuntu/career-agent' }
  stages {
    stage('CI') {
      parallel {
        stage('backend-tests') {
          steps { sh 'cd backend && pip install -e ".[dev]" && python -m pytest -q' }
        }
        stage('frontend-tests') {
          steps { sh 'cd frontend && npm ci && npm test && npm run build' }
        }
        stage('compose-config') {
          steps { sh 'docker compose config -q' }
        }
      }
    }
    stage('CD deploy') {
      steps {
        sh '''
          cd ${DEPLOY_DIR}
          git fetch -q origin main && git reset --hard "$GIT_COMMIT"
          docker compose --env-file .env up -d --build
        '''
      }
    }
    stage('smoke') {
      steps {
        sh '''
          cd ${DEPLOY_DIR}
          curl -sf http://localhost:80/api/health | grep -q '"status":"ok"'
          curl -sf http://localhost:80/ | grep -q '<title>career-agent</title>'
        '''
      }
    }
  }
  post {
    failure {
      sh '''
        WEBHOOK=$(grep '^DISCORD_WEBHOOK_URL=' ${DEPLOY_DIR}/.env 2>/dev/null | cut -d= -f2-)
        [ -n "$WEBHOOK" ] && curl -s -m 15 -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
          -d "{\\"content\\":\\"🔴 career-agent 빌드 실패: ${BUILD_URL}\\"}" "$WEBHOOK" >/dev/null || true
      '''
    }
  }
}
```
*주의: `npm ci`는 `package-lock.json` 필요 → Task 4 후 `cd frontend && npm install`로 생성된 lock을 커밋해 둘 것(아래 Step 2에서 확인).*

- [ ] **Step 2: package-lock 커밋 확인**

Run: `cd /Users/sunny/career-agent && git ls-files frontend/package-lock.json`
Expected: 경로 출력(없으면 `cd frontend && npm install` 후 `git add frontend/package-lock.json`). smoke의 `npm ci` 재현성 위해 필수.

- [ ] **Step 3: Jenkins에 career-agent pipelineJob 추가**

기존 n8n Jenkins의 JCasC(job-dsl)에 career-agent용 pipelineJob을 추가한다(별도 레포 `ssafychs135/career-agent`, branch `main`, `scriptPath('Jenkinsfile')`, `lightweight(false)`, trigger `scm('H/3 * * * *')`). 기존 n8n job 정의를 템플릿으로 복제하되 URL·job 이름만 변경. (n8n 레포의 `deploy/a1/jenkins/casc.yaml` 수정 → Jenkins 재기동 반영, 또는 Jenkins UI/CLI로 job 생성.)
검증: Jenkins UI에 `career-agent` job이 보이고 수동 빌드가 CI 단계까지 통과.

- [ ] **Step 4: 커밋 + 파이프라인 E2E**

```bash
git add Jenkinsfile frontend/package-lock.json
git commit -m "ci: career-agent Jenkins 파이프라인(CI→CD→smoke)"
git push origin main
```
그 후 Jenkins가 폴링(≤3분)해 빌드 → 배포 → smoke 통과 확인:
```bash
ssh a1 'cd /home/ubuntu/career-agent && git rev-parse --short HEAD'   # push한 커밋과 일치
ssh a1 'curl -sf http://localhost:80/api/claude-check'                # {"ok":true,...}
```
Expected: Jenkins 빌드 SUCCESS, A1 HEAD=push 커밋, claude-check 정상.

---

## 완료 기준 (Walking Skeleton Done)

- `https://agent.chs135.com` 이 Google Access 뒤에서 뜨고, 페이지가 `health: ok` + `claude: OK` 표시.
- **컨테이너 안 `claude -p`가 구독 인증(마운트)으로 응답**함이 증명됨(가장 큰 미지수 해소).
- `git push` → Jenkins → docker compose 배포 → smoke 통과의 **자동 배포 체인**이 동작.
- Postgres·리서치·조회 기능은 없음(플랜 ②③④).
