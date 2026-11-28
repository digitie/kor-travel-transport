# 시각과 수집기 기준

## 통합 교통정보 수집

이 저장소의 목적은 공항 주차만 보여주는 데 있지 않다. 국내 여행 중 필요한 고속도로,
유가, 열차·도시철도·항구·배편·TAGO 버스 터미널 데이터를 주기적으로 수집해 PostgreSQL에
보존하고, 저장된 값은 외부 OpenAPI와 내부 통계 API가 즉시 읽도록 하는 것이다.

현재 구현 범위:

- `python-krex-api`: 고속도로 실시간 소통과 돌발을 transport scheduler 기본 주기로 저장
- `python-opinet-api`: 최신 Playwright 지역별 화면 수집기로 주유소/유종 가격/편의정보를
  저장. 현재 pin된 provider의 기본 전체 실행은 8시간이며 허용 범위는 8~12시간,
  24시간 내 최대 3회다. 매 scheduler tick마다 재실행하지 않는다.
- `python-krex-api`: 전국 휴게소 기준정보를 `rest_area_reference_collection_job`으로
  3일에 한 번만 저장한다. 기준정보는 OpenAPI가 아닌 저장 DB에서 지도·Map/PinVi place
  조회에 사용하며, job은 `REST_AREA_REFERENCE_COLLECTION_ENABLED=true`일 때만 외부
  provider를 호출한다.
- `/v1/transport/highways/traffic`, `/v1/transport/highways/incidents`,
  `/v1/transport/fuel/stations`: PostgreSQL 최신/기간 데이터 조회
- `/v1/transport/statistics`: 저장 데이터에서 평균 속도, 돌발 건수, 유종별 가격 통계 계산
- `/v1/transport/collector-status`: 소스별 수집 상태와 마지막 실행 결과/오류 확인
- TAGO 고속·시외버스 터미널은 Dagster가 매일 due를 평가하되 마지막 성공 뒤 72시간이 지난 경우에만
  저장하며,
  `/v1/transport/bus/timetable`은 저장하지 않는 실시간 조회만 제공한다.

통합 수집 실행은 기존 주차 수집과 별도 `CollectionRun.trigger=transport_scheduler`를
사용한다. 따라서 기존 주차 dashboard의 최근 실행/신선도 집계에 섞이지 않는다. 소스별
실행 상태는 `transport_collection_states`로 기록하며 실패 시 원본 오류도
`raw_api_responses`에 남긴다. API는 외부 원본을 매 요청마다 호출하지 않는다.
실행 transaction이 DB flush 단계에서 rollback되더라도 실패한
`CollectionRun(trigger LIKE 'transport_%')`을 별도 transaction으로 보존한다.
`collector-status.last_run`은 이 durable 실행 결과와 안정적인 오류 표지(`collection_failed`, 무효 행 격리만 있는
부분 성공은 `rows_isolated` — 아래 "무효 행 격리의 상태 표시")만 외부에 노출해, 이전 성공 상태를 현재 성공으로 오인하지 않게 한다.

오피넷은 병합된 provider `8708f10`의 60초 화면 대기 상한을 transport 설정과 Compose에도
동일하게 전달한다. 정기 실행은 8시간 tick이다. 다만 실패한 시도는 유가 op의 일시 오류 자동 재시도(1회)와 관리자
"재시도"로 예정 전에 다시 시작할 수 있어 24시간 안 시작 횟수가 3회를 넘을 수 있다(아래 "수집 예약과 조회 시간 상한").
대기 상한 변경은 수집 성공을 뜻하지 않으며 다음 정기 배치의 실제 저장 결과를 따로 확인한다.

여객선 시간표는 네트워크 오류 1건으로 전국 보충을 중단하지 않는다. 실패한 항구·날짜는
빈 성공 스냅샷으로 저장하지 않고 다음 대상으로 진행한다. 실패도 280회 호출 예산에 포함하며
배치 전용 `FERRY_TIMETABLE_COLLECTION_INTERVAL_SECONDS=2` 간격을 유지하고,
3회 연속 네트워크 실패면 중단한다. 인증·quota·파싱 오류는 즉시 중단한다.
호출은 병렬화하지 않으며 이전 요청 완료 후 최소 간격을 둔다. 사용자 실시간 조회의
`FERRY_TIMETABLE_MIN_INTERVAL_SECONDS=30`은 별도다. 30초는 공식 의무가 아니라 PR #37의
공개 조회 보호 설정이었고 PR #40에서 배치에도 재사용됐다. 배치 기본값을 2초로 분리해도
실행당 280회·4시간 주기는 늘리지 않는다(정기 배치 기본 최대 1,680회/일, 실시간 조회 별도).
호출 수 설정도 최대 280으로 제한해 간격을 줄여 호출 총량의 허용 상한이 커지지 않게 한다.
이는 키별 일일 quota를 공유 집계하는 제한기가 아니며 실제 승인 한도는 따로 확인해야 한다.
[공식 안내](https://www.data.go.kr/data/15098523/openapi.do)는 개발계정 신청 가능 트래픽
10,000과 일일/초당 초과 오류를 안내하지만 30초 의무나 구체적인 초당 허용값은 명시하지 않는다.
2초는 제공기관 보장이 아닌 조정 가능한 운영 기본값이다. 제한 응답을 반복 재시도하지 않는다.
일부 네트워크 실패가 있었으면 `partial_success`와 `failed_provider_calls`를 기록하므로 운영 화면에서
전체 성공으로 보이지 않는다. 실패한 날짜는 다음 정기 실행에서 미수집으로 다시 선택된다.
DB 커밋 뒤 Dagster op도 명시적인 실패로 종료한다. 이 실패의 자동 재시도는 비활성화해
수집 간격·호출 예산을 우회하지 않는다.

운영 live E2E는 수집·scheduler 활성화와 `client_mode=live`, 세 소스 모두의 최근 완료를
요구한다. `last_success_at >= last_started_at`과 오류 없음으로 각 소스의 최신 시작이
실제 저장 성공으로 끝났는지 확인한 뒤 API·통계를 새로 읽는다. 소통은 15분, 유가는
13시간 이내 성공이어야 하며 소통 행·유효 유가·통계가 비어 있으면 통과하지 않는다.
소통 행의 `observed_at`과 `collected_at` 모두 15분 이내여야 하고 미래 시각은
60초의 시계 오차만 허용한다. 오래된 관측을 뒤늦게 저장해도 최신성 검증을 통과하지 않는다.
비활성/샘플/부분 성공은 운영 승인으로 취급하지 않는다. 변하지 않은 돌발의 중복 저장 생략은 가능하므로 돌발은
행 수 대신 소스별 최근 저장 완료를 검사한다. 전국 돌발 0건은 상류 이상으로 보고 성공으로 받지 않는다(2026-11-24,
ADR-013 개정 — 한 번 다시 조회해도 비면 실패, 마지막 성공 집합 유지).
결과 저장은 소스별 transaction으로 분리해, 뒤의 돌발/유가 저장 실패가 먼저 성공한
소통정보를 rollback하지 않도록 한다.

### 수집 예약과 조회 시간 상한(ADR-009 세부)

구조는 [ADR-009](../adr/009-durable-transport-collection-reservations.md)가 정한다(짧은 DB 예약 → 트랜잭션 밖 외부 조회 →
소스별 결과 transaction). 값과 규칙은 코드(`backend/app/services/transport_collection.py`,
`backend/app/dagster/definitions.py`)가 정본이고 아래는 2026-11-28 코드 기준이다.

- **조회 시간 상한**: 고속도로 소스별 120초(`HIGHWAY_FETCH_TIMEOUT_SECONDS`), 전국 유가 브라우저 수집 3.5시간
  (`FUEL_FETCH_TIMEOUT_SECONDS = 12_600`). 유가는 2026-09-19 ADR-009 당시 2시간이었고, odroid(ARM)에서 성공한 수집이
  5,946~6,371초 걸려 옛 상한 7,200초 근처에서 시간 초과가 반복되어 2026-10-23 소유자 결정으로 올렸다(ADR-013 개정).
  유가 상한은 저장·정리 여유를 두고 job 전체 상한과 Dagster run 상한(14,400초) 안에 들어야 한다
  (`test_fuel_fetch_timeout_fits_inside_job_budget`).
- **외부 호출 전 예약**: 고속도로 소스의 임시 예약은 시작 + (`2 × HIGHWAY_FETCH_TIMEOUT_SECONDS` + 15분)이고, 같은 실행에서
  유가도 due면 유가 조회 상한을 더한다. 유가 예약은 시작 + provider throttle이 정한 간격(`next_fuel_interval`, pin된
  provider 기본 8시간·허용 8~12시간) − 15분(`FUEL_NEXT_DUE_START_SLACK`)이다. 15분은 8시간 정각 tick보다 run 시작이 매번
  다르게 늦어 다음 tick이 "아직 이르다"로 건너뛰는 것을 막는 여유이고, Dagster 정기 실행은 여전히 8시간 tick(KST 00·08·16시)
  마다다. tick 없이 예정 시각까지 자는 in-process scheduler는 이 여유를 되돌려 기다린다(`next_collection_delay`).
- **고속도로 성공 뒤 다음 예정**: 정기 tick이 띄운 실행이면 그 tick 시각(`dagster/scheduled_execution_time`) + 주기 − 30초
  (`HIGHWAY_TICK_SLACK`), tick이 없는 실행(수동·in-process scheduler·관리자 재시도)은 시작 + 주기다(`_highway_next_due`).
- **유가 실패 재시도**: `collect(retry_failed_fuel=True)`는 직전 유가 시도가 **실패**였을 때만 예정 전이라도 실행하고, 정기
  예약(다음 tick)은 옮기지 않는다. 이 경로는 유가 op의 자동 재시도(`FUEL_RETRY_POLICY` — 같은 run 안 step 재시도 1회, 300초
  지수 backoff·jitter, `AUTO_RETRY_ERROR_CODES`인 브라우저 시간 초과·resource policy·DB 일시 오류만, run 상한에서 경과 시간과 재시도 대기 2×300초를 빼고도
  2시간 이상 남았을 때만)와 관리자 "재시도"(`kortravel/admin-retry-of` 태그)가 쓴다. 브라우저는 체크포인트에서 남은 지역만 요청한다.
  쿼터·차단·인증·파싱·전체 시간 초과는 자동 재시도하지 않는다.
- **quota backoff**: KREX quota 초과는 해당 소스의 다음 예정을 `transport_quota_backoff_seconds` 뒤로 미루고, 다른 고속도로
  소스가 due여도 backoff 중인 소스는 호출하지 않는다(due는 소스별로 판정).
- **상태 API**: `last_run`은 `skipped`를 제외해 재시작·경합의 무호출 기록이 실제 실패/실행 기록을 가리지 않게 한다.

### 고속도로 소통 저장 transaction과 5분 통계(2026-11-24, WLH-06)

운영 odroid에서 소통 source 저장 transaction(원본 + current + 최근 2시간 5분 통계 재구축 + 상태)이 175초를 넘겨
5분 주기의 대부분 동안 xid를 열어 두었다(vacuum horizon 고정, 한 문장이 수집 statement timeout을 넘으면 8,300행
source 전체 rollback). 단계별 계측은 없었다. 아래 변경은 통계 재구축을 원천 transaction 밖으로 빼고 단계별 시간을
남기지만 **175초 문제를 해결했다고 보지 않는다(WLH-06 열림)**. 로컬 측정(6시간 이력 약 60만 행, 응답 8,300행)에서
원천 transaction의 대부분은 `current_upsert`(15~17초)와 `history`(5초 안팎)였고, 이 변경으로 원천 밖으로 나간 몫은 약
2.4초(멈춘 구간 과거 bucket 재집계 약 2.0초 + 최근 창 재구축 약 0.4초)였다. 운영 배분은 배포 뒤 아래 단계별 시간으로
확인한다.

1. **원천 transaction**(한 번의 commit): 응답 원본(`raw_api_responses`), 관측 이력(`highway_traffic_snapshots`),
   current 승격, **이번 저장이 바꾼 bucket의 5분 통계**, 성공 표시(`last_success_at`·`next_due_at`·`last_error=NULL`).
   바뀐 bucket은 새로 넣은 관측과 통계 입력값(`route_no`·`direction`·`speed`·`free_flow_speed`)이 바뀐 관측의
   bucket이다. 그래서 원천 commit이 보이는 순간 그 원본의 통계도 이미 맞다. commit 전에 실패하면 원본과 그 통계가 함께
   rollback되고 source 오류만 기록한다(예전과 같다).
2. **재대조 transaction**(원천 commit 뒤, 돌발까지 확정한 다음): 최근 2시간 창을 원본 정본과 **차이 기반**으로 맞춘다
   (아래 "차이 기반 재대조"). 원천 transaction이 자기 bucket을 이미 맞췄으므로 정상 실행에서는 0행을 바꾼다. 바꾼 행이
   있으면 창 안의 어긋남(이전 실패·수동 수정·버그)을 원본 재계산과 같게 되돌린 것이고, 그 행 수를 어긋남으로 보고한다
   (경고 신호, 실패 아님 — 4번). 원천 상태 행은 이 결과로 바꾸지 않는다 — `last_success_at`은 원천 commit 시각의 성공이다.
   2시간보다 오래된 구간은 장기 복구(7번)가 하루 한 바퀴 맞춘다. 각 원천 commit이 자기 bucket을 함께 맞추므로, 재대조가
   계속 실패해도 정상 저장분의 통계가 원본보다 뒤처지지는 않는다.
3. **통계 잠금**: 성공 표시가 재대조보다 먼저 commit되므로 다음(수동·관리자) 고속도로 실행이 앞 실행의 재대조와 겹칠 수
   있다. 두 transaction이 같은 bucket을 함께 쓰면 `uq_highway_traffic_five_minute_statistics` 위반으로 한쪽 원천 전체가
   rollback될 수 있으므로 통계 쓰기(원천 안 bucket·창 재대조·장기 복구 구간·수동 재대조)는 transaction advisory lock
   (`TRAFFIC_STATISTICS_ADVISORY_LOCK_KEY` 420042, `services/traffic_statistics.py`)으로 직렬화한다. 원천 transaction은
   bucket을 쓰기 직전에 이 잠금을 기다려 잡는다(이 대기만 수집 기본 `lock_timeout` 5초 대신 55초, commit까지 짧게 보유).
   창 재대조·장기 복구·수동 재대조는 `pg_try_advisory_xact_lock`으로 잡고, 다른 transaction이 쥐고 있으면 기다리지 않고
   양보한다(창은 `busy`로 미룸, 장기 복구는 그 실행을 건너뜀, 수동은 잠시 뒤 다시 해 본 뒤 멈춤). Dagster의 job별 동시
   실행 1·run group(highway) 상한 1과 in-process 잠금이 정기 실행을 이미 직렬화하므로 이 잠금은 그 밖의 겹침(수동·관리자
   실행, 운영자 수동 재대조, 다른 프로세스)을 위한 것이다.
4. **재대조 실패·지연**(문장 시간 초과·잠금 대기·연결 오류·`busy`)은 원본·current·바뀐 bucket 통계·성공 상태를
   되돌리지 않는다. run 원장(`collection_runs.status`)은 원천 결과대로 두고(유가 통계 발행 지연과 같은 규칙), Dagster
   결과에 `traffic_statistics_refreshed=false`, 원인 코드 `traffic_statistics_deferred_reason`(`statement_timeout`·
   `lock_timeout`·`deadlock`·`serialization`·`unique_violation`·`connection`·`client_timeout`·`busy`·`database`·
   `sqlstate_<등급>`·`other`), `collection_outcome=partial`, 원천 오류가 없으면 `error_code=DERIVED_CACHE_DEFERRED`,
   op 경고 한 줄을 남긴다(run 태그 `kortravel/collection-outcome=partial`). 관리 콘솔은 error_code와 별도로 "원본·통계
   보존 · 소통 5분 통계 최근 2시간 재대조 대기 (다음 수집이 자동 복구)"와 원인을 보인다. 다음 실행의 같은 단계가 창을
   다시 맞춘다. 대응: 한두 번은 조치가 필요 없다. 1시간(정기 12회) 넘게 연속되면 원인 코드와
   `traffic_statistics_seconds`를 보고 DB 부하·잠금 경합(`lock_timeout`·`busy`)을 확인한다. 2시간 넘게 이어져 창에서
   빠진 구간은 장기 복구(7번)가 다음 한 바퀴에서 맞춘다. 원인을 고친 뒤 바로 맞추려면 수동 재대조(8번)를 쓴다.
   **어긋남**(창 재대조가 바꾼 행, `traffic_statistics_drift_rows` > 0)은 실패가 아니다 — 재대조가 이미 고쳤으므로
   `collection_outcome`은 success 그대로이고, 로그·op 경고 한 줄과 관리 콘솔 경고 표시만 남긴다(대응은
   [트러블슈팅](../runbooks/troubleshooting.md#고속도로-소통-5분-통계-어긋남장기-복구-경고)). 창 재대조의 실패·지연(DB 오류·
   `busy`)만 partial이다. 장기 복구(7번)의 실패·양보·건너뜀은 partial이 아니다.
5. **끊김의 run 원장**: 원천 commit 뒤 재대조 도중 실행이 끊겨도 이미 확정한 원본과 그 bucket 통계는 맞다.
   취소(asyncio 취소·op 시간 예산)는 run 원장을 예전처럼 `failed`(`collection cancelled`)로 닫고 원천 상태는 덮지 않는다.
   SIGKILL·OOM처럼 프로세스가 바로 죽으면 원장은 `running`으로 남고, worker 회수 sensor가 Dagster 실행 종료·소유권
   유실을 확인한 뒤 `failed`로 닫는다(`reconcile_collection_runs`). 두 경우 모두 원천 상태(`last_success_at`)는 그대로다.
6. **반복 관측**: KREX는 센서가 멈춘 구간의 같은 관측(같은 `identity_key`·`observed_at`)을 매 주기 그대로 돌려준다. 값과
   원본 JSON이 모두 같으면 `collected_at`·`collection_run_id`만 batch(400행)당 한 문장(`id IN (…)`)으로 갱신하고 그
   bucket을 다시 만들지 않는다. 예전 코드도 SQLAlchemy가 바뀌지 않은 열을 SET에서 빼므로 원본 JSON을 다시 쓰지는
   않았다 — 차이는 행별 UPDATE(executemany)가 한 문장이 된 것과, 응답에 섞인 2시간 창 밖의 과거 bucket을 매 실행 같은
   결과로 재집계하던 일을 없앤 것이다. 값이 바뀐 정정은 예전처럼 원본 JSON까지 갱신하고, 통계 입력값이 바뀌었으면 그
   bucket을 원천 transaction에서 다시 만든다. `collection_run_id`는 색인 열이라 반복 관측의 갱신도 HOT가 아닌 새 tuple을
   만든다(아래 후속).

7. **장기 어긋남 복구**(2026-11-24, WLH-06 후속): 최근 창보다 오래된 구간을 고속도로 실행 끝(창 재대조 뒤)의 작은
   조각으로 하루 한 바퀴 맞춘다(`repair_traffic_statistics`). 창 시작에서 과거로 2시간 구간(`TRAFFIC_STATISTICS_REPAIR_CHUNK`)씩
   걸어가며 구간마다 한 transaction(통계 try-lock → 진행 위치 읽기 → 차이 기반 재대조 → 진행 위치 전진 → commit)이다.
   지평은 `TRANSPORT_TRAFFIC_STATISTICS_REPAIR_HORIZON_HOURS`(기본 168 = 7일, 0이면 끔, 최대 90일)이고, 가장 오래된 원본이
   담긴 첫 온전한 bucket보다 앞은 하지 않는다(원본 보존 정책이 생겨 원본만 먼저 지워져도 그 통계를 지우지 않게). 하한은
   구간마다 그 transaction에서 다시 잰다. 지평 안이라도 **원본이 하나도 없는 bucket**(원본 정리·부분 복원으로 가운데가 빈
   경우)의 통계 행은 지우지 않는다 — 정본에 없는 행 삭제를 원본이 있는 bucket으로 한정한다(`keep_rawless_buckets`). 원본이
   있는 bucket의 원본 없는 행(유령 노선·방향)은 지운다. 최근 창 재대조는 예전대로 둘 다 지운다.
   - **진행 원장**: migration 없이 `transport_collection_states`의 전용 행 `krex_traffic_statistics_repair`를 쓴다(공항
     KAC 할당량 원장과 같은 방식). `next_due_at` = 다음 구간의 끝(배타, 5분 경계, NULL이면 진행 중인 한 바퀴 없음),
     `last_started_at` = 이번 한 바퀴 시작, `last_success_at` = 마지막 한 바퀴 완료, `last_error` = 연속 구간 실패의
     원인 코드와 횟수(`statement_timeout;failures=2`, 구간을 하나 끝내면 NULL, 마지막 실패 시각은 `updated_at`). 진행 위치는
     그 구간의 재대조와 같은 transaction에서 commit되므로 실패·취소·예산 소진 뒤 다음 실행이 마지막으로 commit한 구간
     다음부터 이어 한다. 새 한 바퀴의 첫 구간이 실패하면 그 위치(창 시작)와 한 바퀴 시작 시각을 실패 기록과 함께 남긴다 —
     막힌 위치가 원장과 `traffic_statistics_repair_cursor`에 보이고, 다음 실행은 그 위치에서 이어 한다. 한 바퀴가 하한에
     닿으면 끝나고, 다음 한 바퀴는 이번 한 바퀴 시작 + 간격(24시간, 지평의 절반이 더 짧으면 그 절반) 뒤에 시작한다. 다음
     한 바퀴의 하한(그때 창 시작 − 지평)이 이번 한 바퀴의 시작점보다 앞이므로, 한 바퀴가 `지평 − 간격`(기본 144시간) 안에
     끝나는 한 그 사이 창에서 빠진 bucket은 다음 한 바퀴에 빠짐없이 든다. 실패 쉼·양보가 길어 한 바퀴가 그보다 오래
     걸리면 그 차이만큼의 bucket은 다음 한 바퀴에서 빠질 수 있다 — 그때는 수동 재대조(8번)로 맞춘다. 수집 상태 API의
     `sources` 목록에서는 뺀다.
   - **실패**: 실패한 구간은 위치를 옮기지 않고, 다음 실행이 같은 위치에서 구간 폭을 연속 실패 횟수만큼 반으로 줄여 다시
     한다(2시간 → 1시간 → 30분 → 15분). 연속 세 번 실패하면 마지막 실패 뒤 한 시간 동안 장기 복구를 쉰다(`deferred`,
     `failure_backoff`) — 한 시간에 한 번만 다시 해 본다. 구간 문장은 `statement_timeout=30s`(수집 기본 60초보다 짧게)로
     돌아, 통계 잠금을 쥐고 원천 transaction의 잠금 대기 상한(55초)을 넘기지 않는다. 같은 원인의 데이터 오류(SQLSTATE
     22 등)는 시간이 지나도 낫지 않으므로 그 위치에서 멈춰 있다 — 트러블슈팅 대응을 따른다.
   - **예산**: 한 실행은 다음 구간을 시작하기 전에 5초 예산(`TRAFFIC_STATISTICS_REPAIR_RUN_BUDGET_SECONDS`, 이미 시작한
     구간은 끝냄)과 12구간 상한을 본다. 독립 transaction이라 병렬 집계를 끈다(`max_parallel_workers_per_gather=0`). 창
     재대조가 실패·지연한 실행(DB 부하 신호, `window_deferred`)과 수집이 이미 10분 넘게 걸린 실행(`run_budget`)은
     건너뛴다. 다른 통계 쓰기가 잠금을 쥐면 그 실행은 양보한다(`busy`, 위치 그대로).
   - **왜 별도 schedule이 아닌가**: odroid(A55×4)에서 Dagster run 하나는 프로세스 기동·import 비용이 크고, 별도 job을
     highway run group에 넣으면 그동안 5분 수집이 큐에서 기다리며, 다른 run group에 넣으면 고속도로 실행과 겹쳐 통계 잠금을
     다툰다(원천의 bucket 쓰기 대기, 창 재대조 `busy` partial). 고속도로 실행 끝의 조각은 job별 동시 실행 1·run group 상한
     1로 이미 직렬화된 같은 실행 안이라 통계 잠금을 다툴 상대가 없고, 새 schedule·배포 instigator 목록·공용 instance 설정이
     필요 없다. 하루 총량은 별도 일일 job과 같고(지평 7일 = 2시간 구간 84개를 하루 한 바퀴) 정기 실행 하나가 더하는 시간은
     예산(5초 + 진행 중 구간)으로 묶인다.
   - **결과**: 실패·양보·어긋남은 원천·수집 결과(outcome)를 바꾸지 않는다. 실패는 원인 코드와 op 경고 한 줄, 어긋남은 행
     수·구간과 op 경고 한 줄이다(대응은 트러블슈팅).
8. **수동 재대조**: `python scripts/reconcile-traffic-statistics.py --start … --end … [--dry-run]`(backend·code-server
   컨테이너 안, 시간대가 없으면 KST). 같은 구현을 구간(기본 2시간)마다 commit하며 돌린다. `--dry-run`은 읽기 전용
   transaction에서 바꿀 행 수만 센다. 쓰기는 구간마다 통계 try-lock을 잡고, 정기 수집이 쥐고 있으면 잠시 뒤 다시 해 본 뒤
   멈추며 이어 할 `--start`를 출력한다(종료 코드 3). `--budget-seconds`(기본 1,800초 = 30분)가 지나도 다음 구간을
   시작하지 않고 같은 안내와 종료 코드 3으로 멈춘다. 한 번에 90일까지, `--chunk-hours`는 5분의 배수로 최대 6시간이고
   구간 문장은 30초 안에 끝나야 한다(넘으면 구간을 줄인다). 입력 오류는 종료 코드 2다. 장기 복구와 같이 가장 오래된 원본보다
   앞 구간과 원본이 하나도 없는 bucket의 통계는 지우지 않는다(`--include-before-oldest-raw`로만 포함). 장기 복구 진행
   위치는 바꾸지 않는다.

#### 차이 기반 재대조(`services/traffic_statistics.py`)

원천 안 bucket(1번), 창 재대조(2번), 장기 복구(7번), 수동 재대조(8번)가 같은 `reconcile_traffic_statistics` 한 문장을
쓴다. 범위 `[start, end)`(창은 끝 없음, 경계는 5분 bucket이어야 한다)의 원본을 예전과 같은 규칙(UTC `date_bin` 5분,
`COALESCE(route_no,'')`·`COALESCE(direction,'')`, 같은 집계 열)으로 집계한 정본 CTE를 한 번 만들고, 같은 문장에서

- 정본과 다른 행만 골라(`LEFT JOIN` + 같지 않음 조건) `INSERT … ON CONFLICT ON CONSTRAINT
  uq_highway_traffic_five_minute_statistics DO UPDATE SET … WHERE (기존 값) ≠ (EXCLUDED)`로 넣거나 고치고,
- 범위 안에서 정본에 없는 통계 행만 지운다(`NOT EXISTS` anti-join).

값이 같은 행은 INSERT·UPDATE 후보에 들지 않으므로 새 tuple·행 잠금·WAL이 없다(어긋남 없는 범위의 재대조는 transaction
id조차 할당되지 않는다 — PG 시험이 확인). 반환은 추가·수정·삭제(= 어긋남)·그대로 둔 행 수와 시간이다. 비교는 관측 수·
최소·최대·최신 관측 시각은 정확히, 배정밀도 합(`speed_sum`·`free_flow_speed_sum`)은 상대 오차 1e-9 안이면 같다고 본다 —
같은 원본이라도 더하는 순서(실행 계획)에 따라 합의 마지막 자리가 달라질 수 있어, 그것만으로 어긋남·재기록이 생기지 않게
한다. 예전 DELETE + INSERT는 매 실행 창의 모든 통계 행(2시간 × 노선·방향 그룹)을 지우고 새로 넣어 dead tuple·WAL·
`id` 시퀀스(int4)를 소모했다. 원천 transaction 안의 bucket도 같은 차이 기반이라 원본과의 원자성은 그대로다(같은
transaction의 한 문장). PG 시험(`tests/test_traffic_statistics_reconcile.py`): 재대조 뒤 범위 통계 = 원본 전체 재계산,
두 번째 재대조 0행(멱등), 값이 같은 행의 `xmin`·`ctid` 불변, 범위 밖 불변, 정본에 없는 행만 삭제, 합의 부동소수 잡음은
어긋남 아님, 장기 복구의 구간·예산·이어 하기·양보·실패, 원본 시작 전 구간 보존, 원천 bucket 쓰기와 다른 transaction의
재대조가 겹쳐도 unique 충돌 없음.

로컬 측정(`tests/benchmarks/traffic_statistics_reconcile.py --hours 6 --segments 8300 --repeat 7`, 개발 PC의 WSL Docker
PostgreSQL 18, 6시간 이력 597,600행, 2시간 창 통계 1,920행, 중앙값; 참고용): 예전 DELETE + INSERT 415 ms·쓴 tuple
3,840(삭제 1,920 + 추가 1,920)·WAL 785 KiB, 차이 기반 어긋남 없음 404 ms·쓴 tuple 0·WAL 0.2 KiB, 어긋난 25행 407 ms·수정
25·WAL 3.4 KiB. 시간은 원본 집계가 지배해 비슷하고, 줄어드는 것은 쓰기다 — 이 측정 규모(노선·방향 그룹 80개)로 5분마다
돌리면 하루 약 110만 dead tuple·약 220 MiB WAL이 0에 가까워진다(운영 그룹 수에 비례). 장기 복구 구간(2시간)도 같은
문장이라 한 구간의 비용은 이 측정과 같다.

#### 계측

단계별 시간과 행 분류는 run 요약, Dagster output metadata, 실패 metadata(원천 저장이 rollback된 실행 포함)에 싣는다:
`highway_fetch_seconds`, `traffic_{raw_response,history,current_upsert,touched_statistics,commit,statistics}_seconds`,
`traffic_{inserted,changed,unchanged}_rows`, `traffic_touched_buckets`(원천 transaction에서 다시 만든 bucket),
`traffic_out_of_window_buckets`(그중 최근 2시간 창보다 오래된 bucket — 과거 관측의 값 정정과 처음 보는 오래된 관측,
예: 센서가 멈춘 구간의 관측이 처음 들어온 실행), `traffic_source_committed`, 실패 시 `traffic_failed_step`·
`traffic_store_failure_reason`(위 원인 코드), `traffic_statistics_refreshed`·`traffic_statistics_deferred_reason`,
5분 통계 행: `traffic_touched_statistics_rows`(원천 안 bucket이 쓴 행), 창 재대조의
`traffic_statistics_{inserted,updated,deleted,unchanged}_rows`·`traffic_statistics_drift_rows`(= 추가 + 수정 + 삭제),
장기 복구의 `traffic_statistics_repair_{status,reason,chunks,seconds,inserted_rows,updated_rows,deleted_rows,
unchanged_rows,drift_rows,busy_skips,sweep_complete,budget_exhausted}`·`traffic_statistics_repair_{range_start,range_end,
cursor,horizon_start}`(UTC `YYYY-MM-DDTHH:MM:SSZ`). 상태는 `idle`(다음 한 바퀴 전)·`repaired`·`busy`·`deferred`
(`run_budget`·`window_deferred`)·`failed`(DB 원인 코드) 고정 값이다.
수집기 로그는 원천 commit 직후 `highway traffic source committed run_id=…`(재대조 전에 남는다), rollback이면
`highway traffic source rolled back … reason=… failed_step=…`, 취소면 `highway traffic source cancelled …`, 재대조 뒤
`highway traffic statistics reconcile …`(추가·수정·삭제·그대로 행 수 포함), 어긋남이 있으면 경고
`highway traffic statistics drift repaired …`, 장기 복구 조각 뒤 `highway traffic statistics repair …`(실패·어긋남이면
경고)를 한 줄씩 남긴다. 고속도로 op는 이 logger를 가린 뒤 Dagster event log로 넘긴다.

후속(이 변경 범위 밖): `current_upsert`(`services/traffic_current.py`) 축소, 반복 관측의 `collection_run_id` 갱신
생략(현재 이 열을 읽는 앱 코드는 없지만 "마지막으로 확인한 실행" 의미가 문서 계약이고, 표가 INSERT 위주라 기본
fillfactor에서 HOT 이득도 불확실하다), 연속 재대조 지연·반복 어긋남의 자동 경보(지금은 metadata·로그·콘솔 표시와
트러블슈팅 기준). 창 재대조의 매 실행 DELETE + INSERT는 차이 기반으로 바꿨고(2026-11-24), 2시간보다 오래된 어긋남은
장기 복구(7번)가 맞춘다.

### 공급자 관측 지연 주의

2026-09-19 20:22 KST의 별도 새 연결 조회에서도 KREX 0405 응답 8,370행의 최신
관측 시각은 19:52 KST였다. 운영 저장 원본도 같은 시각을 반복 반환했다. 따라서
`last_success_at`은 조회·저장 성공이지 새로운 관측의 도착을 보장하지 않는다.
소비자는 `observed_at`/통계의 `latest_observed_at`도 확인해야 한다. 이미 저장된 같은
관측을 새 관측처럼 복제하거나 E2E 신선도 기준을 완화해 정상 상태로 표시하지 않는다.
이 값은 해당 시점의 실측이며 공급자의 공식 갱신 주기/SLA로 해석하지 않는다.

## 목적

`parking-radar`에서 보이는 시각이 왜 다른지, 어떤 시각이 무엇을 뜻하는지, 웹 UI의 강제 수집 버튼이 어떤 규칙으로 동작하는지 정리한다.

운영 수집기는 `192.168.1.14`의 PostgreSQL-backed backend에서만 실행한다. `192.168.1.13`은
cutover 동안 HTTP read-only source로 유지하며 Docker를 조작하지 않는다.

## 주기와 중복 방지

- n150 운영 기본 주기: `COLLECT_INTERVAL_SECONDS=300` (5분)
- 수동 수집 제한: `MANUAL_COLLECT_MIN_INTERVAL_SECONDS=300` (5분)
- scheduler는 collection duration을 포함해 다음 시작 시각을 monotonic deadline으로 계산한다. 수집이 5분을 넘으면 지연을 숨기지 않고 즉시 다음 tick을 시작하며, 운영 verifier가 freshness를 별도로 gate한다.
- 외부 API가 같은 `observed_at`을 반복하면 unique key에 의해 새 snapshot이 생기지
  않을 수 있다. 따라서 row 수와 함께 `observed_at`, `collected_at`, `last_run`을 확인한다.
- 고속도로 소통은 provider가 준 관측 시각과 `identity_key`를 이용해 같은 규칙으로
  중복을 막는다. 유가는 provider 갱신 시각을 우선 관측 시각으로 쓰고, 갱신 시각이 없으면
  collector 실행 시각을 사용한다. 유가 API의 기간 필터와 최신 판정은 실제 응답을 받은
  `collected_at`을 기준으로 하므로 provider 갱신 시각이 오래되어도 최신 수집 결과를
  숨기지 않는다.
- 원천 일부 행의 결함(2026-11-24): 고속도로 소통(0405)의 무효 행이 5% 이하, 공항 주차 원천의 무효 행이 20% 이하이면
  그 행만 격리하고 나머지를 저장한다. run은 부분 성공(`isolated_rows`, `INVALID_ROWS_ISOLATED`)이고 비율을 넘으면
  원천 실패다. 응답 계약 위반(`KrexParseError`)은 같은 응답이라 재호출하지 않는다. current는 완결 집합이라, 빠진
  구간·주차장 수가 격리 수 이하일 때만 1시간 안 관측의 직전 current 행을 값·관측시각 그대로 유지한다.
- 돌발은 provider 발생시각이 아니라 수집시각을 `observed_at`으로 사용한다. 같은
  `series_no`의 처리상태 변경을 새 스냅샷으로 보존하기 위해서다.
- Playwright 수집기는 공개 화면 자동화가 공식 API가 아니라는 위험이 있으므로, 화면
  구조가 바뀌거나 자동화 차단이 발생하면 실패를 기록하고 임의의 빈 성공 데이터로
  덮어쓰지 않는다.
- 오피넷 지역 검색의 기본 응답 대기 상한은 60초다. 이는 지연된 단일 화면 응답을
  기다리는 시간만 늘릴 뿐 그 자체로 재시도나 추가 수집 요청을 만들지 않는다. 정기 실행은 8시간 tick이고, 실패 뒤의
  자동·관리자 재시도는 위 "수집 예약과 조회 시간 상한"의 규칙을 따른다.

## 시각 기준

- 백엔드 저장 기준: UTC
- 백엔드 API 응답 기준: UTC ISO 8601
- 프론트엔드 표시 기준: KST

즉, DB와 API는 UTC를 기준으로 일관되게 다루고, 브라우저 화면에서는 항상 KST로 변환해서 보여준다.

## 화면에 보이는 시각의 의미

현재 UI는 사용자가 해석해야 하는 시각을 하나로 단순화한다.

- `데이터 기준 시각`
  - 사용자가 가장 먼저 봐야 하는 시각
  - 현재 화면에 보이는 주차 상태가 실제로 언제 관측된 값인지 뜻한다.
- 수집기 동기화 시각은 `GET /v1/admin/collector-status`와 운영 로그에서만 확인한다.

### 데이터 기준 시각

- 각 주차장 상태의 `observed_at`
- 원본 데이터가 실제로 관측된 시각
- 사용자가 가장 먼저 봐야 하는 핵심 시각

예시:
- API가 `2026-04-26T11:30:00Z`를 반환하면 UI에는 `04.26 20:30 KST`로 보인다.

### 저장 시각(`collected_at`)

- 각 row의 `collected_at`은 여전히 DB와 API에 남아 있다.
- 다만 사용자에게는 해석 부담이 커서 메인 화면에서는 직접 노출하지 않는다.
- 운영 디버깅이 필요할 때만 API나 백엔드 로그에서 확인한다.

## 왜 관측 시각과 수집 시각이 다를 수 있는가

다음 경우는 정상 동작이다.

1. 원본 제공기관이 아직 같은 관측시각을 계속 내려준다.
2. 수집기는 다시 실행된다.
3. 하지만 `observed_at`이 같아서 중복 저장을 건너뛴다.
4. 이 경우 현재 주차장 row의 `collected_at`은 그대로일 수 있다.
5. 대신 수집기 상태 API나 다른 주차장의 최신 적재 시각은 더 최근일 수 있다.

따라서 화면 해석은 아래처럼 하는 것이 맞다.

- 사용자가 확인해야 하는 기준 시각: `데이터 기준 시각`
- 수집기 동작 점검용 시각: `latest_snapshot_collected_at` (API/로그 전용)

## 강제 수집 버튼 (로컬 개발 전용)

로컬 개발 profile에서 `ENABLE_MANUAL_COLLECT=true`일 때만 웹 UI의 `지금 수집` 버튼이
`POST /v1/admin/collect`를 호출한다. public n150 profile에서는 `ENABLE_MANUAL_COLLECT=false`로
버튼과 endpoint가 모두 비활성화되고, 웹 proxy에도 노출되지 않는다.

동작 규칙:

- 수동 수집 제한은 `manual_collect_min_interval_seconds`를 따른다.
- 프론트엔드는 먼저 `GET /v1/admin/collector-status`를 보고 사용자에게 즉시 안내한다.
- 백엔드도 동일한 제한을 강제한다.
- 즉, 프론트 우회 호출을 하더라도 백엔드에서 다시 막는다.

### 사용자 메시지

제한 시간 이내 재실행 시 UI는 아래와 같은 에러를 보여준다.

- `마지막 업데이트 후 10분이 지나지 않았습니다. 04.26 20:49 KST 이후 다시 시도해 주세요.`

### 성공 시 메시지

- `즉시 수집을 완료했습니다. 신규 스냅샷 10건을 저장했습니다.`

## 검증 방법

### API 검증

1. `GET /v1/parking/current`
2. `GET /v1/admin/collector-status`
3. `observed_at`, `collected_at`, `latest_snapshot_collected_at`이 UTC ISO 문자열인지 확인
4. 브라우저에서는 같은 값이 KST로 보이는지 확인

### 브라우저 검증

1. `http://localhost:3000` 접속
2. `데이터 기준 시각` 확인
3. `지금 수집` 1회 실행
4. 성공 메시지와 `다음 수동 수집 가능` 시각 확인
5. 바로 다시 눌러 제한 에러 메시지 확인

## 이번 기준에서 확인된 사실

- 현재 localhost 스택이 sample 모드여도 UTC 저장과 KST 표시는 정상 동작한다.
- UI의 `데이터 기준 시각` 표기와 API의 UTC 시각 변환은 일치한다.
- 강제 수집 버튼은 정상 동작하고, 제한 시간 이내 재실행은 UI와 백엔드 양쪽에서 차단된다.

### 무효 행 격리의 상태 표시(2026-11-24)

수집이 원천 응답의 무효 행만 격리하고 나머지를 저장한 실행은 부분 성공이다. 운영 상태(`/v1/transport/providers`)는 격리만 있는
실행을 실패와 구분한다: 원천 `status=partial_success`(공항 `shared_job_partial_success`)·`isolated_rows=N`·`error_code=null`, 같은 job의
`job_isolated_rows`. 공개 collector-status의 실행 `error`는 격리만 있으면 `rows_isolated`, 그 밖의 실패는 `collection_failed`다 —
`rows_isolated`는 실패가 아니다(정상 행은 저장됐다).

고속도로 소통의 격리 행 넘김은 건수 기준이다(SDK가 무효 행의 구간 식별자를 주지 않는다). 주차는 격리 행의 `(airport_code, lot_id)` 기준이다.

### 전량 실패는 부분 성공이 아니다(2026-11-24 소유자 결정)

부분 성공 판정의 기준값(고속도로 소통 격리 5%, 주차 원천 격리 20%, 격리 주차장 직전 값 유지 1시간, 좌표 보강 '실패 3건 이상이면서
50% 이상')은 그대로다. 그 위에 **대상 전부가 실패한 실행은 건수와 무관하게 Dagster run 실패**다.

- 좌표 보강(VWorld·카카오, `_place_collection_error`): 이번 실행의 호출이 하나도 성공하지 않으면(1건 중 1건 포함) 실패다
  (`error_code=ALL_SOURCES_FAILED`). 하루 호출이 1~2건이라 '3건 이상' 기준만으로는 제공기관이 완전히 죽어도 녹색 부분 완료로만 남았다.
  - 결정적으로 실패하는 대상은 VWorld·카카오 모두 영수증 대기(연속 실패 n번째 뒤 2^(n-1)일, 최대 30일, 인증·한도 실패는 세지 않음)로
    다시 부른다(카카오는 예전 1일 고정이었다). 그 대상 하나만 부른 날은 전량 실패라 FAILURE이고, 버스·항구 기준정보 job이면 뒤의
    export 준비를 건너뛴다(공항 job이 5분마다 같은 준비를 하므로 지연은 짧다) — 받아들인 비용이다.
  - 한계: 호출이 0건인 날(대상이 모두 대기 중)은 장애 여부를 알 수 없어 녹색이다. 장애가 며칠 이어지면 대상이 대기에 들어가 FAILURE가
    띄엄띄엄 보인다. 제공기관별 기준 질의(알려진 정상 검색어) 같은 별도 탐침은 두지 않았다(호출 예산을 쓴다, 후속 후보).
  - DB 오류(잠금 대기 등)로 대상 처리가 끝나지 못한 것도 수집기는 호출 실패로 센다(예전부터) — 1건 중 1건이면 같은 코드로 실패한다.
- 공항 주차(`collect_airport_parking`): 수집 결과의 `parking_sources_total`·`parking_sources_failed`로 주차 원천(KAC·인천)이 전부
  실패하면 실패다(`error_code=ALL_SOURCES_FAILED`, 원래 원인 분류는 `source_error_code`). 성공 기준은 Map 경로(운영)는 current 승격,
  플래그 OFF 경로는 응답 수신이다(플래그 OFF는 응답을 받았지만 해석된 행이 0인 경우를 실패로 잡지 못한다). 이미 걸린 KAC 호출 한도
  (마감 시각이 있는 유예)로 부르지 않은 KAC는 시도에서 뺀다 — 한도 유예는 장애가 아니다. 거절된 원천의 이력 전용 저장이나 같은 실행의
  요금 갱신은 진척으로 보지 않는다. 사전집계 경보(태그·로그)를 남긴 뒤에 실패로 올린다. DB의 실행 상태(`collection_runs.status`)와
  수동 수집 API 응답은 그대로 `partial_success`일 수 있다(이력은 남았다) — run metadata에는 `status=failed`와
  `collection_run_status`로 따로 싣는다. 관리자 콘솔은 같은 코드로 고정 원인·대응과 시도·실패 원천 수를 보인다.
- 고속도로(`collect_highway_transport`): 이미 보장된다 — 소통·돌발이 모두 실패하면 `raw_count=0`이라 `status=failed`, 소통 응답의 무효 행이
  전부면 격리 대상이 아니다(`highway_invalid_rows_acceptable`의 `invalid_rows < received_rows`). 주차 원천 응답의 무효 행이 전부면
  `유효한 행이 없습니다`로 원천 거부다.
