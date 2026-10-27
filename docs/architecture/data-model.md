# 데이터 모델

## 주차 영구 통계 (`0036_parking_statistics_archive`, 선행 저장 단계)

`parking_statistics_buckets`는 `(airport_id, bucket_at)` PK의 UTC 10분 영구 통계다.
주차장별 표본 가중 충분통계·용량>0 전망 통계·첫/마지막 추이점·동시각 공항 합산 통계·
원관측 기준 임계 이벤트와 수량/hash 검산을 보존한다. 개별 관측 배열·원천 JSON은 복사하지 않는다.
TTL·자동 삭제가 없으며 데이터가 든 downgrade와 공항 삭제를 거절한다.
원본 48시간 정책의 선행 단계여서 기존 읽기는 아직 원본에 의존하고 삭제는 항상 차단된다.
[보존·해상도·전환 수용 조건](parking-retention.md)을 따른다.

## 주차 전국 통계·보류·현재 요약 (`0037_parking_archive_coverage`)

- `parking_global_statistics_buckets`: UTC10분 PK, 전국의 같은 관측시각 합계 count/sum/min/max와
  raw 수량/hash·공항별 검산 proof를 영구 보존한다. 공항별 min/max 합산으로 대체하지 않는다.
- `parking_archive_issues`: scope/bucket PK의 보류 reason·최초/마지막 발견시각·최대id다.
  관측 원문·배열 없이 sealed 재삽입/검산 실패를 드러내고 다음 실행의 성공 위장을 막는다.
- `parking_latest_states`: lot PK와 RESTRICT lot/airport 복합FK의 작은 현재 파생 상태다.
  기존 public current의 observed/id 선택과 원래 시각·혼잡도를 보존하고, 지연 관측의 수신 watermark는 분리한다.
  snapshot/raw FK나 payload는 없다. reader 전환은2B이며 현재 API는 아직 원본을 읽는다.

세 표의 데이터가 있으면 downgrade를 거절한다. 기존 수동 통계 job 외 자동 schedule과 원본 삭제는 없다.
[저장·검산·현재 요약 계약](parking-archive-coverage.md)을 따른다.

## 수집 실행 소유권 (`0024_collection_run_owner`)

`collection_runs.orchestrator_run_id`는 Dagster run UUID이며 nullable index를 갖는다.
`heartbeat_at`은 timezone-aware UTC `TIMESTAMPTZ`다. 기존 API DTO는 변경하지 않는다.
API·legacy 실행의 NULL 소유권은 자동 회수 대상에서 제외한다. migration을 code-server보다
먼저 적용한다. collector의 commit/flush는 status=running과 owner를 잠가 확인하며, terminal
실행의 늦은 게시를 거절한다. metadata 유실은 5시간 heartbeat grace와 CAS로 확인한다.
기존 원천 응답·성공 부분·provider receipt는 삭제하거나 재생성하지 않는다.

## 수집 완료 유가 통계 (`0028_fuel_statistics`)

원천별 발행 포인터 `fuel_statistics_states`, 최신 지도 가격 `fuel_statistics_points`,
KST 일별 범주/유종 집계 `fuel_statistics_daily`를 분리한다. 원본 이력은 보존하고
조회 시에는 읽지 않는다. 지도 가격은 bbox 인덱스를 사용하며 일별 집계는 오늘 포함
7일만 남긴다. 원천 잠금·savepoint로 원본 성공과 통계 발행 실패를 분리한다.
지표·원천·초기 기록 기준은 [유가 통계](../fuel-statistics.md)를 따른다.

## 핵심 테이블

### 지도 좌표·돌발 최신 조회 인덱스 (`0026_transport_map_indexes`)

`fuel_stations`와 `rail_station_references`는 유효한 좌표 쌍만 포함하는 부분 B-tree
인덱스 `(longitude, latitude)`를 둔다. bbox 지도 조회와 저배율 좌표 집계가 상세 행 전체를
읽는 일을 줄인다. PostgreSQL에서는 수집 쓰기를 오래 막지 않도록 `CREATE INDEX CONCURRENTLY`로
추가하고, SQLite 테스트에서는 일반 인덱스로 만든다. 나머지 교통 좌표 테이블은 기존 좌표
인덱스를 사용한다. `highway_incident_snapshots(collected_at)`는 최근 24시간 돌발 관측만
가져오는 지도 쿼리가 오래된 이력을 반복 스캔하지 않도록 한다. 동시 인덱스 생성이 중단돼도
유효한 기존 인덱스는 재사용하고 invalid 인덱스는 제거한 뒤 재시도한다.

### KRIC 역 코드·매핑 JSON (`0027_kric_station_mapping_json`)

`kric_station_mapping_registry`는 `id=1` 단일 행으로 KRIC 코드 파일 전체를 `catalog_json`에,
안전한 자동 연결을 `automatic_mappings_json`에, 관리자 보정을 `manual_mappings_json`에
보관한다. SHA-256 지문에는 코드 카탈로그와 현재 기준 역의 ID·identity·운영기관·노선·역번호·역명이
포함되어, 자료 수집 중 기준 역 목록이 바뀌면 오래 열린 화면의 저장을 거절한다. 자료·매핑 갱신 시각도
함께 제공한다. PostgreSQL에서는 기준 역 수집의 DB 반영과 관리자 매핑 저장이 동일한 트랜잭션 advisory lock을
사용해 동시에 진행되지 않도록 한다. JSON 카탈로그는
운영기관·노선·역 이름과 각 코드를 모두 포함하며, `kric_station_codes`는 API 요청 코드와
시간표 수집에 사용하는 관계형 형태를 유지한다. 0027은 현재 활성 역 코드를 JSON으로 backfill하고
이후 KRIC 자료 수집 때 카탈로그를 갱신한다. 고유 `rail_station_id` 제약은 한 기준 역을
여러 KRIC 코드가 중복 점유하지 못하게 한다. 수동 매핑은 관리 API에서 현재 코드와 기준 역을
확인한 뒤 같은 트랜잭션에서 적용한다. 기준정보 전체를 다시 수집하면 자동 연결은 재계산하고
유효한 수동 연결은 코드 기준으로 다시 적용한다.

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
- 최신 가격은 해당 원본 upsert의 RETURNING으로 받은 id와 값을 작은 묶음으로 반영한다.
  원본·최신 가격·소스 성공 상태를 같은 transaction에서 commit하며 전체 이력을 재검색하지 않는다.
  Provider 체크포인트는 재생 가능한 외부 조회 임시 상태이며 PostgreSQL 정본·API 원본을 대체하지 않는다.
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

## 주소·행정구역 값의 출처 — kor-travel-geo 미사용

본 서비스는 kor-travel-geo를 호출하지 않는다(이 절의 file:line은 2026-10-13 head `2b7b6bc` 기준이고,
경로는 `backend/app/` 기준이며 수집 서비스는 `backend/app/services/` 아래다).
`Settings`(`core/config.py:11-184`)에 geo URL·키 필드가 없고 geo 클라이언트도 없다. 좌표는
provider 원본(주유소는 Opinet `katec_x/y`·경위도 `services/transport_collection.py:1252-1255`, 휴게소·돌발은 provider
값 저장 `models.py:475-476`·`:238-239`, 공항은 `airports` 테이블에 좌표 없이 krairport 번들 좌표·소재지를 export
시점에 그대로 실음 `service_exports.py:255-259`)과 버스 터미널·항구 기준정보의 VWorld/Kakao 장소 검색·KOMSA 기항지
조회 보강(`services/place_targets.py:30-38`, `services/place_locations.py:151-154`,
`services/kakao_place_locations.py:207-212`, `services/rail_maritime_collection.py:537-575`; 옛 항만가이드라인
`data_go_kr_port_guideline` 좌표는 지도에서 제외하고 재적재 시 해제)으로만 채운다. 보강·보존·해제 규칙과 출처
표기(`location_source`, `raw_item_json._*`)는 [좌표 운영 규칙](../runbooks/port-coordinates.md)과 위 핵심 테이블
절(`admin_manual`)이 정본이다. 어느 경로도 kor-travel-geo를 거치지 않는다.

주소·소재지는 provider 문자열 그대로이고(`models.py:261,403-404,510,593,638`), geo에서 유도한 행정표준코드
(법정동·행정동·시군구)·PNU·지오코딩 시각·주소 데이터셋 버전 컬럼은 어느 테이블에도 없다(`models.py`;
`fuel_stations.sido_*/sigungu_*/dong_*`(`:266-271`)는 Opinet 검색 문맥이다 — 위 `fuel_stations` 절). 내부 export
응답 스키마(ADR-013, `schemas.py:748-900`의 `Export*`·`*ExportPage`·`AirportExportResponse` = `docs/openapi.json`의
`/v1/service/exports/*` 응답 컴포넌트)에도 행정코드·PNU 필드는 없다(공개 유가 API `FuelStationItem`/
`FuelStationResponse`의 `sido_value/sigungu_value/dong_value`는 위 Opinet 검색 문맥 값이다). 따라서 geo 주소
데이터셋 릴리스는 본 서비스의 저장 데이터·API 계약에 영향을 주지 않는다. Map의 transport place asset(주유소·휴게소·
공항)이 export 좌표를 reverse geocoder로 넘겨 만든 행정코드만 Map ADR-109·geo ADR-069(둘 다 2026-10-13 기준
**proposed, 미구현**)의 재지오코딩 대상이고(price·notice asset은 reverse를 넘기지 않는다 — 어느 asset이 넘기는지의
정본은 Map `dagster/assets.py`), 본 서비스 책임이 아니다 — 그 설계는 그 ADR이 정본이고 여기에 복제하지 않는다.

단, 하드코딩 시도 표 `_province()`(`services/place_locations.py:25-35`)와 KOMSA 대상 표
`PORT_CALL_TARGETS`(`services/rail_maritime_collection.py:51-71`)는 행정구역 개편(시도 명칭·통합) 때 사람이 갱신한다.
geo 릴리스는 이를 알려 주지 않는다.

## 분석 데이터 처리 원칙

- 현재 조회는 원본을 사용한다. `0036`의 영구 10분 통계는 선행 저장이며 아직 조회 전환을 하지 않았다.
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

## 좌표 기반 파생 주소

`0025_reverse_addresses`에서 `reverse_address_entries`와 `reverse_address_control`을 추가한다.
`provider_id`·`target_key` 복합 식별자로 현재 좌표의 주소·행정구역·확인일·다음 갱신일과 오류/backoff를 분리 보관하고,
제어 행은 수동 cycle·커서·만료 lease를 보관한다. 원천 주소·좌표·관리자 설정과 과거 관측은 변경하지 않는다.
달력 6개월 갱신, VWorld 우선·Kakao fallback, 수동 실행과 복구 계약은 [구현 가이드](../reverse-address-refresh.md)를 따른다.


## Map T2 교통 current 후보 (0030, 기본 OFF)

`highway_traffic_current_states`는 `(source,scope_key)`별 정상 완결 generation·DB run 순서·확인 시각·member_count를 보존한다. `scope_key`는 route/conzone 설정 fingerprint이며 다른 필터 집합을 섞지 않는다. `highway_traffic_current`는 같은 source/scope/identity의 typed 최신 값과 generation membership을 보존한다. 데이터 winner는 `(observed_at,collected_at,snapshot_order)`다. 같은 관측의 정상 재수집 INSERT0도 확인 generation을 전진시킨다.

현재 표는 raw JSON을 복사하지 않는다. 가변 history가 나중에 정정되더라도 승인 current 값이 바뀌지 않도록 작은 DTO 열을 별도로 보존한다. `snapshot_id`는 nullable FK/SET NULL lineage이고, 원래 PK 순서인 `snapshot_order`는 유지한다. 원본 이력을 정리해도 typed current/membership/성공 개수는 사라지지 않는다. current와 이전 membership의 GC·frozen snapshot 보존은 후속이며 기존 이력 보존 정책을 변경하지 않는다.

수집 raw·성공 상태·history·current·통계는 같은 source transaction에서 확정하고 기존 owned worker fence를 유지한다. 늦은 옛 run의 membership 전진은 DB run ID로 거부한다. 정상0/급감은 T5의 provider 완결 guard를 통과한 경우에만 입력한다. rollback은 head/point도 함께 되돌리고 초도 backfill은 새 정상 수집에서만 만든다. `TRANSPORT_MAP_CURRENT_ENABLED=false`가 기본이며 비용/완결/복구 수용 뒤 명시 opt-in한다. 이 모델은 아직 REST·frozen HTTP 페이지·주차/T3 구현을 뜻하지 않는다.


## Map service export 고정 snapshot (migration0031)

`service_export_snapshots`는 UUID handle·kind/scope/source generation·실제 원천확인시각·
15분TTL·건수·DTO SHA256을 보존한다. `service_export_snapshot_items`의 복합PK는
(snapshot_id,ordinal)이고 payload에는 raw 없이 작은 typed DTO만 저장한다. 부모삭제는
CASCADE이다. 최초 freeze만 typed current를 읽고 이후 페이지는 이 복합PK index를 쓴다.
원천/이력/통계 정본으로 쓰거나 기존 보존정책과 연동하지 않는다.


## 기준정보 성공 membership (migration0032)

`reference_export_states(kind,scope_key)`는 source별 성공 generation·native run 순서·
실제확인시각·작은 member PK 목록과 완결 proof, 최근 실패를 저장한다. 원천 row/upsert와
같은 transaction으로 확정한다. 실패 뒤 성공 집합·확인시각은 유지한다. 초도 backfill 없이
새 완결 수집부터 생성하고 API는 이 목록의 명시된 PK만 읽는다.


## 배편 원천별 정상 저장본 (migration0035)

`ferry_reference_snapshots`는 dataset PK(4개 원천 CHECK), nullable JSONB 정상 응답,
TIMESTAMPTZ 최근 시도, nullable 실패 종류를 보존한다. 원천별 bounded 응답을 원자 교체하며
항구·운항시간표 natural key에 합치지 않는다. 실패와 취소는 이전 성공 응답을 지우지 않는다.
상세는 [VadaHub 통합 계약](../reports/2026-10-24-vadahub-ferry.md)을 따른다.

## 일반철도 조회 캐시 (migration0034)

`general_rail_query_snapshots`는 `(operation,request_key)` PK와 fetched_at index, JSONB 정상 응답을 보존한다.
operation은 catalog/stations/timetable/station_guide CHECK로 제한한다. TAGO와 코레일 공개 안내의
source 식별자를 섞지 않으며 실패·인증키·원문 오류는 저장하지 않는다. 32일 경과 캐시만 정리하고
수집 원천/이력과 분리한다. 주차 패턴 집계는 기존 airport_id/observed_at cover index를 이용해
선택 요일·시간대만 읽는다. 상세 TTL·표본 기준은 [검증 원장](../reports/2026-10-24-transport-user-journeys.md)을 따른다.
