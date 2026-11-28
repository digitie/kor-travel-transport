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
새 스냅샷을 게시하기 전에 기본 30일 전체 조회의 gzip 본문을 날짜 조각 압축을 이어 붙여
미리 만든다(아래 PARKING-HISTORY-INCREMENTAL 단락). 같은 스냅샷·조회 시작 행·필터·압축 형식은 준비된 바이트를
재사용하며 압축 응답만 최대 8개 보유한다(75MB 수준의 비압축 본문은 보유하지 않는다).
시작 행이 바뀌거나 원본이 갱신되면
새로 만든다. 이 캐시는 응답 계약을 바꾸지 않고 반복 압축 CPU만 줄인다.
압축 준비 중 원본 지문이 달라지면 준비 결과를 그대로 게시하지 않는다. 준비 전에만 지문을 읽고 끝난 시각을
새로 찍는 신선도 오류를 막기 위한 것이다. 증분 결과는 버리고 다음 폴링에 재시도하고, 전체 재생성 결과는 증분
기준으로 채택해 그 뒤 행만 따라잡은 결과를 다시 확인한 뒤 게시한다(아래 PARKING-HISTORY-INCREMENTAL 단락의 "전체 재생성 채택").
5초마다 원본 최대 ID와 PostgreSQL의 해당 테이블 insert/update/delete 통계
변화를 확인해 변경 시 백그라운드에서 재생성한다. 마지막 정상 확인이 30초를
넘거나 캐시가 요청 기간을 전부 덮지 못하면 오래된 캐시를 반환하지 않고
기존 직접 SQL로 돌아간다. 8일 이상의 공항·전체 범위 직접 SQL은 프로세스당 동시 1건이다(아래 절).
DB 장애·긴 재생성 중에는 3초 목표보다 느릴 수
있으며, 운영 실측에서 이를 별도로 구분한다. 정상적인 무변경 구간의 최대 ID
확인은 내용을 다시 스캔하지 않는다. 운영 표본의 캐시된 52만 행 JSON 연결은
약 0.25초였다. 그때 요청마다 쓰던 gzip 수준 1은 약 5.4MB, 품질 6 Brotli는 약 2.7MB였다.
지금 캐시 적중 gzip은 날짜 조각 압축(보관 수준 9, 첫 날짜 6), 캐시 미사용 직접 조회 gzip은 수준 6이다.
압축률 수치는 배포 전 동일 표본 분석이며 HTTP 3초 달성을 뜻하지 않는다.
공개 웹 프록시의 무제한 이력(`limit` 없음)은 next.config `rewrites`(beforeFiles)로 pages API
`src/pages/api/full-history.ts`가 맡아 backend 압축 본문과 `content-encoding`을
그대로 스트림으로 넘긴다. backend 무제한 이력 응답은 캐시 적중·직접 조회 모두 64KiB 청크 스트리밍이라
`content-length`가 없다(프록시는 있으면 함께 넘긴다). Next 서버 압축은 이미 인코딩된 응답을 건너뛴다. App Router route handler는 응답의
`content-encoding`·`content-length`를 버리고(Next 16.4 send-response) 다시 압축하므로, 거기서 압축 본문을 넘기면
이중 gzip이 됐다(2026-11-24 운영 검증, HISTORY-DOUBLE-GZIP-20261124). rewrite를 비껴 App Router에 온 무제한 이력은
fallback으로 identity를 받아 스트림으로 넘기고 Next가 한 번 압축한다(압축 본문이 오면 풀고, 모르는 인코딩이면 502). 일반 JSON
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
엄밀한 30초 신선도 보장의 잔여 위험이다. 증분 갱신(2026-11-24)부터 뒤늦은 낮은 ID 커밋은 다음 갱신의
`count(*) WHERE id <= W` 검사로 전체 재생성된다(아래 PARKING-HISTORY-INCREMENTAL 단락).

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

### 주차 이력 생성 CPU 중복 제거(2026-11-19)

운영 철도역 조회의5초 표본에서 별도 주차 이력 생성 스레드가 계속 UTC 변환과 행 인코딩을 수행했다. 각 행의 인덱스 시각과 JSON 시각을 따로 변환하던 부분은 한 번 변환한 값으로 통일하고, 동일한 공항/주차장 식별자 접근도 재사용한다. 기존 pydantic-core 인코더, 정렬·필터·신선도·재생성 조건은 유지한다. 로컬10만 SQLAlchemy Row 동일 입력 교대6회에서 생성 CPU 중앙452.04→338.03ms, 벽시계452.11→340.22ms, 전체/필터 바이트와 index는 같았다. 이25.22%는 생성 구간의 로컬 결과이며 운영 철도역4.30초와 최초 cold18.73초의 개선율이나 수용 결과로 확대하지 않는다.

### 주차 이력 갱신 계측과 직접 조회 상한(2026-11-24)

2026-11-24 Map 호출 감사(RT-01·G3-02 P1, WLH-01, RT 누락 #1·#2)의 이력 재생성 비용은 증분 갱신(아래
PARKING-HISTORY-INCREMENTAL 단락)이 주로 줄였다. 통계 반영 지연으로 갱신 결과를 버려도 다음 확인이 싼 증분으로
다시 맞추므로 폐기 조건은 따로 바꾸지 않는다. 이 절은 갱신 계측과 캐시를 쓸 수 없을 때의 직접 조회를 다룬다. 응답
계약(전체·오래된 순서, 최대 30초 신선도)과 API lifespan 시작 순서는 바꾸지 않는다.

- 갱신 로그(`event=parking_history_rebuild`)에 `peak_rss_kib`(start·finish, `getrusage(RUSAGE_SELF).ru_maxrss`, 즉 프로세스
  시작 이후 최고 RSS — finish가 start보다 크면 그 갱신이 최고점을 올린 것이다, POSIX가 아니면 null), `worker_cpu_ms`(갱신
  worker thread 안에서 `thread_time()`으로 잰 전체 적재 변환·증분 반영·30일 gzip 조립 CPU 합계, event loop 위의 DB 행 수신은
  빠진다), `process_cpu_ms`(같은 구간의 프로세스 전체 CPU, 요청 처리도 섞인다)를 더한다. 계측기는 context 변수로 넘겨
  `load_snapshot`·`load_changes`의 호출 모양은 그대로다. 다른 코드가 읽을 수 있게 `ParkingHistoryReadCache.rebuild_active`를
  둔다(아직 읽는 곳은 없다).
- 직접 조회가 쓰이는 때. 기동 직후 첫 전체 적재와, 전체 재생성(새벽 안전망·늦은 커밋·update/delete·대량 변경·증분 오류)이
  30초 유효 시간을 넘는 동안(운영 ARM 전체 적재 77~98초)에는 캐시를 쓸 수 없어 무제한 요청이 직접 조회로 간다. 수집마다의
  증분 갱신은 수 초라 이 구간을 만들지 않는다.
- 직렬화 범위. 주차장 하나가 아닌 8일 이상 범위(전체 30일 약 52만 행·75MB)만 프로세스당 동시 1건으로 묶는다. 주차장
  하나(30일도 약 8,640행)와 7일 이하 범위(기본 3일)는 기존처럼 전송 슬롯 안에서 바로 돈다.
- 기다림. 차례를 기다리는 요청은 캐시가 게시·재확인되거나 앞선 직접 조회가 끝나면 바로 깨어 다시 판정하고, 쓸 수 있는
  캐시가 있으면 그것으로 응답한다(신호를 놓쳐도 1초마다 다시 확인한다). 전송 슬롯이 2개라 차례를 기다리는 요청은 최대
  1건이다. 기다림의 상한은 앞선 직접 조회 1건(DB 문장 상한 120초 + 변환·압축)과 다음 캐시 재확인 중 이른 쪽이다. 나머지
  요청은 DB 연결 없이 전송 슬롯을 기다린다. 차례를 얻은 요청은 연결이 이미 끊겼는지(공개 프록시 헤더 대기 120초 초과, 닫힌
  탭) 확인하고, 끊겼으면 직접 조회 없이 499로 끝낸다.
- 스트리밍. 같은 `DISTINCT ON` 문장을 2048행씩 server-side cursor로 받아 바로 행 JSON으로 바꾸고, br/gzip 요청이면
  조각마다 압축해(gzip 수준 6, br 품질 6) 비압축 본문을 모으지 않는다. identity는 행 JSON 조각과 최종 본문 한 벌만 만든다.
  압축 bytes는 캐시 본문과 다를 수 있지만 압축을 푼 본문은 이전 직렬화·캐시 본문과 같다(시험). 묶음마다 변환·압축하는
  동안에도 cursor 문장의 snapshot을 쥐므로, 전체를 한 번에 받던 이전보다 xmin(vacuum horizon)을 그 변환 시간만큼 더 오래
  붙잡는다(로컬 약 4초 CPU, ARM은 더 길다).
- 측정(로컬 x86·PostgreSQL 18, 최근 30일 본문 50.96만 행·73.87MB 합성 표본, 이전·새 직접 조회를 교대로 5회씩 돈 중앙값,
  다른 작업이 함께 도는 호스트). tracemalloc 최대 할당은 identity 418→149MB, gzip 418→11MB, br 418→4.5MB다. 프로세스 CPU는
  4.27→4.13초, 5.36→4.78초, 5.69→5.39초다. 벽시계는 7.80→9.24초, 9.36→10.43초, 10.32→11.81초로 10~18% 늘었다. 2048행씩 받는
  수신 왕복과 묶음 처리가 직렬이기 때문이다(수신만 5.3~6.2초, CPU 2.0초). 수신과 변환을 겹치는 방식도 재 보았지만 둘 다
  GIL을 쥐는 Python 작업이라 줄지 않아 넣지 않았다. 긴 범위 직접 조회는 동시 1건이므로 메모리 상한을 앞에 둔다. 운영은 ARM
  Cortex-A55·PostgreSQL 18이라 크게 느리다(감사 추정 약 5배). 운영 직접 조회 시간과 갱신 최고 RSS는 배포 뒤 위 로그
  필드로 실측하는 후속이다.
- live E2E. 무제한 이력 요청 시험은 모두 `frontend/e2e/full-history-encoding.spec.ts` 한 파일에 둔다(`fullyParallel: false`라
  한 worker에서 차례로 돈다). 다른 파일에서 동시에 보내면 긴 범위 직접 조회 차례를 서로 기다려 시간 한도를 넘길 수 있다.
  배포 직후 첫 전체 적재(운영 77~98초) 전에는 캐시가 없으므로 3초 브라우저 시험은 캐시가 게시된 뒤에 돌린다.
- 채택하지 않은 것. 갱신 중 이전 캐시를 30초 넘게 내주는 방식은 최대 30초 계약을 바꾸므로 소유자 결정이 필요하다.
  `gc.freeze`는 동결 뒤 생긴 순환 쓰레기가 회수되지 않는 위험을 시험으로 배제하지 못해 넣지 않았다. 기동 직후 첫 갱신 지연과
  lifespan 순서는 별도 작업(reference export prewarm) 몫이다.

## 첫 화면

첫 화면은 `GET /v1/dashboard/bootstrap` 한 번으로 공항·주차 현황·수집기 상태·공휴일 요약을 받는다. 기존 개별 endpoint는 하위 호환과 직접 진단용으로 유지한다. `/v1/airports`는 `selectinload`로 주차장 목록을 한 번에 읽어 공항 수만큼 반복하던 N+1 조회를 제거했다.

## 지연 분석

분석 섹션은 viewport 근처에 들어올 때만 요청한다. 데이터베이스 기반 5개 분석을 `GET /v1/dashboard/analytics`로 묶고, 외부 API가 느려도 주차 분석을 막지 않도록 비행편은 별도 요청과 6초 client timeout을 유지한다. 기본 기간의 시계열·요일·임계치 결과는 `analytics_caches`를 사용한다.

공항 수집 job은 수집 commit 직후 기본 범위 사전집계를 다시 만든다(미리 데우기, `refresh_default_analytics_cache`; 수집 lock 경합으로
건너뛰면 경고 로그). 같은 op가 사전집계에 반영되지 않은 가장 오래된 적재가 15분을 넘으면(또는 사전집계 2시간 초과) run 태그
`kortravel/analytics-refresh`·결과 metadata·한 줄 JSON 로그로 알린다(run은 SUCCESS). 관리 화면 홈 운영 상태와 `/v1/transport/providers`의
`airport_analytics_cache`에도 같은 판정이 보인다(ANALYTICS-REFRESH-ALERT-20261124). 대시보드 묶음(`/v1/dashboard/analytics`)은 엄격한 재사용 조건(생성 10분 이내·그 뒤 같은 범위 새 적재 없음)을
못 채워도 직전 사전집계를 낸다: 사전집계 뒤의 새 적재가 모두 `DASHBOARD_REFRESH_GRACE`(40분 — 수집 상한 30분 + 갱신) 안이면 갱신 대기로,
새 적재가 없으면 그대로 맞는 값으로 본다. 사전집계는 `DASHBOARD_STALE_CACHE_MAX_AGE`(2시간)를 넘으면 쓰지 않고, 유예보다 오래된 새 적재가
있으면(갱신 실패·중단) 원본에서 계산한다. 그래서 수집 직후 몇 분은 시계열 마지막 점·임계 이벤트가 현재값 카드보다 한 수집 주기 늦을 수 있다
(`generated_at`은 시계열·임계 요약 payload에만 있고 화면에는 아직 표시하지 않는다). 단독 분석 route(`/v1/parking/analytics/*`)는 엄격한
조건만 쓴다. 응답 머리말 `X-Analytics-Source`가 경로를 알린다(`cache` 엄격 재사용·`cache-grace` 유예·`source` 원본 계산 또는 memo·`mixed`;
공개 웹 프록시는 이 머리말을 넘기지 않으므로 backend에 직접 요청해 본다). 원본 계산은 DB 읽기 뒤 계산을 thread에서 한다
(순수 Python이라 GIL을 쥐지만 event loop를 계산 내내 막지는 않는다). 특수일 시각별 집계는 지난 날짜분을 5분 보관하고 오늘(현지
주말·공휴일)분만 매번 집계해 합친다(DASHBOARD-STATS-OFFLOAD-20261124).
30일 주차 이력 캐시(`/v1/parking/history` 전체 응답용, `parking_history_cache.py`)는 수집마다 30일 전체를 다시 만들지 않는다
(PARKING-HISTORY-INCREMENTAL-20261124). 예전에는 수집마다 55만 행을 다시 읽고 인코딩했다(운영 ARM 77~98초, GIL을 쥐는 순수 Python이라 같은 프로세스의
다른 공항 요청이 함께 느려졌다). 자식 프로세스로 옮기는 안은 pickling 때문에 더 느려 버렸다.

- **증분**: 원본은 삽입 전용이다. 직전 읽기의 최대 id(`W`) 이후 새 행이 닿은 (관측 시각, 주차장) 키만 찾고, 그 키들의 옛 행·새 행을
  전체 재생성과 같은 SQL(`history_rows_statement`, DISTINCT ON·live 우선·최신 수집)로 다시 골라 정렬된 꼬리에 끼워 넣는다. 같은 관측의 다른 source,
  늦게 들어온 옛 관측, 이관 행 우선순위가 전체 재생성과 같은 결과가 된다. 바뀌지 않은 항목은 인코딩 bytes 객체를 그대로 재사용한다(참조 복사).
  30일 창 밖 앞부분은 갱신마다 잘라 낸다.
- **정확성 조건**: 읽기는 REPEATABLE READ 한 transaction(최대 id·행 수·본문이 같은 시점). 시퀀스는 commit 순서가 아니므로, 직전 읽기 때
  진행 중이던 transaction이 낮은 id로 늦게 commit하면 `count(*) WHERE id <= W`가 저장값과 달라진다 → 전체 재생성. 삭제도 같은 검사로,
  update·delete는 `pg_stat` 지문으로 잡는다(운영 코드에 이 쓰기 경로는 없다). 새 키가 5만 개를 넘으면(대량 이관·복원) 전체 재생성.
  안전망으로 마지막 전체 재생성이 20시간을 넘으면 새벽(KST 03~04시)에 한 번 전체 재생성한다.
- **전체 재생성 채택**(PARKING-HISTORY-ADOPT-FULL-REBUILD, #284·#281 후속): 전체 재생성(운영 ARM 77~98초) 중 수집이 끼어 지문이
  바뀌면 예전에는 결과를 버리고 다음 확인에서 또 전체 재생성했다. 지금은 그 결과를 증분 기준으로 채택한다. 전체 적재는 REPEATABLE READ 한
  시점의 (최대 id, 행 수, 본문)이라 기동 직후 전체 적재와 똑같이 증분 기준이 된다. 곧바로 그 뒤 행만 증분으로 따라잡고(`load_changes`),
  따라잡은 결과를 읽기 직전 지문과 읽은 뒤 지문이 같을 때만 게시·검증한다 — 일반 증분 게시와 같은 신선도 근거라 30초 계약은 그대로다.
  - 채택하지 않고 예전처럼 버리는(`outcome=source_changed`, 다음 확인이 전체 재생성) 경우: 전체 적재 직전 지문부터 update·delete 통계가
    움직였다(적재 시점 뒤의 update는 행 수 검사가 못 본다), 최대 id가 줄었다, 따라잡기 증분이 늦게 commit된 낮은 id·삭제(`count(*) WHERE id <= W`)·
    대량 변경을 찾았다, 따라잡기(증분·사전 압축·지문 확인 중 어느 것이든)가 오류로 실패했다(`catchup_error:*`). rollback된 행은 어느 읽기
    시점에도 보이지 않아 최대 id·행 수·본문에 들지 않는다.
  - 따라잡는 사이에도 수집이 끼면 최대 3번(`ADOPT_MAX_CATCHUPS`) 다시 따라잡는다. 그래도 바뀌면 마지막 결과와 그 읽기 직전 지문을
    검증 전 기준(`pending_base`)으로만 둔다(`outcome=adopted_pending`). 이 기준은 요청에 쓰지 않고, 다음 확인이 이 기준·지문으로 `refresh_mode`를
    판단해(`reason=adopted_pending`) 증분한다. 그 증분 중에도 지문이 바뀌면 결과를 버리지 않고 새 기준(그 읽기 직전 지문과 함께)으로 올린다
    (점점 커지는 차이를 다시 읽지 않게). 그 뒤 update·delete 통계가 보이면 이 지문과 비교해 전체 재생성으로 간다.
  - 게시된 snapshot에서 한 일반 증분의 지문 변화는 그대로 버린다(다음 확인의 같은 기준 증분이 싸다).
  - 메모리: 검증 전 기준이 있는 동안은 게시된 snapshot과 두 벌이 남는다(기동 직후가 아니면 이력 캐시 상주가 약 2배). 그래서 수집이 몰릴 때
    finish 로그의 `peak_rss_kib`가 오를 수 있다. 기준에서 증분이 안 되어 전체 재생성으로 가면 전체 적재 전에 그 기준을 놓는다.
  - 로그 finish에 `adoption`·`catchups`(성공한 따라잡기 증분 수)·`phases_ms.catchup_ms`(따라잡기 합계)·`catchup_count_ms`·`catchup_changes_ms`·
    `catchup_splice_ms`(따라잡기 증분 내부, 여러 번이면 합)가 붙는다. 전체 재생성 비용을 비교할 때는 `duration_ms`(채택·따라잡기 포함)가 아니라
    `phases_ms.full_load_ms`를 쓴다.

  | finish `outcome` | `adoption` | 다음 `reason` | 사용자가 보는 것 |
  |---|---|---|---|
  | `published` | null | — | 새 캐시(일반 증분·전체 재생성) |
  | `published` | `published` | — | 전체 재생성이 수집과 겹쳤지만 따라잡아 새 캐시. 두 번째 전체 재생성 없음 |
  | `adopted_pending` | `adopted_pending` | `adopted_pending`(증분) | 아직 새 캐시 없음. 이전 캐시가 30초 안에 확인됐으면 그것, 아니면 직접 SQL. 다음 확인(5초 뒤)이 증분으로 이어 감 |
  | `source_changed` | null | 같은 기준 증분 | 이전 캐시(30초 확인 안) 또는 직접 SQL. 다음 확인이 싼 증분 |
  | `source_changed` | `update_or_delete`·`max_id_decreased`·`late_commit_or_delete`·`too_many_changes`·`catchup_error:*` | `cold` 또는 그 이유의 전체 재생성 | 예전과 같다. 다음 확인이 전체 재생성(운영 ARM 77~98초) 동안 직접 SQL |
- **날짜 조각**: 범위(전체·공항·주차장)마다 항목을 UTC 하루 단위 조각(불변)으로 나눠 둔다. 증분은 바뀐 키가 있는 날짜의 조각과 기간
  경계의 첫 조각만 새로 만들고 나머지 조각 객체를 그대로 넘긴다(전체 튜플 복사 없음, 55만 항목 기준 0.3초 → 10~20ms).
- **보관 기간**: 30일 + 15분 여유. 여유가 없으면 갱신 직전에 시각을 정하고 전송 슬롯을 기다리던 30일 요청이 앞부분이 잘린 snapshot을
  못 쓰고 직접 SQL로 떨어진다.
- **고장 회복**: 증분이 `IncrementalUnavailable`이 아닌 오류(DB·코드)로 실패해도 같은 갱신에서 전체 재생성으로 회복한다
  (`reason=incremental_error:<예외 이름>`, traceback 로그, 연속 횟수 `incremental_errors` — 0이 아니면 증분이 고장 난 채 매 수집 전체 재생성 중이다).
- **gzip 조각 이어 붙이기**(#270 경로와 일관): 조각마다 독립 deflate(Z_FULL_FLUSH, 수준 9 — 요청마다 새로 만드는 첫 날짜 부분은 6)를 처음 쓸 때 만들어 조각에 보관하고, 요청 때
  gzip 머리말 + 첫 날짜(부분)·나머지 조각 + 빈 마지막 블록 + CRC32(`crc32_combine`)·길이로 한 member의 정상 gzip을 조립한다. 갱신 뒤에는
  바뀐 날짜와 첫 날짜만 새로 압축한다(예전 갱신마다 85MB br 6 + gzip 9 약 7초 → 0.1초 안팎, x86). 크기는 본문 전체를 같은 수준으로
  압축한 것과 같다. 기동·전체 재생성 뒤에는 범위별 첫 gzip 요청이 그 범위의 모든 날짜를 압축한다(30일 전체 본문은 게시 전에 만든다).
  캐시 적중 응답은 클라이언트가 gzip을 받으면 gzip이다(br은 매번 전체 압축이 필요해 gzip을 받지 않는 클라이언트에만). 그래서 공개 전체 이력
  (`br, gzip`)은 br 약 1.2MB 대신 gzip 약 2.0MB(합성 55만 행)를 받는다 — 갱신 비용과 바꾼 선택이다. 30일 전체 gzip 본문은 게시 전에 만들어 둔다.
- 로그 `event=parking_history_rebuild`에 `mode`(`incremental`·`full`)·`reason`(`new_rows`·`cold`·`late_commit_or_delete`·`update_or_delete`·
  `too_many_changes`·`periodic`·`incremental_error:*`·`adopted_pending` 등)·`changed_keys`·`phases_ms`(`count_ms`·`changes_ms`·`splice_ms`·`full_load_ms`·`gzip_ms`·`catchup_ms`)가 붙는다.
- 남은 한계: 늦은 commit 감지용 `count(*)`는 기간이 아니라 표 전체를 센다(원본 정리가 막혀 표가 계속 커진다 — `count_ms`로 본다).
  update·delete 감지는 `pg_stat` 통계(`track_counts` 켜짐 전제)에 기대며 반영 지연 동안은 직전 값을 낼 수 있다. 공항 코드 변경은
  다음 전체 재생성(새벽 안전망)까지 반영되지 않는다. 원본 정리(`parking-retention.md`)를 켜면 정리마다 전체 재생성이 돈다.
- 측정은 journal 2026-11-24 PARKING-HISTORY-INCREMENTAL 항목과 PR 본문 표.

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

## 공항 주차 수집의 반복 조회 감소 (2026-10-18)

관측 저장 한 번 안에서 공항 코드별 ORM 객체만 재사용한다. 1,000개 관측이 3개
공항에 속하는 경우 공항 SELECT는 1,000회에서 3회로 줄어든다. 이름·영문명·
updated_at은 여전히 관측마다 갱신한다. 원천, 원본 payload, 주차장 식별자,
관측 중복 unique key와 snapshot savepoint는 그대로다. 캐시는 저장 호출이 끝나면
폐기하므로 rollback 이후 재호출이나 다음 수집으로 객체가 넘어가지 않는다.
메모리는 관측 수 대신 해당 배치의 공항 수에 비례한다.

WSL RAM SQLite의 실제 공항 helper를 1,000관측/3공항으로 각 3회 독립 프로세스에서
교대로 측정했다. 양쪽 모두 관측마다 flush해 실제 다음 lot SELECT의 autoflush를
모사했으며 UPDATE는 양쪽 모두 1,000회다. CPU 중앙값은 1,227.9ms → 543.9ms
(55.7% 감소), Python 할당 peak 중앙값은 171,567 → 171,144 bytes다.
RSS 중앙값은 55,424 → 55,408 KiB로 사실상 같아서 메모리 개선으로 주장하지 않는다.
이는 공항 helper 국소 수치다. provider·lot/snapshot·네트워크·운영 PostgreSQL을
제외했으므로 전체 수집이나 Odroid CPU 감소율을 의미하지 않는다.
Odroid ARM64의 격리 컨테이너에서도 동일 1,000관측/3공항을 기준·후보 각각
3회 측정했다(SQLAlchemy 2.1.5). CPU 중앙값은 15.2357초 → 7.7411초
(49.2% 감소), wall 중앙값은 15.5154초 → 7.8708초다. SELECT 1,000→3 및
UPDATE 1,000 유지도 확인했다. RSS 중앙값은 51,640→51,540 KiB로 사실상 같고
Python 할당 peak 중앙값은 136,465→132,479 bytes다. WSL과 ARM은 별도 환경의
측정이므로 둘 사이 절대시간을 성능 변화로 비교하지 않는다.

[ARM 원시 6표본](../audits/2026-10-18-airport-helper-arm-ab.json)과
[검증 이력 및 한계](../reviews/2026-10-18-collector-airport-cpu.md)를 보존한다.
이 ARM 결과도 SQLite RAM DB의 공항 helper만 측정했으며 외부 네트워크와 운영 DB에
접근하지 않았다. 실제 운영 job 전체 CPU·메모리 사용량이나 idle 부하는 아직 증명하지
않았다. live UI·독립 리뷰·배포는 별도 게이트다. Dagster daemon은 OFF를 유지한다.

## 2026-11-18 다중 지도와 조건부 참조 읽기

다중 종류 PostgreSQL 장소 조회는 정확한 총계와 제한 투영을 한 왕복에 받으며 출처도 한 UNION으로 읽는다.
일반 요청의 SQL 수는 전체 종류·기본 출처 포함 6개다. `raw_item_json`은 필요한 시설/수동 revision 키만
투영한다. 요청 관측은 query string 없는 느린 요청 로그와 Server-Timing을 사용한다.
CPU는 프로세스 누적 CPU 차이이므로 동시 작업의 영향을 포함한다.
2026-11-24부터 이벤트 루프 thread CPU(`loop_cpu`)·풀 대기(`pool`)를 함께 남기고, 임계는
`SLOW_REQUEST_THRESHOLD_MS`(기본 1000)이며 `/v1/service/exports/*`는 모두 기록한다. gateway access log도
소요 시간을 남긴다. 필드와 지연 분해 순서는 [요청 소요 시간 로그 읽기](../runbooks/request-timing-logs.md)를 따른다.

참조 304는 불변 content digest·handle·만료·페이지·상태로 payload 읽기 전에 판정한다.
입력 지문은 head와실제입력별transactional `(component,epoch,revision)`이같을때만최대64개재사용한다.
공용PG의다른DB/다른표commit은무효화하지않는다.자기transaction쓰기때는항상재계산하고저장하지않는다.
0043의9component/36statement trigger가원본과함께증가하며무변경투영은제외한다.
revision구성누락은503이고MVCC/TTLfallback은없다.자세한측정·미완운영수용은
[보고서](../reports/2026-11-18-read-performance.md)를따른다.주차재구성의프로세스이동은운영p95
채택판정이남아있으며이변경에포함하지않는다.

## 주차 이력 변환 중 API 스레드 실행 기회 (2026-11-19)

기존 이력 구성은 별도 thread에서 실행되지만, 긴 Python 행 변환이 GIL을 계속
다투면 API의 응답 처리와 DB 결과 소비도 늦어진다. 실제 c43 rail 1,000건 GET
4.297초 표본에서 별도 history 생성 thread가 같은 5초 표본 내내 관측됐다.
이 표본으로 과거 최초 cold18.728초의 단독 원인을 확정하지 않는다.

ParkingHistorySnapshot.from_rows는 UTC 값 재사용을 유지하면서
HISTORY_ENCODING_YIELD_ROWS = 400행마다 time.sleep(0)으로 실행 기회를 돌려준다.
400은 동일500k SQLAlchemy Row와 실제 합성 rail PG/ASGI 요청의 교대 비교에서
선택한 값이다. 모든 행의 인코딩·순서·공항/주차장 인덱스를 끝까지 구성한다.
TTL·폴링·신선도·원본 SQL·전체 인터프리터의 switch interval은 기존 계약을 따른다.

| 로컬 median | 기준3af | yield400 |
|---|---:|---:|
| 최초 cadence 비교 rail | 700.22ms | 258.19ms |
| 같은 비교 background thread CPU | 1916.62ms | 2055.64ms |
| 같은 비교 background wall | 1977.75ms | 2191.98ms |
| 이름 있는 상수를 사용한 최종 rail | 690.31ms | 281.07ms |
| 최종 client SQL 시간 | 334.69ms | 126.47ms |
| 최종 background thread CPU | 1888.49ms | 1994.02ms |
| 최종 background wall | 1974.48ms | 2147.26ms |

각 비교는 순차3쌍과 background 없는 control1회다. 최초 rail 감소63.13%의 비용은
background CPU+7.25%/wall+10.83%였다. 최종 정확 코드 비교도 rail 59.28% 감소와
background CPU+5.59%/wall+8.75%를 기록했다. 최종 control은
167.52ms다. SQL18·page build1·fingerprint0과
전체 HTTP bytes/ETag/cursor, artifact digest/count, history bytes/index가 같았다.

고정 clock/handle UUID는 로컬 본문 동등성 시험의 입력이며 실제 monotonic 시간·PG·RR·
검증 경로를 사용했다. HTTP process CPU/client SQL 시간에는 병행 작업의 비용도 섞이고,
history CPU는 thread_time()으로 따로 측정했다. 두 history 구현 모두 GET 종료 때도
동작 중이었다. 운영 API의 1초 목표 달성과 실환경 영향은 배포 후 별도로 검증해야 한다.

집중 회귀는29PASS/실제PG 전용1SKIP이다. 변환 완료 전 bounded peer 실행,
399/400/401/800행 경계, 같은 시각 순서·필터 및 UTC/naive/KST/+05:45/NY fold를
포함한다. 전체 backend 반복 실행과 운영 목표 검증을 대신하지 않는다.

## 철도 내보내기 기동 시 입력 지문 준비

> 2026-11-24부터 기동 warm은 철도역·여객선 두 종류와 풀 채우기·이력 캐시 지연 시작을 함께 한다 —
> 아래 [API 기동 warmup](#api-기동-warmup2026-11-24)을 따른다. 이 절은 철도 한 종류였던 때의 설계와 측정 기록이다.

PostgreSQL API에서 Map current가 활성화되고 배포 revision이 설정돼 있으면(2026-11-25부터는 배포 revision 대신 본문
코드 지문이 있으면 — [본문 코드 지문](#기준정보-본문-코드-지문2026-11-25)),
워커가 기동할 때 철도 입력 지문을 한 번 읽는다. 같은 session factory와
repeatable-read 조회를 사용하므로 첫 페이지가 기존 워커 캐시를 재사용할 수 있다.
조회 전용 트랜잭션으로 최대 10초 동안 실행한다. 작업 완료를 readiness에서
기다리지 않으며, 종료 시 실행 중인 작업을 취소하고 세션이 닫힌 뒤 엔진을 정리한다.

주소나 역·매핑 입력이 갱신되면 기존 revision 검사로 새 지문을 구한다.
HTTP 인증·본문·cursor 계약을 유지하며, 본문과 snapshot의 준비·저장은 기존
경로에서 수행한다. 워밍이 끝나기 전에 도착한 요청은 기존 조회 경로로 처리된다.

격리 PostgreSQL 18의 합성 역 1,466건에서 워밍 완료 후 실제 HTTP 200을
각 6쌍 비교했다. 시험 앱을 매번 띄우기 전에 Python GC 상태를 정리한 비교에서
기존 본문과 snapshot이 있으면 응답 중앙값 196→129ms(6/6 개선), 둘 다 없으면
463→397ms(5/6 개선)였다. 시험 프로세스의 GC 상태를 따로 정리하지 않은 순차 비교에서는
기존 본문이 있을 때 154→103ms, 본문이 없을 때 354→367ms였다. 두 비교에서
첫 요청의 입력 지문 계산과 SQL이 각각 1회 감소했다. 운영 ARM 첫 요청 지연과
기동부터 첫 응답까지 걸리는 총 시간은 별도 측정이 필요하다.

## Map T1 export 본문 구성과 연결 반납 (2026-11-24)

`/v1/service/exports/{fuel-stations,rest-areas,rest-area-fuel-prices,highway-incidents/active,airports}`(T1)는
마지막 SQL 뒤 읽기 transaction을 rollback해 pool 연결과 RR snapshot을 먼저 돌려준다. 그다음 DTO 구성·JSON
직렬화·gzip을 export 전용 `CapacityLimiter(2)` 아래 worker thread에서 한다. 전에는 같은 작업을 단일 uvicorn
event loop에서 했고, request-scope `get_db`라 snapshot과 연결을 응답 송신이 끝날 때까지 쥐었다
(감사 T1-03·T1-04·RT-08). rollback은 세션의 ORM 객체를 만료시키므로, 데이터는 필요한 열만 Core select로
읽고(T1-05) 응답에 쓸 수집 상태는 반납 전에 만든다. 만료된 속성을 반납 뒤 읽으면 `MissingGreenlet`이 나며,
기존 돌발 export 시험이 그 순서 변경을 잡는 것을 확인했다.

thread로 옮겨도 GIL을 오래 쥐는 단일 호출은 event loop를 그대로 멈춘다. 그래서 두 가지를 더 했다.

- 원본 행(`raw_item_json`, JSONB)은 `CAST(... AS TEXT)`로 받아 worker thread에서 `json.loads`한다. asyncpg는
  JSONB를 fetch 중(loop)에 풀며, 합성 500행에서 약 16ms였다. jsonb text 출력은 asyncpg가 받는 문자열과 같은
  정규형이라 풀린 값도 같다.
- pydantic-core `dump_json`은 직렬화 동안 GIL을 놓지 않는다(합성 500행 1.7MB 약 19~30ms). 봉투와 item 25개
  묶음을 따로 직렬화해 한 번의 `b"".join`으로 이어 붙여 한 번에 쥐는 시간을 약 5ms 이하로 줄였다. 전체 직렬화
  시간은 비슷했고 최대 메모리는 본문의 약 2배다. 봉투의 `"items":[]`가 정확히 한 번이 아니면 한 번에 직렬화한다.

본문 바이트는 FastAPI 기본 경로(`TypeAdapter(response_model).dump_json(by_alias=True)`)와 같다.
`tests/test_service_exports_render.py`가 바뀌기 전 핸들러를 그대로 옮긴 legacy router와 5종·여러 limit의
모든 페이지를 바이트 단위로 비교한다. `response_model`은 그대로라 OpenAPI 문서는 바뀌지 않는다.

- gzip: `Accept-Encoding`이 gzip을 허용하고(q=0은 거절) 본문이 512B 이상이면 level 1로 압축하고
  `Vary: Accept-Encoding`을 둔다(T4 가격 이력과 같은 규칙, 감사 T1-06). Map httpx는 기본으로 gzip을 받는다.
- snapshot: `BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY` + transaction 범위
  `statement_timeout='20s'`·`lock_timeout='3s'`(`set_config(..., true)` 한 왕복). 문장 상한은 문장마다라
  주유소 페이지(문장 4개)는 이것만으로 최악 80초가 될 수 있다. 그래서 handler 전체(DB 단계 + 본문 구성 slot
  대기·구성)에 `asyncio.timeout(25초)`를 따로 둬 Map read timeout 30초 안에 응답이나 503이 닿게 한다(감사 RT-04).
  이미 시작한 본문 구성 thread는 끊지 못해 그 경우 구성이 끝난 뒤 503이 된다. migration DDL의 AccessExclusive
  대기 뒤에는 3초까지만 줄 선다. 연결이 pool로 돌아가면 격리 수준·READ ONLY·transaction 범위 설정은 모두
  원래 값이다 — 정상 반납, begin과 end 사이의 HTTP 오류, deadline 취소, 57014 뒤 모두 연결 1개짜리 pool에서
  쓰기로 확인한다(PostgreSQL 전용 시험).
- 503: 잠금 대기(55P03)와 본문 구성 slot(`CapacityLimiter(2)`) 대기 5초 초과는 503 `Retry-After: 10`,
  문장 상한(57014)과 요청 전체 상한은 503 `Retry-After: 60`이다. 그 밖의 DB 오류와 이 deadline이 아닌
  `TimeoutError`는 예전처럼 올린다. slot을 얻었을 때 소비자가 이미 끊었으면 본문을 만들지 않는다(499).
- rollback 실패: 행을 다 읽은 뒤 `_end_snapshot`의 rollback이 연결 오류로 실패하면 연결을 버리고(`invalidate`)
  페이지는 그대로 낸다.
- `/airports`는 요청마다 `KrairportClient`(httpx 클라이언트 2개)를 만들지 않고 공개 `list_airports(active=True)`를
  쓴다(T1-08, ADR-004의 공개 API 사용).
- cursor가 int4 PK 범위(0..2^31-1) 밖이면 DB bind 오류(500) 대신 422다(T1-09).

로컬 측정(Windows dev, PostgreSQL 18 container, 합성 주유소 1,000곳·유종 5개·원본 약 1.5KB, 같은 프로세스에서
옛 구현과 번갈아 `limit=500` 요청 15~20회, 다른 작업이 CPU를 많이 쓰던 상태라 절대값의 편차가 크다)에서
요청 중앙값은 285~420ms → 237~356ms, 동시에 돈 1ms ticker로 잰 event loop 최대 정지의 중앙값은 88~145ms →
31~46ms였다. 본문은 1,741,856B이고 gzip level 1이면 122,5xxB였다(합성 원본이 반복적이라 실데이터 압축률은
더 낮을 것이다). 운영 ARM 수치는 배포 후 Server-Timing으로 따로 확인해야 한다.

T1의 55P03·57014·요청 상한 503은 이 경로가 직접 낸다(`Retry-After`만). 503 사유 `code`와 일시 DB 불가(pool·접속)
503은 export 실패 계약 작업의 몫이다. 계약은 [ADR-013 개정 2026-11-24 (T1 전송)](../adr/013-internal-service-exports-for-map.md)이다.

## 장소 지도 입장 제한·시한·연결 반납 (2026-11-24 감사 MUI-02·04)

`/v1/transport/features/places`(관리 `/map`·`/fuel`·`/flights` 공항 목록·역/항구 목록, 공개 유가 gateway)는
`app/services/place_map_admission.py`의 `PlaceMapGate`를 거친다.

- 동시에 DB 계산을 하는 요청은 `PLACES_MAX_RUNNING`(기본 4)건이다. 슬롯을 기다리는 요청은 첫 SQL 전이라 풀 연결을
  쥐지 않는다. 대기열이 `PLACES_MAX_WAITING`(기본 8)건으로 차면 기다리게 하지 않고 즉시 429 + `Retry-After: 2`를
  낸다(교통 통계 입장 거절과 같은 코드). 거절 경고 로그는 10초에 한 줄이며 그 사이 거절 건수를 함께 남긴다.
- 같은 정규화 요청(FastAPI가 해석한 query 값 전체)은 리더가 **아직 슬롯을 기다리는 동안에만** 합류해 결과를
  함께 받는다. 이미 읽기를 시작한 계산에는 합류하지 않으므로, 합류한 요청도 자기 도착 시각 이후의 snapshot을 본다.
- 도착부터 `PLACES_DEADLINE_SECONDS`(기본·상한 25초, gateway·관리 BFF 30초보다 짧다) 안에 끝내지 못하면 계산을
  취소·rollback하고 504 + `Retry-After: 10`을 낸다. 리더가 슬롯을 기다리다(계산 시작 전) 시한을 넘기면 합류한
  요청은 리더의 504를 받지 않고 자기 시한으로 다시 판단한다. 리더가 계산 중에 시한을 넘기면 같은 계산을 기다린
  요청도 같은 504를 받는다.
- 서버 쪽에도 transaction마다 `SET LOCAL statement_timeout`을 두며 값은 transaction 시작 때 남은 시한(ms)이다.
  PostgreSQL은 이 상한을 문장마다 그 문장의 시작부터 재므로, 첫 문장은 전체 시한에 끝나고 같은 transaction의
  뒤 문장은 transaction 시작 뒤 흐른 시간만큼 넘길 수 있다. 전체 시한은 asyncio 시한이 문장을 클라이언트 쪽에서
  취소해 지키고, 서버 상한은 그 취소가 닿지 않을 때의 안전판이다. 다른 경로의 엔진 상한(120초)은 바꾸지 않는다.
- 클라이언트(관리 BFF·공개 gateway)가 연결을 닫으면 `receive()`의 `http.disconnect`로 알아채 대기열 자리나 계산을
  취소한다. 기록 상태는 499다. 합류한 다른 요청이 결과를 기다리는 리더는 계산을 이어 가되, 합류한 요청까지
  모두 떠나면 그때 취소한다. 관리 BFF는 브라우저의 `request.signal`을 upstream fetch에 전달한다(공개 유가 BFF와 같다).
- 유가 단독·다중 종류 PostgreSQL 경로는 모든 SQL을 끝낸 뒤 `session.close()`로 연결을 반납하고 나서
  `fuel_map_limiter`(2)를 기다려 thread 검증한다. 이전에는 limiter를 기다리는 동안과 검증하는 동안 연결을
  idle-in-transaction으로 쥐었다. 검증 중 요청이 끊기거나 시한을 넘겨도 thread는 멈출 수 없으므로 limiter 토큰은
  thread가 끝날 때 반납한다(`run_in_thread_holding`, 결과는 버린다). 끊김이 잦아도 동시 검증 thread는 2개를 넘지
  않는다. 이때 gate 슬롯은 먼저 풀려 다음 요청이 DB 읽기를 시작할 수 있다(연결은 이미 반납했다).
- 검증 항목 LRU(8개·8MiB)와 revision 증명 페이지 LRU(16개·24MiB)는 예산을 따로 쓴다. 공개 유가 검증 항목이
  관리 `/map` 페이지를 밀어내지 않는다. 항목 예산을 넘는 큰 입력(limit 5000 공개 유가 등)은 저장하지 않는다.
- OpenAPI는 places의 429·504에 `Retry-After` header를 적고, 공개 fuel gateway는 다른 출처 화면이 읽을 수 있게
  `Access-Control-Expose-Headers`에 `Retry-After`를 둔다.

### 화면의 재조회 (관리 `/map`·`/fuel`·`/flights`·역/항구 목록, 공개 유가)

- `lib/place-retry.ts`: 429·503은 `Retry-After`가 5초 이하일 때(없으면 1초) 같은 범위·필터로 한 번만 자동
  재조회한다. 504는 `Retry-After`가 5초 이하로 있을 때만 다시 묻는다. `Retry-After` 없는 504는 BFF·gateway가 30초를
  기다린 끝이고, backend 시한 초과(`Retry-After: 10`)는 25초를 쓴 계산이라 자동으로 되풀이하지 않는다. 대기는
  `Retry-After`를 최소로 지키고 그 절반까지 비례해 흩뜨린다. 범위·필터가 바뀌거나 화면을 떠나면 재조회하지 않는다.
- 재조회를 기다리는 동안 지도는 "조회 중"이다. **지도 이동(같은 필터)** 중이면 이전 범위 결과가 그대로 보이지만,
  필터·종류를 바꿨거나 목록 보기이면 이전 결과는 이미 비운 상태다.
- 두 번째 실패와 시한 초과는 실패 안내에 backend의 한국어 안내(혼잡·범위를 좁히라는 안내)를 함께 보이고,
  `Retry-After`가 지나기 전에는 "다시 조회"(공항 목록 다시 조회·저장 정보 새로고침)를 막는다.

입장 제한 값은 운영 동시성 측정 없이 풀 크기(5+5)와 다른 경로 몫을 기준으로 정한 초기값이다. 거절·시한·끊김은
`places_admission_rejected`·`places_deadline_exceeded`·`places_client_disconnected` 로그로 남는다. 운영 적용 뒤
이 로그와 Server-Timing으로 값을 다시 판단한다.

### 관리·공개 몫 나누기 (2026-11-24 PR #273 후속)

공개 요청과 관리 화면이 gate 하나를 나눠 쓰면 익명 공개 요청이 관리 `/map`을 굶길 수 있었다. 이제 `PlaceMapGate`는
요청을 `admin`·`public` 두 줄로 나눈다.

- **관리 판정의 진짜 문은 파생 증명이다.** 관리 BFF(`app/api/transport/[...path]/route.ts`)는 places GET에만
  `x-transport-places-lane: HMAC-SHA256(TRANSPORT_ADMIN_WRITE_TOKEN, "places-admin-lane")`(hex)을 붙여 loopback
  backend(:12302)로 보낸다. 쓰기 토큰(백업 복원까지 할 수 있다) 자체는 지도 조회 경로에 싣지 않는다. 토큰이 32자
  미만이면 BFF는 아무것도 보내지 않는다(다른 관리 경로와 같은 조건). backend는 같은 값을 계산해 상수 시간으로
  비교한다. 증명은 새 env 없이 쓰기 토큰에서 만든다.
- **함께 요구하는 조건**(공개로 내리기만 한다): ASGI peer가 loopback이고, `Forwarded`·`X-Forwarded-For` header가
  없고(gateway를 거치지 않은 직접 호출 — `fuel_manual_refresh.py`의 private access와 같은 방식), `x-transport-listener`
  표지가 없어야 한다. 공개 transport gateway(:12301 → `X-Forwarded-For` 추가), 공개 fuel gateway(:12307), 공개
  parking-radar BFF(:12303 `frontend/src/app/api/backend/[...path]/route.ts`)는 모두 `x-transport-listener: public`을
  덮어쓴다(nginx `proxy_set_header`, BFF는 허용한 header만 새로 만든다). 이 표지·forwarded header는 공개로
  내리기만 하므로 클라이언트가 꾸며도 얻는 것이 없다. 증명 없이 :12302를 직접 부르는 요청도 공개다.
- **몫**: 동시 계산 전체 `PLACES_MAX_RUNNING`(4) 가운데 공개는 `PLACES_MAX_RUNNING - PLACES_ADMIN_RESERVED_RUNNING`
  (기본 3)건까지 쓴다. 관리는 공개가 기다리지 않으면 `PLACES_MAX_RUNNING - 1`(3)건까지, **공개가 기다리는 동안에는
  `PLACES_ADMIN_RESERVED_RUNNING`(1)건까지만 새로 시작한다.** 그래서 어느 쪽이 몰려도 다른 쪽은 최소 한 슬롯으로
  나아간다(관리 목록 8건 폭주에도 기다리는 공개 요청이 관리 두 물결을 기다려 시한을 넘기지 않는다 —
  `test_admin_burst_does_not_starve_waiting_public_requests_past_the_deadline`). 대기열은 줄마다 따로 센다 — 공개
  `PLACES_MAX_WAITING`(8), 관리 `PLACES_ADMIN_MAX_WAITING`(4). 슬롯이 비면 위 상한 안에서 관리 대기 요청을 먼저
  깨운다(줄 안에서는 도착 순). 대기 중 합치기는 줄 안에서만 한다.
- **설정 경계**: `PLACES_ADMIN_RESERVED_RUNNING >= PLACES_MAX_RUNNING`(동시 2건 이상일 때)은 조용히 줄이지 않고
  설정 검증이 기동을 거절한다. 동시 1건 설정이면 몫을 남기지 않고 관리·공개가 한 슬롯을 나눈다. 토큰을 설정하지
  않았거나 32자 미만이면 관리 줄이 없고 남겨 둔 몫도 0이다(공개가 4건 모두 쓴다). 기동 때
  `places_admission_configured max_running=… public_max_running=… admin_reserved=… admin_lane=enabled|disabled …`
  한 줄로 실제 적용된 값을 남긴다.
- **배포 순서**: backend가 먼저 새 판정으로 올라가고 관리 웹(transport-admin-web)이 아직 옛 이미지면 관리 화면은 증명을
  보내지 않아 공개 몫을 쓰고, 남겨 둔 1슬롯은 그동안 쉰다(공개는 3건). 관리 웹을 backend와 같은 배포(또는 바로 뒤)에
  올린다. 관리 웹만 먼저 올라가면 옛 backend가 모르는 header라 무시한다(지금과 같다).
- **로그**: `places_admission_rejected`·`places_deadline_exceeded`·`places_client_disconnected`에 `lane=`이 붙는다.
  거절 경고 간격(10초)은 줄마다 잰다 — 공개 거절이 쏟아져도 관리 거절 한 줄은 바로 남는다.
- **공개 쪽 클라이언트별 공정성은 하지 않았다.** nginx `limit_conn`을 IP별로 두려면 진짜 클라이언트 IP가 필요한데,
  공개 gateway 앞에는 HAProxy(OPNsense)가 있어 `$remote_addr`가 모든 클라이언트에 같고, fuel gateway는
  `X-Forwarded-For`를 비운다. `real_ip`로 HAProxy의 XFF를 믿으려면 HAProxy 주소·XFF 설정을 운영에서 확인해야 해서
  이 변경에 넣지 않았다. 그 확인 없이 `$remote_addr` 기준으로 걸면 모든 공개 사용자를 연결 몇 개로 묶는다.
  공개 줄 안의 공정성은 지금 대기열 상한(8)과 대기 중 동일 요청 합치기가 맡는다.
  2026-11-25 재조사(MAP-CALL-FOLLOWUPS): HAProxy 설정은 어느 저장소에도 없다(Manager `prod-deployment.md` §9.4
  "OPNsense, 저장소 밖", `multi-host.md` "저장소 밖 손 설정"). 버전 관리되는 근거는 관측된 peer `192.168.1.1`
  (`docs/fuel-mcp.md`, `runbooks/request-timing-logs.md` 로그 예)과 Manager 문서의 한 줄 전제("weather web은 HAProxy의 XFF strip+append 전제")뿐이다.
  transport·fuel frontend의 `option forwardfor`·기존 XFF 제거 여부, `send-proxy` 사용 여부, `192.168.1.1`에서 XFF 없이 오는
  다른 트래픽(NAT reflection 등)이 있는지는 운영 확인이 필요하다. 그래서 `real_ip_from`·IP별 `limit_conn`/`limit_req`는
  넣지 않았다. 운영자 확인 절차는 `docs/tasks.md` MAP-CALL-FOLLOWUPS 항목에 있다.

### 25초 시한과 앞단 30초 여유

관리 BFF(`lib/upstream.ts` 30초)와 공개 gateway(`proxy_read_timeout 30s`)보다 backend 504가 먼저 나가야 화면이
backend 안내(`Retry-After: 10`)를 받는다. 여유를 깨뜨릴 수 있는 것과 처리:

- **thread 검증**: 멈출 수 없지만 `run_in_thread_holding`이 thread 완료를 `asyncio.shield`로 기다리므로 시한 취소는
  thread를 기다리지 않는다. 504는 시한에 바로 나가고 thread는 limiter 토큰을 쥔 채 끝까지 돈 뒤 반납한다
  (`tests/test_places_lanes_and_deadline.py`: 시한 0.05초 전에 시작한 thread가 시한을 넘겨 돌아도 504가 시한 +
  0.35초 안에 나온다).
- **시한·끊김 뒤 rollback**: 서버가 응답하지 않으면 끝없이 기다릴 수 있었다. 이제 시한 경로와 끊김(499) 경로 모두
  `TIMEOUT_CLEANUP_GRACE_SECONDS`(2초) 상한을 두고, 시한 경로는 넘기면 `places_timeout_cleanup_slow`를 남기고 504를
  낸다. 최악은 25 + 2 = 27초다. 문장 도중 취소된 연결은 SQLAlchemy가 무효화해 풀에 되돌리지 않는다(실제 풀 1개
  PostgreSQL 시험: 시한·끊김·rollback 상한 세 경로 모두 무효화 1회, 다음 요청은 새 연결로 성공, `checkedout() == 0`).
- **event loop 위 동기 작업**: 시한 취소는 loop가 돌아야 실행된다. places 본문의 `to_json`·pydantic 직렬화와 다른
  요청의 동기 작업은 그만큼 504를 늦춘다. 이 몫은 측정으로만 확인할 수 있어 아래 로그를 둔다.
- `places_deadline_exceeded`의 `elapsed_ms`는 **handler 진입**(입장 장식자가 시한을 정한 순간)부터 504를 정한
  순간(rollback 포함)까지다. 미들웨어·의존성 해석·응답 직렬화·앞단까지의 시간은 빠지므로 `proxy_margin_ms`(30초까지
  남은 여유)는 **가장 좋은 경우**의 값이다. 끝단 전체 시간은 응답의 `Server-Timing: app;dur=`와
  `slow_request ... status=504 duration_ms=`(미들웨어 기준)로 본다.

**운영 확인(읽기 전용, Odroid)** — 배포·재기동 없이 로그만 읽는다(`docs/runbooks/remote-command-safety.md`):

```bash
# 최근 하루 시한 초과의 lane·경과·여유(handler 진입 기준, 가장 좋은 경우). 여유가 2000 아래면 시한·상한을 다시 본다.
docker logs --since 24h kor-travel-transport-backend-1 2>&1 \
  | grep places_deadline_exceeded \
  | sed -E 's/.*lane=([a-z]+).*elapsed_ms=([0-9]+) proxy_margin_ms=(-?[0-9]+).*/\1 \2 \3/' \
  | sort -k2 -n | tail -5
# 미들웨어 기준 places 504 응답 시간(앞단 30초에 가까우면 gateway가 먼저 502/504를 냈을 수 있다)
docker logs --since 24h kor-travel-transport-backend-1 2>&1 \
  | grep -E 'slow_request route=/v1/transport/features/places status=504' \
  | grep -oE 'duration_ms=[0-9.]+' | sort -t= -k2 -n | tail -5
# rollback 상한을 넘긴 횟수와 줄별 거절 수, 기동 때 적용된 몫
docker logs --since 24h kor-travel-transport-backend-1 2>&1 | grep -c places_timeout_cleanup_slow
docker logs --since 24h kor-travel-transport-backend-1 2>&1 | grep places_admission_rejected \
  | grep -oE 'lane=[a-z]+' | sort | uniq -c
docker logs kor-travel-transport-backend-1 2>&1 | grep places_admission_configured | tail -1
```

판단: `elapsed_ms`가 25,000 근처(± 수백 ms)이고 504 `duration_ms`도 그 근처이며 `places_timeout_cleanup_slow`가 0이면
여유(약 5초)가 지켜진다. `duration_ms`가 27,000을 넘거나 gateway access log에 places 504/502가 backend 기록 없이
보이면 loop 정체를 의심하고 `PLACES_DEADLINE_SECONDS`를 낮춘다. `admin_lane=disabled`이면 운영
`TRANSPORT_ADMIN_WRITE_TOKEN`(32자 이상)을 확인한다.

## API 기동 warmup(2026-11-24)

감사 RT-06·RT-13·G2-09·G3-10. 기동 warmup은 `app/services/startup_warmup.py` 한 task로 순서를 둔다. lifespan은
yield 전에 task만 만들고 아무것도 기다리지 않는다(포트 개방을 늦추지 않는다).

1. 풀 채우기 — `pool_size` 중 비어 있는 만큼 **동시에** checkout해 `SELECT 1`을 하고, 모두 checkout(또는 실패)할
   때까지 쥔 뒤 함께 돌려준다. 하나씩 열고 바로 돌려주면 같은 연결을 재사용해 풀에 하나만 남는다. 3초 상한, 실패는
   무시한다. 이미 요청이 연결을 쓰고 있으면(기동 직후 burst) 아무것도 하지 않는다. 쥐는 시간은 보통 수십 ms이고,
   그동안 들어온 요청은 overflow 연결(`max_overflow` 5)을 쓴다. 시험 DB 모드 엔진(NullPool)에서는 no-op이다.
2. 입력 지문 memo — Map이 읽는 T3인 철도역 → 여객선 터미널을 하나씩(종류별 10초, 읽기 전용 RR).
   bus-terminals·parking/current는 Map 소비자가 없어 데우지 않는다.
3. 위 둘이 끝나면 주차 이력 캐시 첫 구성을 시작한다(이력 구성 CPU가 첫 export와 겹치지 않게). 지연은 보통 수 초,
   최악 약 23초(풀 3초 + 지문 10초×2)이고 안전 상한은 30초다. 그 사이 `/parking/history`는 캐시 없이 직접 SQL
   (무거운 대체 경로)로 응답한다.

끝나면 `{"event": "startup_warmup", "pool_prefilled": n, "kinds": [{kind, status, duration_ms}], ...}` 한 줄을
**WARNING**으로 남긴다(성공도 남겨 'warm 실패'와 'warm 전 도착'을 가른다). API는 app logger에 handler·level을 두지
않고(uvicorn은 자기 logger만 설정) Python 기본 lastResort가 WARNING 이상만 내므로, INFO로는 운영 로그에 남지 않는다.
배포 직후 본문 자체의 준비와 서빙 프로세스의 loopback warm은
[배포 런북](../runbooks/deployment.md#배포-직후-best-effort-warm기준정보-본문-준비loopback-export-확인-2026-11-24)을 따른다.

## 기준정보 본문 오프라인 준비의 격리·상한·정리(2026-11-24)

`prepare_reference_exports`(수집 job 꼬리의 op, 전용 준비 job, 주소 갱신 뒤, 배포 직후)는 HTTP 첫 페이지의 대체
경로다 — 준비가 없거나 실패해도 첫 페이지가 같은 입력으로 같은 본문을 만든다. 그래서(감사 T23-04·T23-05·T23-12·
WLH-04):

- **종류별 격리와 순서** — Map이 읽는 철도역·여객선을 먼저, 이어 버스·주차 순으로 한다. 한 종류의 실패
  (membership 불일치·상한 초과·DB 오류)가 다른 종류의 준비를 막지 않는다. 결과는 종류별
  `{kind, status, duration_ms, item_count, error_type, sqlstate, reason}`이다.
- **전체 예산 하나** — 모든 종류·경합 재시도·정리가 예산 하나를 나눠 쓴다(종류·재시도마다 새로 시작하지 않는다).
  전용 job·배포 직후·주소 갱신 뒤는 120초, 수집 job 꼬리(5분 공항 수집 등)는 60초다 — 꼬리가 길면 run이 STARTED로
  남아 coalescing schedule이 주차 tick을 버린다. 호출자는 run deadline(전용 job은 180−60초)보다 10초 먼저 끝나게
  더 줄인다. 남은 예산이 5초 미만이면 그 종류는 시작하지 않고 `deferred`, 예산 끝에서 난 구성 상한·statement
  timeout도 `deferred`다. 문장·잠금 상한(60초·5초)도 남은 예산보다 길지 않게 줄인다. HTTP 첫 페이지는 그대로
  15초·10초·2초다(Map 응답 시간).
- **경합은 실패가 아니다** — 같은 본문을 다른 준비(배포 직후 준비·다른 수집 job)나 첫 HTTP 페이지가 만들고 있으면
  잠금 대기(55P03)·교착(40P01)·RR 직렬화 실패(40001)·admission/head CAS 경합(SnapshotRace)이 난다. 0.3~1초 뒤 새
  transaction으로 한 번 다시 보고(대개 그사이 끝난 본문을 재사용한다), 그래도 겹치면 그 종류는 `busy`다. busy는
  실패·부분 완료가 아니라 이월(`REFERENCE_EXPORT_BUSY`)로 남기고 run 태그 `kortravel/reference-export-busy`에 종류를
  적는다. 같은 job에서 같은 종류가 **연속 3회** busy면(5분 공항 수집이면 약 15분) 버려진 잠금(idle in transaction 세션
  등)을 의심해 실패로 올린다.
- **결과 표시** — Dagster metadata는 `reference_status`(최상위 `status`는 쓰지 않는다 — 관리 콘솔이 "저장 결과: 실패"로
  읽는다)와 `failed_kinds`·`busy_kinds`·`deferred_kinds`, 수, `error_code`를 남긴다. 일부 실패는 부분 완료
  (`REFERENCE_EXPORT_PARTIAL`), 전부 실패는 전용 `reference_export_prepare_job`에서만 run 실패이고 수집 job 꼬리·주소
  갱신 뒤에서는 부분 완료(`REFERENCE_EXPORT_FAILED`)다 — 수집은 이미 commit됐고 첫 export 요청이 본문을 직접
  구성한다. 예산 소진·원천 미완결은 이월(`REFERENCE_EXPORT_DEFERRED`). 관리 콘솔은 이 코드들과 종류 이름을 고정 문구로
  보인다. 회수된 실행(`CollectionLeaseLost`)·run 상한·취소는 그대로 step을 끝낸다.
- **제한 정리** — 준비 뒤 남은 예산 안에서 만료 handle을 먼저(그 handle이 붙든 옛 본문을 풀어 준다), 이어 미사용
  본문을 묶음마다 commit하며 최대 50개·10초까지 지운다. 정리 실패·경합은 준비 결과를 바꾸지 않는다(`gc_error_type`·
  `gc_busy`·`gc_skipped` metadata).
- **요청 경로 정리는 읽기를 실패시키지 않는다** — HTTP 첫 페이지의 GC(`expire_snapshots`·`collect_unused_artifact`)는
  savepoint 안에서 돈다(`export_current.gc_quietly`). 요청이 RR snapshot을 잡은 뒤 준비의 대량 정리가 같은 만료
  handle을 지우고 commit하면 `FOR UPDATE`가 40001을 내는데, 그 정리만 되돌리고 읽기·handle 발급을 잇는다.

관리자 좌표 보정·KRIC 매핑 저장 뒤 영향 종류를 API 프로세스에서 즉시 준비하는 것은 하지 않는다. 본문 구성은 CPU
작업이라 API event loop를 수 초 막고, 5분 공항 수집의 준비 step이 다음 주기에 같은 본문을 만든다.

## 기준정보 본문 코드 지문(2026-11-25)

ADR-016 결정 갱신. 입력 revision namespace의 배포 식별자가 `RELEASE_SHA`에서 본문 코드 지문
(`export_references.REFERENCE_PAYLOAD_FINGERPRINT`, `app/services/reference_payload_fingerprint.py`)으로 바뀌었다.

- **무효화 범위** — 전에는 배포마다(같은 코드의 재배포·문서만 바뀐 배포 포함) rail·ferry·bus·parking 본문이 모두
  무효가 되어, 배포 직후 준비나 첫 Map 페이지가 전체를 다시 구성했다(감사 WLH-03·MC-07). 이제는 `PAYLOAD_CODE` 모듈
  (`export_references`·`export_addresses`·`rail_station_mapping`·`app.core.time_utils`·`reference_artifacts`·
  `reference_export_revision`)의 전체 소스, builder 모듈의 단순 상수, 네 page model의 JSON schema, 형제 라이브러리·
  pydantic·pydantic-core·SQLAlchemy·asyncpg 버전/commit, Python major.minor 중 하나가 바뀐 배포만 무효로 만든다. 그 밖의
  배포에서 배포 직후 준비는 `reused`이고 첫 Map 페이지는 기존 본문의 새 handle만 발급한다. 모듈 단위라 조회 경로만 바뀐
  배포도 다시 만든다(덜 무효화되어 낡은 본문을 내는 것보다 싸다). builder에서 닿는 `app.*` 코드가 지문 밖이면 시험이
  실패한다(ADR-016 범위 가드).
- **조건부 응답** — ETag semantic(`reference-page-v3`)에 지문 구성 방식과 지문을 넣어, 지문이 바뀐 배포에서 옛 ETag로
  304를 내지 않는다.
- **skew** — API와 code-server의 `RELEASE_SHA`가 달라도(한쪽만 `unknown` 등) 코드가 같으면 같은 namespace라 head를
  서로 덮어쓰지 않는다. `RELEASE_SHA` 없이 띄운 컨테이너도 artifact 경로·기동 warmup(`main.py`의 조건은 Map current
  활성 + 지문 있음)·오프라인 준비를 쓴다.
- **비용** — 지문은 import 때 한 번 계산한다(소스 읽기 + schema 4개 + metadata 6개, 수십 ms). 요청 경로 비용은 그대로다
  (입력 지문 memo 키의 한 값이 바뀌었을 뿐이다).
- **이전** — 처음 배포될 때 namespace 값(`reference-input-v2`)이 한 번 바뀌어 모든 본문을 한 번 다시 만든다(배포 직후 준비,
  다음 공항 수집 준비, 첫 Map 페이지 중 하나). 옛 본문은
  남은 handle이 만료된 뒤 기존 GC가 지운다.
- **안전장치·저하 표시** — 지문을 만들 수 없으면(소스 없는 이미지) artifact 없는 완전 구성 경로로 간다(정확하지만 느리다).
  `/health`의 `reference_artifacts: "disabled"`·`reference_payload_fingerprint: null`, 기동 WARNING 로그로 드러난다. 읽을
  때의 page model 재검증은 그대로다.
- **해시 입력의 세부(ADR-016에서 옮김)** — import 때 한 번 sha256으로 계산한다. 모듈은 함수 단위 허용 목록이 아니라
  전체 소스(`export_references.PAYLOAD_CODE`)다. 단순 상수는 `export_references`의 source 이름·batch 크기 등 유한 float만
  (dunder 제외), page model schema는 `BusTerminalExportPage`·`FerryPortExportPage`·`RailStationExportPage`·
  `ParkingCurrentExportPage`의 `model_json_schema()`(중첩 `ExportAdminAddress`·`ServiceExportMeta` 포함)다. 의존성은
  `kor-travel-common`·`python-krairport-api`·`pydantic`·`pydantic-core`·`sqlalchemy`·`asyncpg`의 설치 버전과 VCS commit
  (`direct_url.json`)이고, commit이 없는 경로/editable 설치(개발 환경)는 형제 라이브러리의 해당 모듈 소스를 해시한다.
  소스는 `inspect.getsource`(universal newline)로 읽어 설치 경로·줄바꿈·hash seed와 무관하다. namespace 표지는
  `reference-input-v2`, 지문 구성 방식은 `FINGERPRINT_SCHEME`(`reference-payload-code-v2`)이다.
- **범위 가드 세부** — `test_reference_payload_fingerprint.py`가 각 `reference_specs()`의 `payload_batches`·
  `prepare_artifact`·`reference_payload_revision`에서 `co_names`를 따라 닿는 `app.*` 함수·모듈을 재귀로 모아,
  `PAYLOAD_CODE`에 없고 사유가 적힌 제외 목록(`app.models`=열 값은 DB 입력 revision이 봄, `app.schemas`=page schema로 봄,
  `app.core.problems`·`app.core.read_timing`·`app.services.export_current`=오류·계측·배관)에도 없으면 실패한다. 모든
  spec의 builder 모듈과 page model이 지문 안에 있는지도 확인한다. 지문 입력 밖에서 envelope를 바꾸면
  `reference-page-vN`을 올린다.
- **배포 직후 준비의 대조** — `/health`의 `reference_payload_fingerprint`를 `scripts/post-deploy-warm.sh`가
  `app.deploy.prepare_references --expect-payload-fingerprint`로 넘긴다. code-server 지문이 다르면 exit 4
  (`fingerprint_mismatch`), 지문을 못 만들면 exit 6(`fingerprint_unavailable`), 플래그를 모르는 옛 code-server 이미지는
  argparse exit 2다. `RELEASE_SHA` 대조는 없앴다(운영 절차는 배포 런북).
- **v1/v2 공존** — 옛 code-server(v1)와 새 API(v2)가 잠깐 함께 돌면 서로 다른 namespace로 head를 짧게 주고받을 수 있다
  (정합성은 그대로, 두 쪽이 같은 이미지가 되면 멈춘다).
- **검증** — `tests/test_reference_payload_fingerprint.py`: builder·모듈 소스·schema·의존성 버전/commit·editable 소스·
  Python 버전·상수가 바뀌면 지문이 바뀐다. 다른 프로세스·hash seed·`RELEASE_SHA`에서 같은 값이다. 지문이 다르면
  artifact를 재사용하지 않고 ETag도 바뀐다. 같은 지문이면 `RELEASE_SHA`가 달라도 재사용한다.

## 유가 통계 시군구 페이지와 장기 추이(2026-11-26)

`/v1/transport/fuel/statistics?scope=sigungu`는 운영 공개 GET에서 1.7~3.4초였다(응답 없는 유종도 2.6~3.0초). 현재 범주 읽기가 기본키
skip scan으로 230개 범주마다 색인을 다시 찾는 것이 원인이라고 추정한다(운영 EXPLAIN 미확인, 배포 뒤 확인). 0050 인덱스 `(source, scope, day, product_code)` 뒤 400일 합성 데이터에서 Index Searches
461→1, 공유 버퍼 3,494→361(B027). 장기 추이는 좁은 표 `fuel_statistics_history`만 읽는다(유종당 최대 400점, 로컬 16~29ms). 측정·원인·한계는
[유가 통계](../fuel-statistics.md#통계-페이지-시군구-읽기-2026-11-26), 측정 스크립트 `backend/tests/benchmarks/fuel_statistics_page.py`.

### 한글 범주 키 정렬 collation(2026-11-28)

0050 뒤에도 실제 유종(B027·D047·K015) 시군구는 0.9~1.8초(TTFB)였다. 운영 transport DB(PostgreSQL 18.6 aarch64, 기본 collation
libc `en_US.utf8`)의 읽기 전용 진단에서 인덱스 스캔은 1~25ms인데, 한글 JSON 배열 `scope_key` 230개를 정렬하는 노드(`DISTINCT`의
Sort→Unique, `min()`, 최종 `ORDER BY`)가 대부분이었다. 같은 키 230개 정렬이 기본 collation 0.65~2.4초, `COLLATE "C"` 43ms였다.
계획 비용은 약 204라 `jit_above_cost`(100000)에 한참 못 미치고 EXPLAIN에 `JIT:` 절이 없었다. JIT는 원인이 아니었다(JIT-OFF는
무해해서 그대로 둔다). 페이지 쿼리는 정렬과 기본 범주 최솟값만 `COLLATE "C"`로 하고 `DISTINCT`를 없앴다. 같음 비교는 기본
collation 그대로라 색인 사용은 같다. 한글 음절은 코드포인트가 가나다순이라 목록·기본 범주가 가나다순이 된다(예전 en_US 순서는
"전남광주통합특별시 강진군"이 맨 앞이었다). 다른 쿼리도 한글 텍스트를 대량 정렬하면 같은 처리를 검토한다.
