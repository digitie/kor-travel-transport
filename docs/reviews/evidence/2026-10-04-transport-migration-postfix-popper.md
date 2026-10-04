<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 kor-travel-transport contributors -->

# Transport migration cleanup Popper 최종 추가 리뷰 원문

- 실행 ID: `popper-migration-0a4588af-20261004T192852-KST`
- 시작: `2026-10-04T19:28:52.3629488+09:00`
- 종료: `2026-10-04T19:30:24.5510067+09:00`
- 저장소: `F:/dev/kor-travel-transport`
- base 및 실제 Git 확인값: `1c5bd965b02b38bc608ce15de196636d7c09ba4b`
- candidate 및 실제 Git 확인값: `0a4588af20bd97bedc0e10686c45145b31544b07`
- 판정: **PASS**. 본인 기존 **B-M-P2-01 CLOSED**, 새 P0/P1/P2 finding 없음.

## READONLY 범위

고정 Git 객체의 테스트 전체 cleanup 흐름과 base→candidate diff만 검토했다.
변경은 `backend/tests/test_fuel_statistics_migration.py:88-89`의 한국어 주석과
kill 이후 무상한 `process.wait()`를 10초 제한 `process.communicate()`로 바꾼 부분이다.
상대 원문·journal·closure·통합 disposition은 읽지 않았다. 본인 이전 원문은 유지한다.

승인된 `027a9ca1ef943d792278cc8a09964bb6e4ea5c44` 대비 제품 app·migration·Dagster
설정·Python pin/lock·packages는 `git diff --quiet` exit 0이었다. 제품 runtime/UI 변경이 아니다.
저장소 수정·commit·설치 변경·새 에이전트 생성은 하지 않았다. 실행 중인 n150
`codex-transport-full-final-20261004` DB·컨테이너·프로세스에 접촉하지 않았다.

## EXECUTED

WSL 기존 Python 3.13 venv에서 고정 후보 AST의 `migrate` helper 본문을 추출하여
격리된 scratch child로 실행했다. 제품 helper 본문과 60초/10초 timeout 값은 바꾸지 않았다.

1. 실제 stdout PIPE child에 reader 정체를 주입하여 backpressure 상태에서 helper task를
   취소했다. cleanup의 두 번째 communicate는 실제 child communicate를 사용했다.
   child는 -9로 종료되고 stdout paused=false·buffer=0이 됐으며 원래 CancelledError가 전달됐다.
   PID 소멸도 확인했다.
2. 같은 native child에서 최초 communicate TimeoutError를 주입했다. cleanup이 실제
   stdout을 비운 뒤 원래 TimeoutError를 전달했고 child PID가 남지 않았다.
   최초 60초 timeout을 실제로 기다린 검사는 아니다.
3. cleanup communicate가 11초 정체하는 fake child를 주입했다. 실제 제품의 10초 timer가
   10.008초에 TimeoutError를 발생시켰고 kill 호출을 확인했다. timer를 축소하지 않았다.
4. 고정 blob의 테스트와 0015 migration을 임시 scratch에 복사하고 SQLite fixture로
   단위 테스트를 실행했다. **4 passed, 1 skipped / 0.15초 / exit 0**.
   skip은 PostgreSQL 전용 DDL 잠금·복구 검사다.

```text
NATIVE_PIPE_DRAIN False error CancelledError seconds 0.001 returncode -9 paused False buffer 0
NATIVE_PIPE_DRAIN True error TimeoutError seconds 0.022 returncode -9 paused False buffer 0
ACTUAL_CLEANUP_10S_BOUND 10.008 calls 2 killed True
4 passed, 1 skipped in 0.15s
```

위 fault injection은 helper cleanup 경계를 검증한다. 실제 Alembic이나 운영 DB에서
stdout 정체가 발생했다는 뜻이 아니다. scratch child는 모두 회수했다.

## B-M-P2-01 처분과 오류 전파

원래 심각도는 **P2**, 위치는 기존 테스트 `:85-88` 및 observer cancellation 경로였다.
kill 이후 PIPE를 drain하지 않는 무상한 wait 때문에 cancelled task가 머물 수 있었다.
수정 후보 `:89`는 communicate로 stdout 회수와 child wait를 함께 수행하고 별도 10초
상한을 둔다. 기존 backpressure 공격은 끝나며 원래 cancellation/timeout도 전달된다.
따라서 **CLOSED**다.

cleanup 자체의 timeout은 성공으로 처리되지 않고 예외로 전파된다. 이 경우 원래 오류보다
cleanup TimeoutError가 최종 오류로 나타날 수 있지만 예외 context는 남고 테스트는 실패한다.
무상한 대기나 false PASS로 바뀌지 않는다. 기존 outer finally의 head 복원 시도와 engine
정리는 그대로이며, 이 수정이 그 복원 경로를 제거하지 않았다.

## NOT_RUN과 제공 증거

이번 독립 실행에서 PostgreSQL migration·native DB lock·head roundtrip·전체 회귀는
실행하지 않았다. 최초 communicate 60초 경과, 반복 cancellation, 운영 worker/RSS,
본인 frontend/live UI도 NOT_RUN이다.

부모가 제공한 CI `37194466593`·`37194463827`의 backend/frontend/admin PASS는 별도
제공 증거이며 본인 실행 수에 합산하지 않았다. workflow live SKIPPED와 변경 없는 runtime
027의 부모 실제 UI 검증도 구분한다. 새 전체 PostgreSQL 실행은 진행 중이므로 완료로 세지 않는다.
앞선 legacy mode 실패의 환경 원인 및 재실행 결과는 이 test-only 수정의 독립 PASS 근거로
전용하지 않았다.

## 최종 판정

**PASS**. 고정 후보에서 본인 P2의 bounded cleanup·drain·오류 전파를 확인했고 새 finding은
없다. 이 판정은 작은 테스트 수정에 한정하며 진행 중 전체 검증이나 운영 배포 완료를 뜻하지 않는다.
