from app.activity import Activity


def test_set_and_snapshot():
    a = Activity()
    a.set_stage("collector", "스크레이핑", "원티드 518 1p", "0")
    snap = a.snapshot()
    assert snap["collector"]["stage"] == "스크레이핑"
    assert snap["collector"]["detail"] == "원티드 518 1p"
    assert snap["worker"] is None


def test_clear():
    a = Activity()
    a.set_stage("worker", "요약 중")
    a.clear("worker")
    assert a.snapshot()["worker"] is None


def test_research_multi_key():
    a = Activity()
    a.add_research("당근", "기업 리서치 중", "웹 검색")
    a.add_research("토스", "공고 리서치 중")
    research = a.snapshot()["research"]
    assert {r["detail_key"] for r in research} == {"당근", "토스"}
    a.clear_research("당근")
    assert [r["detail_key"] for r in a.snapshot()["research"]] == ["토스"]
