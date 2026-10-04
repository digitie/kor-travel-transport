<!-- SPDX-FileCopyrightText: 2026 digitie -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# James — Transport migration 테스트 최종 수정 독립 리뷰 원본

- 실행 ID: `J-TRANSPORT-MIGRATION-POSTFIX-20261004-0a4588af`.
- 관찰: `2026-10-04 10:28:44~10:30:59 UTC` / `19:28:44~19:30:59 KST`.
- 저장소: `F:/dev/kor-travel-transport`.
- 실제 base: `1c5bd965b02b38bc608ce15de196636d7c09ba4b`.
- 실제 candidate: `0a4588af20bd97bedc0e10686c45145b31544b07`.
- 고정 테스트 blob: `0477e81fa858df0a756a4aeb31330905432a4724`.
- Windows Git 고정 test 객체와 diff만 검토했다. 상대 원문·closure·journal·통합 판정은 읽지 않았다. 기존 원본을 수정하지 않았다. 저장소에는 아무것도 쓰지 않았고, 재현·보고서 파일만 저장소 밖 WSL `/tmp`에 작성했다. 전용 자식 subprocess만 종료·회수했으며 진행 중인 DB·컨테이너·전체 suite는 건드리지 않았다.

## 판정과 disposition

**PASS. 기존 J-MIG-P2-01 CLOSED. 신규 P0/P1/P2 finding 없음.**

기존 지적의 심각도는 **P2**로 유지한다. 위치는 `backend/tests/test_fuel_statistics_migration.py:85-89`다. 이전에는 communicate 취소 뒤 kill과 제한 없는 wait만 호출하여, 종료된 자식의 stdout 파이프가 남으면 cleanup이 멈췄다. 후보는 kill 뒤 `wait_for(process.communicate(), timeout=10)`으로 출력 회수와 종료 대기에 별도 상한을 적용한다. 아래 독립 실행에서 원래 두 예외 경로가 모두 완료되는 것을 확인했다.

## EXECUTED

1. 제품 변경 여부를 직접 대조했다. docs/tests를 제외한 제품 전체 tree는 승인 runtime `027a9ca1ef943d792278cc8a09964bb6e4ea5c44`와 동일하다(`git diff --quiet`, exit 0). base→candidate 제품 계약 비교도 exit 0이다. 제품 runtime/UI/migration/common pin 변경은 없다. 이번 source 변경은 해당 테스트의 cleanup 한 줄과 한국어 설명뿐이다.
2. candidate의 고정 `migrate()` AST를 추출하여 WSL Python의 로컬 stdlib 대량 출력 자식으로 실행했다. PostgreSQL·Alembic·provider는 실행하지 않았다. timeout 경로는 첫 60초를 40ms로, cleanup 10초를 400ms로 가속했다. 직접 cancellation 경로는 첫 deadline 전에 task를 취소했다. 호출받은 원래 deadline `[60, 10]`도 assertion으로 확인했다.
3. 두 경로 모두 task 종료, 자식 returncode -9, stdout paused 해제, 잔여 buffer 0을 assertion으로 확인했다. timeout은 `TimeoutError`, 직접 cancellation은 `CancelledError`로 종료했다. 외부 관찰 제한 700ms까지 cleanup이 남아 있는 경우는 없었다. 재현 스크립트는 exit 0이었다.

실행 출력:

```text
{'mode': 'timeout', 'cleanup_wait_blocked': False,
 'exception': 'TimeoutError', 'child_returncode': -9,
 'stdout_paused': False, 'stdout_buffer_bytes': 0,
 'declared_deadlines': [60, 10]}
{'mode': 'cancel', 'cleanup_wait_blocked': False,
 'exception': 'CancelledError', 'child_returncode': -9,
 'stdout_paused': False, 'stdout_buffer_bytes': 0,
 'declared_deadlines': [60, 10]}
```

재현 파일은 `/tmp/james-transport-migration-postfix-0a-probe-20261004.py`다. SHA256은 `a7873cd7dec06da222c433b7e690ab9d0ae2d35186530d4f45ecda69f5b7017e`다.

```powershell
wsl -d Ubuntu-26.04 -- /tmp/transport-recovery-venv/bin/python /tmp/james-transport-migration-postfix-0a-probe-20261004.py
```

## 읽기 전용 검증과 NOT_RUN

- `gh pr view`의 head가 candidate와 일치했다. CI `37194466593`와 `37194463827`의 backend/frontend/transport-admin 각각 SUCCESS를 직접 조회했다. optional live-e2e는 두 실행 모두 **SKIPPED**다.
- cleanup 자체가 실패하면 그 오류가 원래 예외와 함께 실패로 드러나는 구조다. cleanup 상한 10초는 각 migrate 호출의 제한이며 전체 PostgreSQL 테스트에 단일 70초 상한이 생겼다는 뜻은 아니다.
- 직접 PostgreSQL migration·전체 regression·진행 중인 n150 전체 suite·새 live UI 조작: **NOT_RUN**. 진행 중인 결과를 미리 PASS로 기록하지 않았다.
- 기존 승인 UI의 재사용 근거는 제품 tree 동일성이다. 이번 리뷰에서 새 브라우저 실행을 했다고 주장하지 않는다.
- 실제 Alembic의 대량 로그·네트워크 장애·운영 DB 복원·운영 daemon/provider/RSS: **NOT_RUN**. 검증 범위는 고정 helper의 파이프와 cancellation/timeout cleanup이다.

원본은 저장 후 별도 SHA256을 전달하며 이후 통합 판정에 맞춰 고치지 않는다.
