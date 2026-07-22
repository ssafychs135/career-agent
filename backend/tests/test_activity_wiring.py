from app.activity import Activity
from app.research import runner as R


class FakeStore:
    async def get_company(self, db, c): return None
    async def mark_company_running(self, db, c): pass
    async def save_company(self, db, c, **kw): pass


async def test_research_company_publishes_stage(monkeypatch):
    act = Activity()
    seen = {}
    monkeypatch.setattr(R, "store", FakeStore())

    async def fake_runner(prompt, *, allowed_tools="", timeout=0, on_step=None):
        on_step('웹 검색: "x"')                       # claude 서브스텝 시뮬레이트
        seen["research"] = act.snapshot()["research"]  # 실행 중 스냅샷
        return '{"overview":"o","stability":"s","sources":[]}'

    async def noop(*a, **k): pass
    await R.research_company(object(), "당근", runner=fake_runner, notify=noop, activity=act)
    # 실행 중엔 stage가 게시되고, 끝나면 clear
    assert seen["research"][0]["detail_key"] == "당근"
    assert '웹 검색' in seen["research"][0]["stage"] or seen["research"][0]["detail"]
    assert act.snapshot()["research"] == []
