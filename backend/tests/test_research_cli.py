from app.research.__main__ import build_parser, dispatch


def test_parser_job_splits_source_id():
    args = build_parser().parse_args(["--job", "wanted:42", "--force"])
    assert args.job == "wanted:42" and args.force is True


def test_parser_pending_with_limit():
    args = build_parser().parse_args(["--pending-companies", "--limit", "3"])
    assert args.pending_companies is True and args.limit == 3


async def test_dispatch_company(monkeypatch):
    calls = []

    async def rc(db, company, url="", *, force=False):
        calls.append(("company", company, force))
        return "done"

    monkeypatch.setattr("app.research.__main__.runner.research_company", rc)
    args = build_parser().parse_args(["--company", "토스", "--force"])
    await dispatch(object(), args)
    assert calls == [("company", "토스", True)]


async def test_dispatch_job_splits(monkeypatch):
    calls = []

    async def rj(db, source, job_id, *, force=False):
        calls.append((source, job_id, force))
        return "done"

    monkeypatch.setattr("app.research.__main__.runner.research_job", rj)
    args = build_parser().parse_args(["--job", "wanted:42"])
    await dispatch(object(), args)
    assert calls == [("wanted", "42", False)]
