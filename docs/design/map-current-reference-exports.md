# Transport T2/T3 구현 선행 조사와 작은 PR 순서

- 조사 정본: `/mnt/f/dev/kor-travel-transport-map-exports`, HEAD `d697dd7832bf382bf1059f10634a689f13ea11ec`.
- 문서 성격: 최초 조사 당시의 설계 근거를 보존한다. 현재 구현·머지·검증 상태는 아래 갱신 절과 [Map 인계](../map-service-exports-handoff.md), [수용 정산](../reports/2026-10-23-map-t2-t3-acceptance.md)을 따른다. 과거형 코드 조사는 현재 미구현 목록이 아니다.
- 최초 계약 기준: Weather `docs/design/map-service-exports.md`의 공통 성공 snapshot/상태/§T1~T3. 현재 Transport의 확정 응답은 각 route 문서와 OpenAPI를 따른다. T1/T4/T5는 PR108~110에서 별도로 머지·배포됐다.
- 8,300 traffic·44 parking은 부모가 제공한 규모이며 이번에 DB에서 새로 계수한 실측값이 아니다. 아래 비용은 코드 구조의 분석이고 CPU/메모리 감소 실측이 아니다.

## 2026-10-23 구현 상태 갱신

- PR112의 traffic pointer 뒤 PR114가 고정 DTO snapshot과 traffic REST를 구현했다. PR115 버스, PR116 항구, PR117 철도, PR118 주차 현재 상태가 같은 bounded snapshot 엔진을 사용한다. schema 정본은 0033이며, 0030은 traffic 선행 단계다.
- PG snapshot 본문/항목 표, 15분 TTL, 서명 cursor, 페이지 최대 5,000개, ETag/gzip, DB pool 반환 후 직렬화를 적용했다. source·scope 성공 membership/세대와 현재 원천 clock 일치를 확인한다. head 없는 집합은503이며 검증된 traffic 정상0건만 빈 성공 집합을 허용한다.
- provider 완결 receipt와 엄격한 주차 숫자·시각은 SDK PR10/11 public API를 소비한다. PR119는 KAC quota의 실제 실패 deadline을 유지하고, ICN 병행 blocked 관찰로 대기를 연장하지 않도록 분리했다.
- 위 제품 구현과 운영 활성화는 별개다. 현재 새 T2/T3는 운영 미배포/defaultOFF이고, 실제 source bootstrap·Map 새 reader·운영 API/UI 수용 및 ARM CPU/RAM·PG WAL 비교는 남았다. 아래 6절의 비용 항목을 충족했다고 보고하지 않는다.

## 최초 설계 결론

1. T2는 history 전체 DISTINCT를 API에 추가하지 않는다. source 저장 transaction 안에서 traffic/parking의 작은 latest pointer를 갱신하고, API는 pointer→snapshot PK join만 읽는다.
2. pointer만으로 HTTP 페이지 snapshot이 생기지는 않는다. traffic history의 같은 PK 값은 재관측 때 UPDATE되며 참조·수동좌표도 가변이다. HTTP 요청 사이 고정 PG transaction이나 pointer PK 목록만 유지해서 완결 snapshot이라고 표시하면 안 된다.
3. Transport의 작은 current/reference 집합은 Weather 1.8M fact와 같은 COW 구조를 먼저 도입할 필요가 없다. 검증된 current/reference에서 필요한 DTO 열만 고정한 짧은 수명의 export snapshot을 별도 작은 단계로 구현한다. 재생성 비용/저장량을 실측한 뒤 채택하며 이를 현재 구현된 기능으로 보고하지 않는다.
4. source 성공과 전체 job 성공을 구분한다. 교통/돌발, KAC/ICN 주차/요금, 철도 위치파일/KRIC 코드/시간표, 해운 항구 목록/좌표 보충은 서로 다른 성공 범위다. 실패한 source는 마지막 성공 head를 유지한다.
5. T3는 원래 코드/기관/노선/수동매핑 정본을 그대로 export한다. endpoint에서 재지오코딩, 새 역명 보정, KRIC/provider 요청을 하지 않는다.

## 1. 실제 코드의 transaction 경계

### 교통

- `services/transport_collection.py:_collect_unlocked`: source별 due/claim을 commit한 뒤 provider를 호출한다. T5 `_confirm_highway_payload`가 빈/25% 미만·parse 오류를 제한 재확인한다.
- `_collect_highway_source`의 raw/성공 상태, `_store_traffic`, 최근 2시간 5분 통계가 한 source transaction으로 commit된다. incident 실패는 먼저 commit한 traffic을 되돌리지 않는다. 같은 모델을 T2에도 유지한다.
- `_store_traffic`는 `(source, identity_key, observed_at)`로 단건 SELECT하고, 같은 시각이면 기존 행의 값·collected_at·collection_run_id를 UPDATE한다. 새 행은 추가한다. `stored`는 새 INSERT 수이므로 replay 0건도 성공한 전체 관측일 수 있다.
- 기존 traffic 저장은 8,300 입력에 SELECT+write가 행별로 발생하는 구조다. 새 pointer를 행마다 SELECT/flush하면 이 비용을 더한다. pointer만 200~500개씩 묶어 upsert하고 추가 commit은 하지 않는다. history bulk 개편은 별도 후속 PR로 분리한다.
- T5 scope는 route/conzone 설정 fingerprint다. 전체/필터 scope를 같은 denominator나 head로 섞지 않는다. guard 실패/timeout/quota/store rollback에서는 pointer/head/membership을 전진시키지 않는다.

### 주차

- `services/collection.py:_collect_unlocked`: KAC 주차, 선택된 ICN 주차, 요금들이 하나의 저장 transaction을 공유한다. owned Dagster 경로는 run identity를 먼저 commit하며 최종 저장·run 상태는 마지막 commit이다.
- `_safe_fetch`는 raw를 먼저 기록하고 envelope 검증 실패는 source 오류로 남긴다. 일부 provider 실패/요금 실패는 최종 `partial_success`일 수 있으나 성공한 주차 자료는 commit된다. 파싱/저장 예외는 전체 미확정 transaction rollback이다.
- `_store_observations`: 같은 `(lot,observed_at,source)`는 재삽입하지 않으며, unique 경합은 savepoint에서 소비한다. pointer hook은 INSERT 성공에만 붙이면 안 된다. replay와 IntegrityError 후 실제 기존 행도 선택 후보에 포함해야 한다.
- 현재 주차 raw는 provider가 추출한 list일 수 있고 `validate_source_response_body`는 list를 그대로 통과시킨다. 총건수/완결 evidence가 수집 계층에서 소실될 수 있다. 새 source-success/head를 raw200만으로 만들지 않는다. 빈/급감 보호가 필요하면 provider public API의 완결 metadata를 보존하는 작은 provider 선행 수정이 필요하다.
- parking에는 source별 `TransportCollectionState`가 없다. 요금이 성공했다거나 전체 run이 success라는 이유로 주차 44곳을 모두 신선하다고 하면 안 된다. KAC/ICN 및 설정된 공항 scope별 성공 evidence를 별도 기록해야 한다.
- 기존 `main.py:parking_current`는 lot별 indexed correlated LIMIT1이다. 전국 history DISTINCT가 아니다. 기존 `ix_parking_snapshots_airport_lot_observed_desc`가 `(airport_id,lot_id,observed_at DESC,id DESC)`를 제공한다. 비교 기준으로 재사용할 수 있으나 source 성공·확인 clock·활성 lot·동률 collected_at 계약은 새 Map 경로에서 명시해야 한다.

### 철도 위치파일과 KRIC 코드

- `rail_maritime_collection.py:collect_rail_reference`: 파일 fetch 후 `lock_rail_station_reference_catalog`를 획득하고 reference rows+summary raw+run success를 `_finish_run` commit으로 확정한다. 실패/cancel은 미확정 reference rollback이다.
- 현재 위치파일 수집은 빈/급감 파일을 성공으로 저장하지 않는 완결 guard가 충분하지 않다. T3 head 도입 전에 파일 provider의 파일 검증·이전 성공 count/scope 확인이 필요하다. KRIC 코드의 `_sync_codes` guard와 별개다.
- `kric_collection.py:collect`는 `_sync_codes`+calendar+code receipt를 먼저 commit하고 이후 시간표를 역/요일별로 commit한다. 뒤 시간표가 실패해 전체 run이 failed여도 코드 catalog commit은 정상이다. 코드 목록 export를 전체 run.success에 종속시키지 않는다.
- `_sync_codes`는 nonempty/identity/중복/이름을 검증하고, 기존 코드를 active=False로 만든 뒤 이번 코드를 active로 재확정한다. catalog JSON/hash·automatic mapping을 같은 transaction에 저장하며 manual mapping은 보존한다.
- `main.py:load_kric_station_mapping`, `rail_station_mapping.py:provider_key/source_key/effective_station_mappings/mapping_revision`를 정본으로 재사용한다. 관리자 저장은 기존 active code의 rail_station_id를 먼저 비우고 effective mapping으로 재배치한 뒤 registry JSON/revision과 같은 transaction에 commit한다(main.py의 실제 저장 루프 확인). export는 이 동시성 경계를 보존하고 FK와 registry를 동일 snapshot에서 읽어야 한다.

### 버스

- `bus_collection.py:_collect_unlocked`: run을 먼저 commit한 뒤 고속/시외 terminals+summary raw+success를 한 transaction에서 commit한다. 실패/cancel은 두 종류의 미확정 자료를 rollback한다.
- 두 service_type을 서로 다른 source scope로 추적하고, 어느 범위를 성공/완결로 볼지 먼저 고정한다. provider iterator의 page limit이 완결/정상0을 증명하는지 확인해야 하며 현재 nonempty/급감 guard는 없다.
- `_upsert_terminal`은 이름/도시가 같으면 admin_manual 또는 검증된 장소 좌표를 보존하고, 이름/도시가 바뀌면 좌표를 비운다. T3에서 이 정책을 덮지 않는다.

### 해운

- `_collect_maritime_data`는 ports/terminals/ship-types를 먼저 fetch하고 KOMSA 좌표 보충을 수행한 다음 reference upsert를 한다. `_port_call_location`의 여러 commit은 이 reference upsert보다 앞선 예약/좌표 lookup receipt이다. 이 보조 raw 성공을 항구 목록 성공으로 잘못 쓰지 않는다.
- 최종 reference rows+summary raw+run terminal이 같이 commit된다. KOMSA 좌표 실패/유예가 있으면 `partial_success`라도 항구 목록 자체는 정상 저장될 수 있다. 항구 목록의 완결성과 좌표 coverage를 분리한다.
- `_upsert_port`: 같은 이름의 admin_manual 우선, KOMSA 검증 좌표 또는 VWorld/Kakao 장소 좌표 보존, 이름 변경 시 무효화, 정상 KOMSA 무결과와 보충 오류를 구분한다. 항만가이드라인의 한 점을 승선 항구로 사용하지 않는다.

### 소유권

- `dagster/recovery.py:owned_session_factory/_fence`: run/status/orchestrator identity와 lease를 before_flush/before_commit에서 검증한다. bulk SQL도 마지막 commit fence를 통과한다.
- 새 pointer/head hook은 반드시 같은 owned session/transaction을 쓴다. 별도 engine·자체 commit으로 write하면 late worker 차단을 우회한다. filesystem/JSON 압축 중 DB transaction을 보유하지 않는다.

## 2. T2 latest pointer의 최소 구조

새 migration과 모델을 한 PR로 맞춘다. 기존 history/통계/unique/upsert 계약과 반환 INSERT 수는 바꾸지 않는다.

- traffic pointer: `(source, scope_key, identity_key)` PK, `snapshot_id` FK, 비교용 observed_at/collected_at, 마지막 정상 확인 generation/clock. source scope head는 마지막 완결 generation과 마지막 attempt 결과를 분리한다.
- parking pointer: `(source, parking_lot_id)` PK, `snapshot_id` FK, 비교용 observed_at/collected_at, source scope 성공 generation/clock. lot와 airport 소속은 기존 composite FK의 의미를 유지한다.
- 비교는 `(observed_at,collected_at,stable snapshot PK)` 내림차순이다. 같은 PK의 재관측 갱신은 rowcount=0이라도 확인 clock/membership을 갱신한다. 관측 시각이 더 오래된 fetch가 최신 pointer를 되돌리지 못하게 한다.
- 이번 정상 완결 scope에서 사라진 identity는 history/pointer를 즉시 삭제하지 않는다. current export membership을 마지막 완결 generation으로 제한하여 퇴역을 나타낸다. 확인 안 된 0건/급감은 membership/head를 바꾸지 않는다. scope 변경 때 옛 filter의 membership을 새 전체 집합에 합치지 않는다.
- bootstrap은 새 정상 수집에서 받은 키만 bounded PK/unique lookup으로 만든다. 과거 전체 history를 migration에서 rank하지 않는다. 수집 전 초도 pointer/head가 없으면503 not_ready다. 긴 수집 대기가 불가피한 경우에만 소유 CLI의 제한된 identity backfill과 별도 성공 근거 검증을 추가한다.
- replay 결과의 snapshot PK는 history insert/충돌 해결 후 한 번에 읽는다. traffic은 이번 유일 identity/observed pair만 batch query하고 parking은44개 후보이므로 bounded lookup이다. source savepoint/transaction 밖으로 ORM 객체를 넘기지 않는다.
- source 성공 evidence는 parsed/stored 단계를 통과한 scope에만 남긴다. 교통 state의 last_success_at은 `_store_traffic` 이전에 찍힐 수 있으므로 pointer의 실제 확인 clock과 source evidence의 생성 시각을 구분한다.
- 기존 public parking API나 traffic 통계가 새 pointer를 사용하게 바꾸는 것은 Map export 수용 후의 별도 PR이다.

## 3. T3 DTO와 identity

모든 경로는 기존 service token+실제 peer CIDR를 상속한다. 새 browser proxy/provider endpoint는 만들지 않는다.

| 경로 | 정본/안정 키 | 추가 증거 |
|---|---|---|
| `/rail-stations` | KRIC 위치파일 `(source,identity_key)` 그대로. 기관/노선/역번/역명을 임의로 합치지 않음 | nullable operator_code/line_code/station_code, mapping kind/revision, active code 여부. 모든 코드 문자열의 선행0 보존 |
| `/bus-terminals` | `(source,service_type,terminal_id)` | express/intercity 동일 terminal_id 충돌 방지, name/city/coords/location_source, manual_location_revision |
| `/ferry-ports` | `(source,port_id)` | name/coords/location_source/point_count/manual_location_revision. 가이드라인 좌표는 null |

- null 좌표가 있는 reference도 identity·이름·코드와 함께 export한다. unknown을0,0이나 공항/항구 중심으로 임의 대체하지 않는다.
- T1 `export_admin_addresses(session,kind,page)`를 rail_station/bus_terminal/ferry_port kind로 재사용한다. 현재 정확한 좌표의 Common hash, vworld-kakao profile, status ok/error, payload provider, resolved_at 증거가 같을 때만 붙인다. not_found나 좌표 변경은admin=null이다.
- fallback으로 주소만 별도 reverse 요청하지 않는다. 같은 좌표 error 상태의 마지막 성공 주소는 실제 resolved_at을 보존한다.
- rail mapping은 HTTP admin route 내부 함수를 호출하지 말고 순수 read service로 추출해 관리자와 export가 공유한다. automatic 재계산은 catalog/mapping revision이 바뀔 때만 source/admin writer 쪽에서 하고 HTTP 요청마다 전체 역을 name-match하지 않는다.
- 현재 저장된 active code FK와 registry revision을 동일 snapshot에서 읽어 관리자 저장과 코드 수집이 확정한 mapping을 export한다. reference 파일 교체·코드 catalog 갱신 사이의 미연결 상태를 임의 name-match로 보정하지 않는다. 기존 pure effective 함수는 source/admin writer의 정본으로 유지하고, export read service에서는 persisted 결과와 revision을 읽는다. FK와 다른 규칙을 API에서 새로 계산하지 않는다.
- mapping revision만으로 좌표가 동결되지는 않는다. `reference_catalog_digest`에는 좌표가 없다. 별도의 reference/coordinate/address generation 또는 DTO content hash가 필요하다.

## 4. 성공 head·snapshot·status·cursor

- T2/T3 새 endpoint는 공통 snapshot 계약을 먼저 가진 뒤 공개한다. 이미 있는 legacy export의503 의미는 바꾸지 않는다. 같은 기존 path를 확장할 때는 `snapshot=true` opt-in으로 새 envelope/status를 분리한다.
- source scope별 `last_success`와 `last_attempt`를 따로 보존한다. 초도 미확정은503. 마지막 성공 뒤 실패/불확실 empty는 이전 세대+stale metadata, 새 정상 generation 승격 금지. 이번 실제 정상 재관측·완결 증거 없이 success clock을 갱신하지 않는다. 동일값 replay0이어도 실제 재관측 시각은 전진한다.
- rail 위치파일, KRIC code catalog, mapping, 버스 service_type, 항구 목록과 좌표 coverage의 범위를 metadata에 드러낸다. 시간표/요금/부차 좌표 실패로 core 목록 전체를 지우지 않는다. worst-status와 coverage는 canonical 설계대로 고정한다.
- parking 좌표는 lot 실측 좌표가 없으므로 검증된 krairport airport metadata를 로컬로 재사용하되 `coordinate_source=airport_metadata`, `coordinate_precision=airport_anchor`를 명시한다. request에서 네트워크 provider 호출을 하지 않는다. anchor가 없으면null이다.
- 권장 최소 HTTP snapshot: 검증된 current/reference read model만 짧은 REPEATABLE READ로 읽고, raw 제외한 bounded DTO 값+좌표/admin/mapping revision을 불변 snapshot item/chunk로 고정한다. mutable history PK만 보관하는 manifest는 불충분하다. API의 자체 동일 REPEATABLE READ session 안에서 성공 head와 current/reference를 함께 검증한다. 다른 요청/프로세스의 writer session을 공유하지 않는다.
- 예시 저장은 `service_export_snapshots`와 `service_export_snapshot_items(snapshot_id,ordinal,kind,key,payload,digest)`이며 UUID random handle·filter digest·schema/limit/byte-cap revision·as_of/TTL을 갖는다. 이는 제안이고 Weather migration0023이나 T4 cursor를 그대로 재사용한다는 뜻은 아니다.
- 첫 snapshot 생성은 current8,300/44 또는 제한 reference 집합만 읽는다. HTTP endpoint에서 history 전체 scan/provider 호출을 하지 않는다. 500~1000개 streaming fetch와 고정 point/byte cap으로 source 크기 상한을 둔다. 일반 페이지는 `(snapshot_id,ordinal)` index에서 limit+1만 읽는다.
- 만료/잘못된 handle/filter/limit 정책은 canonical 계약의410/422로 고정하고, GC는 TTL+active-reader lease 상한 뒤에만 bounded 삭제한다. 긴 exported PG snapshot을 유지하지 않는다.
- ETag는 데이터뿐 아니라 health/status revision·representation/cursor epoch를 포함한다. T4에서 확인한 stale/TTL cursor를304로 고정하는 문제를 재발시키지 않는다. DB 반환 후 JSON/gzip(level1) 처리한다.
- 수동 좌표/주소/매핑 수정도 다음 export snapshot revision에 반영돼야 한다. source 수집 last_seen_at만 ETag/revision으로 쓰면 이 변경이 누락된다. freeze 시 DTO digest로 검증하거나 해당 writer에 bounded generation hook을 추가한다.

## 5. 작은 PR 순서와 파일 책임

1. **source 성공 범위·빈 응답 보호 준비(순차 체크리스트)**: 네 collector를 한 PR로 묶지 않는다. T5를 끝낸 traffic은 바로2단계로 갈 수 있고, parking/각 T3의 구현 직전 해당 source 하나의 완결 evidence·실패 보존을 작은 선행 PR로 확정한다. `collection.py`, `bus_collection.py`, `rail_maritime_collection.py`, `kric_collection.py`의 source 성공 boundary와 test만. provider metadata가 부족하면 provider 저장소의 작은 선행 PR. T5 KREX guard는 유지·재사용하고 전체 run.status를 임의 재정의하지 않는다.
2. **traffic pointer 모델+hook(지금 가능한 첫 제품 PR)**: migration/`models.py`/전용 `current_read_models.py`/`transport_collection.py`/회귀. 다른 history bulk·통계 최적화는 섞지 않는다. endpoint는 아직 비공개다.
3. **parking pointer+scope evidence hook**: 별도 작은 migration 또는2의 고정 스키마가 공통이면 모델만 재사용. `collection.py:_store_observations/_collect_unlocked`, 소유권/replay/savepoint 테스트. 기존 public parking 읽기는 바꾸지 않는다.
4. **Transport snapshot 공통 기반**: 별도 `service_export_snapshots.py`, DTO/OpenAPI/TS, TTL/GC·상태/ETag/gzip·입력/권한 회귀. API에서 read-model만 접근하도록 query 수/테이블을 단언한다. 실제 current 집합 materialize의 CPU/WAL/메모리 비용 gate를 통과시키고서 다음에 활성화한다.
5. **T2 두 current route 공개**: service router의 작은 모듈로 traffic/parking을 추가하고 동일 snapshot+status 정책을 연결한다. 최초/오류/정상0/역전/8300/44 PG plan 및 실제Map UI 게이트. provider/statistics/raw 조회0을 계측한다.
6. **T3 bus/ferry export(서로 별도 PR)**: source proof가 확보된 두 reference와 T1 admin helper, 좌표 provenance/수동 revision만 추가한다. PK/keyset으로 page를 읽고 snapshot을 고정한다.
7. **T3 rail export**: mapping read service 추출+코드/identity/revision DTO+좌표/admin 연결. 코드 먼저 commit 후 시간표 실패, 수동 mapping 우선과 중복 역명/선행0을 집중 검증한다. source code sync/관리 UI 동작은 보존한다.

각 PR은 draft→기능 CI→독립2리뷰→실제 API/UI→머지, 배포는 Manager 정본의 기존 소유권/drain 절차를 따른다. 여기서는 배포·daemon 상태를 변경하지 않았다. T4 PR110 merge 후 DTO/유틸 중복 여부를 다시 보고 실제 중복만 작게 공유한다.

## 6. 읽기 계획·비용 수용 게이트

- traffic: pointer에서 source/scope/확인 generation 및 안정 key range로 index scan→snapshot PK nested-loop lookup. history 전체 WindowAgg/Sort/Distinct나 raw JSON de-TOAST가 없어야 한다.
- parking: pointer44행→lot/airport FK→snapshot PK. 기존 indexed per-lot LIMIT1을 같은 input에서 비교한다. source별 stale와 단일공항 filter도 검사한다.
- references: source/current membership/key PK page scan, page당 admin query1회, KRIC code/projection bounded join. mapping catalog 전체 O(N) 계산을 모든 page마다 반복하지 않는다.
- snapshot page: `(snapshot_id,ordinal)` index와 TTL/health 한정 조회. 첫 freeze의 전체 current만 허용하며 active snapshot 재사용/캐시가 DB 수정이나 validator를 감추지 않아야 한다.
- 각 source 저장의 추가 SQL 수·upsert roundtrip·CPU usage_usec·cgroup current/peak·PG CPU/WAL·API p50/p95를 같은 원천 입력으로 최소3쌍 비교한다. 기존 traffic 단건 hotpath의 비용과 pointer 추가비용을 구분한다. 단순 프로세스 RSS 합으로 메모리 개선을 주장하지 않는다.
- pointer write만200~500 batch, identity dedupe set은 해당 bounded 응답 수준, 반환 row는 필요한 PK/clock만 읽는다. current freeze는 row/byte cap을 초과하면 부분 정상 snapshot이 아니라 명시 실패/not_ready다.
- migration에 무조건 전국 history backfill을 넣지 않는다. 신규 테이블/좁은 PK index를 만들고 새 정상 수집 후 bootstrap한다. 실제 FK/unique/index/alembic check·downgrade/upgrade·create_all 정합을 별도 전용DB에서 검사한다.

## 7. 필요한 회귀

- T2: 새 정상/동일관측 replay0/같은시각 정정/오래된관측/collected_at 및 PK tie/두 source 동시 성공·실패/claim 만료·late writer/rollback 직전 실패/통계 실패/duplicate input/parking unique 경합과 lot legacy ID.
- 버스 후기 실패: express upsert가 DB transaction을 시작한 뒤 intercity가 실패/취소할 때 기존 reference/pointer/head rollback과 durable failed run 기록을 함께 검증한다. 현재 bus `_fail`은 rollback 뒤 ORM run.id를 읽으므로, 새 hook 구현 시 scalar run_id를 선취해 만료 객체 접근을 피하는지 점검한다. 이는 코드상 위험 조사이며 이번에 실행 재현한 결함이라는 뜻은 아니다.
- 성공 보호: 초도 빈·106→0/1·정상0 완결·재확인 복구·timeout/quota·scope 변경·필터 denominator·KAC 성공+ICN 실패·주차 성공+요금 실패·parking unconfirmed empty.
- T3: 기관/노선별 동명이역, 001 등 코드 선행0, 미매핑 보존, inactive 코드, 수동 mapping 우선·경합 revision, code catalog commit 뒤 시간표 실패, rail 위치파일 빈/급감, express/intercity 같은 terminal_id, 이름/도시 변경 후 좌표 무효화.
- 좌표/admin: 수동 좌표 보존·동시 수정409·정확1e-8 좌표 이동 후 stale reverse null·not_found 옛 payload null·같은좌표 error의 실제 resolved_at 보존·가이드라인 좌표 미공개·KOMSA 보충 실패/정상 무결과 차이·null airport anchor.
- snapshot: 페이지 사이 source 재수집·같은 PK UPDATE·mapping/좌표/address 변경에도 최초 snapshot 값은 고정, 신규 snapshot은 새 revision. stale/failed health는304로 숨기지 않음. TTL/GC reader lease/filter/limit 변경/위조 handle/point-byte cap/empty page/취소·풀 반환 후 gzip.
- 모든 새 경로 token/peer fail-closed, 무권한404, provider 호출0, history fullscan0 및 source raw Python 로딩0. 기존 public/legacy exports/수집/통계 전체 회귀도 보존한다.

## 남은 운영 실측

source별 stale/정상0 증빙과 PG DTO snapshot/TTL/GC 정책은 PR114~118의 각 계약으로 확정했다. 격리 PG/실제 TCP fixture 수용은 [정산](../reports/2026-10-23-map-t2-t3-acceptance.md)에 남긴다. 운영 source head bootstrap, Map의 별도 frozen reader, 실제 운영 API/UI 및 동일 입력 최소3쌍 ARM CPU/RAM·PG WAL 비교는 아직 수행 전이다. 격리 fixture 속도를 Odroid 개선 수치로 대신하지 않는다.
