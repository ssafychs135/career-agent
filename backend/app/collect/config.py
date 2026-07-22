import os

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://host.docker.internal:1234")
JOB_PROXY_URL = os.environ.get("JOB_PROXY_URL", "")
JOB_PROXY_SECRET = os.environ.get("JOB_PROXY_SECRET", "")
SUMMARY_TIMEOUT = int(os.environ.get("SUMMARY_TIMEOUT", "120"))
DETAIL_TIMEOUT = int(os.environ.get("DETAIL_TIMEOUT", "20"))
