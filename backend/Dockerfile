FROM python:3.12-slim

# Node.js(claude-code 런타임) + claude-code CLI
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && npm install -g @anthropic-ai/claude-code \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.32"
COPY app ./app

# 런타임에 호스트 ~/.claude 를 여기로 마운트. uid는 compose에서 ubuntu와 일치시킴.
ENV HOME=/home/appuser
RUN mkdir -p /home/appuser && chmod 777 /home/appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
