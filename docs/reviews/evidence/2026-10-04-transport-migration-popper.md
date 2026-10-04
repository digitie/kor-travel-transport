<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 kor-travel-transport contributors -->

# Transport migration 테스트 Popper 독립 추가 리뷰 원문

- 실행 ID: `popper-migration-1c5bd965-20261004T185809-KST`
- 시작: `2026-10-04T18:58:09.4795559+09:00`
- 종료: `2026-10-04T19:03:31.7457890+09:00`
- 저장소: `F:/dev/kor-travel-transport`
- base 및 실제 Git 확인값: `1cb935551222ded6357b02fefed4c03c80183d5b`
- candidate 및 실제 Git 확인값: `1c5bd965b02b38bc608ce15de196636d7c09ba4b`
- 판정: **PASS**, 비차단 P2 1건. P0/P1 없음.

## READONLY 범위와 독립성

고정 Git 객체에서 `backend/tests/test_fuel_statistics_migration.py`의 전체 본문과 base→candidate diff를 읽었다. 변경 파일은 해당 테스트와 `docs/journal.md`뿐이었다. journal, 상대 리뷰, 통합 disposition은 판정 근거에서 제외했다.

관련된 고정 migration `0015`, `0018`, `0022`, Alembic env와 CI PostgreSQL 실행 구성을 함께 검토했다. 승인된 runtime `027a9ca1ef943d792278cc8a09964bb6e4ea5c44` 대비 `backend/app`, migration, Dagster 설정, Python pin/lock 및 packages는 `git diff --quiet` exit 0이었다. 제품 runtime·UI·migration 변경으로 취급하지 않았다.

저장소 파일 수정·commit·설치 변경·새 에이전트 생성은 하지 않았다. 실행 중인 n150 project `codex-transport-full-pg-20261004`의 DB·컨테이너·프로세스를 건드리지 않았다. 부모가 이 원문을 보존한다.

## EXECUTED

1. 고정 Git blob에서 테스트 및 `0015` 파일만 WSL 임시 scratch로 복사했다. SQLite URL을 제공하는 임시 fixture로 단위 테스트를 실행했다.

   **4 passed, 1 skipped / 0.15초 / exit 0**

   skip은 PostgreSQL 전용 DDL 잠금·복구 검사다. PostgreSQL PASS로 계산하지 않는다.

2. 후보 AST에서 `migrate` helper 본문을 추출하여 scratch에서 그대로 실행했다. 실제 stdout PIPE를 가진 별도 Python child를 띄우고, communicate reader 정체를 주입하여 PIPE backpressure 상태에서 helper task를 취소했다. child는 kill됐지만 helper의 `process.wait()`는 stdout을 drain할 때까지 끝나지 않았다.

   ```text
   PIPE_BACKPRESSURE_CHILD_RETURN_CODE -9 CLEANUP_TASK_DONE False
   AFTER_DRAIN_CLEANUP_TASK_DONE True
   ```

   이 검사는 helper cleanup 경계의 fault injection이다. 실제 Alembic migration이 이 상태에 빠졌다고 주장하지 않는다. scratch child는 drain·wait로 정리했다.

## 잠금·시각·복원 검토

- `pg_locks` 조회는 현재 DB OID와 `fuel_price_snapshots` relation으로 제한하고 observer PID를 제외한다. 다른 DB 또는 다른 테이블의 lock을 그대로 관찰하여 통과하는 기존 우려를 줄인다.
- migration backend PID 자체를 식별하는 방식은 아니다. 현재 CI는 전용 PostgreSQL test DB에서 단일 pytest 실행이고, 테스트는 observer와 migration만 연결한다는 가정을 명시한다. 그 격리 조건에서는 다른 actor의 동일 relation 대기를 원인으로 오인하는 실제 false pass를 확인하지 못했다.
- `waitstart`와 `clock_timestamp()`를 같은 PostgreSQL 서버에서 읽으므로 Python monotonic clock과 서버 timestamp를 섞지 않는다. CLI import 이전 시간도 제외한다.
- 종료 시각은 migration CLI 완료 뒤 측정하므로 차이는 순수 lock 대기만이 아니라 lock 실패 이후 CLI 종료·observer 질의 지연도 포함한다. 따라서 `<10초`는 해당 전용 환경의 관찰 상한이다. 제품 DB의 정확한 lock timeout 값을 독립적으로 측정한 결과로 확대하면 안 된다.
- CLI 60초 제한과 DB lock timeout 3초를 구분한 수정은 타당하다.
- observer 실패나 cancellation에서는 migration task를 취소하고 회수하려 한다. 이후 `engine.begin()` 범위를 벗어나 observer lock을 해제한 뒤 outer finally에서 `upgrade head`를 수행한다.
- 성공 경로에서도 최종 head upgrade를 수행하며, assertion 실패 경로도 복원을 시도한다. 복원 실패를 assert로 드러내고 마지막 engine dispose를 별도 finally에 둔다.
- 실제 schema 복원이 필요한 변경은 제품 migration 추가가 아니라 테스트의 cleanup 보강이다.

## B-M-P2-01 — child kill 이후 wait에는 상한과 PIPE drainage가 없다

- 위치: `backend/tests/test_fuel_statistics_migration.py:85-88`, 새 cancellation 호출 경로 `:112-118`.
- 심각도: **P2**, 비차단.
- 실패 시나리오: observer 오류 또는 cancellation 시 migration child의 stdout reader가 정체·backpressure 상태다. helper는 communicate를 취소하고 child를 kill하지만, drain 없이 무상한 `process.wait()`를 기다린다. asyncio transport의 pipe 종료 처리가 끝나지 않으면 cancelled migration task를 await하는 outer cleanup도 머무를 수 있다.
- 재현: EXECUTED의 고정 AST helper·실제 scratch child·주입된 정체 reader 검사에서 child returncode `-9` 이후에도 helper가 완료되지 않았고 stdout drainage 후 완료됐다.
- 영향: 테스트 cleanup이 observer lock 해제·head 복원 단계에 도달하지 못할 수 있다. 60초 communicate 제한이 cleanup까지의 전체 제한을 뜻하지 않는다.
- 범위: kill→wait helper 자체는 base에도 존재한다. 이번 diff는 observer finally에서 명시적 cancellation을 추가하여 이 경계를 추가 사용한다. 정상 Alembic의 제한된 출력이나 제공된 PostgreSQL 검사에서 이 문제가 발생했다고 판단하지 않는다.
- 권고: kill 이후 PIPE drainage/communicate와 wait를 제한된 cleanup budget 안에서 처리하고, backpressure cancellation 회귀를 추가한다. 현재 격리 CI의 정상 출력 조건을 유지하는 동안 후속 보강으로 처리할 수 있다.

## 부모 증거 READONLY와 NOT_RUN

허용된 부모 raw 로그 두 개를 읽었다.

- `/tmp/transport-ram-migration-lock-postfix.log`
  - SHA256: `8aa221bbee1ea06fcd27a10c9060e1e940b25ca83a4e094e57da71169b4fc166`
  - native positive 14.19초 기록이다. 부모 설명대로 최종 relation filter 추가 이전 결과이며 현재 후보 전체의 직접 PASS로 집계하지 않는다.
- `/tmp/transport-migration-failure-cleanup-probe.log`
  - SHA256: `88c600dc796c9db81d2b14c6541a1731f9acce08bcc37f89a74c54d1374a8d4a`
  - relation filter가 포함된 흐름에서 잠금 실패 검증과 성공 downgrade 뒤 의도한 assertion이 발생했다.
  - 예상 `1 failed / 24.07초` 뒤 `head0024, owner columns2` 복원 확인이 기록되어 있다. 의도한 실패를 테스트 실패 결함으로 분류하지 않았다.

부모가 제공한 candidate CI `37192358801`·`37192355824`의 backend/frontend/admin PASS는 제공 증거다. 내가 CI 전체나 PostgreSQL migration을 새로 실행한 통과 수에 합산하지 않았다.

이번 리뷰에서 **NOT_RUN**:

- 별도 PostgreSQL DB에서 본인 직접 native lock/migration roundtrip.
- 현재 실행 중인 n150 전체 PostgreSQL 회귀.
- 운영 DB migration·worker·컨테이너 조작.
- 실제 Alembic stdout backpressure 및 60초 timeout 발생 실험.
- 다른 actor를 추가한 PostgreSQL 동일 relation wrong-lock 공격.
- 서버 시계 변경이나 극심한 scheduler 지연에 대한 timestamp 상한 실험.

## 최종 판정

**PASS**. 고정 후보의 테스트 변경에서 머지를 막는 P0/P1은 확인하지 못했다. DB/relation 범위, CLI 시간과 DB 잠금 시간의 분리, 실패 뒤 head 복원 보강은 타당하다. 비차단 P2 cleanup 경계는 후속 판단 근거와 함께 남긴다.

이 판정은 테스트 변경에 한정한다. 제품 runtime은 승인된 `027a9ca`와 동일하며, 실행 중인 전체 PostgreSQL 회귀나 운영 배포가 완료됐다는 의미는 아니다.
