# 현재 상태 요약

이 문서는 `parking-radar`의 현재 구현 상태와 운영 시 알아야 할 결정을 한 곳에 모아둔 문서다.  
세부 기능 문서가 흩어져 있을 때 먼저 이 문서를 읽고, 필요하면 링크된 개별 문서로 내려가는 것을 권장한다.

최종 확인 기준일:
- `2026-09-20`

## 0. 통합 교통정보 목적과 현재 구현

`kor-travel-transport`는 국내 여행을 위한 통합 교통정보 라이브러리/API다. 필요한
교통 데이터를 provider에서 주기적으로 얻어 PostgreSQL에 원본/정규화 스냅샷으로
저장하고, 저장 자료를 외부 OpenAPI로 즉시 제공하며, 스냅샷 기반 내부 통계를 부가
정보로 제공한다. 공항 주차 대시보드는 기존 기능이며 통합 플랫폼의 한 소비 화면이다.

PR #30에서 구현·머지한 범위:

- `python-krex-api` `traffic.flow`/`traffic.incident`를 transport scheduler에 연결
- 최신 `python-opinet-api` Playwright collector를 사용해 지역·주유소·유종 가격·편의
  정보를 PostgreSQL에 저장
- `highway_traffic_snapshots`, `highway_incident_snapshots`, `fuel_stations`,
  `fuel_price_snapshots`, `transport_collection_states`와 Alembic `0004`/`0005` 추가
- `/v1/transport/highways/traffic`, `/v1/transport/highways/incidents`,
  `/v1/transport/fuel/stations`, `/v1/transport/statistics`,
  `/v1/transport/collector-status` 제공
- KREX 전체 페이지 수집·쿼터 backoff·PostgreSQL advisory lock, OPINET 빈 결과 보호,
  고속도로/돌발/유가의 중복 저장 방지, 소스별 수집 상태와 공개 오류 마스킹 제공

다음 범위는 [KRIC 신청 목록/계획](research/kric-api-applications.md)과
[교통정보 확장 조사](research/transport-data-gaps.md)에 정리했다. KRIC 라이브러리와
철도/선박 수집·DB 연결은 아직 완료되지 않았다. 운영 검증의 최신 상태와 배포 중 취소
후 회복 여부는 `docs/resume.md`를 따른다.

## 1. 현재 구현 범위

현재 구현된 주요 기능은 다음과 같다.

- 공항별 현재 주차 현황 조회
- 세부 주차장 단위 조회
- 최근 7일, 10분 단위 시계열
- 시계열 hover / touch 툴팁
- 시계열 X축 6시간 단위 라벨
- 시계열 계단형(step) 차트
- 시계열 최신 포인트 기본 활성화 및 오른쪽 최신 구간 우선 노출
- 공휴일/토요일/일요일 날짜 배경 강조와 이름 표시
- 하루 흐름과 비행편 오버레이 차트
  - 0시부터 24시까지 최근 7일 잔여 주차면 겹침 표시
  - 날짜별 선 숨김 / 다시 표시
  - 출발편 / 도착편 마커 개별 토글
  - 공휴일/토요일/일요일 선과 마커 구분 표시
- 선택 공항 비행편 출도착 시간 마커
- 공동운항편 묶음 표시
- 요일 x 시간 평균 잔여 주차면 히트맵
- 최근 8개 공휴일/토요일/일요일 날짜별 시간대 잔여 주차면 패턴
- 평균으로 가장 빠듯한 시간 / 가장 여유 있는 시간 요약
- 요일 x 시간 평균 잔여 주차면 히트맵 내 최고/최저 혼잡 시간 요약
- 요일별 임계 달성 시간
- 날짜별 임계 달성 시간 히스토리
- 10대 / 50대 임계치 이벤트 분석
- 공항/세부 주차장 스코프 전환
- 마지막으로 본 공항 / 세부 주차장 복원
- 주차 요금 계산
  - 한국공항공사 요금 API
  - 인천공항공사 요금 API
- 웹 UI에서 수동 수집 실행
- 수동 수집 쿨다운 제한
- 웹 UI 15초 자동 갱신
- 모바일 / 데스크톱 반응형 대응

## 2. 기본 실행 모드

로컬 `docker compose up -d` 기본 실행은 개발용 기준이다.

기본값:

- `seed_sample_data=true`
- `enable_scheduler=false`
- `use_sample_client_when_no_key=true`

즉, 별도 설정 없이 띄우면:

- 샘플 데이터가 들어간다.
- 자동 수집은 돌지 않는다.
- 인증키가 없어도 앱은 동작한다.
- 이 상태에서는 `client_mode=sample`로 보는 것이 맞다.

실제 수집 모드 여부는 항상 아래 API로 확인한다.

```bash
curl http://localhost:8000/v1/admin/collector-status
```

핵심 확인 필드:

- `client_mode`
- `scheduler_enabled`
- `data_go_kr_service_key_configured`
- `enabled_sources`

## 3. 데이터 소스 결정

현재 주 수집원:

- `15056803` 한국공항공사 공항 주차장 정보

보조 / 선택 소스:

- `15063437` 한국공항공사 전국공항 주차장 혼잡도
- `15038474` 한국공항공사 전국공항 주차요금
- `15095047` 인천국제공항공사 주차 정보
- `15095053` 인천국제공항공사 주차요금 정보
- `15113771` 한국공항공사 실시간 항공운항 현황 정보 상세 조회 서비스
- `15112968` 인천국제공항공사 여객기 운항 정보
- `15012690` 한국천문연구원 특일 정보

현재 코드 기준 운영 판단:

- 한국공항공사 실시간 주차 현황은 `15056803`을 기본으로 사용한다.
- `15063437`은 혼잡도 참고용 후보지만 기본 수집원은 아니다.
- `15038474`, `15095047`, `15095053`은 별도 플래그를 켰을 때만 시도한다.
- `15056803`이 한도 초과 상태여도 `15095047`, `15095053` 인천 전용 소스는 계속 시도한다.
- 비행편 정보는 주차 수집과 분리된 조회용 API이며, `/v1/flights/status`를 통해 하루 흐름 오버레이 차트 마커에만 사용한다.
- 공휴일 정보는 주차 수집과 분리된 조회용 API이며, `/v1/holidays/summary`와 `/v1/parking/analytics/holiday-patterns`를 통해 차트 배경과 공휴일/토/일요일 패턴에 사용한다.
- `2026-05-09` 현재 보유 키로 `15113771` 한국공항공사 실시간 항공운항 현황 정보 상세 조회 서비스는 정상 응답을 확인했다.
- `2026-05-09` 현재 보유 키로 `15112968` 인천 여객기 운항 정보는 정상 응답을 확인했다.
- `2026-05-09` 현재 보유 키로 `15012690` 한국천문연구원 특일 정보의 `2026년 5월` 조회는 `resultCode=00`을 반환했다.
- 기존 `15000126` 계열 `FlightStatusList/getFlightStatusList`는 현재 보유 키로 `SERVICE ACCESS DENIED ERROR.`가 반환되어 live 호출에서 제외한다.

관련 문서:
- [architecture/data-sources.md](</F:/dev/kor-travel-airport/docs/architecture/data-sources.md>)

## 4. 공항별 세부 주차장 기준

현재 화면과 샘플/파서 기준으로 특히 주의한 공항은 다음과 같다.

### 김해 `PUS`

- `P1 여객주차장`
- `P2 여객주차장`
- `P3 여객(화물)주차장`

### 김포 `GMP`

- `국내선 제1주차장`
- `국내선 제2주차장`
- `국제선 지하주차장`
- `국제선 주차빌딩`

### 제주 `CJU`

- `P1 주차장`
- `P2 장기주차장`
- `화물터미널주차장`

### 인천 `ICN`

샘플 기준으로 아래 구조를 둔다.

- `T1 단기주차장`
- `T1 장기주차장 P1 / P2 / P3`
- `T1 예약주차장`
- `T2 단기주차장`
- `T2 장기주차장`
- `T2 예약주차장`

실제 `15095047` 응답에서는 `T1 단기주차장지하1층`처럼 층 정보가 붙은 이름도 내려온다. 파서는 실데이터 이름을 유지하되 단기/장기/예약/화물 성격을 분류하고, 요금 규칙은 `T1 단기주차장` 같은 접두어 기준으로 연결한다.

## 5. 시각 기준

시각은 아래처럼 나뉜다.

- DB 저장 기준: UTC
- API 응답 기준: UTC ISO 8601
- `/health`의 `release_sha`는 n150에 배포한 Git full SHA를 나타내며, deploy script와 CI live
  E2E에서 candidate 일치를 확인한다.
- 브라우저 표시 기준: KST

웹 UI에서 보이는 대표 시각:

- `데이터 기준 시각`
  - 원본 데이터가 실제로 관측된 시각
row-level `collected_at`과 전체 시스템 기준 동기화 시각은 백엔드/API에 남아 있지만, 메인 UI에서는
직접 노출하지 않는다. 사용자에게 필요한 데이터 기준 시각만 표시한다.

관련 문서:
- [architecture/collection.md](</F:/dev/kor-travel-airport/docs/architecture/collection.md>)

## 6. 수동 수집 버튼

로컬 개발 profile에서 `ENABLE_MANUAL_COLLECT=true`이면 웹 UI의 `지금 수집` 버튼이
`POST /v1/admin/collect`를 호출한다. public n150 profile에서는 버튼과 endpoint가 모두
비활성화된다.

동작 규칙:

- 마지막 적재 후 제한 시간이 지나지 않았으면 실행하지 않는다.
- 프론트엔드는 먼저 상태를 확인해 사용자 메시지를 보여준다.
- 백엔드도 같은 규칙으로 다시 검증한다.
- 외부 API 한도 초과 상태이면 백엔드는 `429`로 막고 다음 재시도 가능 시각을 안내한다.
- 현재 한도 보호는 `UPSTREAM_RATE_LIMIT_BACKOFF_SECONDS` 기준의 짧은 backoff를 사용한다. 하루가 끝날 때까지 통으로 멈추지 않는다.

성공 시 예시:

- `즉시 수집을 완료했습니다. 신규 스냅샷 10건을 저장했습니다.`

실패 시 예시:

- `마지막 업데이트 후 10분이 지나지 않았습니다. 04.26 20:49 KST 이후 다시 시도해 주세요.`

## 7. 스케줄러와 중복 저장

자동 수집은 `ENABLE_SCHEDULER=true`일 때만 돈다.

중복 저장 기준:

- `parking_lot_id + observed_at + source`

따라서 다음 상황은 정상이다.

1. 수집 자체는 성공했다.
2. 원본 API의 `observed_at`이 이전 수집과 같다.
3. 중복 저장을 막아서 `snapshot_count=0`이 나온다.

이 경우 해석은 아래처럼 한다.

- `raw_response_count>=1`이면 하나 이상의 원본 소스 호출은 성공
- `status=success`이면 실행은 정상
- `snapshot_count=0`이면 중복 저장 방지 가능성 먼저 확인

## Historical: 2026-05 ODROID 관찰 기록

아래 수집기 rate-limit과 ODROID 항목은 13번에서 읽기 전용으로 확인했던 과거 운영 기록이다.
현재 Docker/PostgreSQL 운영은 192.168.1.14에서만 수행한다.

추가 규칙:

- `collector-status`에 `upstream_rate_limited=true`가 보이면 외부 API 쿼터 보호 상태다.
- `15056803` 공식 문서상 개발계정 트래픽은 `5,000/일`이지만, 실제 운영에서는 더 이르게 `LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR.`가 발생할 수 있다.
- 이때는 `UPSTREAM_RATE_LIMIT_BACKOFF_SECONDS` 동안만 수집기가 자동으로 API 호출을 건너뛴다.
- 같은 인증키를 쓰는 live 수집기는 동시에 하나만 유지한다.
- `2026-04-30` 기준 ODROID에는 별도 프로젝트 `airport-parking-monitor`의 `parking-collector.timer`가 10분마다 같은 키로 `GMP,PUS,CJU,TAE`를 호출하고 있었고, 현재는 중지했다.
- 현재 ODROID `parking-radar`는 `CJJ,CJU,GMP,HIN,ICN,KUV,KWJ,MWX,PUS,RSU,TAE,USN,WJU,YNY`를 10분마다 처리하도록 설정한다.
- 한국공항공사 소스가 한도 초과 상태여도 인천공항 전용 주차/요금 소스는 같은 수집 실행 안에서 계속 시도한다.
- `2026-05-01 06:13:53 KST` ODROID에서 자동 재시도했지만 원 API가 다시 `resultCode=99`를 반환했다.
- 같은 시각 ODROID에서 원 API를 직접 호출해도 동일한 99 응답이 반환되어, 최신 데이터가 `2026-04-28 17:18:02 KST`에 멈춘 직접 원인은 앱 내부 중단이 아니라 원 API의 키 제한 상태로 본다.
- `2026-05-01` 확인 기준 ODROID의 활성 중복 수집기는 발견되지 않았다. 운영 장애 조사 시 사용자가 명시하지 않은 다른 WSL2 프로젝트의 컨테이너/프로세스는 임의로 중지하거나 변경하지 않는다.
- 임시 운영 조치로 ODROID의 `UPSTREAM_RATE_LIMIT_BACKOFF_SECONDS`를 `409567`로 변경해 다음 원 API 재시도를 `2026-05-06 00:00:00 KST` 이후로 미뤘다.
- ODROID에는 `parking-radar-restore-backoff.timer`를 등록해 `2026-05-05 06:00:00 KST`에 backoff 값을 `3600`으로 되돌리고 backend 컨테이너를 재생성하도록 예약했다.

## 8. 프론트엔드 동작 기준

### 스코프 전환

- 공항 전체 선택:
  - 활성 주차장을 합산해서 보여준다.
- 세부 주차장 선택:
  - 선택한 주차장 하나 기준으로 모든 패널이 바뀐다.
- 마지막 선택 정보는 브라우저 localStorage에 저장되고 다음 접속 시 복원된다.
- 화면 데이터는 15초마다 자동으로 다시 읽는다. 자동 갱신은 원 API 수집을 강제로 실행하지 않고, 백엔드에 이미 저장된 현재/분석 데이터를 다시 조회한다.
- 브라우저 탭이 숨겨져 있으면 주기 갱신을 건너뛰고, 다시 보이거나 포커스를 얻으면 현재 선택 기준으로 조용히 갱신한다.
- 하루 흐름 오버레이 차트의 비행편 마커도 같은 대시보드 새로고침 흐름에서 다시 조회한다.
- 비행편 정보는 보조 데이터이므로 초기 대시보드 로딩을 막지 않는다. 주차 현황, 시계열, 분석 데이터가 먼저 표시되고 비행편 정보는 별도로 반영된다.
- 비행편 API 응답이 6초 이상 지연되면 주차 현황을 먼저 표시하고 비행편 패널에는 지연 안내 상태를 남긴다.
- 백엔드는 비행편 API 응답을 5분 동안 캐시해 차트 갱신 때문에 외부 API 호출이 과도하게 늘지 않도록 한다.
- 백엔드는 공휴일 API 응답을 월 단위로 조회하고 기본 1일 동안 캐시한다.

스코프가 함께 바뀌는 패널:

- 현재 잔여 주차면
- 현재 점유율
- 최근 7일 시계열
- 하루 흐름 오버레이 차트의 선택 공항 출도착 비행편 마커
- 지난주/이번주/다음주 공휴일 문장
- 시계열 공휴일/토요일/일요일 배경
- 요일 x 시간 평균 잔여 주차면 히트맵 요약
- 공휴일/토요일/일요일 날짜별 시간대 패턴
- 요일별 임계 달성 시간
- 날짜별 임계 달성 시간 히스토리
- 임계치 이벤트
- 시계열의 마지막 값은 화면 상단 `현재 잔여 주차면`과 같은 계산 기준으로 고정한다.
- 최근 7일 시계열 주차선은 실제 관측값까지만 그리고, 기본 X축을 미래로 확장하지 않는다.
- 비행편 마커는 별도 `하루 흐름과 비행편` 차트에서 0시부터 24시까지의 하루 축에 표시한다.
- `하루 흐름과 비행편` 차트는 최근 7일 선을 겹쳐 보여주고, 날짜별 선과 출발편/도착편 마커를 각각 켜고 끌 수 있다.
- 공휴일/토요일/일요일 날짜의 선은 점선과 사각 마커로 일반일과 구분한다.
- 같은 출도착 시각/출발지/도착지를 가진 비행편은 공동운항편으로 묶어 표시한다.
- 모바일 화면에서는 현재 주차 여유, 빠듯한 주차장, 최근 7일 흐름, 요일별 평균을 우선 보여준다.
- 모바일 화면에서는 비행편 흐름, 공휴일/토/일요일 패턴, 임계 달성 시간, 임계치 이벤트, 주차요금 계산기를 접힘 섹션으로 내려 스크롤 부담을 줄인다.
- 모바일 표와 차트는 가로 스크롤을 허용하고, 시간대 히트맵은 첫 열을 고정해 어느 요일/특수일의 값인지 잃지 않게 한다.

### API 주소 결정

- `NEXT_PUBLIC_API_BASE_URL`이 있으면 그 값을 쓴다.
- 없으면 브라우저는 같은 origin의 `/api/backend`를 호출한다.
- Next.js 서버가 `/api/backend/*` 요청을 Docker 내부 백엔드 주소인 `BACKEND_INTERNAL_URL`로 프록시한다.
- n150 기본값은 `BACKEND_INTERNAL_URL=http://backend:8000`이다.

이 규칙은 n150 외부 주소(`https://pr.digitie.mywire.org/`)를 같은 빌드로 처리하고, 외부
HTTPS 페이지에서 HTTP API 포트를 직접 호출하는 문제를 피하기 위한 것이다. 13번 주소는
cutover read-only source로만 남긴다.

### 공개 서비스 보안

- n150 외부 서비스 기준 주소는 `https://pr.digitie.mywire.org/`이다.
- 운영 백엔드는 `TRUSTED_HOSTS_CSV`로 허용 Host를 제한한다.
- n150 운영 CORS는 `http://192.168.1.14:14002`(web, T-032 이후), `https://pr.digitie.mywire.org`,
  `https://pr-api.digitie.mywire.org`를 기준으로 제한한다.
- 운영에서는 `ENABLE_API_DOCS=false`로 API 문서를 공개하지 않는다.
- 운영 n150에서는 `ENABLE_MANUAL_COLLECT=false`로 `POST /v1/admin/collect`를 비활성화한다.
  로컬 개발 profile에서만 명시적으로 활성화한다.
- 일반 조회와 자동 갱신은 서버에 저장된 `DATA_GO_KR_SERVICE_KEY`로 동작하며, 브라우저에 공공데이터 API 키를 요구하거나 노출하지 않는다.
- `GET /v1/admin/collector-status`는 화면 갱신과 운영 상태 확인을 위해 공개 조회로 둔다.

## 9. 배포 자산

현재 운영 배포 자산:

- [scripts/deploy-server14.sh](</F:/dev/kor-travel-airport/scripts/deploy-server14.sh>)
- [.env.server14.example](</F:/dev/kor-travel-airport/.env.server14.example>)
- [docker-compose.yml](</F:/dev/kor-travel-airport/docker-compose.yml>)
- `deploy/odroid/*`와 `scripts/deploy-odroid.ps1`는 historical fail-closed 자산이며 실행하지 않는다.

배포 대상:

- IP: `192.168.1.14`
- 사용자: `digitie`
- 앱 경로: `/home/digitie/apps/parking-radar`

비밀번호는 저장하지 않는 것이 원칙이다.

관련 문서:
- [runbooks/deployment.md](</F:/dev/kor-travel-airport/docs/runbooks/deployment.md>)
- [deploy/odroid/README.md](</F:/dev/kor-travel-airport/deploy/odroid/README.md>)

## 10. 테스트 기준

현재 기준으로 반드시 유지해야 하는 검증 축:

- WSL2 셸에서 1차 테스트
- WSL2 Docker에서 2차 테스트
- 백엔드 pytest
- 프론트 Vitest
- Docker 컨테이너 내부 실행
- 반응형 렌더링 확인
- 시계열 툴팁 확인
- 하루 흐름 오버레이 차트의 비행편 마커와 편명/출도착 정보 표시 확인
- 수동 수집 성공 / 쿨다운 제한 확인
- `collector-status` 기반 모드 확인

마지막 확인 기준:

- 백엔드: `67 passed` (SQLite/WSL 기준; CI에서는 PostgreSQL container와 `alembic check`도 통과)
- 프론트: `47 passed` 및 TypeScript/build 통과

관련 문서:
- [runbooks/testing.md](</F:/dev/kor-travel-airport/docs/runbooks/testing.md>)

## 11. 운영 중 자주 헷갈리는 점

- `client_mode=sample`이면 실데이터가 아니다.
- `scheduler_enabled=false`면 자동 수집은 안 돈다.
- `snapshot_count=0`은 실패가 아닐 수 있다.
- `collected_at`과 `데이터 기준 시각`은 서로 달라도 정상일 수 있다. `collected_at`은 API/운영 점검용이고 메인 UI에는 표시하지 않는다.
- 프론트 이미지를 다시 빌드했으면 컨테이너 재생성까지 해야 화면이 바뀐다.
- SQLite 런타임 파일을 OneDrive bind mount에 직접 두면 간헐 오류가 날 수 있다.

관련 문서:
- [runbooks/troubleshooting.md](</F:/dev/kor-travel-airport/docs/runbooks/troubleshooting.md>)

## 12. 다음 변경 시 같이 갱신해야 하는 문서

아래 중 하나가 바뀌면 이 문서도 같이 업데이트하는 것을 권장한다.

- 기본 수집원 결정
- live / sample 기본 실행 정책
- 세부 주차장 정규화 기준
- 시각 표시 규칙
- 수동 수집 제약
- 배포 스크립트와 배포 경로
- 검증 기준과 테스트 결과

## 13. WSL 테스트 기준

- 모든 테스트 기준 환경은 `WSL2`이다.
- Windows 로컬 테스트는 지양하고 참고 결과로만 취급한다.
- 1차 테스트는 `WSL2` 셸에서 로컬 런타임으로 실행한다.
- 2차 테스트는 `WSL2 + Docker`에서 실행한다.
- n150 배포는 1차/2차 테스트가 모두 통과한 뒤 진행한다.
- Windows PowerShell은 배포와 원격 상태 확인 보조 환경으로 취급한다.
## 14. Live Seed Policy

- n150 live 운영에서는 `client_mode=live`, `SEED_SAMPLE_DATA=false`를 기본값으로 사용한다.
- 샘플 시계열은 `client_mode=sample` 개발 모드에서만 시드한다.
- live 환경 DB에서 `collection_run_id is null` row는 샘플 스냅샷 가능성이 높으므로, 시계열이 이상하게 길어지면 먼저 이 조건을 확인한다.
- `15056803` 카탈로그에는 개발계정 `5,000` 트래픽이 보이지만, `2026-04-28` 실측에서는 100회 성공 후 101번째부터 `LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR.`가 발생했다.
- 중복 수집기를 제거한 현재 기준으로는 n150 live 프로파일이 5분 configured 주기와
  5분 수동 수집 제한 계약을 사용한다.
