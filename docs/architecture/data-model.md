# 데이터 모델

## 핵심 테이블

운영 DB는 PostgreSQL 16이며 모든 이벤트 시각은 timezone-aware UTC `TIMESTAMPTZ`로
저장한다. Alembic의 `0001_initial`이 기준 스키마이고, 테스트와 legacy import에서만
SQLite dialect를 허용한다.

### `airports`

- 공항 기본 정보
- 예: `GMP`, `CJU`, `PUS`, `ICN`

### `parking_lots`

- 공항별 주차장 정보
- 터미널, 카테고리, 원본 소스 식별자 포함
- 가능한 한 공항의 실제 사용자용 구획 이름을 그대로 유지한다.
- 예:
  - 김해국제공항: `P1 여객주차장`, `P2 여객주차장`, `P3 여객(화물)주차장`
  - 김포국제공항: `국내선 제1주차장`, `국내선 제2주차장`, `국제선 지하주차장`, `국제선 주차빌딩`

### `parking_snapshots`

- 주차 현황 스냅샷 저장
- 주요 필드:
  - `airport_id`
  - `parking_lot_id`
  - `observed_at`
  - `collected_at`
  - `occupied_spaces`
  - `total_spaces`
  - `available_spaces`
  - `congestion_label`
  - `congestion_ratio`

### `parking_fee_rules`

- 공항별/주차장별 요금 규칙
- 소형/대형, 평일/휴일 요금 계산에 사용

### `collection_runs`

- 수집 실행 단위 기록

### `raw_api_responses`

- 외부 API 원본 응답 기록
- 파싱 오류 추적과 운영 디버깅에 사용

## 통합 교통정보 테이블

통합 교통정보도 원본과 정규화 데이터를 분리한다. 모든 event time은 UTC
`TIMESTAMPTZ`이고, `raw_item_json`은 provider가 전달한 선택 필드를 보존하는 JSONB다.

### `highway_traffic_snapshots`

- `python-krex-api` `traffic.flow`의 고속도로 구간별 속도 스냅샷
- 노선/콘존/방향/현재속도/자유속도/혼잡도를 저장
- `(source, identity_key, observed_at)` unique로 반복 수집 중복을 방지

### `highway_incident_snapshots`

- `python-krex-api` `traffic.incident`의 돌발·사고·처리상태·위치·정체길이
- 제공기관 발생 시각을 `observed_at`으로 정규화하고 원본 날짜/시각도 보존
- 소통 스냅샷과 분리해 분석·장애 추적 시 역할을 섞지 않음

### `fuel_stations` / `fuel_price_snapshots`

- 최신 `python-opinet-api` Playwright collector의 지역, 주유소 식별자, 주소/좌표,
  브랜드, 셀프/24시간/품질인증/세차/정비/편의점/이벤트 플래그를 `fuel_stations`에 저장
- 유종별 가격과 provider 갱신 시각은 `fuel_price_snapshots`에 저장
- 가격은 금액 의미를 보존하기 위해 PostgreSQL `NUMERIC(10,2)`를 사용하고 음수를 막음
- 주유소 identity와 `(station, source, product_code, observed_at)` unique로 upsert/중복 방지

### `transport_collection_states`

- `krex_traffic_flow`, `krex_traffic_incident`, `opinet_browser`별 수집 시작/성공/다음
  예정/마지막 오류를 저장
- 브라우저 수집의 10~12시간 재실행 정책과 고속도로 scheduler 상태를 운영 API에서
  구분해 확인하는 기준 테이블

## 분석 데이터 처리 원칙

- 시계열 차트용 집계 결과는 현재 별도 테이블에 저장하지 않는다.
- 최근 7일 10분 시계열은 `parking_snapshots`에서 조회 시점에 계산한다.
- 같은 10분 구간 안에서 주차장별 최신 상태를 사용해 공항 합산 값을 만든다.

## Query indexes

Alembic migration이 PostgreSQL 인덱스를 생성한다. SQLite 테스트에서는 같은 모델을
사용하되 dialect 호환 인덱스 생성만 수행한다.

- `parking_snapshots (airport_id, parking_lot_id, observed_at)` supports airport-scoped history and analytics scans.
- `parking_snapshots (airport_id, parking_lot_id, observed_at DESC, id DESC)` supports latest snapshot ranking for `/v1/parking/current`.
- `parking_snapshots (collected_at)` supports collector status metadata.
- `parking_snapshots (collection_run_id)` and `raw_api_responses (collection_run_id)` support recent collector run summaries.

통합 교통정보 조회를 위해 다음 인덱스를 함께 둔다.

- `highway_traffic_snapshots (route_no, observed_at)` 및 `(conzone_id, observed_at)`
- `highway_incident_snapshots (route_no, observed_at)`
- `fuel_stations (sido_value, sigungu_value)` 및 `last_seen_at`
- `fuel_price_snapshots (fuel_station_id, observed_at)` 및 `(product_code, observed_at)`

## Migration and backup contract

- 기존 SQLite를 옮길 때는 `scripts/migrate_sqlite_to_postgres.py`를 n150에서 실행한다.
- exact dump를 얻지 못하면 `scripts/migrate_http_history.py`로 관측 시계열을 먼저
  가져오고, 원본 응답·collection run·fee rule 보존 한계를 `docs/journal.md`에 기록한다.
- 백업은 PostgreSQL custom format(`pg_dump -Fc`)이며 복원 전 자동 pre-restore backup을
  생성한다.
