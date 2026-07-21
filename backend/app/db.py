import os

import asyncpg
from fastapi import Request


async def connect() -> asyncpg.Pool:
    """DATABASE_URL(asyncpg DSN)로 커넥션 풀 생성. main.py lifespan이 호출."""
    return await asyncpg.create_pool(
        dsn=os.environ["DATABASE_URL"], min_size=1, max_size=10
    )


async def close(pool: asyncpg.Pool) -> None:
    await pool.close()


async def get_conn(request: Request):
    """FastAPI Depends용 — 앱 풀(app.state.db)에서 conn을 빌려 yield."""
    async with request.app.state.db.acquire() as conn:
        yield conn
