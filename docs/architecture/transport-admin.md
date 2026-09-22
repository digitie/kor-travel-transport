# Transport 운영 관리 UI

## 목적과 경계

`packages/kor-travel-transport-admin/frontend`는 국내 여행 통합 교통정보의 운영 상태를
조회하는 별도 Next.js 관리 UI다. 기존 `frontend/`의 배포 브랜드인 `parking-radar`는
수정하거나 재기동하지 않는다.

관리 UI는 provider API·PostgreSQL·RustFS credential을 받지 않는다. 브라우저 요청은
HttpOnly 서명 세션을 통과한 뒤에만 Next.js server route가 다음의 저장 데이터 읽기 API를
중계한다.

- `GET /v1/transport/collector-status`
- `GET /v1/transport/statistics`
- `GET /v1/transport/highways/traffic`
- `GET /v1/transport/highways/incidents`
- `GET /v1/transport/fuel/stations`

수집 실행, 백업, DB 변경, provider 키는 관리 UI의 허용 목록에 없다. 이 경계는
`lib/transport.ts` 단위 테스트와 `backend/tests/test_transport_admin_contract.py`가
회귀를 막는다.

## 운영 경로

```text
브라우저 ── TLS ── transport.digitie.mywire.org:443
                         │ Caddy ACME TLS 종단
                         │ 서명 세션 + same-origin API
                         ▼
                 transport-admin-web
                  ├─ 127.0.0.1:14001/v1/transport/*
                  └─ 127.0.0.1:14004/graphql

외부 OpenAPI ── TLS ── transport-api.digitie.mywire.org:443
                         ▼
                   transport-api-gateway ── 127.0.0.1:14001

Dagster 운영 UI ── TLS ── transport-dagster.digitie.mywire.org:443
                         ▼
                  transport-dagster-gateway (Basic Auth + Origin POST 차단)
                         ▼
                       127.0.0.1:14004
```

세 upstream listener는 `127.0.0.1:12301`/`12302`/`12305`에만 bind하고, 별도
`transport-tls-gateway` Caddy가 공용 80/443에서 세 hostname을 HTTPS로 종단한다.
모두 `kor-travel-transport-admin` project에 속하며 기존 `kor-travel-airport`
서비스의 port·network·lifecycle은 바꾸지 않는다.

## 인증과 CSRF

- `TRANSPORT_UI_PASSWORD`와 32자 이상 `TRANSPORT_UI_SESSION_SECRET`이 없으면
  production 로그인은 fail-closed 한다.
- 로그인·로그아웃과 Dagster GraphQL POST는 `TRANSPORT_UI_PUBLIC_ORIGIN`과 exact
  비교한다. reverse proxy가 client IP를 재작성하는 계약이 있을 때만
  `TRANSPORT_UI_TRUST_PROXY=true`를 허용한다.
- 외부 Dagster gateway는 별도의 Basic Auth를 요구하고 POST의 `Origin`을
  `TRANSPORT_DAGSTER_PUBLIC_ORIGIN`으로 제한한다. `/health`만 인증 없이 204를
  반환한다.

## 배포와 검증

운영 환경값은 n150의 추적하지 않는 `.env.server14`에 둔다. 배포는
`scripts/deploy-transport-admin-server14.sh`만 사용하며, 서비스가 아직 실행 중이지
않은 port에 listener가 있으면 기존 프로세스를 중단하지 않고 실패한다.

포트 전환 같은 공용 인프라 작업은 `kor-travel-docker-manager`가 소유한다. 이 저장소가
cAdvisor, Prometheus, Grafana의 lifecycle을 조작하지 않는다.

live E2E는 n150에서 다음처럼 실행한다. 비밀번호는 shell history에 넣지 않고 안전한
환경변수로 전달한다.

```bash
cd packages/kor-travel-transport-admin/frontend
E2E_BASE_URL=https://transport.digitie.mywire.org \
E2E_TRANSPORT_API_BASE_URL=https://transport-api.digitie.mywire.org \
E2E_TRANSPORT_DAGSTER_BASE_URL=https://transport-dagster.digitie.mywire.org \
E2E_TRANSPORT_UI_PASSWORD="$E2E_TRANSPORT_UI_PASSWORD" \
npm run test:e2e
```
