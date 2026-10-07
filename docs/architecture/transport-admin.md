# Transport 운영 관리 UI

## 목적과 경계

`packages/kor-travel-transport-admin/frontend`는 국내 여행 통합 교통정보의 운영 상태를
조회하는 별도 Next.js 관리 UI다. 기존 `frontend/`의 배포 브랜드인 `parking-radar`는
수정하거나 재기동하지 않는다.

관리 UI는 provider API·PostgreSQL·RustFS credential을 받지 않는다. 브라우저 요청은
HttpOnly 서명 세션을 통과한 뒤에만 Next.js server route가 다음의 저장 데이터 읽기 API를
중계한다. 별도 수동 좌표 보정 쓰기 토큰은 서버 측에만 전달하고 브라우저로 보내지 않는다.

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

수집 실행, 백업, 일반 DB 변경, provider 키는 관리 UI의 읽기 proxy 허용 목록에 없다.
예외는 공식 항구·버스터미널 기존 행의 좌표 수동 보정 BFF 한 경로뿐이다. 이 경계는
`lib/transport.ts` 단위 테스트와 `backend/tests/test_transport_admin_contract.py`가
회귀를 막는다.

## 화면과 지도 데이터 경계

- 공통 UI는 shadcn/ui(Base UI, base-nova) + Tailwind v4다. 공식 컴포넌트 소스는
  `components/ui/`, 설정은 `components.json`, 의미 색상 연결은 `app/globals.css`에 둔다.
  Weather `c25642099`의 실제 배치·색상·글꼴 fallback을 기준으로 한다. 밝은 17rem
  레일, 파란 강조색, 24px 헤더 제목, 24/16/12px 반응형 여백을 공유한다.
  모바일에서는 가로 메뉴와 로그아웃을 유지한다. legacy 스타일은 별도 CSS 레이어로 분리한다.
  로그인·검색·다중 선택·탭·상태·Dagster 표의 키보드 및 반응형 계약을 E2E로 검증한다.
- `교통·유가`는 고속도로·유가를 한 화면에서 저장된 7일 통계와 함께 보여 준다. 유종·노선·수집
  source 코드는 화면에서 사람이 이해할 수 있는 명칭으로 바꾸며, 비교가 필요한 값은 Apache
  ECharts 막대 그래프로 제공한다.
- `열차·도시철도`와 `배편`은 각각 저장한 장소 기준정보를 별도 탭에서 검색한다. 배편은
  선택 항구·운항일의 DB 시간표를 읽으며 검색/선택으로 provider를 호출하지 않는다.
  지도 우측 상세는 한 항구·하루만 읽고 오늘부터 9일 뒤까지 선택할 수 있다.
- `/map`의 장소 검색은 저장 장소 API만 읽는다. 공항 상세는 저장 주차를 자동 조회하고
  출도착 버튼을 누를 때만 항공편 조회를 수행한다. 429 보호, 타임아웃, 선택 전환 취소를 적용한다.
  주유소에는 최신 가격·브랜드, 역에는 노선, 항구에는 저장된
  위치·노선을 표시한다. 지도 이동이 끝난 현재 bbox만 종류별로 조회하고, 범위에 한 종류가
  `min(300, floor(900 / 선택 종류 수))`곳을 넘으면 잘린 사실과 확대 방법을 화면에 표시한다.
- 지도는 kor-travel-map admin 지도와 같은 마커·배경지도·컨트롤을 쓴다(2026-10-08,
  Map `399d6b6a` 기준). 이전의 `digitie/maplibre-vworld-react` tarball(`vworld-map-web`/`core`)은
  걷어냈고 `third_party/maplibre-vworld-react` submodule은 이력 참조로만 남는다.
  - 배경지도: `lib/vworld-style.ts`는 Map in-repo VWorld style builder의 사본이다. VWorld WMTS
    `Base` raster(`https://api.vworld.kr/req/wmts/1.0.0/{key}/Base/{z}/{y}/{x}.png`, 256px, 최대 19)를
    MapLibre가 직접 받는다. 키가 비거나 `CHANGE_ME`면 배경색(`#edf1f5`)만 그려 지도와 마커는 그대로
    쓰고 "배경지도 없이" 안내를 띄운다.
  - 셸: `components/vworld-map.tsx`는 Map `VWorldMapView` 포팅이다. 확대/축소(나침반 없음) 오른쪽 위,
    축척(150px·미터) 오른쪽 아래, 접힌 출처 표기. VWorld 타일 오류는 키를 가린 채 화면 안내로만 알린다.
  - 마커: `lib/vendor/map-marker-react/`는 Map 공용 `@kor-travel-map/map-marker-react` 소스(MIT)를
    수정 없이 복사한 것이다(npm 게시 금지·Map ADR-043). 장소 종류 → maki·팔레트 매핑은
    `lib/place-marker-style.ts`가 Map provider 상수(OpiNet·KREX·공항)와 category catalog에서 가져온다.
    주유소 가격은 Map 가격 마커 라벨(`휘 1,650` 한 줄씩)로 쓴다. 이름은 배지에 쓰지 않고 hover 제목·접근 이름으로 준다.
  - 묶음: supercluster(main thread)로 계산하고 Map `createClusterElement`와 같은 brand 원으로 그린다.
    확대 한계 묶음은 Map 겹친 지점 팝업과 같은 MapLibre Popup으로 고른다. 열린 팝업은 viewport 재조회로 닫지 않는다.
- VWorld 브라우저 키는 `NEXT_PUBLIC_VWORLD_API_KEY`로 Docker build 시점에 주입한다
  (`docker-compose.transport-admin.yml`의 `transport-admin-web` build arg → Dockerfile `ARG`/`ENV` →
  `next build`가 번들에 넣는다). compose는 값이 없으면 build를 거부한다(`:?`). 추적 파일에 값을 넣지 않는다.
  기본 `docker-compose.yml`의 `frontend` 서비스에는 지도가 없어 이 키를 받지 않는다.

## 운영 경로

```text
브라우저 ── TLS ── transport.digitie.mywire.org:12305
                         │ 서명 세션 + same-origin API
                         ▼
                 transport-admin-web
                  ├─ 127.0.0.1:14001/v1/transport/*
                  └─ 127.0.0.1:11002/graphql (공용 Dagster webserver, location 범위 query만)

외부 OpenAPI ── TLS ── transport-api.digitie.mywire.org:12301
                         ▼
                   transport-api-gateway ── 127.0.0.1:14001

Dagster 운영 UI ── TLS ── dagster.digitie.mywire.org (Manager 공용 gateway 11001, Basic Auth)
                         ▼
                 공용 Dagster webserver 127.0.0.1:11002 — location `kor-travel-transport`
```

두 listener(12301·12305)는 `docker-compose.transport-admin.yml`의 독립
`kor-travel-transport-admin` project에 속한다. host network를 쓰지만 기존
`kor-travel-transport` 서비스의 port·network·lifecycle은 바꾸지 않는다. 두 project는 같은 앱
디렉터리(`/home/digitie/apps/kor-travel-transport`)에서 돈다. 컨테이너 이름 접두어가 겹치므로
(`kor-travel-transport-*`와 `kor-travel-transport-admin-*`) 이름 필터 대신
`com.docker.compose.project` label의 정확한 값으로 찾는다.

## 인증과 CSRF

- `TRANSPORT_UI_PASSWORD`와 32자 이상 `TRANSPORT_UI_SESSION_SECRET`이 없으면
  production 로그인은 fail-closed 한다.
- Next.js transport proxy는 upstream `Retry-After`를 그대로 전달한다. 항구 시간표 cache
  miss는 provider 전체에서 기본 30초의 보호 간격을 적용하며, 기간 중에는 `429`과 재시도
  초를 반환한다. 따라서 항구 목록을 순회하는 호출도 provider quota를 소진하지 않는다.
- 항구·버스터미널 좌표 수동 보정 POST는 기존 읽기 proxy와 분리한다. 관리자 세션과
  exact origin을 검사한 BFF만 별도 32자 이상 `TRANSPORT_ADMIN_WRITE_TOKEN`을 backend에
  전달한다. 공개 API gateway는 이 경로를 열지 않는다. 토큰이 없는 환경에서는
  쓰기가 비활성화되며 기존 관리자 아이디·비밀번호 초기값은 바꾸지 않는다.
- 로그인·로그아웃과 Dagster GraphQL POST는 `TRANSPORT_UI_PUBLIC_ORIGIN`과 exact
  비교한다. reverse proxy가 client IP를 재작성하는 계약이 있을 때만
  `TRANSPORT_UI_TRUST_PROXY=true`를 허용한다.
- Dagster는 Manager의 공용 제어 평면이다(ADR-54). 운영 UI의 `/api/dagster/graphql`은 브라우저의 GraphQL
  문서를 넘기지 않고, 이름 붙은 작업(`TransportDagsterOverview`)을 이 location(`kor-travel-transport`)으로 좁힌
  query로 바꿔 공용 webserver에 보낸다(`lib/dagster-scope.ts`). 외부 Dagster UI는 공용 gateway(Basic Auth,
  same-origin POST, `/health`만 무인증 204)다. 옛 `transport-dagster-gateway`(12302)는 없어졌다(redirect 없음).

## 배포와 검증

운영 환경값은 n150의 추적하지 않는 `.env.server14`에 둔다. 초기 스택 배포는
`scripts/deploy-transport-admin-server14.sh`를 사용하며, 서비스가 아직 실행 중이지
않은 port에 listener가 있으면 기존 프로세스를 중단하지 않고 실패한다.
공개 API gateway는 bind mount한 allowlist 설정을 쓰므로 배포 때 전용 두 서비스를
강제 재생성하여 변경된 공개 경로가 즉시 적용되게 한다.
수동 좌표 보정 기능이 포함된 관리자 UI는 새 backend를 먼저 배포한다. 전용 관리자
배포 스크립트가 내부 `coordinate-write-v1` capability와 비추적 쓰기 토큰 설정을
사전 확인하므로, 이전 backend와 새 UI의 엇갈린 배포를 성공으로 보지 않는다.

UI만 바뀌는 경우 전체 스택 배포는 하지 않는다. 검증한 UI 이미지만 지정한 뒤
`up -d --no-deps --no-build --force-recreate transport-admin-web`으로 교체한다.
이전 UI 이미지를 보존하고 실패 시 같은 명령으로 복구한다. 전후 API·worker·daemon·
webserver·gateway·기존 parking-radar의 컨테이너 ID와 이미지를 대조한다.
서로 다른 API/worker release를 전체 Compose 명령으로 임의 통일하지 않는다.

포트 전환 같은 공용 인프라 작업은 `kor-travel-docker-manager`가 소유한다. 이 저장소가
cAdvisor, Prometheus, Grafana의 lifecycle을 조작하지 않는다.

live E2E는 n150에서 다음처럼 실행한다. 비밀번호는 shell history에 넣지 않고 안전한
환경변수로 전달한다.

```bash
cd packages/kor-travel-transport-admin/frontend
E2E_BASE_URL=https://transport.digitie.mywire.org \
E2E_TRANSPORT_API_BASE_URL=https://transport-api.digitie.mywire.org \
E2E_TRANSPORT_DAGSTER_BASE_URL=https://dagster.digitie.mywire.org \
E2E_TRANSPORT_UI_PASSWORD="$E2E_TRANSPORT_UI_PASSWORD" \
npm run test:e2e
```
