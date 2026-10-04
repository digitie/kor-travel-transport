<!-- SPDX-FileCopyrightText: 2026 digitie -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# James — Transport migration 테스트 독립 적대 리뷰 원본

## 실행·격리

- 실행 ID: `J-TRANSPORT-MIGRATION-20261004-1c5bd965`.
- 관찰 시각: `2026-10-04 09:58:05~10:02:53 UTC` / `18:58:05~19:02:53 KST`.
- 저장소: `F:/dev/kor-travel-transport`.
- 실제 base: `1cb935551222ded6357b02fefed4c03c80183d5b`.
- 실제 candidate: `1c5bd965b02b38bc608ce15de196636d7c09ba4b`.
- 검토 파일 Git blob: `f0b59c7b3d0929a97905e1596dd80b571635931e`.
- Windows Git 고정 객체만 읽었다. 상대 원문·통합 판정·closure·journal 판단은 참조하지 않았다.
- 저장소·DB·컨테이너·진행 중인 전체 suite를 변경하지 않았다. 재현용 Python 파일 하나를 저장소 밖 WSL `/tmp`에 작성하고 자신이 생성한 로컬 subprocess만 종료·회수했다.
- 렌즈: 테스트 격리, subprocess 취소, 실패 후 복구, CI·live 검증 표현의 정확성.

## 판정

**PASS — P0/P1 없음. 비차단 P2 한 건.**

제품 runtime/UI/migration/common pin은 승인한 `027a9ca1ef943d792278cc8a09964bb6e4ea5c44`와 동일하다. P2는 수정하거나 저장소 규칙에 따라 유지 근거를 남길 수 있다. 진행 중인 전체 PostgreSQL suite와 운영 배포의 완료를 뜻하지 않는다.

## Finding

### J-MIG-P2-01 — 취소 후 출력 파이프를 비우지 않는 cleanup이 무기한 대기할 수 있다

- 심각도: **P2**.
- 위치: `backend/tests/test_fuel_statistics_migration.py:85-88`.
- 성격: 기존 helper의 약점이 유지된 사례다. 이번 수정에서 추가한 취소 경로와 CLI 60초 상한의 실효성을 검토하면서 확인했다.
- 실패 시나리오: Alembic subprocess가 많은 진단 출력을 내는 동안 `process.communicate()`가 timeout 또는 cancellation으로 중단된다. 출력 소비도 중단되고 파이프 읽기가 일시 정지될 수 있다. 이후 `kill()`은 자식을 종료하지만 `await process.wait()`가 파이프 정리를 기다리면서 끝나지 않는다. 따라서 취소 cleanup에 진입한 뒤의 실행에는 60초 상한이 적용되지 않는다.
- 영향: 일반적인 적은 Alembic 출력에서는 현재 CI가 정상 통과한다. 많은 실패 로그가 발생하는 조건에서는 테스트가 멈추고, 바깥 `finally`의 head 복원과 engine dispose까지 진행하지 못할 수 있다. 제품 런타임 변경이나 데이터 손실을 재현한 것은 아니다.
- 최소 수정: 취소 시 자식 종료 후 출력 drain/`communicate()`와 reap도 별도 상한 안에서 수행한다. 출력 파이프가 남아 있는 상태에서 제한 없는 `wait()`만 호출하지 않는다. 원래 timeout/cancellation 예외와 복구 실패 정보를 보존한다.

독립 재현은 후보의 `migrate()` AST를 그대로 추출했다. subprocess 실행 대상만 PostgreSQL과 무관한 stdlib 대량 출력 자식으로 대체하고, 60초 deadline을 40ms로 가속했다. 두 번 모두 다음 결과가 나왔다.

```text
{'cleanup_wait_blocked': True,
 'child_returncode': -9,
 'stdout_paused': True,
 'stdout_buffer_bytes': 196608}
{'final_exception': 'TimeoutError',
 'task_finished_after_draining': True}
```

자식이 이미 종료됐는데 cleanup이 계속 대기했다. 재현 harness가 파이프를 직접 비우자 원래 `TimeoutError`로 종료했다.

재현 파일:

```text
/tmp/james-transport-migration-cancel-probe-20261004.py
```

SHA256:

```text
bcbbda4cf668dade45467e0a65e757983cf9dca79f3bb069b3504b8df0b08ffa
```

PowerShell 실행 명령:

```powershell
wsl -d Ubuntu-26.04 -- /tmp/transport-recovery-venv/bin/python /tmp/james-transport-migration-cancel-probe-20261004.py
```

첫 작성 시 harness 문자열의 줄바꿈으로 SyntaxError가 발생했다. 문자열을 수정한 뒤 정상 실행한 두 결과만 재현 근거로 사용했다.

## 직접 확인한 계약

- base→candidate에서 journal을 제외한 변경은 해당 테스트 파일 하나다.
- `027a9ca1`→candidate 전체 비교에서 `docs/**`와 `backend/tests/**`를 제외한 제품 파일은 동일했다. `git diff --quiet` exit 0을 직접 확인했다.
- migration subprocess의 `DATABASE_URL`은 `test_settings.database_url`로 명시적으로 덮어쓴다. fixture는 운영 `DATABASE_URL`을 상속하지 않고 PostgreSQL 테스트에 별도 안전 표지를 요구한다.
- 잠금 관찰은 현재 DB와 `fuel_price_snapshots` relation으로 제한한다. CLI import 시간을 포함하던 측정에서 실제 DB 잠금 대기 시작 시각을 관찰하는 방식으로 개선됐다.
- 정상 경로는 잠금 해제 후 downgrade 재실행, head upgrade와 index 상태 확인을 수행한다.
- assertion 실패 경로도 바깥 `finally`에서 head upgrade를 시도하고, 그 성공 여부와 무관하게 engine dispose를 수행한다. 단, 위 P2처럼 subprocess cleanup 자체가 멈추는 조건에서는 이 단계까지 도달하지 못한다.
- 기존 migration의 MV 보존 순서와 3초 lock timeout은 바뀌지 않았다.
- `pg_locks.waitstart` 이후 측정값에는 CLI 종료 시간이 일부 포함된다. 따라서 정확한 서버 lock timeout 수치만을 직접 측정했다고 해석하지 않았다.

## CI·외부 실행 기록 확인

`gh pr view`의 head가 candidate와 일치했다. 다음 두 실행의 backend/frontend/transport-admin 각각 SUCCESS를 직접 확인했다.

- `37192358801`
- `37192355824`

두 workflow의 `live-e2e`는 **SKIPPED**다. 이를 PASS로 기록하지 않는다.

허용된 로그 두 개를 읽었다.

- `/tmp/transport-ram-migration-lock-postfix.log`: native 단일 테스트 `1 passed`, 14.19초. relation filter 추가 전 실행이라는 전달 조건에 따라 최종 candidate 전체 실행 증거로 집계하지 않았다.
- `/tmp/transport-migration-failure-cleanup-probe.log`: 성공한 downgrade 직후 강제 assertion으로 예상한 `1 failed`, 24.07초. 이어서 `head0024, owner columns2` 복원 확인이 기록돼 있다. 의도한 실패와 cleanup 검증 결과를 구분했다.

이 로그들은 원 작업자 수행 결과다. James가 PostgreSQL migration을 직접 실행한 것으로 표시하지 않는다.

## NOT_RUN·검증 한계

- 직접 PostgreSQL downgrade/upgrade: **NOT_RUN**.
- 진행 중인 n150 전체 PostgreSQL suite: **미확정**, 접근·변경·재실행하지 않았다.
- 새 direct live UI 조작: **NOT_RUN**. 제품 UI가 승인 후보와 동일하다는 Git 비교만 수행했다.
- 실제 Alembic에서 대량 출력을 발생시킨 cancellation: **NOT_RUN**. finding 재현은 고정 helper와 격리된 로컬 stdlib 자식의 파이프 동작 검증이다.
- timeout 이후 head 복구가 모든 네트워크·DB 장애에서도 성공한다는 보장: **미검증**. 복구 실패를 assertion으로 드러내는 코드와 전달된 강제 실패 로그를 확인했다.
- 운영 DB·provider·daemon·컨테이너·RSS 검증: **NOT_RUN**.
