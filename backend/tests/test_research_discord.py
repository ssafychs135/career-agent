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
        is_error = False
        status_code = 204
        text = ""

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


def _failing_client(monkeypatch, discord, status, body):
    class FakeResp:
        is_error = True
        status_code = status
        text = body

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None):
            return FakeResp()

    monkeypatch.setattr(discord.httpx, "AsyncClient", lambda **kw: FakeClient())


async def test_push_embeds_error_carries_status_and_response_body(monkeypatch):
    """디스코드의 거절 사유는 응답 본문에만 있다. raise_for_status는 그걸 버려서
    운영 로그에 상태줄만 남았고, 500이 왜 나는지 알 수 없었다."""
    import pytest
    from app.research import discord
    _failing_client(monkeypatch, discord, 500, '{"message": "무언가 잘못됨", "code": 50035}')
    discord.set_webhook("https://settings.example/hook/tok")
    try:
        with pytest.raises(RuntimeError) as ei:
            await discord.push_embeds(None, [{"title": "t"}])
    finally:
        discord.set_webhook("")
    msg = str(ei.value)
    assert "500" in msg
    assert "무언가 잘못됨" in msg and "50035" in msg


async def test_push_embeds_error_does_not_leak_webhook_token(monkeypatch):
    """httpx 기본 에러는 URL 전체를 메시지에 넣어 웹훅 토큰이 로그에 찍혔다
    (실패가 5분마다 반복되며 운영 로그에 계속 누적)."""
    import pytest
    from app.research import discord
    _failing_client(monkeypatch, discord, 500, "boom")
    discord.set_webhook("https://discord.example/api/webhooks/123/SUPERSECRETTOKEN")
    try:
        with pytest.raises(RuntimeError) as ei:
            await discord.push_embeds(None, [{"title": "t"}])
    finally:
        discord.set_webhook("")
    assert "SUPERSECRETTOKEN" not in str(ei.value)
