// career-agent CI→CD (GitOps). Jenkins엔 docker만 있어(node/npm/pip 없음) 테스트는 일회용
// 컨테이너로 실행. 작업은 경로동일 마운트된 /home/ubuntu/career-agent에서 수행(docker-out-of-docker
// 상대 바인드마운트가 host 데몬에서 올바른 host 경로로 해석되게).
pipeline {
  agent any
  environment {
    DEPLOY_DIR = '/home/ubuntu/career-agent'
    // Jenkins가 uid 1001로 돌며 HOME 미설정 → docker buildx가 /.docker에 쓰려다 거부됨.
    // 쓰기가능한 Jenkins 홈 하위로 지정(빌드 시 buildx 상태 저장 위치).
    DOCKER_CONFIG = '/var/jenkins_home/.docker'
  }
  stages {
    stage('sync') {
      // Jenkins가 빌드한 정확한 커밋으로 배포 디렉터리 동기화(TOCTOU 방지). .env는 untracked라 보존.
      steps {
        sh '''
          cd ${DEPLOY_DIR}
          git fetch -q origin main && git reset --hard "$GIT_COMMIT"
        '''
      }
    }
    stage('CI') {
      parallel {
        stage('backend-tests') {
          steps {
            sh '''
              docker run --rm -v ${DEPLOY_DIR}/backend:/app -w /app python:3.12-slim \
                sh -c 'pip install -e ".[dev]" -q && python -m pytest -q'
            '''
          }
        }
        stage('frontend-tests') {
          steps {
            sh '''
              docker run --rm -v ${DEPLOY_DIR}/frontend:/app -w /app node:22-slim \
                sh -c 'npm ci && npm test && npm run build'
            '''
          }
        }
        stage('compose-config') {
          steps { sh 'cd ${DEPLOY_DIR} && docker compose --env-file .env config -q' }
        }
      }
    }
    stage('CD deploy') {
      steps {
        sh '''
          mkdir -p "$DOCKER_CONFIG"
          cd ${DEPLOY_DIR} && docker compose --env-file .env up -d --build
        '''
      }
    }
    stage('smoke') {
      // nginx 컨테이너 안에서 확인(localhost=nginx:80, /api는 backend로 프록시).
      // up -d 직후 backend(uvicorn) 부팅 대기 — health가 200 될 때까지 재시도(최대 ~40s).
      steps {
        sh '''
          cd ${DEPLOY_DIR}
          ok=
          for i in $(seq 1 20); do
            if docker compose --env-file .env exec -T nginx wget -qO- http://127.0.0.1/api/health 2>/dev/null | grep -q '"status":"ok"'; then ok=1; break; fi
            sleep 2
          done
          [ "$ok" = 1 ] || { echo "backend health 미준비"; exit 1; }
          docker compose --env-file .env exec -T nginx wget -qO- http://127.0.0.1/ | grep -q '<title>career-agent</title>'
          # (가산) DB 헬스 — postgres·migrate 배포 회귀 방지. 기존 nginx-exec wget 형태 유지(curl 금지).
          dbok=
          for i in $(seq 1 10); do
            if docker compose --env-file .env exec -T nginx wget -qO- http://127.0.0.1/api/db/health 2>/dev/null | grep -q '"ok":true'; then dbok=1; break; fi
            sleep 3
          done
          [ "$dbok" = 1 ] || { echo "db health 미준비"; exit 1; }
          echo "smoke ok"
        '''
      }
    }
  }
  post {
    failure {
      sh '''
        WEBHOOK=$(grep '^DISCORD_WEBHOOK_URL=' ${DEPLOY_DIR}/.env 2>/dev/null | cut -d= -f2-)
        [ -n "$WEBHOOK" ] && curl -s -m 15 -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
          -d "{\\"content\\":\\"🔴 career-agent 빌드 실패: ${BUILD_URL}\\"}" "$WEBHOOK" >/dev/null || true
      '''
    }
  }
}
