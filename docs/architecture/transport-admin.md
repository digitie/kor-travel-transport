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
- `GET /v1/transport/features/places`

`/v1/transport/statistics`는 PostgreSQL에 저장된 스냅샷만 집계하고, 같은
`route_no`·기간 조합은 기본 60초 동안 backend 메모리에 재사용한다. 이는 반복 대시보드
조회가 집계를 중복 실행하지 않게 하는 성능 경계이며, 수집 원본을 다시 호출하지 않는다.
서로 다른 cache miss도 기본 두 개까지만 동시에 집계해 public 요청이 공용 PostgreSQL을
점유하지 못하게 한다.

수집 실행, 백업, DB 변경, provider 키는 관리 UI의 허용 목록에 없다. 이 경계는
`lib/transport.ts` 단위 테스트와 `backend/tests/test_transport_admin_contract.py`가
회귀를 막는다.

## 화면과 지도 데이터 경계

- `교통·유가`는 고속도로·유가를 한 화면에서 저장된 7일 통계와 함께 보여 준다. 유종·노선·수집
  source 코드는 화면에서 사람이 이해할 수 있는 명칭으로 바꾸며, 비교가 필요한 값은 Apache
  ECharts 막대 그래프로 제공한다.
- `열차·도시철도`와 `배편`은 각각 저장한 장소 기준정보를 별도 탭에서 검색한다. 배편 탭은
  목록을 열거나 검색할 때 시간표 provider를 호출하지 않는다. 사용자가 특정 항구의 `오늘 운항 보기`
  를 선택한 경우에만 해당 항구의 실시간 시간표를 한 번 요청한다.
- `/map`은 저장 장소 API만 읽는다. 주유소에는 최신 가격·브랜드, 역에는 노선, 항구에는 저장된
  위치·노선을 표시한다. 운영 앱은 지도 엔진을 직접 조작하지 않고
  [`digitie/maplibre-vworld-react`](https://github.com/digitie/maplibre-vworld-react) 의
  `VWorldMapView`, `ClusterLayer`, `Marker`, `Popup` 선언형 컴포넌트를 사용한다.
- 위 provider는 Git submodule `third_party/maplibre-vworld-react`의 `cfdc64f` 고정 revision과
  `frontend/vendor/README.md`의 SHA-256 매핑과 재현 가능한 tarball로 추적한다. Docker build는 tarball만 설치하므로
  checkout 경로에 의존하지 않는다. VWorld 키는 `NEXT_PUBLIC_VWORLD_API_KEY`로 Docker
  build 시점에 주입하며, 추적 파일에 넣지 않는다.

## 운영 경로

```text
브라우저 ── TLS ── transport.digitie.mywire.org:12305
                         │ 서명 세션 + same-origin API
                         ▼
                 transport-admin-web
                  ├─ 127.0.0.1:14001/v1/transport/*
                  └─ 127.0.0.1:14004/graphql

외부 OpenAPI ── TLS ── transport-api.digitie.mywire.org:12301
                         ▼
                   transport-api-gateway ── 127.0.0.1:14001

Dagster 운영 UI ── TLS ── transport-dagster.digitie.mywire.org:12302
                         ▼
                  transport-dagster-gateway (Basic Auth + Origin POST 차단)
                         ▼
                       127.0.0.1:14004
```

세 listener는 `docker-compose.transport-admin.yml`의 독립
`kor-travel-transport-admin` project에 속한다. host network를 쓰지만 기존
`kor-travel-airport` 서비스의 port·network·lifecycle은 바꾸지 않는다.

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
공개 API gateway는 bind mount한 allowlist 설정을 쓰므로 배포 때 전용 세 서비스를
강제 재생성하여 변경된 공개 경로가 즉시 적용되게 한다.

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
