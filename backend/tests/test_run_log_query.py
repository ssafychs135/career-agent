from app.run_log import build_runs_query, list_runs


def test_build_runs_query_no_filters():
    sql, params = build_runs_query()
    assert "FROM run_log" in sql
    assert "ORDER BY finished_at DESC" in sql
    assert "WHERE" not in sql
    assert "LIMIT $1" in sql
    assert params == [30]


def test_build_runs_query_pipeline_and_status():
    sql, params = build_runs_query(pipeline="collector", status="ok", limit=10)
    assert "pipeline = $1" in sql
    assert "status = $2" in sql
    assert "LIMIT $3" in sql
    assert params == ["collector", "ok", 10]


class FakeFetchConn:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, sql, *args):
        return self._rows


async def test_list_runs_shapes_rows():
    from datetime import datetime, timezone
    ts = datetime(2026, 7, 23, 1, 2, 3, tzinfo=timezone.utc)
    rows = [{
        "id": 1, "pipeline": "collector", "ref": "", "label": "",
        "trigger": "manual", "status": "ok",
        "result": '{"scraped": 3, "inserted": 3}',  # asyncpg가 jsonb를 str로 줄 수 있음
        "error": "", "started_at": ts, "finished_at": ts, "duration_ms": 1200,
    }]
    out = await list_runs(FakeFetchConn(rows), limit=5)
    item = out["items"][0]
    assert item["result"] == {"scraped": 3, "inserted": 3}
    assert item["finished_at"] == ts.isoformat()
    assert item["pipeline"] == "collector"
