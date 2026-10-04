# Transport Dagster 공통 채택 적대 리뷰

상태: POST_FIX_REVIEW. base `e00e634b8502cdd1060d735b250ece96fd9fc945`.
사용자가 최신 weather/common 채택·2인 적대 리뷰·live UI·PR 머지를 요청했다.
각 reviewer는 상대 원문을 제외한 고정 Git 객체를 읽었으며 source를 수정하지 않았다.

## 첫 후보 원문

runtime `781723356e3f73ae2f48f8df831b3a6970a898e3`, common Python `430a9e9`.
두 CI에서 PostgreSQL 655 passed·1 skipped와 관리자·공개 UI가 통과한 뒤 리뷰했다.

- [James](evidence/2026-10-04-transport-final-james.md): PASS, 비차단 P2 두 건.
  SHA256 `49BE6EE2E166593C179C998725D18336970CD640F5E07825D408EA0E128600AF`.
- [Popper](evidence/2026-10-04-transport-final-popper.md): BLOCK, P1 두 건·P2 두 건.
  SHA256 `FF324ADB927ED08C277B1E6142CA0B31F0FEAC489C37523E0E52251E14339CD3`.

| finding | 재현·반영 | 상태 |
|---|---|---|
| B-T-P1-01 rollback 뒤 만료된 상태가 fence 추적 삭제 | 실제 read rollback·오류 receipt commit·reaper failed·ORM/bulk late commit. 알 수 없는 ORM 상태도 추적 유지 | 수정·재리뷰 대기 |
| B-T-P1-02 lease loss를 삼킨 뒤 다음 provider가 새 run 게시 | lease loss 즉시 전파, 같은 op의 새 session에 회수 사실 유지, 새 op/session native owner 생존 확인 | 수정·재리뷰 대기 |
| J-FINAL-P2-01 / B-T-P2-01 오래된 pending 실행 누락 | QUEUED·STARTING·STARTED·CANCELING 모두 별도 1000건 조회, 최근 30건 밖의 세 상태 표시 회귀 | 수정·재리뷰 대기 |
| J-FINAL-P2-02 / B-T-P2-02 Python provenance 불일치 | Python pin 430a9e9와 UI source 9da1889 구분 | 수정·재리뷰 대기 |

처음 다섯 공격 회귀는 옛 source에서 5 FAIL을 확인한 뒤 수정 source에서 PASS로 확인했다.
metadata 장애는 provider 호출 전에 예외로 전달하고 생존 owner를 revoked로 오판하지 않는
회귀도 추가했다. ordinary provider RuntimeError 때 다음 provider를 계속하는 기존 계약을 유지한다.
복구 경계 35 tests·ruff, 관리자 149 tests/type/build PASS. 수정 후보의 전체 회귀·CI·두 재리뷰가 필요하다.

## 실제 검증 범위

[live UI 원문](evidence/2026-10-04-transport-live-ui.md)과 캡처를 보존한다.
격리 API 홈 응답과 공통 메뉴의 Dagster 이동도 확인했다. 전용 migration DB에서
0023→0024→check→0023 downgrade(두 owner column 제거 확인)→0024→check PASS.
이전 후보 WSL 전체 647 passed·9 skipped, 격리 PostgreSQL 복구 29 tests·설치 common
56 tests, 관리자 Docker 146·공개 Docker 130 tests PASS. 새 코드 결과로 바꾸어 집계하지 않는다.

운영 shared coordinator 변경·운영 worker 강제 종료/실제 retry child·운영 RSS는 NOT_RUN이다.
reaper의 전체 tick 공정성·동시 heartbeat CAS barrier·모든 savepoint 조합은 추가 규모/동시성
검증 범위이며 단위·코드 승인이나 live UI 성공과 합산하지 않는다.
