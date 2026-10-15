# Transport Dagster 중단 복구

Weather PR #72의 개선과 common PR #24·#25 Python 코어를 채택한다.
공용 가이드: https://github.com/digitie/kor-travel-common/blob/main/docs/runbooks/dagster-adoption.md

## 구조와 호출 보호

각 job은 4시간 실행 상한, step 동시성 1을 유지한다. common의 project/job 태그와
coalescing schedule은 같은 location의 pending/active 실행이 있으면 새 예약을 합친다.
collector pool은 2 connections와 overflow 0으로 제한한다. 한 connection은 기존 session
advisory lease, 다른 하나는 부분 게시 transaction에 필요하다. DB 접속 10초, statement 60초,
lock 5초와 async action 14340초 제한을 적용한다. provider public cancellation 계약을 사용한다.

`0024` migration 뒤 worker는 `CollectionRun`을 외부 호출 전에 commit하여 소유권을 남긴다.
소유 session은 ORM flush와 bulk SQL commit에서 기존 running/owner를 잠그고 heartbeat를
갱신한다. 회수된 worker의 늦은 게시·완료 덮어쓰기는 rollback된다. 부분 저장본은 유지한다.
rollback으로 ORM 상태가 만료되어도 소유권 fence를 유지한다. 권한 상실은 같은 op의
새 session에도 전파하고 다음 provider를 시작하지 않는다. 후속 op/session 시작 때 native
owner 생존을 10초 상한으로 확인하며 조회 장애는 provider 호출 전에 실패로 전달한다.
회수 sensor는 외부 provider 없이 stable ID keyset 100행씩 확인한다. Dagster terminal은
running 수집 기록을 failed로 회수하고, 없는 run은 5시간 grace·heartbeat CAS로 확인한다.
metadata 장애는 회수 사유가 아니다. legacy NULL owner 행은 자동 변경하지 않는다.

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

동일 job active/pending coalescing, project/job/run_group 태그, 4시간 실행 상한,
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
