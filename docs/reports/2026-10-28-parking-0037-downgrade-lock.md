# 0037 downgrade의 영구 행 소실 경쟁 조건 보완

## 범위와 현재 수용

PR161의 exact833a69ee1ae551c9c0323495d6d9d417766a0bd3 독립 리뷰에서 빈 표 검사와 DROP 사이의 경쟁 조건을 발견했다. 원833/WT/ref/집중·CI와 이전 c763/d2 실패·전체 원장은 그대로 보존한다. 새 전용 branch에서0037 downgrade와 회귀만 보완했으며 API·reader·수집·Dagster·모델·의존성·프론트 제품은 변경하지 않았다. 새 후보의 정확 CI와 독립 두 증분 리뷰는 별도 수용 항목이다. main push·머지·운영 변경·prune 실행은0이다.

원본48시간·통계영구 정책은 아직 미완이다. PR162 pure reader와163 DB adapter가 실제 API/cache/bundle/outlook에 연결되지 않았고, 운영 backfill/연속 coverage·history48h/cursor410·정밀도·현재/Map export·복원 보호와 검산 후 bounded prune도 남는다. downgrade만 안전하게 바꿨다고 보존 정책 완료로 표시하지 않는다.

## 실제 RED와 최소 수정

기존0037은 세 표를 `SELECT 1 ... LIMIT 1`로 비었다고 확인한 뒤 각각 DROP했다. 검사 뒤 두 번째 실제 PG 세션이 영구 행을 INSERT·COMMIT하면 DROP이 그 행까지 지웠다. 새 독립 PG18.6에서 실제 Alembic37→36 step과 version 갱신을 같은 transaction으로 실행했다. 세 번째 세션의 `pg_blocking_pids`로 writer의 실제 잠금 대기를 관측했다. 각 테스트는 최종 판정을 기록한 뒤 schema37로 복원하여 뒤 테스트를 격리한다. dump가 경쟁 시점의 중간 상태를 그대로 담았다고 주장하지 않는다.

| 실행 | 실제 결과 | 의미 |
| --- | --- | --- |
|첫 RED|7 FAIL/1 PASS·actual1|fixture의 필수 airport_id 누락. 제품 경쟁 조건 재현이 아니며 원문을 별도 보존했다.|
|수정 fixture RED2 + 원833 제품|3 FAIL/5 PASS·actual1|세 표 각각 writer가 DROP 전에 commit했고,37→36 commit 후 세 표가 모두 사라졌다. 원본 snapshot·기존0036 통계 sentinel은 유지됐다.|
|수정 제품 WSL|12 PASS·실패/오류/skip0·actual0|세 writer가 DDL 잠금을 실제 기다렸고, 빈 표 DROP commit 후42P01로 거절되어 새 행이 commit되지 않았다.|
|동일 수정 제품 Docker|12 PASS·실패/오류/skip0·actual0·독립 wait0|동일 세 경합과 나머지 경계를 다시 검증했다.|

RED2의 migration은 원833 Git blob과 LF 정규화 후 동일하고, RED2와 GREEN의 세 경합 테스트 함수 AST는 동일하다. 기존 archive의 CRLF와 Git blob의 LF 차이는 별도 기록했다. 제품 수정은 `parking_archive_issues`→`parking_global_statistics_buckets`→`parking_latest_states` 고정 순서의 단일 `LOCK TABLE ... IN ACCESS EXCLUSIVE MODE`를 먼저 실행하고 잠금 아래 빈 표를 재검사하는 것이다. `SET LOCAL lock_timeout = '5s'`는 대기를 제한하며, 실패하면 transaction을 rollback한다. 삭제 허용 조건을 넓히지 않는다.

12회귀는 세 표의 검사 후 writer3건, 이미 commit한 행 거절3건, 잠금보다 먼저 시작한 writer의 commit 후 재검사 거절3건, 일부 DROP 뒤 주입한 DDL 실패의 전체 rollback1건, 잠금 timeout의 표·version·writer 행 보존1건, SQLite 빈 표 DROP/유데이터 거절1건이다. 실제 Alembic step으로 DROP과 version 변경의 원자성을 확인했으며 PostgreSQL 외 분기에는 전용 잠금 문법을 보내지 않는다.

## 환경·원장·검증 한계

- PG18.6/server_version_num180006, 새 UUID의 독립 DB4개, disk volume·2GiB/1CPU·internal subnet·공개 port0이다. 기존 PG/venv/다른 프로젝트를 변경하지 않았다.
- WSL Python3.12.13의 frozen106/Git10을 실행 전후 비교했다. Docker는 기존 검산된 strict106 이미지 `71be1a0e98da…`와 동일 source를 읽기 전용으로 사용했다. source 전후 동일·원 child 종료·실제 exit와 Docker wait를 회수했다.
- 앱 QA 이미지의 native client16을 그대로 사용했다. 이번 검증은 PG18 서버의 migration 경쟁 조건이며 앱 backup/restore의 native18 적합성이나 운영 ARM 이미지 수용으로 확대하지 않는다.
- WSL pytest6.83초, Docker6.94초이고 기존 FastAPI/Starlette deprecation warning 각1건이다. 새 전체 검증은 실행하지 않았다. 원833의 각310PASS+6subtests 및 두 CI run40600192409/40600199508의 backend/frontend/admin SUCCESS·live SKIPPED를 새 source의 전체 수용으로 바꾸지 않는다.
- 원장 `/var/tmp/parking37-downgrade-lock-20261028-f78c063adaca`에 RED/RED2/GREEN source·JUnit·로그·PID/startticks/CID·실제 종료를 보존한다. `final/focused-proof.json` SHA256 `bdcc67d1fd4183f9b4f68bab8d52300af7961d2d43d50ef647e7b24d7112addc`가 세 경합의 실제 증거·동일 source/runtime와 네 dump를 연결한다.
- 각 DB dump·SHA와 disk volume을 보존한 뒤 client0·정확 CID/owner/자식 종료를 확인하고 소유 PG/container/network만 정리했다. `final/cleanup.json` SHA256 `e247ef72d3a2206a238a66f9e289a00c10ed326660682635f393bc696b462c67`이다. 원본 운영 데이터 삭제나 다른 자원 정리는0이다.

새 정확 head의 CI와 독립 James/Popper의833→수정 증분 리뷰가 끝나기 전 머지하지 않는다. 기존833의 collection/Dagster 자동병합 검토도 이 downgrade 집중 검증으로 대신하지 않는다.
