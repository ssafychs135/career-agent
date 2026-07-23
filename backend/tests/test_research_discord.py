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
