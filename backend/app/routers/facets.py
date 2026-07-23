from typing import Any

from fastapi import APIRouter, Depends

from app.db import get_conn
from app.facets_repo import get_facets

router = APIRouter(prefix="/api", tags=["facets"])


@router.get("/facets")
async def read_facets(conn: Any = Depends(get_conn)):
    return await get_facets(conn)
