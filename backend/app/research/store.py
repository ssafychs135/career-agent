import json


def _jsonb(value):
    return json.dumps(value, ensure_ascii=False) if value is not None else None


async def get_company(db, company):
    row = await db.fetchrow(
        "SELECT * FROM company_research WHERE company = $1", company
    )
    return dict(row) if row else None


async def get_job(db, source, job_id):
    row = await db.fetchrow(
        "SELECT * FROM job_research WHERE source = $1 AND job_id = $2",
        source,
        job_id,
    )
    return dict(row) if row else None


async def get_job_meta(db, source, job_id):
    """jobs 테이블에서 리서치 컨텍스트를 조회. 컬럼명은 실제 jobs 스키마에 맞춤."""
    row = await db.fetchrow(
        "SELECT source, job_id, company, title, tech_stacks, summary, url "
        "FROM jobs WHERE source = $1 AND job_id = $2",
        source,
        job_id,
    )
    return dict(row) if row else None


async def mark_company_running(db, company):
    await db.execute(
        """INSERT INTO company_research (company, status, researched_at)
           VALUES ($1, 'running', now())
           ON CONFLICT (company)
           DO UPDATE SET status = 'running', researched_at = now()""",
        company,
    )


async def mark_job_running(db, source, job_id, company):
    await db.execute(
        """INSERT INTO job_research (source, job_id, company, status, researched_at)
           VALUES ($1, $2, $3, 'running', now())
           ON CONFLICT (source, job_id)
           DO UPDATE SET status = 'running', company = EXCLUDED.company,
                         researched_at = now()""",
        source,
        job_id,
        company,
    )


async def save_company(
    db, company, *, status, overview=None, stability=None,
    data=None, sources=None, model=None,
):
    await db.execute(
        """INSERT INTO company_research
             (company, overview, stability, data, sources, model, status, researched_at)
           VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7, now())
           ON CONFLICT (company) DO UPDATE SET
             overview = EXCLUDED.overview, stability = EXCLUDED.stability,
             data = EXCLUDED.data, sources = EXCLUDED.sources,
             model = EXCLUDED.model, status = EXCLUDED.status,
             researched_at = now()""",
        company, overview, stability, _jsonb(data), _jsonb(sources), model, status,
    )


async def save_job(
    db, source, job_id, company, *, status, tech_detail=None,
    role_detail=None, data=None, sources=None, model=None,
):
    await db.execute(
        """INSERT INTO job_research
             (source, job_id, company, tech_detail, role_detail,
              data, sources, model, status, researched_at)
           VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, now())
           ON CONFLICT (source, job_id) DO UPDATE SET
             company = EXCLUDED.company, tech_detail = EXCLUDED.tech_detail,
             role_detail = EXCLUDED.role_detail, data = EXCLUDED.data,
             sources = EXCLUDED.sources, model = EXCLUDED.model,
             status = EXCLUDED.status, researched_at = now()""",
        source, job_id, company, tech_detail, role_detail,
        _jsonb(data), _jsonb(sources), model, status,
    )


async def pending_companies(db, limit=10):
    rows = await db.fetch(
        """SELECT DISTINCT j.company
           FROM jobs j
           LEFT JOIN company_research c ON c.company = j.company
           WHERE j.company IS NOT NULL AND j.company <> ''
             AND (c.company IS NULL OR c.status = 'failed')
           LIMIT $1""",
        limit,
    )
    return [r["company"] for r in rows]


async def pending_jobs(db, limit=10):
    rows = await db.fetch(
        """SELECT j.source, j.job_id
           FROM jobs j
           LEFT JOIN job_research r ON r.source = j.source AND r.job_id = j.job_id
           WHERE (r.source IS NULL OR r.status = 'failed')
           LIMIT $1""",
        limit,
    )
    return [(r["source"], r["job_id"]) for r in rows]
