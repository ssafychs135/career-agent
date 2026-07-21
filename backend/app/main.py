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
