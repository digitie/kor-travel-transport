<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 kor-travel-transport contributors -->

# Transport 최종 후보 Popper 독립 적대 리뷰 원문

- 실행 ID: `popper-transport-781723-20261004T163220-KST`.
- 시작: `2026-10-04T16:32:20.5920948+09:00`.
- 검토 종료: `2026-10-04T16:41:03.6499961+09:00`.
- 저장소: `F:/dev/kor-travel-transport`.
- 요청 base와 실제 `git rev-parse` 확인값: `e00e634b8502cdd1060d735b250ece96fd9fc945`.
- 요청 후보와 실제 `git rev-parse` 확인값: `781723356e3f73ae2f48f8df831b3a6970a898e3`.
- 실제 Python 고정 의존: `430a9e9cd5429204579792b1d4f8e399366dcb2f`.
- 판정: **BLOCK**. P0 0건, P1 2건, P2 2건. 정상 경로 테스트 통과로 아래 소유권 우회를 승인하지 않는다.

## 격리와 검토 범위

Popper 관점은 backend/PostgreSQL/ops와 장애 복구 계약이다. Windows Git의 고정 객체
`show`·`diff`·`grep`·`ls-tree`만으로 source를 읽었다. 코드와 설치 패키지는 수정하지 않았다.
WSL 임시 snapshot `/tmp/popper-transport-781723-m0y3hxa2`는 위 후보의 backend blob을
그대로 복사했다. 기존 `/tmp/transport-recovery-source`의 오래된 후보를 사용하지 않았다.
유일한 저장소 쓰기 대상은 이 원문이다. 다른 작업자의 변경을 되돌리지 않았다.

James 원문, `docs/reviews`의 상대 리뷰 및 root 통합 peer 판정을 읽지 않았다. 본인의
baseline 계약을 참고하고, backend/services/DB/migration/definitions, common 채택,
관리자 HTTP·scope·로그 pagination·컴포넌트·CSS·패키징·lock, 적용 문서의 전체 기능 delta를
검토했다. journal의 상대 판정은 리뷰 근거로 사용하지 않았다.

부모의 독립 live 증거만 허용된 예외로 읽었다. 파일은
`docs/reviews/evidence/2026-10-04-transport-live-ui.md`이고 실제 SHA256은
`6C2E14391206956A3B9C2FBF016EC6F1E86C08C1459F246DF335B85ADB782828`로 전달값과 일치했다.
이는 부모가 수행한 격리 production UI 검증이며, 내가 브라우저 검증을 실행했다는 뜻이 아니다.

## 독립 실행 근거

- WSL Python `3.13.14`, Dagster `1.13.24`, 기존 venv를 설치 변경 없이 사용했다.
- 실제 설치 common Dagster 모듈 SHA256:
  `3fb1df0f98dc1d6828bb25db10ce3e1c3605fae7619fa3080ac2d240228cc979`.
- `KOR_TRAVEL_TRANSPORT_TEST_SQLITE_TEMP=1`을 명시했다. 운영 `DATABASE_URL`을 사용하지
  않고 임시 SQLite 및 fake provider만 사용했다. 운영 DB와 외부 provider는 변경하지 않았다.
- 고정 snapshot의 `test_collector_recovery.py`, `test_dagster_definitions.py`,
  `test_place_locations.py`, `test_kakao_place_locations.py`, `test_kric_collection.py`,
  `test_rail_maritime_collection.py` 선택 회귀를 실행했다.
  첫 실행은 `108 passed, 1 skipped, 1 failed`였다. 실패는 내가 backend만 복사하여
  `docker-compose.shared.yml` 계약 파일이 snapshot에 없었기 때문이다.
  같은 고정 객체의 Compose 파일을 추가 복사한 뒤 해당 실패 1개만 재실행하여 PASS였다.
  서로 다른 통과 테스트 합계는 **109 passed, 1 skipped**다. skip은 PostgreSQL advisory lock
  통합 검증(`test_kric_collection.py:321`)이며 PostgreSQL 통과로 집계하지 않는다.
- 아래 두 P1은 별도의 실제 SQLAlchemy owned session·임시 DB 공격으로 재현했다.
  두 번째는 고정 후보 `enrich_new_reference_locations.compute_fn.decorated_fn` 본문과
  실제 `_run_with_session`을 호출하고 provider만 fake로 교체했다.
- 고정 Git blob의 vendored tarball을 메모리에서 열고 SHA256, package 이름,
  `LICENSE`·`NOTICE`·`THIRD_PARTY_NOTICES.md`, lockfile SHA512 integrity를 직접 확인했다.
  tokens SHA256 `22b7613085e55885987ce05720a178b65ac649b097763db650b8c7b8b4acaa84`,
  UI SHA256 `5c7bb61dce3245bf175795c39a9310782557ce65948ddc161452faa7c0cfca4b`;
  두 lock integrity 모두 일치했다.

부모가 전달한 CI `37185005593`·`37185007505`, 전체 PostgreSQL 655+1 skip,
WSL 647+9 skip, n150 복구 29 tests, 관리자/공개 UI Docker와 live 결과는 별도 제공 증거다.
이번 원문에서 이를 내가 실행한 통과 수로 합산하지 않았다. common 430의 56 tests와
floor 1.9 검증은 이전 본인 common handoff 원문에서 독립 실행했고 이번 transport
후보 검증에서 재실행한 것으로 주장하지 않는다.

## B-T-P1-01 — rollback으로 만료된 ORM 상태가 fencing 추적을 삭제한다

- 위치: `backend/app/dagster/recovery.py:105-110`, 특히 `:109`.
  실제 소비 흐름: `backend/app/services/transport_collection.py:445-447`, 이후 다음 source 게시.
- 심각도: **P1**, 머지 전 수정 필요.
- 실패 시나리오: owned CollectionRun을 durable commit한 뒤 한 source의 저장 실패로
  transaction을 rollback한다. SQLAlchemy가 run ORM 속성을 만료한다. 오류 receipt와
  source 실패 상태를 commit할 때 `_fence`는 DB의 running/owner를 정상 확인하지만 ORM
  run.status를 다시 로드하지 않는다. `_after_commit`의 `row.__dict__.get("status")`는
  `None`이므로 그 실행을 `collector_runs`에서 지운다. 이후 native terminal을 확인한
  reaper가 failed로 회수해도 다음 source의 flush/commit은 검사할 run이 없어 통과한다.
  늦은 게시와 terminal 상태 덮어쓰기를 함께 허용한다.
- 재현: 후보의 `owned_session_factory`로 run 생성·commit → `select`로 새 transaction
  시작 → rollback → RawApiResponse 오류 receipt 생성·commit → 일반 session에서 같은
  run을 failed로 update·commit → owned session에서 late RawApiResponse commit →
  같은 run을 다시 get하여 success commit. SQLite에서 실제 수행한 출력은 다음과 같다.

```text
AFTER_ROLLBACK_STATUS None TRACKED [1]
AFTER_ERROR_RECEIPT_COMMIT_TRACKED []
ROLLBACK_ATTACK_DB_STATUS success
ROLLBACK_ATTACK_LATE_COUNT 1
```

- 근거: `_after_rollback`은 durable run의 ID를 유지하지만, 다음 `_after_commit`이 만료된
  ORM 표현을 terminal로 취급한다. 이는 PostgreSQL row lock 자체의 문제가 아닌 ORM
  bookkeeping 결함이다. PostgreSQL에서도 SQLAlchemy rollback 만료 계약은 같다.
  이번 공격은 SQLite에서 직접 실행했으며 PostgreSQL에서 직접 재실행했다고 주장하지 않는다.
- 영향: 앞선 source 오류가 발생한 worker는 뒤따르는 source부터 소유권 fencing을 잃는다.
  reaper 뒤의 stale publication과 failed→success/partial_success 덮어쓰기가 가능하다.
  기존 성공 부분과 due reservation 보존 계약도 stale worker 경로에서 흔들린다.
- 권고: 실행 추적을 ORM 속성의 현재 캐시 여부에 의존시키지 않는다. rollback 만료·savepoint·
  bulk-only commit을 거쳐도 durable run ID/owner 추적을 보존하고, 실제로 승인하여 commit한
  terminal 전이에만 추적을 제거한다. 위 재현을 ORM·bulk 및 PostgreSQL 회귀로 추가한다.

## B-T-P1-02 — 소유권 상실을 provider 오류로 삼켜 다음 provider가 새 run으로 게시한다

- 위치: `backend/app/dagster/definitions.py:206-208`;
  우회 경계: `backend/app/dagster/recovery.py:79-97`의 신규 owned run 생성·capture.
- 심각도: **P1**, 머지 전 수정 필요.
- 실패 시나리오: bus/maritime의 `enrich_new_reference_locations`에서 VWorld가 처리 중일 때
  Dagster terminal 회수로 해당 CollectionRun이 failed가 된다. 늦은 VWorld commit은
  `CollectionLeaseLost`로 정확히 거절된다. 그러나 enrichment는 이를 `Exception`으로
  잡아 provider 실패로 취급하고 Kakao를 이어 실행한다. 새 owned session/CollectionRun은
  같은 종료된 Dagster UUID를 부여받지만 신규 INSERT를 자기 소유로 승인한다. 이때 새 기록에
  기존 회수 행의 fencing이 적용되지 않아 Kakao 예약·외부 호출·게시를 계속할 수 있다.
- 재현: 실제 후보 enrichment 함수와 `_run_with_session`을 사용했다. fake 첫 provider는
  자기 owned run을 commit한 뒤 별도 reaper session으로 failed 회수하고 늦은 Raw 게시를
  시도하여 CollectionLeaseLost를 발생시킨다. fake 두 번째 provider는 실제 owned session으로
  새 run·Raw를 commit한다. 출력은 다음과 같다.

```text
ENRICH_EXCEPTION Failure
ENRICH_RUNS [('first-vworld', 'failed', 'already-terminal-dagster-owner'),
            ('second-kakao', 'success', 'already-terminal-dagster-owner')]
ENRICH_LATE_PUBLICATION_COUNT 1
```

- 근거: 최종 enrichment가 Dagster Failure를 던지는 것과 그 전에 Kakao가 게시한 사실은
  별개다. 일반 provider의 장애 시 다른 provider를 계속하는 기존 계약은 타당하지만,
  CollectionLeaseLost는 소유 작업 전체의 권한 상실이고 provider별 실패가 아니다.
- 영향: native monitor/취소 이후 남은 stale worker가 다음 제공기관 호출 예산과 publication을
  계속 사용한다. 사용자가 요구한 회수 뒤 늦은 게시 금지 계약을 새 기록 생성으로 우회한다.
- 권고: `CollectionLeaseLost`는 enrichment에서 즉시 재전파하여 다음 제공기관을 호출하지
  않는다. 같은 Dagster owner의 후속 session/run을 시작하는 다른 경계도 소유권 상실을
  우회하지 않는지 확인한다. 일반 RuntimeError provider 실패 때 Kakao 계속 실행 테스트는
  유지하고, lease loss 때 Kakao 미실행/새 run·receipt 없음 회귀를 별도로 추가한다.

## B-T-P2-01 — active 별도 목록이 STARTED만 조회한다

- 위치: `packages/kor-travel-transport-admin/frontend/lib/dagster-scope.ts:51`.
- 심각도: **P2**, 비차단 개선.
- 실패 시나리오/재현: 오래된 QUEUED·STARTING·CANCELING 실행 1건 뒤에 최근 terminal
  실행 30건을 둔다. overview 최근 30건에서 해당 실행이 밀리고 별도 active query의
  `statuses: [STARTED]`에도 포함되지 않는다. 이는 query 고정 객체에서 직접 확인한 선택
  조건이고 해당 metadata fixture를 이번 실행에서 구성하지는 않았다.
- 영향: 시작/취소가 멈춘 오래된 실행은 화면에서 사라져 운영자가 전체 active 상태를 오인할
  수 있다. 이 상태 필터는 baseline에도 있었으므로 새 회귀로 주장하지 않는다. 이번 active
  합침 개선의 잔여 범위다. backend common의 schedule active guard는 네 상태를 보므로
  UI가 숨긴 실행 때문에 schedule이 건너뛰는 상태가 될 수 있다.
- 권고: QUEUED·STARTING·STARTED·CANCELING을 함께 조회하고, 1000건 도달 경고와
  중복 제거 계약을 유지한다. 각 상태의 오래된 실행이 최근 30건 밖에서도 보이는 회귀를 추가한다.

## B-T-P2-02 — vendor 문서의 Python pin이 실제 후보와 다르다

- 위치: `packages/kor-travel-transport-admin/frontend/vendor/README.md:24`.
- 심각도: **P2**, 비차단 문서 정정.
- 재현/근거: 문서는 common `090f984` 고정을 선언하지만 같은 후보의 backend pyproject와
  uv.lock은 `430a9e9cd5429204579792b1d4f8e399366dcb2f`다. Git 객체를 직접 비교했다.
- 영향: 복구 sensor를 재현하거나 장애 시 설치 provenance를 추적할 때 과거 코어를 사용하게
  만들 수 있다. 실제 lock integrity나 설치 오류는 확인하지 않았다.
- 권고: UI tarball provenance와 현재 Python 코어 pin을 구분하여 실제 값을 기록한다.

## 본인 baseline finding의 처분과 유지 계약

- baseline B-P1-01 owner/자동 회수 부재: nullable owner·heartbeat migration과 등록된
  recovery sensor로 새 Dagster 실행에는 개선됐다. legacy NULL owner는 의도적으로 자동
  회수하지 않는다고 문서화했다. 운영 기존 stuck 행의 실제 수동 정리는 이번 검증 범위 밖이다.
- baseline B-P1-02 늦은 게시: 정상 ORM/bulk 거절 회귀는 통과했다. 그러나 위 두 새 P1 때문에
  복구 계약 전체는 아직 닫히지 않았다.
- baseline B-P1-03 공항 실패 SUCCESS/시작 기록 미확정: owned 시작 commit 및 부분 실패
  Dagster Failure로 개선됐다. 제공기관 오류를 infrastructure retry 대상으로 확대하지 않았다.
- baseline B-P1-04 중복 schedule: common coalescing 도입으로 동일 location/job active를
  합친다. shared coordinator의 운영 limit 적용은 별도 미실행 작업으로 문서에 구분했다.
- baseline B-P2-01 메모리: ferry JSON 전체 로딩 대신 DB 길이 projection, 장소 target 100개
  ID keyset·현재 row, KRIC 호출 예산만큼 heap 후보, provider 100페이지/50,000행 상한으로
  개선됐다. 서비스 카탈로그·provider page 자체 payload와 전체 RSS는 독립 실측하지 않았다.
- baseline B-P2-02 collector DB 대기: pool 2/overflow 0, connect 10초, statement 60초,
  lock 5초, async action 14340초로 개선됐다. 운영 shared process의 실제 강제 종료 시간은
  이번 정적/격리 리뷰에서 검증하지 않았다.

provider 보호의 due reservation·실패 receipt·KRIC 마지막 시도 48시간·버스 성공 72시간·
철도 성공 48시간·과금 키/일·월 예산·manual 좌표 보존·ferry 날짜별 부분 commit 계약을
검토했다. 성공분을 삭제하여 재시도를 강제하는 변경은 없었다. ordinary provider 실패의
계속 실행과 CollectionLeaseLost의 즉시 종료를 분리해야 이 계약을 유지할 수 있다.

## 추가 공격 시나리오와 불확실성

- 첫 page가 live인 뒤 terminal 행 회수, known live의 오래된 heartbeat 보존,
  missing metadata의 5시간 grace, metadata 장애 시 미회수, 부분 저장본 유지:
  후보 선택 회귀로 검증했다.
- ORM/bulk stale commit 및 terminal 덮어쓰기: 정상 회귀는 통과하지만 rollback 공격은 실패했다.
- reaper가 heartbeat 관찰 뒤 worker가 heartbeat 갱신하는 동시 race: WHERE heartbeat CAS를
  정적으로 확인했다. PostgreSQL barrier를 둔 별도 동시 실행은 NOT_RUN이다.
- savepoint release/rollback, 늦은 commit ACK, 여러 CollectionRun의 같은 owner, 장시간 metadata
  prefix의 reaper 전체 tick 공정성: 정적 검토 범위이며 모든 조합을 실제 실행하지 않았다.
  reaper는 per-record deadline이 있지만 tick 전체 상한·지속 cursor는 없다. 많은 live 행과
  느린 metadata에서 RPC 예산을 넘기는 운영 규모 검증은 아직 남는다.
- `0024`는 기존 행을 nullable로 보존하고 upgrade에 5초 lock timeout을 둔다. downgrade는
  index·두 column만 제거한다. migration 전 drain·추가 migration 선적용 문서와 맞는다.
  내가 이번 snapshot에서 PostgreSQL upgrade/downgrade/check를 실행한 것은 아니다.
- sensor 실제 등록은 definitions와 선택 회귀에서 확인했다. native OFF fallback의 core,
  pending ACK 유실/late commit/native ON 인계는 동일 common 430의 이전 독립 검증 근거다.
  transport 운영 shared daemon에서 sensor를 실제 발화하여 worker를 죽인 실험은 NOT_RUN이다.
- shared instance의 monitoring enabled만으로 project limit 3/job limit 1/coordinator 설정이
  배포됐다고 판단하지 않았다. 전용 YAML 변경은 실제 shared YAML을 바꾸지 않는다.
  운영 coordinator 설정 적용·worker kill/retry child·전체 RSS와 floor Dagster로 transport
  전체 실행은 NOT_RUN이다. 부모의 live 원문도 이 경계를 명시한다.
- UI는 요청/응답 byte·본문 deadline, named query/location/UUID scope, 실패 로그 페이지
  상한, 최대 3개 failure 상세를 확인했다. 내가 frontend clean build/브라우저/CUA를 이번
  원문에서 별도로 수행하지 않았고 부모의 실행 증거와 정적 검토로 한계를 구분했다.

## 최종 판정

**BLOCK**. P1 두 건의 실제 stale publication 재현을 닫은 고정 후속 후보에서 독립
재검토해야 한다. 원문은 이 SHA에 대한 판단이며 후속 수정 결과를 덮어쓰지 않는다.
P2 두 건은 정정하거나 후속 판단 근거를 남길 수 있다. 운영 shared 제어 평면 미적용 및
NOT_RUN 항목을 후보 코드 승인이나 UI live 성공과 혼합하지 않는다.
