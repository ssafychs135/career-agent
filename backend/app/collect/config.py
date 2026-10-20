import os

JOB_PROXY_URL = os.environ.get("JOB_PROXY_URL", "")
JOB_PROXY_SECRET = os.environ.get("JOB_PROXY_SECRET", "")
SUMMARY_TIMEOUT = int(os.environ.get("SUMMARY_TIMEOUT", "120"))
DETAIL_TIMEOUT = int(os.environ.get("DETAIL_TIMEOUT", "20"))
