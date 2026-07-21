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
