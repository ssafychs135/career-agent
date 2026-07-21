import argparse
import asyncio

from app.research import runner, store


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.research")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--company", help="기업 리서치할 회사명")
    g.add_argument("--job", help="공고 리서치. 형식 source:job_id")
    g.add_argument("--pending-companies", action="store_true", help="미리서치 회사 일괄")
    g.add_argument("--pending-jobs", action="store_true", help="미리서치 공고 일괄")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--force", action="store_true")
    return p


async def dispatch(db, args) -> None:
    if args.company:
        print(await runner.research_company(db, args.company, force=args.force))
    elif args.job:
        source, job_id = args.job.split(":", 1)
        print(await runner.research_job(db, source, job_id, force=args.force))
    elif args.pending_companies:
        for company in await store.pending_companies(db, args.limit):
            print(company, await runner.research_company(db, company, force=args.force))
    elif args.pending_jobs:
        for source, job_id in await store.pending_jobs(db, args.limit):
            print(source, job_id, await runner.research_job(db, source, job_id, force=args.force))


async def _amain(args) -> None:
    from app.db import connect, close  # Plan ② 제공

    pool = await connect()
    try:
        await dispatch(pool, args)
    finally:
        await close(pool)


def main() -> None:
    asyncio.run(_amain(build_parser().parse_args()))


if __name__ == "__main__":
    main()
