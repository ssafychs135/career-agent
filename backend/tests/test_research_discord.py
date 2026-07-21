import httpx
from app.research import discord


class FakeClient:
    posted = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        FakeClient.posted.append((url, kw))
        return None


async def test_push_posts_when_webhook_set(monkeypatch):
    FakeClient.posted = []
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord/hook")
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    await discord.push("hi")
    assert FakeClient.posted[0][0] == "https://discord/hook"
    assert FakeClient.posted[0][1]["json"] == {"content": "hi"}


async def test_push_noop_without_webhook(monkeypatch):
    FakeClient.posted = []
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    await discord.push("hi")
    assert FakeClient.posted == []


async def test_push_swallows_errors(monkeypatch):
    class Boom(FakeClient):
        async def post(self, url, **kw):
            raise httpx.ConnectError("down")

    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord/hook")
    monkeypatch.setattr(httpx, "AsyncClient", Boom)
    await discord.push("hi")  # 예외 전파 없이 반환
