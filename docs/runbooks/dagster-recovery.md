# Transport Dagster 중단 복구

Weather PR #72의 개선과 common PR #24·#25 Python 코어를 채택한다.
공용 가이드: https://github.com/digitie/kor-travel-common/blob/main/docs/runbooks/dagster-adoption.md

## 구조와 호출 보호

각 job은 4시간 실행 상한, step 동시성 1을 유지한다. common의 project/job 태그와
coalescing schedule은 같은 location의 pending/active 실행이 있으면 새 예약을 합친다.
collector pool은 2 connections와 overflow 0으로 제한한다. 한 connection은 기존 session
advisory lease, 다른 하나는 부분 게시 transaction에 필요하다. DB 접속 10초, 문장 60초
(asyncpg `command_timeout` 클라이언트 측 + 서버 `statement_timeout` 60초, 2026-10-21부터 둘 다),
lock 5초와 async action 14340초 제한을 적용한다. provider public cancellation 계약을 사용한다.
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
  timeout 모두 5초다. 예산을 넘겨 끊긴 thread는 `context`를 더 쓰지 않고 metadata도 더 부르지 않는다.
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
  5분 수집 schedule을 일부러 멈추면 같은 경보가 난다(수집이 실제로 멈췄으므로 의도된 동작).
  실패 중에 sensor를 오래 멈췄다가 다시 켜면 옛 `first_failed_at` 때문에 첫 실패에 바로 경보할 수
  있다. 원치 않으면 다시 켜기 전에 sensor cursor를 지운다(UI 또는 `dagster sensor cursor --delete`).
- **이 경보가 다루지 못하는 것**: code-server gRPC 자체가 멈추면(2026-09-27 11:53Z~19:51Z 정지)
  sensor 평가도 같은 프로세스에서 하므로 경보할 주체가 없다. 그 경우는 code-server healthcheck
  probe가 연속 timeout 300초(실행 중인 run worker가 있으면 7200초) 뒤 PID 1을 종료해 재시작시키는 것이 회복 경로다
  (`docker-compose.shared.yml`·`transport.override.yml`의 `x-dagster-code-server-probe`).
  재시작 뒤 수집이 돌아오지 않으면 이 sensor가 20분+900초 뒤 경보한다.

공항 일부 실패도 성공분을 commit한 뒤 Dagster FAILURE로 표시한다. 자동 인프라 재시도
1회는 공항·고속도로·휴게소 기준정보만 허용한다. provider 실패·KRIC 마지막 시도 48시간·
버스 성공 72시간·철도 성공 48시간·과금/유가 receipt 보호는 그대로 유지한다.
수동 재실행도 이 보호를 우회하지 않는다. 보호가 끝나면 정기 tick이나 Dagster Re-execute로
누락 범위를 보충한다. 기존 정상 데이터 삭제·전국 재수집은 복구 절차가 아니다.

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
