from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

SETTINGS_DEFAULTS = dict(
    keywords=["백엔드"],  # 비어 있으면 안 됨: _clean_keywords가 []를 거부(무레코드 시 get_settings 폴백에 사용)
    allowed_wanted_categories=[518, 507], max_career_years=2,
    max_pages=9999, collect_hour=9, batch_size=20,
    model="kanana-1.5-8b-instruct-2505-mlx", summary_backend="local",
    max_attempts=5, worker_interval_min=5, enabled=False, discord_webhook_url="",
    allowed_regions=[], hidden_companies=[],
    notify_enabled=False,
)

# UPSERT 컬럼 순서(단일 소스 오브 트루스). updated_at은 now()로 별도 처리.
_COLUMNS = [
    "keywords", "allowed_wanted_categories", "max_career_years", "max_pages",
    "collect_hour", "batch_size", "model", "summary_backend", "max_attempts",
    "worker_interval_min", "enabled", "discord_webhook_url",
    "allowed_regions", "hidden_companies",
    "notify_enabled",
]


class Settings(BaseModel):
    keywords: list[str]
    allowed_wanted_categories: list[int]
    max_career_years: int = Field(ge=0)
    max_pages: int = Field(ge=1)
    collect_hour: int = Field(ge=0, le=23)
    batch_size: int = Field(ge=1, le=100)
    model: str = Field(min_length=1)
    summary_backend: Literal["local", "claude"]
    max_attempts: int = Field(ge=1, le=20)
    worker_interval_min: int = Field(ge=1)
    enabled: bool
    discord_webhook_url: str = ""
    # 전역 필터 — 빈 배열이면 미적용(지역=전체 표시, 기업=아무것도 숨기지 않음)
    allowed_regions: list[str] = Field(default_factory=list)
    hidden_companies: list[str] = Field(default_factory=list)
    # 알림 발송 마스터 스위치 — 컷오버 통제를 위해 기본 false
    notify_enabled: bool = False
    updated_at: Optional[datetime] = None

    @field_validator("keywords")
    @classmethod
    def _clean_keywords(cls, v: list[str]) -> list[str]:
        cleaned = [k.strip() for k in v if k and k.strip()]
        if not cleaned:
            raise ValueError("keywords must have at least one non-empty value")
        return cleaned


def build_upsert(s: Settings) -> tuple[str, list]:
    """싱글턴(id=1) UPSERT. 편집 컬럼만 파라미터화, updated_at=now()."""
    cols = ", ".join(_COLUMNS)
    placeholders = ", ".join(f"${i}" for i in range(1, len(_COLUMNS) + 1))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in _COLUMNS)
    sql = (
        f"INSERT INTO app_settings (id, {cols}, updated_at) "
        f"VALUES (1, {placeholders}, now()) "
        f"ON CONFLICT (id) DO UPDATE SET {updates}, updated_at = now() "
        f"RETURNING {cols}, updated_at"
    )
    params = [getattr(s, c) for c in _COLUMNS]
    return sql, params


async def get_settings(conn) -> Settings:
    row = await conn.fetchrow(
        f"SELECT {', '.join(_COLUMNS)}, updated_at FROM app_settings WHERE id = 1"
    )
    if row is None:
        return Settings(**SETTINGS_DEFAULTS)
    return Settings(**dict(row))


async def put_settings(conn, s: Settings) -> Settings:
    sql, params = build_upsert(s)
    row = await conn.fetchrow(sql, *params)
    return Settings(**dict(row))
