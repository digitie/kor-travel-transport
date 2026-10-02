# 성능 기준

## 통합 조회 지연 목표

- 저장 데이터 기반 API의 요청부터 본문 수신 완료까지 1초 이내를 목표로 한다. 단,
  기존 `/v1/parking/history`의 `limit` 없는 전체·오래된 순서 응답은 계약을
  유지하면서 3초 이내를 목표로 한다. 운영의
  DB·애플리케이션·응답 직렬화 시간을 함께 측정하며, 기본값뿐 아니라 허용된 큰
  `limit`와 유종 필터도 점검한다. 외부 제공기관을 실시간 호출하는 비행편·누락
  배편은 별도로 계측하고 이 DB 목표 달성으로 오인하지 않는다.
- 2026-09-30 변경 전 n150 단건 기준: `/v1/transport/fuel/stations?days=7&limit=1000`
  3.84~4.67초, 유가 지도 `limit=5000` 1.78~4.09초, `/v1/dashboard/analytics?airport_code=GMP`
  1.57~2.28초, GMP 주차 이력 30일은 2.90초(약 6.3MB)였다.
  고속도로 1,000건과 다른 장소 기준정보는 1초 이내였다. 동시
  요청 시 수치는 더 나빠질 수 있으므로 배포 뒤 냉·온 조회와 반복 표본을 다시 남긴다.
- 원인 분리: 운영 DB의 유가 1,000곳 최신 가격 window 쿼리는 `EXPLAIN ANALYZE`
  약 83ms였지만 Python이 각 주유소마다 전체 가격 목록을 재순회하고 원본 JSONB까지
  ORM으로 읽었다. 고속도로 원본 약 1,241만 행은 기존 5분 집계를 사용해 현 조회
  지연의 주원인이 아니므로 무근거로 삭제하거나 재적재하지 않는다.

## 최신 유가 테이블 (`0022_fuel_latest_prices_table`, 이전 `0018` MV)

- `fuel_price_snapshots`는 이력 원본으로 유지한다. `fuel_latest_prices`는 일반 테이블로,
  `(fuel_station_id, product_code)` PK별 `collected_at DESC, id DESC` 한 행(`snapshot_id`)을
  보존한다. 가격 NULL도 최신 행이면 그대로 보존하며, 지도 유종 필터는 현재
  `price > 0`인 장소만 포함한다. 유가 목록은 요청 `days` 내 마지막 수집 가격만
  보여주는 기존 계약을 유지한다.
- 유가 수집이 원본 행을 쓴 **같은 트랜잭션**에서 그 배치(`collected_at`)의 행만 읽어
  upsert한다(`upsert_latest_fuel_prices`). 기존 행보다 `(collected_at, id)`가 작은 늦은
  배치는 덮어쓰지 않고, 제자리 재수집(가격 정정)은 반영한다. 원본과 최신 행이
  어긋날 수 없으므로 MV 시절의 세대(`0019`)·체크포인트(`0020`)·원본 대조와 고속도로
  job의 재시도는 모두 없앴다. SQLite 테스트도 같은 테이블·같은 upsert를 쓴다.
- **바꾼 이유(2026-10-02 n150).** 원본이 73만 행·987MB가 되자 MV `REFRESH ... CONCURRENTLY`와
  원본 대조 SQL이 모두 60초 statement timeout을 넘겼다(대조 SQL 단독 실측 61.2초). 매 5분
  고속도로 job이 실패를 기록해 `fuel_prices_stale=true`가 영구히 굳었다(실제 차이는 0행).
  둘 다 이력 전체를 읽으므로 수집할수록 더 느려지는 구조였다. 증분 upsert는 수집 한 번
  크기(약 6만 행)만 읽는다.
- `fuel_prices_stale`은 이제 오피넷 수집 상태만 본다: 저장된 가격이 있는데 마지막 성공이
  없거나, 마지막 수집이 실패했거나, 마지막 성공이 24시간(정기 수집 약 3회)보다 오래되면
  참이다. `fuel_prices_last_refreshed_at`은 마지막 오피넷 수집 성공 시각이다.
  `/v1/transport/providers`의 별도 `fuel_latest_prices` 상태 행은 없어졌다.
- `0022` upgrade는 MV를 지우고 테이블을 만든 뒤 전 이력에서 한 번 채운다(문장 상한 900초,
  n150 약 60초 예상). `ix_fuel_prices_latest_lookup`(0018)이 이 backfill을 받친다.
- 조회는 원본 `raw_item_json`을 가져오지 않고, 가격 응답은 주유소 ID로 한 번만
  그룹화한다. 전용 로컬 PostgreSQL 12,000곳·12만 가격 이력 표본에서 유가 목록
  1,000곳 약 0.10초였다. 지도는 5,000개 주유소의 30여 ORM 필드와 25,000개
  최신 가격 ORM 객체를 만들지 않고 표시 필드만 투영한다. 같은 로컬 표본의
  5,000곳 응답 10회 중앙값은 0.53초·최대 0.65초였다. 이는 운영 달성 수치가 아니다.

## 주차 공휴일 패턴

통합 분석의 지연은 공휴일/주말 8개 날짜 사이의 모든 주차 관측을 읽는 범위
쿼리에서 두드러졌다. 선택된 한국 시간 날짜 각각의 UTC 하루 범위만 조회하도록
변경했다. 날짜·요일별 분석 계산과 응답 계약은 유지한다.

## 장기 주차 이력

30일 원본 이력은 GMP만 약 60,585행이다. PostgreSQL에서
`parking_snapshots` ORM 전체 행·원본 JSONB를 만들고 Python으로 중복 제거하던
경로를, 원본 우선순위(`migration_`보다 live, 그다음 수집시각·ID)를 같은 규칙의
SQL window로 옮기고 응답에 필요한 네 필드만 읽는다. DB 계획 자체는 운영 표본
약 177ms였다. 응답에 필요한 네 필드를 Core JSON 인코더로 직접 반환해
Pydantic 객체 생성·이중 직렬화를 피한다.
실제 이력 화면이 쓰는 90일 `/parking/analytics/timeseries`는 각 시각·주차장의 최신
관측 원본을 기간당 한 번 훑어 `date_bin`/`DISTINCT ON`으로 주차장·버킷의
최신 유효 관측을 고른 뒤, DB에서 버킷별 합계를 만든다. 각 버킷마다 주차장별
`LATERAL` 탐색을 반복하지 않는다. 한국시간 자정, live/migration 중복 우선순위,
수집 공백 시 요청한 종료일 고정은 유지한다. 각 버킷은 이전 한 간격 안의 관측만
사용하며, 마지막 관측 이후나 중간 수집 공백에는 오래된 주차값을 이월하지 않는다.
날짜 범위의 생략 기본값은 공개 `/v1` 계약대로 10분을 유지한다. n150의
90일·10분 12,960개 버킷의 운영 표본은 이전 단일 스캔 후보와 기존 쿼리가
일치했고 `EXPLAIN ANALYZE`는 약 0.17~0.42초였다. 적대적 리뷰가 정확히
경계인 관측의 다음 버킷 누락을 찾아 후보를 보강했으므로, 최종 SQL 동등성과
본문 수신까지의 HTTP 1초 목표는 새 버전 배포 전후에 다시 검증한다.
30일 원본 이력은 `limit`을 지정해 최신 1,000건씩 커서로 조회한다.
서명된 커서는 기간 시작을 고정한다. 기존 무제한 호출은 전체 반환·오래된 순서를
유지하고 3초를 별도로 목표로 한다. 대량 데이터의 1초 조회 목표에는 명시적
페이지를 사용한다. n150에서
1,001개 키와 유효 관측의 조인 SQL은 약 7ms였으나, 이 역시 배포 전
DB 내부 실행시간일 뿐이다.
커서 서명 키는 비공개 DB 접속 문자열에서 용도별로 파생하므로 같은 DB 설정의
프로세스·재시작 간 유효하다. DB 자격증명 교체 시 기존 커서는 만료된다.
커서는 첫 페이지에서 읽은 최대 스냅샷 ID도 고정해 이후 들어온 과거 관측이
다음 페이지에 끼어들지 않게 한다. PostgreSQL 전체 응답은 `DISTINCT ON`으로
중복을 원본에서 한 번 정리하고 필요한 열만 반환한다. 2026-10-01 운영의
30일 무제한 표본은 약 52만 건·75MB였으며, 읽기 전용 진단의 반복 실행은
DB 읽기 약 2.0~2.8초와 앱 직렬화 약 2.7초로 3초 목표에 미달했다.
DB 자체 JSON 집계는 45초로 더 느려 채택하지 않는다. 목표 충족 전까지
이를 완료로 표시하거나 머지하지 않는다.

사용자는 2026-10-01 전체·오래된 순서 JSON 계약을 유지하는 조건으로 최대 30초
지난 사전 생성 결과를 허용했다. PostgreSQL API 기동 후 백그라운드에서 30일 범위의 live 우선
중복 제거 결과를 한 번 만들고 각 행의 JSON을 보관한다. 무제한 요청은 요청 당시의
`days` 시작 시각·공항·주차장 조건으로 행 조각을 선택·연결하므로 기간 경계와
필터 계약을 유지한다. 클라이언트가 `br` 또는 `gzip`을 허용하면 압축해 전송한다.
새 스냅샷을 게시하기 전에 기본 30일 전체 조회의 Brotli 품질 6과 gzip 수준 9
본문을 미리 만든다. 같은 스냅샷·조회 시작 행·필터·압축 형식은 준비된 바이트를
재사용하며 압축 응답만 최대 8개 보유한다(75MB 수준의 비압축 본문은 보유하지 않는다).
시작 행이 바뀌거나 원본이 갱신되면
새로 만든다. 이 캐시는 응답 계약을 바꾸지 않고 반복 압축 CPU만 줄인다.
압축 준비 중 원본 지문이 달라지면 준비 결과를 게시하지 않고 다음 폴링에
재시도한다. 준비 전에만 지문을 읽고 끝난 시각을 새로 찍는 신선도 오류를
막기 위한 것이다.
5초마다 원본 최대 ID와 PostgreSQL의 해당 테이블 insert/update/delete 통계
변화를 확인해 변경 시 백그라운드에서 재생성한다. 마지막 정상 확인이 30초를
넘거나 캐시가 요청 기간을 전부 덮지 못하면 오래된 캐시를 반환하지 않고
기존 직접 SQL로 돌아간다. DB 장애·긴 재생성 중에는 3초 목표보다 느릴 수
있으며, 운영 실측에서 이를 별도로 구분한다. 정상적인 무변경 구간의 최대 ID
확인은 내용을 다시 스캔하지 않는다. 운영 표본의 캐시된 52만 행 JSON 연결은
약 0.25초였다. 기존 gzip 수준 1은 약 5.4MB, 품질 6 Brotli는 약 2.7MB다.
압축률 수치는 배포 전 동일 표본 분석이며 HTTP 3초 달성을 뜻하지 않는다.
공개 웹 프록시의 무제한 이력은 압축 원본 스트림으로 전달하고, 일반 JSON
프록시에서는 자동 압축 해제 후 잘못된 `Content-Length`를 버린다. 캐시 응답의
캐시 적중·실패 시 직접 조회 모두 직렬화부터 실제 전송 완료까지 최대 2건만
동시 실행해 대용량 본문의 메모리
점유를 제한한다. 응답은 64KiB 청크로 전송해 느린 수신자의 backpressure를
받으며, 실패·취소 시 슬롯을 반환한다. 캐시 판정은 슬롯 대기 뒤 다시 한다.
공개 프록시는 전체 전송 시간이 아니라 상류 비활성 시간을 제한한다.
앞선 응답의 전송 슬롯을 기다리는 새 요청에 일반 JSON의 짧은 헤더 제한을
적용하지 않도록 전체 이력 헤더 대기 한도를 최소 120초로 둔다.
헤더 대기 요청은 프록시 프로세스당 최대 8건이며 초과 요청은 503으로
빠르게 거절한다. PostgreSQL 무제한 이력의 공항 필터는 캐시 적중/전송
슬롯 대기 전에 연결을 획득하지 않는다.
PostgreSQL 통계 반영 지연·낮은 ID의 뒤늦은 커밋은
엄밀한 30초 신선도 보장의 잔여 위험이다.

2026-10-01 n150 재측정에서는 `parking_snapshots`의 추정 행 수가 실제 약
77만 행에 비해 3.6만 행에 머물고 `last_analyze`가 비어 있었다. `ANALYZE` 뒤
공항·관측시각 인덱스를 선택했지만, 30일 GMP 약 6만 행의 heap 접근이
많아 공유 호스트 부하 중에는 SQL만 약 10초 걸렸다. `0021`은
`(airport_id, observed_at)`에 순위 계산과 응답에 필요한 열을 포함하는
covering index를 concurrent로 만들고 해당 테이블의 auto-analyze 임계비를
0.02로 낮춘다. index-only scan은 visibility map에 좌우되므로 인덱스
생성만으로 1초 목표를 달성했다고 간주하지 않는다. 배포 뒤
`EXPLAIN (ANALYZE, BUFFERS)`의 heap fetch와 본문 수신 완료 시간을 다시
측정한다. 중단으로 invalid index가 남으면 해당 이름·valid 상태를 확인한 뒤
그 인덱스만 별도로 정리하고 migration을 재실행한다. 롤백에서는 버전 갱신과
원자적으로 묶을 수 없는 concurrent 인덱스 삭제를 하지 않는다. 안전한 추가
인덱스를 남기고 테이블 설정만 되돌리며, 재적용은 정의를 확인해 재사용한다.

## 첫 화면

첫 화면은 `GET /v1/dashboard/bootstrap` 한 번으로 공항·주차 현황·수집기 상태·공휴일 요약을 받는다. 기존 개별 endpoint는 하위 호환과 직접 진단용으로 유지한다. `/v1/airports`는 `selectinload`로 주차장 목록을 한 번에 읽어 공항 수만큼 반복하던 N+1 조회를 제거했다.

## 지연 분석

분석 섹션은 viewport 근처에 들어올 때만 요청한다. 데이터베이스 기반 5개 분석을 `GET /v1/dashboard/analytics`로 묶고, 외부 API가 느려도 주차 분석을 막지 않도록 비행편은 별도 요청과 6초 client timeout을 유지한다. 기본 기간의 시계열·요일·임계치 결과는 `analytics_caches`를 사용한다.

## PostgreSQL 인덱스

- `parking_snapshots (airport_id, parking_lot_id, observed_at DESC, id DESC)` — 주차장별 최신 관측
- `parking_snapshots (airport_id, parking_lot_id, observed_at)` — 기간 분석
- `parking_snapshots (airport_id, observed_at) INCLUDE (parking_lot_id, id, collected_at, source, occupied_spaces, total_spaces, available_spaces)` — 30일 원본 이력
- `parking_snapshots (collected_at)` — 수집 신선도 확인
- `parking_snapshots (collection_run_id)` — 실행과 원본 추적
- `highway_traffic_snapshots (route_no, observed_at, direction) INCLUDE (speed, free_flow_speed)` —
  노선 동일성·기간 범위로 좁혀진 고속도로 통계의 index-only 집계

운영에서는 `EXPLAIN (ANALYZE, BUFFERS)`로 7일 시계열과 current query를 확인하고, 임의로 인덱스를 추가하지 말고 `docs/journal.md`에 근거를 기록한다.

`0008_transport_route_stats`는 `CREATE INDEX CONCURRENTLY`를 사용한다. 배포가 DDL 수행 중
중단되면 PostgreSQL은 같은 이름의 invalid index를 남길 수 있으며 `IF NOT EXISTS`는 그 index를
수리하지 않고 생성을 건너뛴다. 다음 배포 전 운영자가 `pg_index.indisvalid`를 확인하고, invalid이면
해당 index만 `DROP INDEX CONCURRENTLY`한 뒤 migration을 재실행한다. 이 절차는 정상 index를
무단 삭제하거나 전체 schema를 되돌리지 않는다.

## 교통 통계의 집계 상한과 유가 정비

- 통계 cache miss는 `TRANSPORT_STATISTICS_TIMEOUT_SECONDS=20` 안에 집계를 마치며,
  같은 키 대기 시간도 포함한다. 초과 시 실제 쿼리를 취소·rollback하고 슬롯을 반환한 뒤
  504를 반환한다. 실패 결과는 캐시하지 않고 대기자가 남아 있는 lock은 유지한다.
  설정 상한은 25초로 제한해 관리 UI의 30초 upstream 제한보다 먼저 종료한다.
- `0015_fuel_statistics_priced`는 가격 없는 행을 제외한 covering index를 concurrent로
  생성한 뒤 기존 전체 가격 통계 index만 제거한다. 관측 원본·유일 키·응답 계산은 유지한다.
  n150 7일 표본의 유효 행은 141,776개인데 이전 index는 NULL 가격 176,419개도 읽었다.
  DDL 연결에 잠금 3초·문장 180초 제한을 직접 적용한다. asyncpg에는 `PGOPTIONS`가
  적용되지 않는다. invalid index 실검증이 필요하므로 이 revision은 온라인 실행만
  지원하며 `--sql`은 명시적인 오류로 중단한다.
- 가격 테이블의 auto vacuum/analyze scale factor를 0.02로 조정한다. 전체 PostgreSQL
  설정이나 다른 앱 테이블은 변경하지 않는다. 중단된 DDL의 invalid index는 자동으로
  정상 취급하지 않으며 이름을 확인한 뒤 그 index만 정리하고 migration을 재실행한다.
- 테이블 복원·대량 적재 뒤에는 `EXPLAIN (ANALYZE, BUFFERS)`와 `relallvisible`을 확인한다.
  일반 `VACUUM (ANALYZE, TRUNCATE FALSE, PARALLEL 0)`는 데이터를 삭제하거나 파일을
  재작성하지 않는다. 공유 서버에서는 lock/statement timeout·cost delay를 지정한다.
  긴 index cleanup이 상한을 넘으면 visibility 정비만 별도로 하고, index 정리를 완료했다고
  보고하지 않는다. [`PostgreSQL 정기 정비`](https://www.postgresql.org/docs/17/routine-vacuuming.html) 참조.

### 배포 전후 확인

1. 유가 2/7/10일 cold·warm 계획/응답 시간, heap fetch, 버린 NULL 가격 행 수를 구분한다.
2. 실제 PostgreSQL `pg_sleep` 취소 뒤 같은 session의 후속 조회와 집계 슬롯 반환을 검사한다.
3. concurrent index 생성 성공/valid를 확인한 뒤만 구 index를 제거한다. rollback은 새 runtime을
   내리기 전에 `0014_kric_timetables`로 downgrade하고 이전 이미지를 재기동한다.

## 수용 기준

- bootstrap 성공 후 주차 현황이 표시되고 외부 비행편 지연으로 loading 전체가 붙잡히지 않는다.
- 모바일에서 page-level 가로 스크롤은 없고, 큰 테이블/차트만 자체 스크롤한다.
- 14 운영에서 `/health` 200, `/v1/parking/current`, `/v1/dashboard/bootstrap`, `/v1/dashboard/analytics`가 정상 응답한다.
