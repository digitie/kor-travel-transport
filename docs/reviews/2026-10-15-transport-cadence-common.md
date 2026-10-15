# Transport 5분 phase와 Common Python 채택 검증

## 범위

기준 origin/main `15a928b07c7a30415cfa3d81ba5ee412e79981f5`.
브랜치 `agent/codex-transport-cadence-20261015`.
공항 phase1·고속도로 phase3 및 Common Python `41b672c562c059a1f41f459925364459e320bc16`
pin/lock만 런타임 변경 대상이다. 구현자는 다른 작업과 원본의 미커밋 변경을 되돌리지 않았다.
health 교체, graph cache, coordinator/동시성 하향, provider 정책 변경은 없다.

## 달력·실행 계약

실제 Dagster1.13.24의 cron iterator로 KST4일 창3개(평일·윤일·연말)를 평가한다.
각 job288회/일·300초 간격·자정 순환 간격을 보존하고 시작은 공항1분/고속도로3분,
두 job의 예약 교집합은0이며 쌍별 시작은2분 차이다.
이는 예약 달력이며 실제 provider 관측 수나 운영 CPU 감소율을 대신하지 않는다.

OLD immutable Transport15a928b+Common430a9e9 source archive에서 동일 회귀는
달력3 FAIL, 기존 executor/resources/tags/coalescing10 PASS였다.
최초 시험에는 QUEUED run의 origin을 생략한 fixture 오류2건이 추가로 있었고 원본 로그를 보존했다.
origin 보완 뒤 정정 OLD 결과를 따로 고정했다.
NEW 최초 표적은 달력/계약13 PASS와 실제 Transport retry sensor12 PASS다.
후속 focused 회귀는 checkpoint 재개/뒤 page provider 실패 거절2건과 parent native 예산/
pending 표식 검사를 포함한 retry sensor14 PASS다. 서로 다른 실행을 전체 suite 수에 합산하지 않는다.

## Common430a→41b 소비 영향

Common Python source delta를 직접 읽었다. 신규 `scheduling.py`27행을 채택한다.
`dagster.py`의 의미 있는 변화는 retry의 proven child-process crash 허용 및
step-history checkpoint 재개다. 단순 pin 교체나 순수 cron 변경만이라고 표현하지 않는다.

직접 소비는 `definitions.py`의 RecoveryPolicy/coalescing_schedule/
infrastructure_retry_sensor/reconciliation_sensor와 `recovery.py`의
call_with_deadline이다. deadline 모듈은 Git blob이 같으며 policy/coalescing/
reconciliation 함수 구현도 바뀌지 않는다. 앱 소유 CollectionRun 게시 fence·회수 SQL은 그대로다.

실제 Transport definitions의 멱등 airport/highway/rest_area_reference sensor를
Dagster local instance에서 평가했다. framework child crash는 기존 config와 job 태그로
1회 요청하며 재평가 run key가 같고 native max_retries는0이다.
provider/user 실패·crash+provider 혼합·step 증거 없음은 요청하지 않는다.
유가·철도·배편·과금/좌표 job을 retry 대상으로 추가하지 않았다.
각 retry sensor evaluation은 실패 parent를100개까지 읽지만 첫 RunRequest를 만들면 즉시
반환하므로 요청은0/1개다. sensor3개 전체에서는 서로 다른 job에 최대3개 요청이 가능하다.
최대1회 예산은 failed parent당 제한이며 job의 전체 queued 개수 상한을 뜻하지 않는다.
활성 조회는 이미 저장된 QUEUED/STARTING/STARTED/CANCELING을 확인한다.
아직 저장되지 않은 RunRequest·NOT_STARTED 창·수동/예약 발화의 경쟁은 원자적으로 묶지
않는다. coordinator의 job limit1은 실행 동시성을, DB lease는 중복 provider 게시·호출을
보호하며 queue 길이1을 보장하지 않는다. 운영에서 cursor·후보 이력을 보존하고
sensor 요청·queued/running 수·provider 실제 호출과 lease 결과를 구분해 관측한다.

새 factory의 FAILED 이력 순회에는 생성 시각 하한이 없으므로, 이전 pin에서 제외했던
과거의 증명된 child crash도 새 복구 후보가 될 수 있다. 새 장애만의 변화라고
표현하지 않는다. 운영 sensor 복원 전 기존 cursor·대상 이력·retry child·provider receipt를
확인해야 하며 임의 cursor 초기화로 이를 숨기지 않는다.
기존 consumer recovery 회귀는 부분 commit 보존·terminal owner fence·metadata 오류와
마지막 성공/시도 guard를 계속 검증한다.

신규 `http.py`110행도 전체 읽었다. identity encoding, 압축 거절, bounded body,
절대 timeout 및 짧은 close 예산, redirect/auth hook 제한을 가진 선택 API다.
Transport 앱과 현재 pin된 provider 패키지의 Python source에는 kortravelcommon.http
import가 없다. 기존 provider는 자체 HTTPX send/redirect 흐름을 사용한다.
이 PR은 HTTP factory를 채택하거나 provider를 wrapper로 감싸지 않으며 HTTP 동작 변화로
성과를 주장하지 않는다. HTTP extra 추가도 없다.
신규 dagster_health는 미채택이다. 운영 HC provenance와 tracked Compose 차이는 별개다.
Common 상류/Weather의 테스트 수를 본인 Transport 결과로 합산하지 않았다.

## 운영 및 후속 gate

실제 운영·SSH·수집·배포·merge는 수행하지 않는다. root PG15432에도 접속하지 않는다.
테스트는 운영 DATABASE_URL/TEST_DATABASE_URL을 제거하고 임시 SQLite를 강제한다.
steady-state5분 freshness와 달리 cutover 직후 첫 tick 지연은 전환 시각·drain에 좌우되므로
별도 비교하며 source만으로 무공백을 주장하지 않는다.

[채택 가이드](https://github.com/digitie/kor-travel-common/blob/41b672c562c059a1f41f459925364459e320bc16/docs/runbooks/dagster-adoption.md)와
[Transport 복구 runbook](../runbooks/dagster-recovery.md)을 따른다.
현재 상태·cursor·run UUID·최근 관측과 provider receipt를 보존한 뒤 drain/전환하고,
동일 길이의 전후 창에서 실제 호출 총량·최신 관측·queue/start 지연·CPU/RSS·다른 location health를
측정해야 한다. 실측 없이 peak 감소나 메모리 개선을 확정하지 않는다.

## 실행 결과

- 제품 commit `0860c948085797c78bb1c829e0fc5d41db61a244`에서 native 전체 **759 PASS / 10 SKIP**,
  1433.08초(23분53초), Python3.13.14. 이 실행에는 최초 표적25건이 포함된다.
- 뒤에 추가한 테스트/문서 변경에서 focused retry sensor **14 PASS**,3.61초.
  추가2건은 같은 실제 sensor의100개 step-history page checkpoint 재개와 다음 page의
  provider 실패 거절을 검증한다. parent `max_retries=0`/`will_retry=false` 및
  child에 pending 표식 미상속도 확인한다.
- `uv lock --check --offline`, OpenAPI export `--check` PASS.
- deadline Git blob은 두 pin에서 `4bc7421b5772a5a3e91560eb659b9b659147149e`로 동일하며
  RecoveryPolicy/coalescing/reconciliation/has_active_run은 AST가 동일하다.
- frontend native, Docker2차 전체와 canonical cwd 재검증, 최종 CI, 두 독립 적대 리뷰,
  운영 live/E2E·CPU/RSS/freshness 실측은 **NOT_RUN**이다.

전체 native759건은 제품086에서 수행한 결과다. 추가 test/docs를 포함한 최종 HEAD의
별도 전체 CI 결과와 구분한다. Docker2차는 공유 환경의 동시 부하를 피하도록 보류한다.
원래 Docker에서 알려진2개 경로 통합 실패는 이번 후보에서 아직 실행하지 않았으므로
현재 재현/해소됐다고 주장하지 않는다. 시작 뒤 발견한 실패는 숨기거나 skip 완화하지 않는다.
운영이 아닌 offline 전용 image/SQLite/network none/CPU1/memory2GiB 검증 경로를 준비했다.
이 이미지의 installed Common7파일 바이트를 commit41b Git 객체와 확인한 뒤 사용한다.
