# agent.chs135.com — cloudflared 라우트 + Cloudflare Access 셋업

career-agent를 기존 A1 cloudflared 터널로 노출한 절차 기록. (토큰·시크릿 값은 제외.)

## 터널 (원격관리, 토큰 기반)
- account: `8bd9456dc35bf6b46fe8d757c1e5f947`
- tunnel: `fe00b800-f181-452e-80c0-06340fded55a` (컨테이너 `a1-cloudflared-1`)
- ingress 규칙 추가 (`PUT /accounts/{acct}/cfd_tunnel/{tunnel}/configurations`):
  `agent.chs135.com → http://localhost:80` (catch-all `http_status:404` 앞에 삽입)
  - 기존 유지: n8n→localhost:5678, jenkins→localhost:8080

## DNS
- zone: `chs135.com` (`6583a54fdbe333681d5659ecdd113eb0`)
- `agent` CNAME → `fe00b800-f181-452e-80c0-06340fded55a.cfargotunnel.com` (proxied)

## Access (self-hosted app)
- app: `career-agent` / domain `agent.chs135.com` / id `6d91bc8f-c51b-43f4-af6a-9bd2712a4598`
- IdP: Google (`0e5f3e73-5d7f-4a46-979a-33e53586f2ed`), auto_redirect_to_identity=true, session 24h
- policy `allow-owner`: include email `ssafychs135@gmail.com` (n8n 앱 정책 미러링)

## 검증
- 미인증 요청 → `HTTP 302` → `chs135.cloudflareaccess.com/cdn-cgi/access/login/agent.chs135.com` (게이트 작동)
- 브라우저에서 Google 로그인 후 페이지 접근(health ok, claude OK 표시).

## nginx는 localhost:80 바인딩(인터넷 직접노출 없음). 진입점은 터널뿐.
