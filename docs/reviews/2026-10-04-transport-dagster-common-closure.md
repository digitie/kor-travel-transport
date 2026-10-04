# Transport Dagster 공통 채택 최종 코드 판정

- 상태: CODE_REVIEW_PASS. 최종 문서 CI·격리 Docker 전체 회귀·merge는 PR #67 기록에서 확인한다.
- base: `e00e634b8502cdd1060d735b250ece96fd9fc945`.
- immutable runtime candidate: `027a9ca1ef943d792278cc8a09964bb6e4ea5c44`.
- common Python: `430a9e9cd5429204579792b1d4f8e399366dcb2f`.
- common [PR #25](https://github.com/digitie/kor-travel-common/pull/25)는
  `589a01ef63ff1ce81960e3d531874b5e4c892995`로 merge됐고 Python pin이 main 이력에 포함된다.
- 두 reviewer는 서로의 원문과 통합 판정을 배제한 고정 Git 객체를 독립적으로 검토했다.
- [첫 후보의 BLOCK/PASS 원문·수정 이력](2026-10-04-transport-dagster-common.md)을 보존한다.

## 독립 판정

- [James](evidence/2026-10-04-transport-postfix-james.md): **PASS**, 신규 actionable finding 없음.
  SHA256 `E70808B5B564E5D3FA9B60D752F2929E1F089D92B63F50E561B30937241FFBA8`.
- [Popper](evidence/2026-10-04-transport-postfix-popper.md): **PASS**, 신규 actionable finding 없음.
  SHA256 `2A83B15005488279BC15167180E0A47B1C72F61B2E3C6E05702D72A385366ED1`.

| 기존 finding | 최종 disposition | 검증 |
|---|---|---|
| B-T-P1-01 | CLOSED / FIXED | rollback으로 만료된 ORM도 추적 유지. 오류 receipt commit·reaper failed 이후 ORM/bulk 늦은 게시 차단 |
| B-T-P1-02 | CLOSED / FIXED | lease loss 전파·동일 owner의 새 session에서도 회수 유지·provider 시작 전 native owner 생존 확인 |
| J-FINAL-P2-01 / B-T-P2-01 | CLOSED / FIXED | QUEUED·STARTING·STARTED·CANCELING을 별도 조회, 최근 30건 밖 pending 표시·정체 오탐 방지 |
| J-FINAL-P2-02 / B-T-P2-02 | CLOSED / FIXED | 실제 Python pin 430a9e9와 UI source 9da1889의 provenance 구분 |

심각도를 낮추거나 운영 위험 수용으로 닫지 않았다. Popper는 고정 후보의 선택 회귀
116 passed·1 skipped와 독립 공격을 수행했다. savepoint·heartbeat CAS는 SQLite 공격이며
PostgreSQL 동시 barrier 실행으로 확대 해석하지 않는다. 실제 10초 metadata timeout과 복원,
실제 Dagster FAILURE owner 차단과 생존 owner의 metadata 장애 때 revoked 오판 방지도 확인했다.
James는 고정 source·vendored UI 실행으로 34건 합치기·중복 제거·label/link·scope·조회 상한을 검증했다.

## 원 작업자 검증

- 동일 후보 WSL 전체: **653 passed·9 skipped / 1439.71초**.
- 동일 후보 PostgreSQL 전체 CI: 두 실행 모두 **661 passed·1 skipped**.
  [37187027193](https://github.com/digitie/kor-travel-transport/actions/runs/37187027193),
  [37187024121](https://github.com/digitie/kor-travel-transport/actions/runs/37187024121).
  migration·DB check·OpenAPI export·관리자·공개 frontend도 통과했다.
- WSL 관리자: **149 tests·type-check·build PASS**. 공개 frontend: **130 tests·type-check·build PASS**.
- 격리 n150 PostgreSQL recovery/definitions/runtime: **35 passed / 21.16초**.
- 전용 migration DB: **0023→0024→check→0023→0024→check PASS**.
  downgrade에서 owner 두 column 제거를 확인했다. 수정 후보는 migration을 바꾸지 않았다.
- 격리 서버 설치 common wheel: **56 passed**. 두 common reviewer는 1.13.24와 floor 1.9.0에서도
  각각 56 tests를 실행했고 common CI 8개가 통과했다.
- 공통 UI: **42 tests·build·pack·소비자 설치 PASS**. 최신 후보 관리자 Docker type-check·
  **149 tests PASS / 23.73초**. 첫 전체 실행의 기존 동기 요금 표시 테스트 1개가 5초 timeout을
  넘었으며, source/timeout 설정을 바꾸지 않은 재실행이 통과했다. 공개 Docker **130 tests PASS**.
- [최신 live UI 원문](evidence/2026-10-04-transport-live-ui-postfix.md): 최신 production bundle,
  실제 실패 op, 최근 30건 밖 세 pending 상태, 모바일·키보드, 연결 중단 시 마지막 결과 유지·
  다시 시도 복원 **PASS**. 원문 SHA256
  `79368B90F018D6739995CC9F833EB63D8756358784D172351DFEC18BEE8CA8C7`.
  첫 후보의 로그인·공통 메뉴·native 실패 링크·여러 viewport 증거도 별도로 보존한다.

두 workflow의 live-e2e 항목은 **SKIPPED**이며 브라우저 live 검증과 구분한다.
두 reviewer의 직접 CUA 조작은 NOT_RUN이다. 원 작업자의 실제 CUA 원문·캡처를 검토했다.
metadata SUCCESS 35개와 과거 STARTED는 synthetic fixture이며 실제 provider 수집 성공·
실제 장시간 worker 실행으로 세지 않는다.

## 서버 전체 회귀와 남은 범위

이전 디스크 기반 격리 Docker 전체 테스트는 host I/O 지연으로 중단해 PASS로 세지 않았다.
수정 후보의 디스크 기반 전체 재실행도 `TRUNCATE`의 DataFileImmediateSync 22초·blocker 없음이
확인돼 중단했다. 전용 project `codex-transport-full-pg-20261004`의 PostgreSQL data tmpfs
512MiB / container 768MiB 한도와 backend 2GiB 한도로 다시 실행한다. WAL/fsync 설정을 끄지 않는다.
WAL checkpoint는 max 128MiB·min 32MiB·60초로 설정했다. 첫 RAM DB는 schema bootstrap 누락으로
테이블 없음 오류가 발생해 중단했고 PASS로 세지 않았다. 새 전용 DB에서 Alembic head 초기화 후 다시 실행한다.
RAM DB는 디스크 장애·전원 손실 내구성 검증을 대체하지 않는다. 최종 결과는 PR #67에 기록한다.

운영 shared coordinator 변경·운영 daemon/launcher worker kill·실제 retry child·운영 RSS는
**NOT_RUN**이다. per-record RPC deadline을 넘어 reaper 전체 tick의 규모·공정성/지속 cursor,
PostgreSQL heartbeat 동시 barrier, native metadata와 app DB 사이 cross-storage 원자성도
실측 보장하지 않는다. DB 회수 이후의 게시 금지는 durable owner/status fencing으로 판단한다.

이 closure는 원문·판정·검증 문서만 추가한다. runtime은 위 candidate와 같다.
적용·운영 순서는 [복구 runbook](../runbooks/dagster-recovery.md) 및
[공통 구현 가이드](https://github.com/digitie/kor-travel-common/blob/main/docs/runbooks/dagster-adoption.md)를 따른다.
