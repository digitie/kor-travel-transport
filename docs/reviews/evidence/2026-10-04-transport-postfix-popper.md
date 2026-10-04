<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 kor-travel-transport contributors -->

# Transport 수정 후보 Popper 독립 적대 리뷰 원문

- 실행 ID: `popper-transport-027a9ca-20261004T171628-KST`.
- 시작: `2026-10-04T17:16:28.8187443+09:00`.
- 검토 종료: `2026-10-04T17:21:58.8855423+09:00`.
- 저장소: `F:/dev/kor-travel-transport`.
- base 요청값 및 실제 Git 객체: `e00e634b8502cdd1060d735b250ece96fd9fc945`.
- 후보 요청값 및 실제 Git 객체: `027a9ca1ef943d792278cc8a09964bb6e4ea5c44`.
- Python common pin: `430a9e9cd5429204579792b1d4f8e399366dcb2f`, 이전 본인 독립 PASS 코어와 동일.
- 판정: **PASS**. 이번 고정 후보에서 새 P0/P1/P2 finding 없음. 이전 P1 두 건과 P2 두 건은 CLOSED.

## 독립성·범위·실행 환경

Windows Git의 고정 객체 `show`·`diff`·`grep`·`ls-tree`로 원 base→후보 전체 기능 delta와
이전 후보 `781723356e3f73ae2f48f8df831b3a6970a898e3`→후보 수정 delta를 읽었다.
backend/PostgreSQL/ops 관점으로 owner fencing, terminal CAS, metadata 장애, provider 예약·
부분 commit, DB timeout, sensor 등록, common fallback, 메모리 상한, migration·배포 순서,
관리자 active 조회·HTTP scope·패키징을 검토했다. source 수정·설치 변경·commit은 하지 않았다.

본인 이전 원문은 허용된 비교 근거다. 상대 리뷰 원문과 root 통합 판정 및 그 내용이 들어갈 수
있는 `docs/reviews/**`·journal/resume/완료 task 증거를 제외했다. 상대 리뷰 결과는 읽지 않았다.
쓰기 대상은 이 새 원문 하나다. 다른 작업자의 변경을 되돌리지 않았다.

WSL snapshot `/tmp/popper-transport-027a9ca-x_2iuqvq`에는 고정 Git blob의 backend와
필요한 Compose·example 계약 파일을 그대로 복사했다. stale WSL mirror나 편집 중 worktree
source로 실행하지 않았다. Python `3.13.14`, Dagster `1.13.24`의 기존 venv를 사용했다.
실제 설치 common Dagster 모듈 SHA256은
`3fb1df0f98dc1d6828bb25db10ce3e1c3605fae7619fa3080ac2d240228cc979`로 이전 검증 코어와 같다.
`KOR_TRAVEL_TRANSPORT_TEST_SQLITE_TEMP=1` 및 임시 SQLite/fake provider로만 독립 실행했다.
운영 DB·외부 provider·운영 Docker를 변경하지 않았다.

## 독립 실행 결과

- 후보의 `test_collector_recovery.py`, `test_dagster_definitions.py`, `test_place_locations.py`,
  `test_kakao_place_locations.py`, `test_kric_collection.py`, `test_rail_maritime_collection.py`:
  **115 passed, 1 skipped**, 62.13초, exit 0.
- 같은 고정 snapshot의 `test_dagster_runtime_dependencies.py`: **1 passed**, 0.09초, exit 0.
  독립 선택 회귀 합계는 **116 passed, 1 skipped**다. skip은 KRIC PostgreSQL advisory lock
  통합 검증(`test_kric_collection.py:321`)이고 PostgreSQL PASS로 계산하지 않는다.
- 본인 이전 B-T-P1-01 공격을 ORM와 bulk로 각각 다시 실행했다. error receipt만 남고,
  회수 뒤 late 게시·terminal 덮어쓰기·nested context의 새 run commit 모두 거절됐다.
- 본인 이전 B-T-P1-02 공격을 실제 후보 enrichment 본문과 `_run_with_session`으로 다시
  실행했다. 첫 fake provider의 DB 회수→늦은 flush는 CollectionLeaseLost를 전파하고,
  두 번째 provider는 호출되지 않았다.
- 별도 savepoint commit→savepoint rollback→outer commit→reaper→late ORM 공격에서
  durable run 추적과 이미 성공한 Raw 1개를 보존하고 late 게시를 거절했다.
- missing run의 오래된 heartbeat를 읽은 뒤 metadata lookup 중 별도 connection으로
  heartbeat를 갱신하는 CAS 공격을 실제 SQLite에서 수행했다. 회수 0, status running 보존.
- 실제 Dagster local metadata의 FAILURE·CANCELED·SUCCESS owner 각각에서 새 provider
  session 시작을 거절했다. provider 호출 0이고 native terminal은 sticky revoked였다.
- metadata lookup을 실제 10.2초 지연시켜 제품의 10초 deadline을 직접 실행했다.
  10.000초 부근 TimeoutError, provider 호출 0, 살아 있는 owner의 revoked=false를 확인했다.
  native lookup 복원 후 같은 lease/session 시작 경계가 성공하여 provider 1회만 호출됐다.
  테스트를 위해 제품 deadline을 짧게 바꾸지 않았다.

주요 직접 공격 출력은 다음과 같다.

```text
POSTFIX_EXPIRED_TRACKED False [1]
POSTFIX_ROLLBACK_LATE_ORM_BULK_AND_NESTED_FRESH_DENIED False failed 1
POSTFIX_EXPIRED_TRACKED True [1]
POSTFIX_ROLLBACK_LATE_ORM_BULK_AND_NESTED_FRESH_DENIED True failed 1
POSTFIX_ENRICH_NEXT_PROVIDER_DENIED ['first']
SAVEPOINT_COMMIT_ROLLBACK_THEN_REAPER_LATE_DENIED
MISSING_RUN_HEARTBEAT_OBSERVE_THEN_TOUCH_CAS_PRESERVES_RUNNING
NATIVE_TERMINAL_FAILURE_CANCELED_SUCCESS_DENIED
ACTUAL_METADATA_10S_TIMEOUT_NO_PROVIDER_NONREVOKED 10.0
AFTER_TIMEOUT_RESTORED_LIVE_OWNER_ALLOWED
```

## 이전 finding 처분

### B-T-P1-01 — CLOSED

- 수정 위치: `backend/app/dagster/recovery.py:145-153`, 특히 `:152`.
- 이전 실패는 rollback 후 ORM status 캐시가 None인 run을 오류 receipt commit에서 추적
  목록에서 삭제하고, reaper 뒤 late publication/failed→success를 승인하는 것이었다.
- 후보는 상태 캐시가 None이어도 ID를 보존한다. 직접 공격에서 오류 receipt commit 뒤
  `collector_runs=[1]`이 유지되고 ORM·bulk 모두 DB fence를 수행하여 late commit을 거절했다.
- `recovery.py:94-95,112-113`의 sticky lease는 회수 뒤 새 run/session 우회까지 차단한다.
  기존 error receipt·성공 부분은 보존하고 failed 상태를 다시 success로 바꾸지 않았다.
- 본인 원문 권고의 rollback/오류 commit/late ORM·bulk 재현이 닫혔다.

### B-T-P1-02 — CLOSED

- 수정 위치: `backend/app/dagster/definitions.py:210-212`와 `recovery.py:22-69,80-95`.
- CollectionLeaseLost는 일반 provider 오류와 분리하여 즉시 전파한다. 동일 op의 lease
  객체를 session/async context가 공유하고, 회수 상태가 rollback 뒤에도 남는다.
- 실제 enrichment 공격에서 호출 목록이 `['first']`이고 Kakao가 새 CollectionRun이나
  receipt를 생성하는 후속 경로는 실행되지 않았다.
- 같은 owner nested context/새 session 공격도 거절됐다. 새로운 후속 op는
  `_run_with_session` 시작 시 native owner를 확인하므로 실제 terminal metadata에서도
  새 provider를 시작하지 않았다.
- 일반 RuntimeError provider 장애 때 Kakao를 계속하는 기존 회귀는 PASS다. 정상 provider
  장애를 lease 상실로 확대하거나 metadata ConnectionError/timeout을 sticky revoked로
  오판하지 않았다.

### B-T-P2-01 — CLOSED

`packages/kor-travel-transport-admin/frontend/lib/dagster-scope.ts:51`은 active query를 QUEUED·STARTING·STARTED·CANCELING
네 상태로 넓혔다. 1000건 상한/경고·중복 제거·location scope는 유지한다. 새 component/query
회귀와 부모의 별도 live 증거가 최근 30건 밖의 pending 상태를 다룬다. 내가 부모의 브라우저
세션을 직접 실행한 것으로 주장하지 않는다.

### B-T-P2-02 — CLOSED

`packages/kor-travel-transport-admin/frontend/vendor/README.md:24-25`는 Python pin을 실제 `430a9e9...`로 정정하고 UI tarball
source `9da1889`와 구분했다. 실제 pyproject/uv.lock과 일치한다.

## 전체 복구·DB·메모리 계약 점검

- 신규 owned CollectionRun은 provider 호출 전에 durable commit된다. ORM flush·bulk commit의
  DB owner/status lock, terminal 회수 WHERE status/owner CAS, missing metadata의 5시간
  heartbeat CAS, metadata 장애 시 미회수, legacy NULL owner 제외를 확인했다.
- PostgreSQL row lock을 직접 새 환경에서 실행했다고 주장하지 않는다. 위 heartbeat race와
  ORM bookkeeping 공격은 SQLite 실행 근거이며, PostgreSQL SELECT FOR UPDATE 및 CAS
  조건은 고정 source로 검토했다. 부모의 PostgreSQL 복구 35 tests와 구분했다.
- DB pool 2/overflow 0은 session advisory lease 한 connection과 부분 게시 transaction의
  다른 connection을 허용한다. connect 10초·statement 60초·lock 5초와 async action
  14340초, provider close 10초를 확인했다. 변경 없는 native runtime tag 4시간과 맞는다.
- `0024`와 models/DB session, provider services, Python pin·uv.lock·vendored tarball·npm lock은
  이전 후보와 `git diff --quiet` exit 0으로 동일함을 확인했다. 기존 provenance/integrity
  검증을 새 source 변경에 잘못 적용하지 않았다. migration은 nullable 추가, upgrade lock
  timeout, index/두 column downgrade, provider 데이터 미삭제 계약을 유지한다.
- due reservation·부분 성공 commit·고속도로 source별 복구·KRIC 마지막 시도 48시간·버스 성공
  72시간·철도 성공 48시간·VWorld/Kakao TTL/일·월 예산·manual 좌표 보호·ferry 날짜별 저장을
  검토했다. 수동/인프라 retry로 이미 소비한 호출 예산을 초기화하는 변경은 없다.
- ferry 재사용은 JSON 전체 대신 metadata/DB 배열 길이를 읽는다. 장소는 100개 ID keyset·
  현재 row, KRIC 후보는 호출 예산만큼 heap, highway provider 목록은 100페이지/50,000행
  상한으로 제한한다. 서비스 카탈로그와 provider가 반환하는 한 payload의 크기까지 RSS
  절대 상한을 보장한다는 문구로 해석하지 않았다.
- recovery sensor 4개와 coalescing schedule 등록을 definitions/선택 회귀에서 확인했다.
  common 430의 native OFF fallback·provider/step 실패 제외·pending ACK 인계·총 retry budget·
  subset/origin/tag 경계는 이전 본인 common 독립 PASS 코드와 동일하다.
- 전용 YAML 변경이 실제 shared coordinator에 적용됐다고 판단하지 않았다. 운영 shared에는
  monitoring이 확인됐지만 coordinator/native 설정 적용은 별도 운영 작업이며, 새 문서는
  native ON에서도 durable pending 인계를 마무리하는 계약을 정확히 설명한다.
- 적용 문서의 schedule 정지→worker drain→migration→code reload/recovery sensor 확인→
  shared 설정 확인→schedule 복원 순서를 검토했다. native 설정을 daemon drain 없이 즉시
  전환하는 새 배포 경로는 추가되지 않았다.

## 부모 live/CI 증거와 NOT_RUN

허용된 부모 원문 `docs/reviews/evidence/2026-10-04-transport-live-ui-postfix.md`의 실제
SHA256은 `79368B90F018D6739995CC9F833EB63D8756358784D172351DFEC18BEE8CA8C7`로 일치했다.
허용된 네 JPG의 실제 hash도 원문의 값과 일치했다. 그중 pending/outage 캡처를 직접 읽어
대기·시작·취소 중 상태, 정체 표시, 조회 실패 때 마지막 결과 유지 화면을 확인했다.
이는 캡처 검토이며 내가 CUA live 조작을 새로 수행했다는 증거가 아니다.

부모가 제공한 CI `37187027193`·`37187024121`, PostgreSQL 661 passed/1 skipped,
n150 동일 후보 복구 35 PASS/21.16초, 전용 migration DB 0023→24→check→23→24→check
roundtrip PASS는 외부 제공 증거로 분리한다. 내가 이를 직접 실행한 통과 수에 합산하지 않았다.
전체 WSL 및 전체 Docker PostgreSQL은 요청 당시 실행 중이었다. 완료로 세지 않았다.

다음은 이번 리뷰에서 **NOT_RUN** 또는 제한된 근거다.

- 운영 shared daemon/coordinator 설정 적용·실제 launcher worker kill·운영 retry child·전체 RSS.
- 이번 후보의 PostgreSQL row-lock barrier 공격 및 본인 직접 migration roundtrip.
- 본인 직접 frontend clean install/build/CUA. 부모 live 및 고정 source/회귀 증거로만 검토했다.
- common floor Dagster 1.9 재실행과 transport 전체 floor 실행. transport는 1.13.24로 pin되어
  있으며 unchanged common 430의 floor 검증은 이전 본인 원문의 별도 근거다.
- 많은 live 행/느린 metadata에서 reaper 전체 tick의 운영 규모·RPC 예산/공정성 실측.
  per-record deadline은 있지만 reaper의 지속 cursor/전체 tick 상한은 없다. 이번 규모에서
  새 영구 유실 결함을 재현한 것으로 주장하지 않는다.
- 모든 native terminal 전이와 DB publication 사이의 cross-storage 원자성을 보장하는
  검증. native owner 생존 확인은 시작 checkpoint이고, DB 회수 뒤의 publication 금지는
  durable owner/status fencing으로 판단했다.

## 최종 판정

**PASS**. 이전 두 P1의 실제 공격은 차단됐고, P2 두 건도 정정됐다. 전체 기능 delta를
다시 공격한 범위에서 새 actionable P0/P1/P2는 확인하지 못했다. 이는 고정 후보 코드의
독립 리뷰 판단이며 실행 중 전체 검증 완료, 운영 shared 제어 평면 적용, 실제 운영 worker
kill/RSS 또는 PR 머지가 완료됐다는 판단과 구분한다. 이전 BLOCK 원문은 변경하지 않는다.
