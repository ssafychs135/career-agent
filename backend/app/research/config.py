import os

RESEARCH_MODEL = os.environ.get("RESEARCH_MODEL", "")
RESEARCH_TIMEOUT = int(os.environ.get("RESEARCH_TIMEOUT", "180"))

# 자동모드(APScheduler) — 기본 꺼짐
RESEARCH_AUTO_ENABLED = os.environ.get("RESEARCH_AUTO_ENABLED", "false").lower() == "true"
RESEARCH_AUTO_INTERVAL_MIN = int(os.environ.get("RESEARCH_AUTO_INTERVAL_MIN", "30"))
RESEARCH_AUTO_LIMIT = int(os.environ.get("RESEARCH_AUTO_LIMIT", "5"))
