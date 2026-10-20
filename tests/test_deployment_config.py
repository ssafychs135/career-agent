"""Static deployment regressions; effective Compose validation runs in CI."""
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def test_compose_has_only_application_default_network():
    compose = (ROOT / "docker-compose.yml").read_text()
    assert compose.split("\nnetworks:\n")[1].strip() == "default:"
    assert compose.count("    networks:\n      - default\n") == 4
    for obsolete in ("jobs_shared", "llm_net", "n8n-pjt_default", "LLM_BASE_URL", "host.docker.internal", "host-gateway"):
        assert obsolete not in compose
    assert "- DATABASE_URL=${DATABASE_URL}" in compose
    assert "- ./data/postgres:/var/lib/postgresql/data" in compose
    assert "- ./db:/docker-entrypoint-initdb.d:ro" in compose
    assert "- JOB_PROXY_URL=${JOB_PROXY_URL}" in compose
    assert "- JOB_PROXY_SECRET=${JOB_PROXY_SECRET}" in compose
    assert "- /home/ubuntu/.claude:/home/appuser/.claude:rw" in compose
    assert "- /home/ubuntu/.claude.json:/home/appuser/.claude.json:rw" in compose
    assert 'pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}' in compose


def test_example_database_credentials_are_consistent_and_local_llm_absent():
    example = (ROOT / ".env.example").read_text()
    env = dict(line.split("=", 1) for line in example.splitlines() if line and not line.startswith("#"))
    dsn = urlparse(env["DATABASE_URL"])
    assert dsn.username == env["POSTGRES_USER"] == "career_agent"
    assert dsn.password == env["POSTGRES_PASSWORD"]
    assert dsn.path == f'/{env["POSTGRES_DB"]}'
    assert dsn.hostname == "postgres"
    assert "LLM_BASE_URL" not in example
    assert "host.docker.internal" not in example
    assert "JOB_PROXY_URL" in env and "JOB_PROXY_SECRET" in env
    assert "기존 배포는 실제 DB 사용자·비밀번호·DB명·데이터를 유지" in example
