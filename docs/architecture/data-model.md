# 데이터 모델

## 수집 실행 소유권 (`0024_collection_run_owner`)

`collection_runs.orchestrator_run_id`는 Dagster run UUID이며 nullable index를 갖는다.
`heartbeat_at`은 timezone-aware UTC `TIMESTAMPTZ`다. 기존 API DTO는 변경하지 않는다.
API·legacy 실행의 NULL 소유권은 자동 회수 대상에서 제외한다. migration을 code-server보다
먼저 적용한다. collector의 commit/flush는 status=running과 owner를 잠가 확인하며, terminal
실행의 늦은 게시를 거절한다. metadata 유실은 5시간 heartbeat grace와 CAS로 확인한다.
기존 원천 응답·성공 부분·provider receipt는 삭제하거나 재생성하지 않는다.

## 핵심 테이블

### 최신 유가 테이블 (`0022_fuel_latest_prices_table`)

`fuel_latest_prices`는 `(fuel_station_id, product_code)` PK의 일반 테이블이다. 원본
`fuel_price_snapshots`의 주유소·유종별 최신 `collected_at`, 동일 시각이면 최대 `id`
행(`snapshot_id`)과 가격·시각을 담는다. 유가 수집이 원본과 같은 트랜잭션에서 그 배치만
upsert하며, 더 오래된 배치는 기존 행을 덮지 못한다. `0018`~`0020`의 materialized view와
갱신 세대·체크포인트 열은 `0022`가 제거했다(배경은 `performance.md`).

항구 `ferry_ports`와 버스 `bus_terminal_references`의 관리자 좌표 보정은 새 장소를
만들지 않는다. 기존 행의 위도·경도와 `location_source=admin_manual`을 갱신하고
`raw_item_json._manual_location`에 마지막 근거·보정 시간·이전 좌표·수정 버전을 보존한다.
같은 코드·이름·지역의 기준정보 재적재 시 이 값의 우선순위가 높다. 이름·지역이 바뀌면
위치를 재검증하도록 해제한다. 전체 편집 이력은 별도 보관하지 않는다.

### 버스 시간표 저장본 (`0016_bus_timetable_snapshots`)

`bus_timetable_snapshots`는 TAGO의 정상 시간표 응답을 JSONB로 보관한다. 기본 키는
`(service_type, departure_terminal_id, arrival_terminal_id, service_date, bus_grade_id)`다.
등급 전체 조회는 NULL 대신 빈 문자열로 정규화해 PostgreSQL 중복 키 문제를 막는다.
응답 확인 시각은 `TIMESTAMPTZ`, 운행일은 한국 날짜 기준 `DATE`다. `service_date` 인덱스를 둔다.
동일 키의 오래된 응답이 늦게 도착해 최신 저장본을 덮어쓰지 못하도록 upsert 시각을 비교한다.

정상 빈 응답과 일부 결과의 `total/truncated`도 보존하지만 오류 응답은 저장하지 않는다.
관리자 날짜 선택은 10일 범위이며 시외버스 API는 오늘만 허용한다. 고속버스 API의 기존 날짜
계약은 유지한다. DB 저장본을 키 설정·제공자 호출 보호보다
먼저 읽는다. 유효시간이 지난 저장본은 `stale=true`와 원래 `fetched_at`을 유지하고,
`refresh_status`로 저장 전용·호출 보호·설정 누락·갱신 오류를 구분한다.
`stored_only=true`는 누락 시 404이며 어떤 경우에도 외부 API를 호출하지 않는다.
기존 in-memory 호출 보호가 영속화되거나 다중 프로세스에서 공유되는 것은 아니다.
이 migration은 기존 테이블을 변경하지 않는 추가 전용이다. 운영 되돌림은 아래 검증 기록의
스키마 호환 후보를 준비해야 하며, 이전 이미지로 단순 교체하거나 새 저장본을 삭제하지 않는다.

[PR #52 후속 검증·배포 조건](../runbooks/pr52-journey-fixes.md).

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

- 외부 API 응답의 수집 실행별 요약/오류 기록
- 파싱 오류 추적과 운영 디버깅에 사용

## 통합 교통정보 테이블

통합 교통정보도 원본과 정규화 데이터를 분리한다. 모든 event time은 UTC
`TIMESTAMPTZ`이고, `raw_item_json`은 provider가 전달한 선택 필드를 보존하는 JSONB다.

### `highway_traffic_snapshots`

- `python-krex-api` `traffic.flow_all`의 고속도로 VDS별 속도 스냅샷
- 노선/콘존/방향/현재속도/자유속도/혼잡도를 저장
- VDS ID가 있으면 `identity_key=vds:<ID>:<방향>`으로 같은 콘존의 여러 검지기를
  보존한다. 없는 provider 표본은 콘존 기반 identity를 사용한다. `S`/`E`는 남/동쪽이
  아니라 기점/종점 방향이다. 속도 결측은 0으로 바꾸지 않고 `NULL`로 보존한다.
- `(source, identity_key, observed_at)` unique로 반복 수집 중복을 방지

### `highway_incident_snapshots`

- `python-krex-api` `traffic.incident`의 돌발·사고·처리상태·위치·정체길이
- provider의 발생 날짜/시각은 `occurred_date`/`occurred_time`으로 보존하고,
  처리상태 변경을 시계열로 남길 수 있도록 현재 수집 시각을 `observed_at`으로 사용
- 상태가 같으면 이력을 추가하지 않고 `collected_at`만 마지막 재관측 시각으로 갱신한다.
  지도 TTL과 갱신 표시에는 `collected_at`을 사용해 장기 공사/통제가 사라지지 않게 한다.
- 소통 스냅샷과 분리해 분석·장애 추적 시 역할을 섞지 않음

### `fuel_stations` / `fuel_price_snapshots`

- 최신 `python-opinet-api` Playwright collector의 지역, 주유소 식별자, 주소/좌표,
  브랜드, 셀프/24시간/품질인증/세차/정비/편의점/이벤트 플래그를 `fuel_stations`에 저장
- 유종별 가격과 provider 갱신 시각은 `fuel_price_snapshots`에 저장
- 가격은 금액 의미를 보존하기 위해 PostgreSQL `NUMERIC(10,2)`를 사용하고 음수를 막음
- 주유소 identity와 `(station, source, product_code, observed_at)` unique로 upsert/중복 방지
- provider는 서로 다른 검색지역의 동일 UID를 전역 병합한 뒤 저장 계층에 전달한다.
  빈 가격이 유효 가격을 지우지 않으며 가격·갱신 시각은 같은 입력의 쌍으로 선택한다.
  `sido_*`/`sigungu_*`/`dong_*`와 API 지역 필터는 검색 문맥이며 실제 소재지 분류가 아니다.
  새 provider는 최초 검색 문맥을 유지한다. 이 수정 이전 run 13556 자료는 후행 문맥이
  남아 있을 수 있으며, 전체 입력이 없어 이전 덮어쓰기 유무·손실량의 확정 또는 복구를
  주장하지 않는다. 실제 위치는 주소·좌표를 사용한다.

### `transport_collection_states`

- `krex_traffic_flow`, `krex_traffic_incident`, `opinet_browser`별 수집 시작/성공/다음
  예정/마지막 오류를 저장
- 브라우저 수집의 기본 8시간(허용 8~12시간, 24시간 내 최대 3회) 재실행 정책과 고속도로 scheduler 상태를 운영 API에서
  구분해 확인하는 기준 테이블

### `rail_station_references`

- KRIC 공개 XLSX dataset 1294의 도시·광역철도 역사 기준정보
- `(source, identity_key)`로 운영기관·노선·역번호·역명을 조합한 자연키를 고정
- 좌표, 주소, 전화, 파일의 `data_reference_date`, 최초/최종 확인 시각과 원본 필드를 보존
- 공개 파일 원문 자체는 RustFS object로 보관하며 DB에는 정규화 행과 원본 필드만 둔다

### `ferry_ports` / `ferry_terminal_references` / `ferry_ship_type_references`

- 공공데이터포털 국내선박운항정보의 항구, 여객선 터미널, 선박종류 기준정보
- 원천 ID와 source의 조합으로 중복을 막고 최초/최종 확인 시각을 기록
- 항구 지도 위치는 KOMSA 기항지 코드/행정구역을 정확 대조한 결과 또는 VWorld에서
  이름이 정확히 일치하는 단일 페리/해운 시설만 연결한다. 후자는 승선 장소를 보장하지
  않으므로 출처를 구분한다. 항만가이드라인 항로 안내 점은 지도에서 제외한다. 원문은
  `raw_item_json._komsa_port_call`·`_vworld_place`, 호출 예약/결과/확인 시각은
  `raw_api_responses`에 둔다.
  기존 테이블 스키마는 유지하며 상세는 [좌표 운영 규칙](../runbooks/port-coordinates.md)을 따른다.

### `ferry_timetable_snapshots`

- 출발 항구, 운항일, source를 자연키로 하는 국내 여객선 운항시간표 응답 스냅샷
- 공개 API와 동일한 선박명·출발/도착 항구·계획 시각·운임 JSON 배열과 `collected_at`을 저장
- 오늘을 포함한 10일 범위만 유지한다. Dagster는 한 run에 최대 280건만 적재해 최초 누락
  범위를 재개 가능하게 채우고, 이후에는 새 미래 운항일과 당일만 갱신하므로 항구 화면 반복
  조회나 프로세스 재시작이 provider 재호출로 이어지지 않는다.

### `bus_terminal_references`

- TAGO 고속·시외버스의 터미널 기준정보를 서비스 유형과 터미널 ID의 조합으로 저장한다.
- `0017_bus_terminal_locations`는 nullable 위도·경도·위치 출처를 추가한다. 좌표쌍과
  국내 범위 제약 및 좌표 인덱스를 둔다. VWorld의 정확한 터미널명·시설 분류·시도
  단일 일치만 채택하고 원문 선택 결과를 `raw_item_json._vworld_place`에 보존한다.
- 도시·등급 목록은 수집 receipt의 수량으로만 남기고, 운행 시간표는 시간 민감 자료이므로
  별도 `bus_timetable_snapshots`에 저장한다.

## 분석 데이터 처리 원칙

- 시계열 차트용 집계 결과는 현재 별도 테이블에 저장하지 않는다.
- 최근 7일 10분 시계열은 `parking_snapshots`에서 조회 시점에 계산한다.
- 같은 10분 구간 안에서 주차장별 최신 상태를 사용해 공항 합산 값을 만든다.

## Query indexes

Alembic migration이 PostgreSQL 인덱스를 생성한다. SQLite 테스트에서는 같은 모델을
사용하되 dialect 호환 인덱스 생성만 수행한다.

- `parking_snapshots (airport_id, parking_lot_id, observed_at)`은 공항별 이력·분석 범위 조회에 쓴다.
- `parking_snapshots (airport_id, parking_lot_id, observed_at DESC, id DESC)`는 `/v1/parking/current`의 주차장별 최신 행 선택에 쓴다.
- `parking_snapshots (airport_id, observed_at) INCLUDE (parking_lot_id, id, collected_at, source, occupied_spaces, total_spaces, available_spaces)`는 30일 원본 이력의 순위·응답 열을 포함한다.
- `parking_snapshots (collected_at)`은 수집 신선도에 쓴다.
- `parking_snapshots (collection_run_id)`와 `raw_api_responses (collection_run_id)`는 최근 수집 실행 요약에 쓴다.

통합 교통정보 조회를 위해 다음 인덱스를 함께 둔다.

- `highway_traffic_snapshots (route_no, observed_at)` 및 `(conzone_id, observed_at)`
- `highway_incident_snapshots (route_no, observed_at)`
- `fuel_stations (sido_value, sigungu_value)` 및 `last_seen_at`
- `fuel_price_snapshots (fuel_station_id, observed_at)` 및 `(product_code, observed_at)`
- `ferry_timetable_snapshots (source, departure_port_id, service_date)` 및 `service_date`

## Migration and backup contract

- 기존 SQLite를 옮길 때는 `scripts/migrate_sqlite_to_postgres.py`를 n150에서 실행한다.
- exact dump를 얻지 못하면 `scripts/migrate_http_history.py`로 관측 시계열을 먼저
  가져오고, 원본 응답·collection run·fee rule 보존 한계를 `docs/journal.md`에 기록한다.
- 백업은 PostgreSQL custom format(`pg_dump -Fc`)이며 복원 전 자동 pre-restore backup을
  생성한다.
