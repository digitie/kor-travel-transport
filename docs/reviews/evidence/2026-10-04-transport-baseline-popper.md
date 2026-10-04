# transport baseline 적대적 감사 원본 — Popper

- 실행 ID: POPPER-TRANSPORT-BASELINE-20261004-01
- 시작: 2026-10-04T13:57:42.7138992+09:00
- 소스 검토 종료: 2026-10-04T14:04:05.0776111+09:00
- 대상: `e00e634b8502cdd1060d735b250ece96fd9fc945` (transport 기존 기준점)
- 비교 참고: weather `8ed94e744b89b0b3ffbc088441d7089068f5ae40`, common `090f98429453d8882150eb9e56ccae98e0e353a2`
- 격리: Windows Git `show`/`grep`/`ls-tree`로 고정 객체만 읽었다. 구현자가 편집하는 작업트리 소스, 다른 리뷰어 결과를 읽거나 수정하지 않았다. 이 원본 evidence 파일만 생성한다.
- 규칙: 대상 객체의 AGENTS.md, CLAUDE.md, SKILL.md, hostile-review.md와 ADR-009를 확인했다. Backend/PostgreSQL/ops 관점이다.
- 검증: 정적 제어 흐름·트랜잭션·쿼리 검토. 아래 재현은 실행할 실패 시나리오이며 실제 장애 주입, PostgreSQL 실행, pytest, CI, live UI를 수행했다고 주장하지 않는다. 최종 후보의 독립 PR 리뷰를 대체하지 않는다.

## 판정

**BLOCK — 현재 baseline은 요청한 자동 복구·늦은 게시 차단·중복 schedule 억제를 충족하지 않는다.** P0 확정 지적은 없다. P1 네 항목은 개선 후보에서 해결해야 한다. P2 두 항목은 메모리/대기 예산 설계에 반영하거나 명시적 판단을 남겨야 한다. 기존 기준점의 승인 이력을 소급 부정하는 판정은 아니다.

## 지적

### B-P1-01 — 강제 종료 후 앱 running 실행을 자동 회수할 소유권이 없다

- 위치: `backend/app/models.py:85–94`; `backend/app/services/transport_collection.py:352–407`; `bus_collection.py:97–99`; `kric_collection.py:62–64`; `rail_maritime_collection.py:463–471`; `rest_area_collection.py:103–108`; `place_locations.py:141–143`; `kakao_place_locations.py:100–102`.
- 근거: CollectionRun에는 owner/heartbeat가 없다. 대부분 서비스는 running을 먼저 commit하지만 프로세스 종료 시 후속 terminal commit은 실행되지 않는다. `backend/dagster_home/dagster.yaml`의 run monitoring은 Dagster metadata만 정리하며 앱 행을 terminalize하지 않는다. 수동 reconcile 스크립트는 highway/fuel만 대상으로 하고 자동 sensor가 아니다.
- 실패 시나리오: running commit 직후 SIGKILL → Dagster는 monitoring으로 FAILED → 앱 collection_run은 계속 running. 이후 성공 실행이 생겨도 옛 행은 그대로 남는다. heartbeat 없이 시간만 기준으로 정리하면 정상적인 긴 fuel 수집도 실패로 오인한다.
- 영향: UI/운영 상태가 서로 어긋나고 중지된 실행 복구 여부를 확정할 수 없다.
- 최소 권고: 기존 행을 nullable migration으로 보존하며 owner_run_id, heartbeat_at을 도입한다. 서비스 시작 행을 Dagster owner에 결속하고 heartbeat는 별도 짧은 세션으로 갱신한다. sensor는 소유 Dagster run의 terminal 상태를 확인하여 running+owner+관측 heartbeat CAS로 정리한다. metadata outage를 실패로 간주하지 말고, metadata가 없을 때만 별도 lease 만료 정책을 적용한다. healthy STARTED를 단순 오래됐다는 이유로 회수하지 않는다. keyset 페이지와 tick 예산으로 오래된 정상 첫 페이지가 뒤쪽 실패 행을 영구 굶기지 않게 한다.

### B-P1-02 — reaper 추가만으로는 늦게 돌아온 worker의 게시를 막지 못한다

- 위치: `transport_collection.py:442–503`; `bus_collection.py:115–117,200–204`; `kric_collection.py:112–124`; `rail_maritime_collection.py:302,477–488`; `rest_area_collection.py:136–152`; `place_locations.py:225,265–291`; `kakao_place_locations.py:194,229–257`; `backend/app/db/session.py`의 일반 AsyncSession factory.
- 근거: 서비스들은 원본 ORM run의 status를 직접 변경하며 중간 결과/receipt/state를 여러 번 commit한다. DB 소유권을 확인하는 게시 fence가 없다. baseline 자체에는 자동 reaper가 없으므로 아래는 **자동 복구를 추가할 때 반드시 닫아야 할 경쟁 조건**이다. 현재 수동 스크립트가 살아 있는 worker를 확인하고 거절하는 방어를 무시해 안전하지 않다고 주장하지 않는다.
- 실패 시나리오: 외부 호출 중 worker 정지 → reaper가 failed commit → provider가 뒤늦게 반환 → 원 worker가 데이터와 source freshness/좌표/receipt를 commit하고 마지막에 success로 덮어씀. 종료 예외 handler도 failed 상태와 collection_state를 무조건 commit하여 새 owner 결과를 덮을 수 있다.
- 영향: 복구된 실행이 다시 success가 되거나 오래된 응답이 새 결과를 훼손한다. 요청한 늦은 commit 차단 계약 위반이다.
- 최소 권고: collector 전용 session을 도입해 **모든 게시 transaction**에서 DB run 행을 SELECT FOR UPDATE하고 running+owner를 실제 DB 값으로 검사한다. 검사와 commit은 같은 transaction이어야 한다. ORM identity map 값 또는 transaction 바깥 사전 검사로 대체하지 않는다. autoflush/direct SQL DML/중간 receipt commit/최종 status 변경까지 포함해야 한다. terminal status를 로컬 ORM에 먼저 설정해도 기존 DB running 상태를 no-autoflush로 확인해야 한다. 소유권 상실 시 rollback하고 예외 handler의 추가 게시도 차단한다. heartbeat/reaper 세션은 이 게시 session과 분리한다. 다른 서비스나 API가 이 fence를 우회해 owned run을 게시하지 않는지 최종 후보에서 전체 호출 경로를 재검토해야 한다.

### B-P1-03 — airport 실패를 Dagster SUCCESS로 보고하며 종료 추적 행도 durable하지 않다

- 위치: `backend/app/dagster/definitions.py:58–60`; `backend/app/services/collection.py:441–443,499–522,541`.
- 근거: airport op는 서비스 결과를 그대로 반환한다. `_safe_fetch`로 수집한 provider 오류는 service status failed/partial_success가 되지만 예외가 아니므로 Dagster SUCCESS가 된다. 반면 highway/fuel op는 이 결과에 Failure(allow_retries=False)를 발생시킨다. airport의 시작 run은 flush만 하고 provider IO 전 commit하지 않으며, 예외 시 rollback 후 새 failed run을 만든다.
- 실패 시나리오: KAC 오류만 발생하고 Incheon 비활성 → service failed를 commit → airport Dagster run은 SUCCESS. 또는 시작 flush 후 SIGKILL → transaction rollback으로 collection_run 자체가 사라짐 → 앱 sensor가 중지된 실행을 찾을 수 없음.
- 영향: 실패 감지/로그/복구 판정이 불완전하다.
- 최소 권고: airport도 저장된 failed/partial_success 결과를 보존한 후 Dagster Failure로 전달한다. 호출 전에 원본 owned run을 durable하게 만들고 예외 처리도 그 행을 조건부 terminalize한다. 기존 성공 원천 보존, rate-limit skip, 오류 가림, 주차 unique/savepoint 계약을 유지한다. run 등록 commit 때문에 기존 데이터 atomicity가 달라지는지 명시하고 검증한다.

### B-P1-04 — 5분 schedule이 오래 걸리는 실행 동안 계속 큐를 추가한다

- 위치: `backend/app/dagster/definitions.py:28–31,292–308`; `backend/dagster_home/dagster.yaml`의 QueuedRunCoordinator.
- 근거: plain ScheduleDefinition은 매 tick 생성한다. concurrency limit 1은 실행 수만 제한하고 새 queued run 생성을 막지 않는다. runtime은 모든 job에 4시간이다. 5분 airport/highway는 긴 실행 한 번 동안 약 48개 tick을 생성할 수 있다. 실제 enqueue 개수는 daemon availability/tick 정책에 따라 다르다.
- 실패 시나리오: provider 지연으로 한 run이 장시간 STARTED → 같은 job의 QUEUED 증가 → 종료 후 오래된 run을 순차 시작/skip. app advisory lock이나 due guard는 worker 시작 후 작동하므로 launcher/DB/metadata 부하를 막지 못한다.
- 영향: 불필요한 worker 비용과 backlog로 복구가 느려진다. shared Dagster 환경에서는 다른 작업의 제한된 실행 슬롯에도 영향을 줄 수 있다.
- 최소 권고: common coalescing_schedule을 사용해 QUEUED/STARTING/STARTED/CANCELING을 project+job+code location 경계로 확인한다. 기존 run_group tag는 shared manager concurrency 계약이므로 그대로 유지한다. native infra retry는 Dagster instance의 run_retries 활성화와 tags 양쪽을 확인하고, 검증된 멱등 job만 제한 횟수 opt-in한다. asset/op Failure 자동 재시도로 provider cooldown을 우회하지 않는다. 실제 운영은 shared manager 설정이므로 transport 저장소 YAML 수정만으로 배포 적용을 주장하면 안 된다.

### B-P2-01 — 호출 예산과 별개로 전체 대상/과거 JSON을 메모리에 적재한다

- 위치: `rail_maritime_collection.py:224–238`; `place_locations.py:147–169`; `kakao_place_locations.py:106–149`; `bus_collection.py:136–140`; `rail_maritime_collection.py:344–346`.
- 근거: ferry는 10일 범위의 snapshot ORM 전체와 items_json을 한 번에 로드한다. 좌표 서비스는 missing ORM 전체, 전체 catalog 이름 Counter, 전체 interleaved targets를 만들고 list.pop(0)으로 O(n²) 이동을 한다. 실제 하루 호출 수가 작아도 preload는 줄지 않는다. bus는 최대 100페이지×100개를 list comprehension 후 tuple로 복사하고 maritime는 각각 20페이지인 세 provider 목록을 동시에 보유한다.
- 실패 시나리오: 기존 snapshot payload 또는 누적 catalog가 커짐 → 소수만 실제 호출해도 RSS/초기 CPU가 증가. 확정 OOM이나 현재 운영 RSS 수치는 측정하지 않았다.
- 권고 우선순위: ferry는 source/port/date/collected_at/item_count projection만 읽고 실제 갱신 row만 로드한다. 좌표는 ID keyset page로 후보를 가져오고 이름 유일성은 SQL 집계/조회로 확인한다. bus/port 교대·호출 예산·manual 재확인을 유지한다. 단순 deque만으로 CPU는 개선돼도 전체 적재 메모리는 남는다. provider iterator는 batch 처리하고 summary count만 유지한다. 하나의 provider 응답이 원래 전체 snapshot인 fuel/traffic는 무조건 쪼개는 대신 불필요한 복제와 응답 수명을 먼저 줄인다. 부분 chunk를 complete freshness로 표시하면 안 된다.

### B-P2-02 — collector SQL 대기 예산이 run 상한보다 훨씬 느슨하다

- 위치: `backend/app/db/session.py:29–39`; `transport_collection.py:344`; `place_locations.py:203`.
- 근거: collector engine에 명시적 PostgreSQL lock_timeout/statement_timeout이 없으며 pg_advisory_xact_lock은 대기한다. DB/driver 자체 기본 연결 timeout은 존재할 수 있으므로 모든 연결이 무한이라고 단정하지 않는다. run의 4시간 monitoring은 수집 SQL이 오래 막히는 것을 빠르게 회복하는 경계가 아니다.
- 실패 시나리오: 다른 세션이 advisory 또는 publish row lock을 오래 보유 → worker/heartbeat/reaper가 지연. 무턱대고 같은 기본 timeout을 모든 DB 경로에 넣으면 통계 재계산/마이그레이션도 실패할 수 있다.
- 권고: collector와 recovery DB 호출에 각각 명시적인 connect/lock/statement 예산을 적용한다. CPU/SQL 집계 작업을 수용하는 값으로 정하고 timeout을 rollback 가능한 실패로 분류한다. heartbeat 장애만으로 healthy Dagster worker를 회수하지 않는다. async provider는 asyncio cancellation/timeout 경계를 사용하고 취소를 무시하는 동기 deadline worker를 무제한 생성하지 않는다.

## 서비스별 유지할 계약

| 서비스 | run/guard 및 기존 게시 | 재실행·저메모리 변경 시 보존할 계약 |
| --- | --- | --- |
| Airport | 프로세스 lock+전용 연결 session advisory lease. 시작 run 미커밋, 전체 수집 후 commit. | `(lot, observed_at, source)` unique/savepoint; 원천 성공분/요금 upsert; KAC rate limit에도 Incheon 독립 수집. owned 시작 행만 먼저 commit하고 실패를 같은 행으로 추적. |
| Highway/Fuel | group별 process/advisory transaction lock, 실행+next_due 예약을 HTTP 전에 commit. source별 독립 commit. highway 240초, fuel 2시간 내부 상한. | ADR-009 예약을 종료/재시도로 지우지 않는다. provider IO 동안 DB transaction을 유지하지 않는다. traffic 보정/최근 통계, incident 완전한 최신 활성 집합, fuel 전체 snapshot/최신 materialization은 source 게시 단위로 보존한다. 실패/부분 성공 후 native retry가 due guard로 skip하는 것은 예산 보호 계약이다. |
| Bus | session advisory lease; 최근 성공 72시간 guard; 시작 run durable, terminal/city/class 전체 게시 후 success. | source/service/terminal natural identity, 이름/도시 unchanged면 manual 좌표 보존. iterator batch는 가능하되 실제 partial commit을 도입하면 기존 전체 게시 계약을 문서화한다. |
| Rail/Maritime | 시작 run durable; rail 성공 48시간 guard. maritime 목록/좌표 receipt를 사용. rail/maritime 자체에는 bus와 같은 전용 cross-process lease가 없다. | provider 파일 public API/RustFS 경계 유지. port 좌표 pending 예약은 HTTP 전에 durable; success 30일·실패 1일 TTL, 하루 cap/rate-limit guard를 bypass하지 않는다. native retry는 공백 채우기이지 호출 예약 삭제가 아니다. |
| Ferry | 시작 durable; 10일 범위 정리 먼저 commit; 오늘 전체 항구 우선, 재사용/예산/연속 network failure 3회 종료; 각 snapshot commit. | `(source, port, date)` unique/upsert; 이미 성공한 snapshot 유지. 실패한 응답으로 기존 정상 items_json을 비우지 않는다. 재시도는 빠진 범위만 채운다. |
| KRIC | session advisory lease; 성공 여부와 무관한 최근 시도 48시간 guard; code/calendar 먼저 commit; station/day별 commit. | empty/duplicate/불완전 code 파일 전체 검증 전에 기존 code를 비활성화하면 안 된다. station/day 응답 identity 검증, 성공 station 보존, missing/old/link priority와 호출/3시간 예산 유지. 즉시 retry skip은 의도된 guard다. |
| Rest area/reference/fuel | 시작 run/state durable; provider 전체 페이지 후 저장, empty 결과 거절; final state/run commit. | natural identity/upsert와 0개 성공 금지 유지. source freshness를 전체 검증 전에 갱신하지 않는다. 작은 reference 응답의 무조건 chunk commit보다 fence가 우선이다. |
| Vworld/Kakao coordinates | session advisory lease; run durable; per-request pending receipt와 global budget reservation을 IO 전 commit; 응답마다 commit. | manual coordinates 재확인+row lock, 이름 유일성, bus/port 교대, TTL, 일/월 호출 cap 유지. Kakao key fingerprint가 다른 교체 키의 401/403 회복과 같은 키 429 제한을 구분하는 계약 유지. pending도 비용을 소비하므로 장애 retry에서 삭제하지 않는다. |

## 후보 검증 시 반드시 실행할 공격 시나리오

1. 각 service의 시작 commit 직후 worker kill: owner가 보존되고 앱 running이 terminal로 수렴한다. airport도 시작 행이 남는다.
2. 두 세션 barrier: provider 반환 직전 worker 정지 → reaper terminal commit → worker 재개. facts/raw/receipt/state/terminal status 어느 것도 옛 owner가 새로 commit하지 못한다. 예외 정리 경로도 검사한다.
3. publish lock을 worker가 먼저 얻은 반대 순서: reaper가 기다리고 commit 후 현재 heartbeat/state를 다시 확인하여 정상 성공을 실패로 덮지 않는다.
4. Dagster metadata outage/timeout, healthy long fuel run, missing owner metadata, legacy null owner 각각 분리한다. 앞 100개 healthy 실행 뒤에 failed 실행을 두고 paging 수렴도 검증한다.
5. 5분 중복 tick/수동 launch/infra retry가 겹쳐도 같은 job backlog가 억제되고, 다른 project/code location run을 잘못 차단하지 않는다.
6. provider 실패는 Dagster Failure로 표시하되 성공분/next_due/pending receipts는 유지한다. KRIC 48시간, bus/rail guard와 fuel 예약을 infra retry로 우회하지 않는다.
7. ferry 대형 JSON/좌표 수만 개 후보로 RSS와 호출 수를 함께 측정한다. stream/chunk 후 이름 유일성, manual coords, 오늘 항구 우선, source freshness 및 normalized 집계가 동일한지 확인한다.

## 불확실성

실제 shared manager Dagster 버전/config, scheduler tick 상태, PostgreSQL pool/메모리 한계, provider 실제 payload 크기는 이번 객체 감사에서 실행 확인하지 않았다. native infra retry의 실효성과 RSS 감소는 최종 immutable candidate의 테스트/운영 증거로 확인해야 한다. UI/common 패키지 설치/배포/provenance 및 migration upgrade/downgrade는 최종 후보 정식 리뷰 범위에 남아 있다.
