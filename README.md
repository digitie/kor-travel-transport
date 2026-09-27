# kor-travel-transport

이 저장소는 국내 여행을 위한 통합 교통정보 라이브러리/API와 이를 검증하는
`parking-radar` 웹앱을 함께 담는다. 저장소/패키지 식별자는 `kor-travel-transport`이며,
웹앱의 사용자 노출 브랜드/화면 표시 이름은 호환성을 위해 계속 `parking-radar`다.

`kor-travel-transport`의 목표는 공항·열차·고속도로·도시철도·여객항구·배편 등 여행에
필요한 데이터를 provider 라이브러리로 수집하고, 주기적으로 PostgreSQL에 원본/정규화
스냅샷을 저장한 뒤, 외부 OpenAPI와 저장 데이터 기반 내부 통계 API로 즉시 제공하는
것이다. 현재 이 PR은 `python-krex-api`의 고속도로 소통·돌발 정보와
`python-opinet-api` 최신 Playwright 지역별 화면 수집기의 주유소·유가 데이터를 이
흐름에 연결한다.

`parking-radar` 화면은 이 통합 데이터 플랫폼 중 기존 공항 주차 기능을 검증하는
반응형 웹앱이다. 공항 전체 기준과 세부 주차장 기준을 같은 화면에서 오가며 여행
출발 전에 “지금 어디가 얼마나 남았는지”와 “보통 언제 빠르게 줄어드는지”를 함께 볼 수
있게 만든다.

## 핵심 기능

- 공항별 현재 주차 현황 조회
- 세부 주차장 단위 조회
  - 예: 김해 `P1 / P2 / P3`
- 최근 7일 10분 단위 주차 시계열
- 시계열 차트 hover / touch 툴팁
- 시계열 X축 6시간 단위 라벨
- 시계열 보간 없는 계단형 표시
- 시계열 기본 커서가 최신 값에 고정되고 오른쪽 끝부터 바로 표시
- 공휴일 날짜 배경 강조와 그래프 상단 공휴일명 표시
- 하루 흐름과 비행편 오버레이 차트
  - 0시부터 24시까지 최근 7일 잔여 주차면 겹침 표시
  - 원하는 날짜의 선 숨김 / 다시 표시
  - 출발편 / 도착편 마커 개별 표시 토글
  - 공휴일 선과 마커를 일반일과 다르게 표시
- 선택 공항 비행편 출도착 시간 마커
  - 시간, 편명, 출발공항, 도착공항 표시
- 같은 시간/출발지/도착지 공동운항편 묶음 표시
- 요일 x 시간 기준 평균 잔여 주차면 히트맵
- 최근 8개 공휴일 기준 시간대별 잔여 주차면 패턴
- 평균으로 가장 빠듯한 시간 / 가장 여유 있는 시간 요약
- 요일 x 시간 히트맵의 최고/최저 혼잡 시간 요약
- 요일별 임계 달성 시간 / 날짜별 임계 달성 시간 히스토리
- 10대 / 50대 임계치 진입 및 회복 이벤트
- 마지막으로 본 공항 / 세부 주차장 자동 복원
- 웹페이지 자동 갱신
- 주차 요금 계산
  - 한국공항공사 요금과 인천공항공사 요금 API를 분리해 사용
- 통합 교통정보 수집 기반
  - 고속도로 실시간 소통·돌발 정보의 주기적 PostgreSQL 적재
  - 오피넷 Playwright 지역별 주유소·유종별 가격·편의 플래그의 주기적 적재
  - 적재 원본, 정규화 스냅샷, 소스별 수집 상태와 중복 방지
  - 저장 데이터 기반 고속도로 속도·돌발·유가 통계

## 기술 스택

- 백엔드: FastAPI, SQLAlchemy 2, PostgreSQL 16, Alembic
- 프론트엔드: Next.js App Router, React, TypeScript
- 테스트: pytest, Vitest
- 실행: Docker Compose (PostgreSQL은 `docker-compose.db.yml`로 별도 컨테이너, T-032)
- 개발 환경: WSL2 + Docker
- 운영 목표 환경: Ubuntu 24.04 on Odroid M1S

## 데이터 소스

- 한국공항공사 공항 주차장 정보  
  [https://www.data.go.kr/data/15056803/openapi.do](https://www.data.go.kr/data/15056803/openapi.do)
- 한국공항공사 전국공항 주차장 혼잡도  
  [https://www.data.go.kr/data/15063437/openapi.do](https://www.data.go.kr/data/15063437/openapi.do)
- 한국공항공사 전국공항 주차요금  
  [https://www.data.go.kr/data/15038474/openapi.do](https://www.data.go.kr/data/15038474/openapi.do)
- 인천국제공항공사 주차 정보  
  [https://www.data.go.kr/data/15095047/openapi.do](https://www.data.go.kr/data/15095047/openapi.do)
- 인천국제공항공사 주차요금 정보
  [https://www.data.go.kr/data/15095053/openapi.do](https://www.data.go.kr/data/15095053/openapi.do)
- 한국공항공사 실시간 항공편 운항 정보
  [https://www.data.go.kr/data/15113771/openapi.do](https://www.data.go.kr/data/15113771/openapi.do)
- 인천국제공항공사 여객기 운항 정보
  [https://www.data.go.kr/data/15112968/openapi.do](https://www.data.go.kr/data/15112968/openapi.do)
- 한국천문연구원 특일 정보
  [https://www.data.go.kr/data/15012690/openapi.do](https://www.data.go.kr/data/15012690/openapi.do)

고속도로 소통·돌발은 `python-krex-api`의 `traffic.flow`/`traffic.incident`를 사용하고,
오피넷 지역별 공개 화면은 `python-opinet-api`의 `OpinetBrowserCollector`를 사용한다.
Playwright 수집은 공식 Open API 대체가 아니라 공개 화면의 실험적 수집이며, 현재 pin된
provider의 기본 전체 실행 간격은 8시간이다. provider 정책상 허용 범위는 8~12시간이고
24시간 내 최대 3회다.

현재 실시간 기본 수집원은 `15056803`이며, 인천 주차/요금 API는 별도 플래그로 분리되어 있다.
비행편 정보는 주차 현황 수집과 분리된 조회용 API이며, 하루 흐름 오버레이 차트의 마커 표시 용도로만 사용한다.
공휴일 정보는 주차 현황 수집과 분리된 조회용 API이며, 차트 배경 강조와 공휴일 패턴 분석에 사용한다.

## 빠른 시작

PostgreSQL은 앱(backend/frontend)과 분리된 별도 compose 스택이다(T-032). DB 스택을 먼저
올려야 `kor-travel-airport-net` 외부 네트워크가 생기고, 앱 스택이 거기에 연결된다.

```bash
docker compose -f docker-compose.db.yml up -d
docker compose build
docker compose up -d
```

- 프론트엔드: [http://localhost:3000](http://localhost:3000)
- 백엔드 문서: [http://localhost:8000/docs](http://localhost:8000/docs)

## 192.168.1.14 운영 배포

n150에서만 Docker/PostgreSQL을 실행한다. PostgreSQL은 `docker-compose.db.yml`로 앱과
분리된 독립 컨테이너에서 운영한다(T-032). 운영 공개 포트는 API `14001`, web `14002`이며
DB는 `14000`(loopback 전용, 외부 미노출)이다. 외부 API 주소는
[https://pr-api.digitie.mywire.org](https://pr-api.digitie.mywire.org),
live E2E 기준 웹 주소는 [https://pr.digitie.mywire.org/](https://pr.digitie.mywire.org/)다.
13번에서는 Docker를 실행하거나 중지하지 않고, cutover 전까지 source API와 rollback
기준으로 유지한다.

운영 환경 파일은 n150의
`/home/digitie/apps/kor-travel-airport/.env.server14`에만 두며
[`.env.server14.example`](.env.server14.example)을 시작점으로 사용한다.

```bash
REMOTE_HOST=192.168.1.14 \
REMOTE_APP_DIR=/home/digitie/apps/kor-travel-airport \
./scripts/deploy-server14.sh
```

배포 후 확인:

```bash
curl -fsS http://192.168.1.14:14001/health
curl -fsS http://192.168.1.14:14002/
curl -fsS https://pr-api.digitie.mywire.org/health
curl -fsS https://pr.digitie.mywire.org/api/backend/health
```

데이터 이전과 5분 무손실 cutover는 [`docs/runbooks/migration.md`](docs/runbooks/migration.md)를
따른다. live UI 검증은 다음처럼 외부 도메인으로 실행한다.

```bash
cd frontend
E2E_BASE_URL=https://pr.digitie.mywire.org npm run test:e2e
```

## Historical: 기존 13번 ODROID 배포 (실행 금지)

배포 기준 정보는 루트의 [.env.odroid](</F:/dev/kor-travel-airport/.env.odroid>)에 저장한다.

- 대상 IP: `192.168.1.13`
- 기존 13번 외부 주소: [https://pr2.digitie.mywire.org/](https://pr2.digitie.mywire.org/)
- 사용자: `digitie`
- 앱 디렉터리: `/home/digitie/apps/parking-radar`

13번은 보존된 기존 시스템이며 배포 대상이 아니다. 이 프로젝트의 Docker,
PostgreSQL, 백업/복원, 수집 스케줄러는 모두 n150에서만 실행한다. 따라서
13번을 대상으로 하는 배포 스크립트와 `docker compose` 명령은 실행하지 않는다.
13번은 `https://pr2.digitie.mywire.org/`의 기존 서비스에서 HTTP 읽기만 허용되는
마이그레이션 원본으로 취급한다.

n150 배포와 상태 확인은 [n150 배포 런북](docs/runbooks/deployment.md)을 따른다.

운영 프론트는 기본적으로 같은 origin의 `/api/backend`를 호출하고, Next.js 서버가 Docker 내부 백엔드(`BACKEND_INTERNAL_URL=http://backend:8000`)로 프록시한다. 그래서 내부 LAN 주소와 외부 HTTPS 주소를 같은 빌드로 처리한다.

운영 보안 기본값:

- n150 `CORS_ORIGINS_CSV`는 `https://pr.digitie.mywire.org`와
  `https://pr-api.digitie.mywire.org`를 기준으로 한다. 기존 13번은
  `https://pr2.digitie.mywire.org`를 사용한다.
- `TRUSTED_HOSTS_CSV`는 운영 도메인/내부 호스트만 허용한다.
- `ENABLE_API_DOCS=false`로 공개 API 문서를 닫는다.
- 백업/복원 UI는 별도 app auth 없이 제공하되 private ACL/gateway 보호를 전제로 한다. `지금 수집`은
  local development profile에서만 활성화하며, 브라우저에 공공데이터 API 키를 요구하거나 노출하지 않는다.

## 실데이터 수집

기본 개발 모드는 샘플 데이터 기준이다.  
실데이터 수집으로 전환하려면 `.env` 또는 실행 환경 변수에 아래 값을 넣는다.

```env
ENABLE_SCHEDULER=true
ENABLE_MANUAL_COLLECT=false
SEED_SAMPLE_DATA=false
USE_SAMPLE_CLIENT_WHEN_NO_KEY=false
COLLECT_INTERVAL_SECONDS=300
MANUAL_COLLECT_MIN_INTERVAL_SECONDS=300
UPSTREAM_RATE_LIMIT_BACKOFF_SECONDS=3600
HOLIDAY_CACHE_SECONDS=86400
ENABLE_INCHEON_COLLECTION=true
ENABLE_INCHEON_FEE_COLLECTION=true
AIRPORT_CODES_CSV=CJJ,CJU,GMP,HIN,ICN,KUV,KWJ,MWX,PUS,RSU,TAE,USN,WJU,YNY
DATA_GO_KR_SERVICE_KEY=...

# 통합 교통정보 수집
KEX_EX_API_KEY=...
TRANSPORT_COLLECTION_ENABLED=true
TRANSPORT_COLLECT_INTERVAL_SECONDS=300
TRANSPORT_ROUTE_NOS_CSV=001,050
TRANSPORT_CONZONE_IDS_CSV=
OPINET_BROWSER_ENABLED=true
OPINET_QUERY_LEVEL=sigungu
OPINET_BROWSER_TIMEOUT_MS=60000
```

- `client_mode=live`로 운영할 때는 `SEED_SAMPLE_DATA=false`를 유지한다.
- 샘플 시계열은 `client_mode=sample`에서만 시드한다.
- `15056803` 카탈로그에는 개발계정 `5,000` 트래픽이 보이지만, ODROID 실측에서는 `2026-04-28`에 100회 성공 후 101번째부터 `LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR.`가 발생했다.
- 현재 n150 live는 5분(`300초`) 계약을 지키며, `SCHEDULER_SAFETY_BUFFER_SECONDS=120`에
  따라 유효 tick 시작 간격은 180초다. 외부 API 응답/DB commit 지연을 흡수하고 public n150
  profile의 수동 수집 endpoint는 비활성화한다.
- 현재 n150 live는 `CJJ,CJU,GMP,HIN,ICN,KUV,KWJ,MWX,PUS,RSU,TAE,USN,WJU,YNY`를 처리한다.
- 기존 13번/ODROID의 10분(`600초`) 설정은 historical reference이며 현재 배포 계약이 아니다.
- `15056803`이 한도 초과 상태여도 인천 전용 API(`15095047`, `15095053`)가 활성화되어 있으면 인천 주차/요금 수집은 계속 시도한다.
- 같은 인증키를 쓰는 live 수집기는 동시에 하나만 유지한다.
- 빠른 검증용 live 스택을 잠깐 띄웠다면 검증 직후 반드시 내려야 한다.
- 수집기가 한도 초과를 감지하면 `UPSTREAM_RATE_LIMIT_BACKOFF_SECONDS` 동안 API 호출을 잠시 건너뛰고, `collector-status`에 `upstream_rate_limited=true`와 `upstream_rate_limited_until`을 남긴다.
- `15056803` 공식 문서상 개발계정 트래픽은 `5,000/일`이지만, 실제 운영에서는 더 이르게 `LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR.`가 발생할 수 있으므로 하루 단위 정지 대신 짧은 backoff 후 재시도한다.
- 통합 교통정보 수집은 `TRANSPORT_COLLECTION_ENABLED=true`이고 `ENABLE_SCHEDULER=true`일
  때 같은 backend 안에서 별도 scheduler로 실행된다. 주차 수집 실행 기록과 섞이지 않도록
  `collection_runs.trigger=transport_scheduler`로 분리한다.
- 고속도로 소통·돌발은 기본 5분 주기(`TRANSPORT_COLLECT_INTERVAL_SECONDS`)로 저장한다.
  소통 행과 돌발 행은 각각 `(source, identity_key, observed_at)` unique로 중복을 막는다.
- 오피넷 Playwright 수집은 pin된 provider의 기본 8시간 throttle(허용 범위 8~12시간,
  24시간 내 최대 3회)을 따른다. 화면 자동화가 실패하면 오류를 숨기지 않고
  `transport_collection_states`와 `raw_api_responses`에 남긴다.

동작 방식:

1. 백엔드 기동 직후 스케줄러가 1회 즉시 수집한다.
2. 이후 `COLLECT_INTERVAL_SECONDS` 기준으로 반복 수집한다.
3. 기본 실시간 소스는 `kac_parking`이다.
4. 동일한 `parking_lot_id + observed_at + source` 조합은 중복 저장하지 않는다. HTTP fallback
   migration과 live source가 같은 관측시각을 공유하면 API/분석은 live source를 우선해 한 번만 집계한다.

중요:

- `snapshot_count=0`은 항상 실패가 아니다.
- 공공데이터 원본의 `observed_at`이 이전 수집과 같으면 중복 방지로 저장 건수가 0이 될 수 있다.
- 이 경우에도 `raw_response_count>=1`, `status=success`이면 하나 이상의 원본 소스 호출 자체는 정상이다.

현재 데이터 즉시 갱신:

```bash
curl -X POST http://localhost:8000/v1/admin/collect
```

상태 확인:

```bash
curl http://localhost:8000/v1/admin/collector-status
```

확인 포인트:

- `scheduler_enabled=true`
- `client_mode=live`
- `enabled_sources`에 `kac_parking`, `incheon_parking`, `incheon_fee`가 의도대로 포함되는지 확인
- `data_go_kr_service_key_configured=true`
- `upstream_rate_limited=false`

통합 교통정보 API 확인:

```bash
curl 'http://localhost:8000/v1/transport/highways/traffic?route_no=001'
curl 'http://localhost:8000/v1/transport/highways/incidents?days=1'
curl 'http://localhost:8000/v1/transport/fuel/stations?sido_value=11&product_code=B027'
curl 'http://localhost:8000/v1/transport/statistics?days=7&route_no=001'
curl http://localhost:8000/v1/transport/collector-status
```

위 API는 외부 원본을 매 요청에 재호출하지 않고 PostgreSQL에 저장된 스냅샷을 응답한다.
`/v1/transport/statistics`는 저장 데이터에서 평균/최소/최대 속도, 돌발 건수, 유종별
평균·최소·최대 가격을 계산한다. 전체 API 계약은 `docs/openapi.json`에 기록한다.

## 분석 화면 기준

- `공항 선택` 변경 시 현재 현황과 모든 분석 패널이 해당 공항 기준으로 바뀐다.
- `세부 주차장` 선택 시 아래 패널이 모두 같은 주차장 기준으로 바뀐다.
- 마지막으로 선택한 `공항 / 세부 주차장`은 브라우저에 저장되어 다음 접속 시 자동 복원된다.
  - 현재 잔여 주차면
  - 최근 7일 시계열
  - 요일 x 시간 평균 잔여 주차면
  - 요일 x 시간 히트맵 요약
  - 요일별 임계 달성 시간
  - 날짜별 임계 달성 시간 히스토리
  - 임계치 이벤트
- `전체 주차장`이면 공항 내 활성 주차장을 합산해서 보여준다.
- 시계열의 마지막 값은 항상 화면 상단 `현재 잔여 주차면`과 같은 기준으로 맞춘다.
- 최근 7일 시계열 차트의 주차선은 실제 관측 구간까지만 그리고, 기본 X축을 미래로 확장하지 않는다.
- 비행편 마커는 별도 `하루 흐름과 비행편` 차트에서 0시부터 24시까지의 X축 시간 위치에 표시한다.
- `하루 흐름과 비행편` 차트는 최근 7일 선을 겹쳐 보여주며 날짜별 표시 여부를 토글할 수 있다.
- `하루 흐름과 비행편` 차트에서는 출발편과 도착편 마커를 각각 켜고 끌 수 있으며, 둘 다 끄면 비행편 마커가 모두 숨겨진다.
- 공휴일 날짜는 `하루 흐름과 비행편` 차트에서도 선 모양과 마커 모양을 일반일과 다르게 표시한다.
- 같은 출도착 시간, 출발공항, 도착공항을 가진 공동운항편은 하나의 마커로 묶는다.
- 지난주/이번주/다음주 공휴일은 공항 이름 옆에 문장으로 표시한다.
- 최근 7일 시계열 안에 공휴일이 있으면 해당 날짜의 배경과 공휴일명을 차트에 표시한다.
- 최근 8개 공휴일은 날짜별/시간대별 패턴으로 별도 표시한다.
- 비행편 API 권한이 없거나 응답 오류가 나면 주차장 화면은 유지하고, 하루 흐름 오버레이 차트의 비행편 영역에 오류 상태만 표시한다.

## 테스트

검증과 배포 순서:

1. `WSL2` 셸에서 1차 테스트
2. `WSL2 + Docker`에서 2차 테스트
3. 192.168.1.14 n150 배포
4. `https://pr.digitie.mywire.org` live 스모크 체크

Windows 로컬 PowerShell 테스트는 지양하고, 테스트 통과 기준으로 삼지 않는다.

WSL 1차 백엔드:

```bash
python -m pytest backend/tests -q
```

WSL 1차 프론트엔드:

```bash
cd frontend
npm run test -- --run
npm run build
```

WSL Docker 2차 백엔드:

```bash
docker compose run --rm --no-deps backend pytest -q
```

WSL Docker 2차 프론트엔드:

```bash
docker compose run --rm --no-deps frontend npm run test -- --run
```

반영 시 확인해야 할 항목:

- Docker 컨테이너 내부 테스트 통과
- 모바일 / 데스크톱 반응형 화면
- 시계열 툴팁 동작
- 시계열 계단형 라인과 X축 라벨 레이아웃
- 하루 흐름 오버레이 차트의 비행편 마커와 편명/출도착 정보 표시
- 요일 x 시간 분석 패널 렌더링
- `GET /v1/admin/collector-status`로 수집 모드 확인

## 주요 API

`/health`를 제외한 모든 경로는 `/v1` 아래에 있다([ADR-005](</F:/dev/kor-travel-airport/docs/adr/005-versioned-rest-api-contract.md>)).
에러 응답은 RFC7807 `application/problem+json`. 기계 정본은 `docs/openapi.json`.

- `GET /health`
- `GET /v1/airports`
- `GET /v1/parking/current`
- `GET /v1/parking/history`
- `GET /v1/parking/analytics/timeseries`
- `GET /v1/parking/analytics/by-hour`
- `GET /v1/parking/analytics/by-weekday`
- `GET /v1/parking/analytics/by-weekday-hour`
- `GET /v1/parking/analytics/threshold-events`
- `GET /v1/parking/analytics/threshold-insights`
- `GET /v1/flights/status`
- `POST /v1/fees/calculate`
- `POST /v1/admin/collect` (로컬에서 `ENABLE_MANUAL_COLLECT=true`일 때만)
- `GET /v1/admin/collector-status`

## 문서

- [docs/current-state.md](</F:/dev/kor-travel-airport/docs/current-state.md>)
- [docs/architecture/data-sources.md](</F:/dev/kor-travel-airport/docs/architecture/data-sources.md>)
- [AGENTS.md](</F:/dev/kor-travel-airport/AGENTS.md>)
- [deploy/odroid/README.md](</F:/dev/kor-travel-airport/deploy/odroid/README.md>)
- [docs/architecture/architecture.md](</F:/dev/kor-travel-airport/docs/architecture/architecture.md>)
- [docs/architecture/analytics.md](</F:/dev/kor-travel-airport/docs/architecture/analytics.md>)
- [docs/runbooks/testing.md](</F:/dev/kor-travel-airport/docs/runbooks/testing.md>)
- [docs/runbooks/deployment.md](</F:/dev/kor-travel-airport/docs/runbooks/deployment.md>)
- [docs/architecture/collection.md](</F:/dev/kor-travel-airport/docs/architecture/collection.md>)
- [docs/runbooks/troubleshooting.md](</F:/dev/kor-travel-airport/docs/runbooks/troubleshooting.md>)
- [docs/runbooks/remote-command-safety.md](</F:/dev/kor-travel-airport/docs/runbooks/remote-command-safety.md>)
- [docs/test-strategy.md](</F:/dev/kor-travel-airport/docs/test-strategy.md>)
- [docs/dev-environment.md](</F:/dev/kor-travel-airport/docs/dev-environment.md>)
- [docs/adr/README.md](</F:/dev/kor-travel-airport/docs/adr/README.md>)
- [docs/runbooks/agent-failure-patterns.md](</F:/dev/kor-travel-airport/docs/runbooks/agent-failure-patterns.md>)
- [docs/runbooks/branch-protection.md](</F:/dev/kor-travel-airport/docs/runbooks/branch-protection.md>)
- [docs/runbooks/cross-repo-audit-checklist.md](</F:/dev/kor-travel-airport/docs/runbooks/cross-repo-audit-checklist.md>)
- [docs/runbooks/hostile-review.md](</F:/dev/kor-travel-airport/docs/runbooks/hostile-review.md>)
- [docs/tasks.md](</F:/dev/kor-travel-airport/docs/tasks.md>)

## WSL 테스트 기준

- 모든 테스트와 기본 검증 기준 환경은 `WSL2`이다.
- Windows 로컬 테스트는 지양한다.
- 1차 테스트는 `WSL2` 셸에서 로컬 런타임으로 실행한다.
- 2차 테스트는 `WSL2 + Docker`에서 `docker compose run --rm --no-deps ...` 형태로 실행한다.
- 192.168.1.14 n150 배포는 1차/2차 테스트 통과 이후 진행한다.
- Windows PowerShell은 배포 스크립트와 상태 확인 용도로 사용하되, 테스트 합격 기준은 `WSL2` 결과를 따른다.
