# Transport Dagster 중단 복구

Weather PR #72의 개선과 common PR #24·#25 Python 코어를 채택한다.
공용 가이드: https://github.com/digitie/kor-travel-common/blob/main/docs/runbooks/dagster-adoption.md

## 구조와 호출 보호

각 job은 job tag `dagster/max_runtime` 실행 상한(기본 4시간, 공항 30분·고속도로 20분·본문 준비 3분), step 동시성 1을 유지한다. common의 project/job 태그와
coalescing schedule은 같은 location의 pending/active 실행이 있으면 새 예약을 합친다.
collector pool은 2 connections와 overflow 0으로 제한한다. 한 connection은 기존 session
advisory lease, 다른 하나는 부분 게시 transaction에 필요하다. DB 접속 10초, 문장 60초
(asyncpg `command_timeout` 클라이언트 측 + 서버 `statement_timeout` 60초, 2026-10-21부터 둘 다),
lock 5초와 async action 제한(run 시작부터 잰 실행 상한 − 60초, `_run_deadline_seconds`)을 적용한다. provider public cancellation 계약을 사용한다.
API 엔진은 서버 `statement_timeout` 120초만 둔다(클라이언트 timeout 없음). 근거와 값은
`backend/app/db/session.py` 상수 주석이 정본이다.

`0024` migration 뒤 worker는 `CollectionRun`을 외부 호출 전에 commit하여 소유권을 남긴다.
소유 session은 ORM flush와 bulk SQL commit에서 기존 running/owner를 잠그고 heartbeat를
갱신한다. 회수된 worker의 늦은 게시·완료 덮어쓰기는 rollback된다. 부분 저장본은 유지한다.
rollback으로 ORM 상태가 만료되어도 소유권 fence를 유지한다. 권한 상실은 같은 op의
새 session에도 전파하고 다음 provider를 시작하지 않는다. 후속 op/session 시작 때 native
owner 생존을 10초 상한으로 확인하며 조회 장애는 provider 호출 전에 실패로 전달한다.
회수 sensor는 외부 provider 없이 stable ID keyset 100행씩 확인한다. Dagster terminal은
running 수집 기록을 failed로 회수하고, 없는 run은 5시간 grace·heartbeat CAS로 확인한다.
metadata 장애는 회수 사유가 아니다. legacy NULL owner 행은 자동 변경하지 않는다.

## 회수 sensor의 tick 예산과 정체 경보 (common e746e4b §19)

`transport_worker_recovery`는 common `reconciliation_sensor(budget_seconds=45, on_stall=...)`다.

- **예산**: 한 tick은 45초 안에서 끝난다. 다음 단계를 시작하려면 25초(가장 긴 단계인 한 행의
  metadata 10초 + 새 session 접속 5초 + UPDATE 5초 + COMMIT 5초)가 남아 있어야 하고, 모자라면 위치를
  저장하고 정상 종료한다. sensor 전용 엔진은 서버 `statement_timeout`·`command_timeout`·접속
  timeout 모두 5초다. 단계 예약이 세지 않는 시간(첫 접속의 dialect 초기화 문장, 마지막 빈 page 확인)은
  작업 전체에 건 `asyncio.timeout(예산 - 정리 5초)`이 끊고, 엔진 dispose는 정리 5초 중 4초에서 포기한다.
  그래서 느린 DB에서도 콜백이 예산 안에 `TimeoutError`로 돌아오며 common의 예산 끊김(thread 누수)에
  이르지 않는다. 예산을 넘겨 끊긴 thread는 `context`를 더 쓰지 않고 metadata도 더 부르지 않는다.
- **위치**: keyset 위치는 code-server 프로세스 안(`ScanPosition`)에 둔다. sensor cursor는 common
  정체 시계(`stall:` JSON)가 소유하므로 쓰지 않는다. 재시작으로 위치를 잃으면 처음부터 다시 볼 뿐
  행을 건너뛰지 않고, 끝까지 보면 0으로 돌아가 위치 앞의 행도 다음 바퀴에 본다. common §19는 위치를
  소비자 DB에 두라고 하지만, 대상이 running 행뿐이고(평소 수 건) ID가 단조 증가해 잃어도 누락이
  없으므로 새 테이블을 만들지 않았다.
- **정체로 세는 것**: (1) DB 오류(서명은 예외 형식 이름과 SQLSTATE), (2) Dagster metadata 장애
  (`RecoveryMetadataUnavailable` — 예전에는 조용히 0건 반환), (3) 공항(`dagster_airport`)·고속도로
  (`transport_dagster_highway`) 5분 수집의 마지막 `CollectionRun` 시작이 20분보다 오래됨
  (`CollectionStalled`), (4) 콜백이 예산을 넘김(`DeadlineExceeded`). 신선도 판정은 회수보다 먼저
  매 tick 한다. 행이 하나도 없는 trigger는 판단하지 않는다.
- **경보**: 첫 실패 뒤 900초에 한 줄을 남기고 3600초마다 다시 남긴다. 성공한 tick이 시계를 지운다.
  이 저장소에는 경보 테이블·채널이 없어 같은 줄을 Dagster sensor tick 로그(`context.log.error`)와
  code-server 프로세스 로그(logger `app.dagster.recovery`, 컨테이너 stderr → `docker logs`)에 남긴다.
  형식(검색 기준):

  ```text
  transport_worker_recovery.stalled key=transport_worker_recovery first_failed_at=<UTC ISO> stalled_seconds=<n> last_failure=<형식이름[:SQLSTATE]>
  ```

  예외 원문은 경보 줄과 cursor에 없다(traceback은 기존 tick 실패처럼 `context.log`에 남는다).
  5분 수집 schedule을 일부러 멈추면(점검, Dagster instance의 schedule 상태 STOPPED) 그 trigger는 정체로
  세지 않는다. tick마다 경고 한 줄만 남기고(traceback 없음) 회수는 계속 돈다. 같은 이름의 상태가 여럿이면
  모두 STOPPED일 때만 멈춘 것으로 본다. schedule은 RUNNING인데 실행이 시작되지 않으면 경보한다.
  실패 중에 sensor를 오래 멈췄다가 다시 켜면 옛 `first_failed_at` 때문에 첫 실패에 바로 경보할 수
  있다. 원치 않으면 다시 켜기 전에 sensor cursor를 지운다(UI 또는 `dagster sensor cursor --delete`).
- **이 경보가 다루지 못하는 것**: code-server gRPC 자체가 멈추면(2026-09-27 11:53Z~19:51Z 정지)
  sensor 평가도 같은 프로세스에서 하므로 경보할 주체가 없다. 그 경우는 code-server healthcheck
  probe가 연속 timeout 300초(실행 중인 run worker가 있으면 7200초) 뒤 PID 1을 종료해 재시작시키는 것이 회복 경로다
  (`docker-compose.shared.yml`·`transport.override.yml`의 `x-dagster-code-server-probe`).
  재시작 뒤 수집이 돌아오지 않으면 이 sensor가 20분+900초 뒤 경보한다.

## 유가 시도 소실 기록과 유가 신선도 경보 (2026-11-24 감사 G1-F5·G1-F6)

2026-11-23 08:17Z~11-24 00:17Z T1 주유소 export(`/v1/service/exports/fuel-stations`)가 약 16.6시간 503이었는데
경보가 없었다. 위 정체 경보는 5분 수집만 보기 때문이다. 또 유가 run이 op 밖에서 죽으면(code-server·run worker 재시작,
SIGKILL, 배포 `--no-drain`) `_mark_fuel_failure`가 불리지 않아 직전 성공의 `last_error=None`이 남았다. 그러면 관리자
"재시도"(`kortravel/admin-retry-of`, `retry_failed_fuel=True`)도 "직전 시도 성공"으로 보고 호출 유예로 건너뛰어, 한
주기(8시간)를 잃었다. 둘 다 `transport_worker_recovery` tick 안에서, **회수 뒤에** 처리한다. 새 run·schedule을 만들지
않고 오피넷도 부르지 않는다.

- **유가 시도 소실 기록**(`recovery.record_lost_fuel_attempt`, 판정 규칙은 서비스의 `lost_fuel_claim_owner`):
  - 조건: 오피넷 상태 행의 claim(`last_started_at`)에 결과가 없다(`last_error` 없음, `last_success_at < last_started_at`).
    그 claim의 주인 실행 — claim 직전 15분 안에 시작한 마지막 Dagster 유가 실행(`transport_dagster_fuel`) — 이 `failed`다.
    진행 중(running, 24시간 안에 시작)인 Dagster 유가 실행이 하나도 없다.
  - 기록: `last_error`에 고정 문장 `실행 소실: …(회수 sensor 기록).`을 남긴다. `last_success_at`·`next_due_at`은 그대로다.
  - 경합: PostgreSQL에서는 유가 수집기의 advisory lock(`420040 + 1`)을 `pg_try_advisory_xact_lock`으로 먼저 잡는다.
    수집기가 claim·저장 중이라 못 잡으면 그 tick은 건너뛴다(기다리지 않음). 갱신은 읽은 claim 그대로이고 결과가 여전히
    없으며 진행 중인 유가 실행이 없을 때만 한다(CAS + `NOT EXISTS`, `lock_timeout=1s`). 그래서 그 사이의 새 claim·성공·
    실패를 덮지 않는다. 늦게 도착한 실패 처리는 원래 오류 문장으로 이 값을 덮는다.
  - 시점: 회수가 그 tick에 run 행을 `failed`로 닫으면(Dagster run terminal이면 즉시, Dagster 기록이 없으면 5시간 grace)
    같은 tick에서 바로 기록한다. 실패 기록 commit 자체가 실패한 실행(run 행은 `failed`, 상태 행에 오류 없음)도 같은
    규칙으로 잡는다. 주인이 정상 종료(`success`·`skipped`·`partial_success`)했으면 판단하지 않는다.
  - 효과는 실패 1회와 같다. T1 export는 200 그대로이고 `collection.last_attempt_failed=true`만 바뀐다(503 사유가 아니다).
    T4 `source_status=stale`, 공개 상태 `fuel_prices_stale=true`·`last_error=collection_failed`(고정 코드)가 된다. 관리
    화면 수집 상태는 `error_code=collection_lost`와 "실행 소실" 문구로 원인 미상 실패와 구분한다. 관리 화면의 Dagster 실패
    진단은 run monitoring의 작업자 소실 메시지를 `RUN_WORKER_LOST`로 분류해 재시도 안내를 준다.
- **관리자 재시도**: 재시도 경로(`collect(retry_failed_fuel=True)`)도 같은 규칙(`lost_fuel_claim_owner`, 자기 실행 제외)으로
  소실을 직접 본다. 그래서 sensor가 기록하기 전이라도 회수가 run 행을 닫은 뒤라면 재시도가 예약을 옮기지 않고
  체크포인트에서 이어 한다. **남은 창**: Dagster run은 끝났지만 회수가 아직 run 행을 닫지 않았으면(다음 sensor tick
  전, 약 1분. Dagster 기록이 없는 run은 5시간 grace 동안) 서비스는 그 실행이 살아 있는지 알 수 없어 재시도를 여전히
  호출 유예로 건너뛴다. 이때는 1분 뒤 다시 재시도하거나, Dagster 기록이 없는 run이면 다음 정기 tick을 기다린다.
  재시도가 다시 소실되면 상태 문장은 직전 실패 문장 그대로다(실패로는 보이고 재시도도 된다).
- **유가 신선도 단계**(`recovery.evaluate_fuel_freshness`): 오피넷(`opinet_browser`)과 휴게소 유가(`krex_rest_area_fuel`)
  상태 행의 마지막 성공 나이로 정한다. 성공 이력이 없으면 판단하지 않는다(export가 이미 503이다).

  | 단계 | 조건 | 오피넷 | 휴게소 유가 |
  |---|---|---|---|
  | `warning` | 나이 > 2주기 **이고** 마지막으로 **끝난** 시도가 실패 | 16시간 | 8시간 |
  | `critical` | 나이 > export stale 기준(`REFERENCE_STALE_AFTER`)의 80% | 기준 × 0.8(24시간이면 19.2시간) | 9.6시간 |
  | `expired` | 나이 > export stale 기준 — **export가 지금 503** | 기준(24시간이면 24시간) | 12시간 |

  "마지막으로 끝난 시도가 실패": claim은 이전 오류를 지우지 않으므로 오류가 남아 있어도 그 원천의 정기 실행이 진행 중
  (running)이면 실패로 세지 않는다. 그래서 실패 **1회** 뒤 다음 정기 실행이 수집 중인 동안에는 경고하지 않는다. 다음
  실행이 큐에서 오래 기다려 시작 전이면 직전 실패가 그대로 "마지막 시도"다 — 그 사이 나이가 2주기를 넘으면 경고한다.
  유가는 연속 2회 실패(16시간)가 "다음 실패면 export 503"의 선행 신호다. 위험·만료는 실패 여부와 무관해 수집이 멈춰도
  잡는다. 위험·만료 기준은 `REFERENCE_STALE_AFTER`를 그대로 따라가므로 export 기준을 바꾸면 같이 바뀐다. 주기(8시간·
  4시간)는 schedule cron과 테스트로 묶었다.
- **경보에서 빼는 원천**(`paused`): provider가 설정에서 꺼졌거나(오피넷 `transport_collection_enabled`·`opinet_browser_enabled`,
  휴게소 유가 `rest_area_collection_enabled`·`KEX_EX_API_KEY` — 관리 화면 `enabled`와 같은 조건) 그 schedule
  (`fuel_collection_job_schedule`·`rest_area_fuel_price_collection_job_schedule`)이 STOPPED면 경보하지 않고 sensor 로그에
  "유가 신선도 경보에서 제외" 한 줄만 남긴다. schedule 상태 확인은 경고 이상일 때만 하고, 확인이 실패하거나 예산이 없으면
  경보 쪽(감시 중)으로 본다.
- **경보 줄**: `_alert_stall`과 같이 고정 event 이름 한 줄을 Dagster sensor tick 로그와 code-server stderr(logger
  `app.dagster.recovery`)에 남긴다. 정체가 아니라서 정체 시계(`stall:` cursor)를 건드리지 않는다. 형식(검색 기준):

  ```text
  transport_fuel_freshness.warning source=<원천> age_seconds=<n> last_success_at=<UTC ISO> cause=<lost|failed|running|none> last_attempt_failed=<true|false> warning_after_seconds=<n> critical_after_seconds=<n> expired_after_seconds=<n>
  transport_fuel_freshness.critical source=<원천> …(같은 필드, error 수준)
  transport_fuel_freshness.expired source=<원천> …(같은 필드, error 수준 — export 503 중)
  transport_fuel_freshness.recovered source=<원천> age_seconds=<n> last_success_at=<UTC ISO> previous=<warning|critical|expired>
  transport_fuel_freshness.lost_attempt source=opinet_browser collection_run_id=<id|none> orchestrator_run_id=<Dagster run ID|none> last_started_at=<UTC ISO>
  transport_fuel_freshness.check_failed step=<lost_attempt|levels> error=<형식이름[:SQLSTATE]>
  transport_fuel_freshness.report_failed
  ```

  - `cause`: `lost`(실행 소실), `failed`(실패 기록), `running`(정기 실행 진행 중), `none`(실패 기록도 진행 중인 실행도
    없음 — 수집이 돌지 않는다. schedule·daemon을 본다).
  - 반복: 단계가 바뀌면 바로, 같은 단계는 3600초마다 다시 남긴다. `lost_attempt`는 claim마다 한 번이다. 줄은 이번 tick의
    기록 여부가 아니라 상태 행(`실행 소실` + 주인 failed + 진행 중 없음)에서 만들므로, 기록한 tick에 예산이 모자라 못 남긴
    줄도 다음 tick에 남긴다.
  - 기억: 경보 기억은 code-server 프로세스 안에 있고, 줄을 두 곳에 다 남긴 **뒤에** 반영한다. 로그 기록이 실패하면
    `report_failed` 한 줄을 남기고 그 줄은 다음 tick에 다시 만든다. 재시작하면 기억이 비어 현재 비정상 단계·소실을 한
    번 더 남긴다. 재시작 사이에 회복했으면 `recovered` 줄은 없다 — 그 원천의 경보 줄이 3600초보다 오래 없으면 정상이다.
  - 점검 실패: 소실 기록과 단계 판정은 따로 끊고(각 10초) 따로 실패한다. 소실 기록이 실패해도 위험·만료 판정은 한다.
    실패한 단계는 `check_failed step=…` 한 줄만 남기고 회수·정체 판정은 계속한다. 판정을 하지 못한 tick(실패·예산 부족·
    앞 단계 DB 장애)은 단계 기억을 바꾸지 않는다 — 회복으로 보지 않는다.
  - 예산: 유가 점검은 회수 **뒤에** 돈다. 회수는 단계 여유(25초)가 남을 때까지 먼저 쓰고, 유가 점검은 남은 예산이 판정
    상한(10초)을 넘을 때만, 소실 기록은 두 상한의 합(20초)을 넘을 때만 한다(판정 우선). 그래서 회수가 굶지 않는다. 회수
    backlog가 예산을 다 쓰는 tick에는 유가 점검을 건너뛴다(기억은 그대로, 다음 tick에 본다). 정상 운영에서 유가 점검은
    문장 3~7개(밀리초)다. 회수가 metadata 장애로 실패해도 유가 점검은 하고 그 예외를 다시 올린다.

  대응: `warning`이면 마지막 실패의 원인(Dagster run의 `error_code`)을 확인하고, 일시 오류면 관리자 "재시도"를 쓴다.
  `critical`이면 export 503까지 남은 시간이 기준의 20% 이하다(오피넷 24시간 기준이면 4.8시간). `expired`면 export가 이미
  503이다(Map은 자기 `max_age` 안에서 직전 세대를 계속 낸다). `lost_attempt`·`cause=lost`는 실행이 결과 없이 끝났다는
  뜻이므로 code-server·run worker 재시작·배포 이력을 보고 관리자 "재시도"로 같은 회차를 이어 한다.
- **휴게소 유가 run의 소실**(기록하지 않음): 휴게소 유가는 실패 여부로 다음 실행을 막지 않는다(4시간마다 정기 실행, 예약
  없음). 그래서 run이 op 밖에서 죽어도 다음 tick이 그대로 다시 한다. 그 사이 결과는 이렇다. 상태 행은 직전 성공
  (`last_error=None`)이라 관리 화면은 성공 배지인데 Dagster run은 실패다. T1 `rest-area-fuel-prices`의
  `last_attempt_failed`는 false다. 실패 기록이 없으므로 `warning`(실패 조건)은 뜨지 않고, 소실이 이어져 성공 나이가
  9.6시간·12시간을 넘으면 `critical`·`expired`(`cause=none`)로만 잡힌다.
- **하지 않는 것**: 경보에 따른 자동 추가 유가 run은 만들지 않는다. 오피넷 호출 정책(ADR-013 하루 3회·8시간 tick,
  provider 호출 유예)은 소유자 결정이다. 경보 채널(Manager·운영 알림, Dagster plane 밖)도 아직 붙이지 않았다 — 지금은 위
  로그 줄이 유일한 신호다.
- **제안(소유자 결정 대기) — 신선도 보호 재시도**(감사 G1-F4 (b)): 마지막 시도가 실패했고 마지막 성공 나이가 16시간
  이상이며 진행 중인 유가 run이 없으면, 이 sensor가 다음 tick 전에 체크포인트 재개 run(`retry_failed_fuel=True`, 예약
  보존)을 한 번만 띄운다. 연속 2회 실패 뒤 세 번째 정기 시도까지 기다리는 동안 생기는 503 틈을 줄인다. 다만 하루 3회
  상한을 넘는 오피넷 브라우저 세션이 생길 수 있어 ADR-013 개정과 소유자 승인 없이는 구현하지 않는다. 구현한다면
  `lost_attempt`와 `warning` 판정을 그대로 조건으로 쓰고, 같은 claim에는 한 번만 띄우며(claim 시각을 run 태그로),
  관리자 재시도와 같은 `kortravel/admin-retry-of` 경로를 쓴다.

공항 일부 실패도 성공분을 commit한 뒤 Dagster FAILURE로 표시한다. 자동 인프라 재시도
1회는 공항·고속도로·휴게소 기준정보만 허용한다. provider 실패·KRIC 마지막 시도 48시간·
버스 성공 72시간·철도 성공 48시간·과금/유가 receipt 보호는 그대로 유지한다.
수동 재실행도 이 보호를 우회하지 않는다. 보호가 끝나면 정기 tick이나 Dagster Re-execute로
누락 범위를 보충한다. 기존 정상 데이터 삭제·전국 재수집은 복구 절차가 아니다.

## 5분 수집 phase와 Common Python pin

후보는 Common Python `41b672c562c059a1f41f459925364459e320bc16`의
[고정 phase·복구 채택 가이드](https://github.com/digitie/kor-travel-common/blob/41b672c562c059a1f41f459925364459e320bc16/docs/runbooks/dagster-adoption.md)를
따른다. `staggered_cron(interval_minutes=5, phase_minutes=1)`은 공항을
KST 매시1·6·11…56분에, phase3은 고속도로를3·8·13…58분에 예약한다.
각각 하루288회이며 자정·월말·연말·윤일을 넘어 간격300초를 유지한다.
두 예약의 시작을2분 벌리는 변경이며, 실제 run 실행 시간이 길면 서로 겹칠 수 있다.

동일 job active/pending coalescing, project/job/run_group 태그, 실행 상한(2026-11-24부터 공항 30분·고속도로 20분),
step 동시성1, resources, provider 호출·유예·일일 예산은 그대로다.
다른 schedule·sensor의 실행 주기나 공용 coordinator 한도를 변경하지 않는다.

이 pin은 복구 의미도 포함한다. 기존 명시적 worker 인프라 종료 외에,
`DagsterSubprocessError`와 순수 framework `ChildProcessCrashException`
step 증거를 모두 확인한 장애를 멱등 job3개에서만 최대1회 재예약한다.
provider/user step 실패가 한 건이라도 섞이거나 증거가 없으면 재예약하지 않는다.
step 이력은100개씩 끝까지 검사하고 시간 예산이 부족하면 cursor를 다음 tick에 잇는다.
기존 native retry 인계·중복 key·선택 실행 보호와 consumer DB lease는 유지한다.

각 retry sensor evaluation은 실패 parent를100개까지 읽지만 첫 RunRequest를 만들면 즉시
반환하므로 요청은0/1개다. sensor3개 전체에서는 서로 다른 job에 최대3개 요청이 가능하다.
최대1회 예산은 failed parent당 제한이며 job의 전체 queued 개수 상한을 뜻하지 않는다.
활성 조회는 이미 저장된 QUEUED/STARTING/STARTED/CANCELING을 확인한다.
아직 저장되지 않은 RunRequest·NOT_STARTED 창·수동/예약 발화의 경쟁은 원자적으로 묶지
않는다. coordinator의 job limit1은 실행 동시성을, DB lease는 중복 provider 게시·호출을
보호하며 queue 길이1을 보장하지 않는다. 운영에서 cursor·후보 이력을 보존하고
sensor 요청·queued/running 수·provider 실제 호출과 lease 결과를 구분해 관측한다.


새 factory는 기존 FAILED 이력도 순회하므로 이전 pin에서 제외한 과거의 증명된
child crash가 새 복구 후보가 될 수 있다. sensor 복원 전 기존 cursor와 대상 실패 이력,
run config·provider receipt·이미 발급된 retry child를 확인하며 임의 cursor 초기화로
과거 이력을 숨기거나 provider 보호를 우회하지 않는다.
`call_with_deadline`, coalescing, reconciliation factory의 구현은 이전 pin과 같다.

Transport 앱은 Common `bounded_request`를 호출하지 않으며 기존 provider HTTP 구현도
이번에 옮기지 않는다. Common HTTP는 신규 선택 모듈이고 Python `http` extra도 추가하지
않는다. `dagster_health`도 이번에 채택하지 않으며 tracked Compose와 운영 HC의 차이는
별도 배포 입력 검증 대상이다.

소스의 예약 총량 보존은 운영 관측 수·지연·CPU 감소를 증명하지 않는다.
배포 시 기존 instigator 상태와 sensor cursor, 마지막 관측 시각/CollectionRun을 보존하고
기존 worker를 drain한 후 원래 running 상태만 복원한다. 전환 시각에 따른 첫 tick 공백도
관측하며, 배포 직후와 정상5분 주기 구간의 provider 호출 수·관측 시각·queue/start 지연·
CPU/RSS·다른 location health를 같은 길이의 전후 창으로 비교한다.
두 예약이 분리되었어도 실행시간이2분보다 길면 CPU peak가 겹칠 수 있다.
실측 악화 시 원인과 provider 보호 상태를 확인하고, 수집 주기·동시성을 임의로 낮추지 않는다.

## 실제 instance와 배포 순서

공용 운영은 Manager instance YAML을 사용한다. 소비자의 `backend/dagster_home/dagster.yaml`
변경은 전용 instance에만 적용된다. 읽어 확인한 shared 설정은 monitoring enabled,
start/cancel 600초·전역 6시간이며 native retry/coordinator 설정은 없었다. native retry가 꺼져
있을 때 공통 인프라 retry sensor 3개가 명시적 worker 종료만 1회 재예약한다. 같은 run의
step 실패·원인 불명·취소는 제외한다. native retry를 켜면 fallback은 pending 인계를 마무리하고
새 실패를 native에 위임한다. project transport
limit 3과 common job별 limit 1 및 기존 run_group 제한도 shared coordinator에 적용해야 한다.
Manager coordinator 설정·운영 shared daemon의 실제 worker kill/retry child/RSS 검증은 별도 운영 작업이다.

1. 별도 테스트 DB에 `alembic upgrade head`·`alembic check` 실행.
2. provider 보호 상태/최근 관측을 기록하고 새 스케줄 발화를 멈춘 뒤 worker drain.
3. 운영 DB에 추가 migration 적용, code-server 후보 배포, location reload 및 recovery sensor 확인.
4. shared instance 설정을 읽어 위 조건 확인, 스케줄을 복구한다.
5. active 오래된 실행·CollectionRun terminal·다른 location health와 provider receipt를 관찰한다.

## 메모리와 관리자 UI

배편 재사용 조회는 전체 시간표 JSON 대신 날짜·항구·시각·DB JSON 길이만 읽는다.
장소 보강은 100개 ID와 현재 시설 한 행, KRIC는 호출 예산 수만큼 후보를 보유한다.
provider 목록은 100페이지/50,000행을 넘으면 저장 전 실패하여 무한 페이지 누적을 막는다.
이는 Python 구조 상한이며 전체 운영 RSS를 보장하는 실측 값은 아니다.

공통 LoginForm/AppMenu/DagsterOperations와 tokens를 vendored tarball로 사용한다.
최근 30건 밖의 active run도 별도로 조회·중복 제거하고 runtime tag로 정체를 표시한다.
실패 상세는 소유 location+UUID, 1000 event 페이지/최대20페이지/15초/최근3개로 제한한다.
GraphQL proxy는 인증·Origin·허용 작업을 유지하고 요청 4KiB·응답 4MiB·10초 본문 제한을 적용한다.

## 검증 기록

최종 candidate SHA, CI, 두 독립 적대 리뷰, n150 live UI 결과는 이 PR의
`docs/reviews`와 `docs/journal.md`에 기록한다. 운영 shared 제어 평면 적용 여부를 격리 후보
검증과 구분하며, 실행하지 않은 운영 배포 검증을 PASS로 집계하지 않는다.
