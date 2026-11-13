# CI 표본 생성의 반복 조회 제거

## 실제 지연과 원인

- PR192의 backend CI는 중단된 것이 아니라 2026-11-13 03:17UTC에 성공 종료했다. 원문은 1912PASS/2SKIP/54subtests, 3942.17초다. 이 결과를 새 후보의 CI 결과로 쓰지 않는다.
- 기본 `client` fixture는 시험마다 데이터베이스를 비우고 실제 lifespan에서18개 주차장의7일 이상 관측·요금·통계를 다시 구성한다. 표본 생성은 매 시각의 존재 확인 SELECT가 다음 ORM autoflush를 유발해 수천 번 왕복했다. `health`처럼 본문이 작은 시험도 이 준비 비용을 냈다.
- 동일 SHA의 `codex/**` push와 PR 이벤트가 각각 전체 workflow를 실행했다. 이것은 단일 실행65분의 원인과 별개의 중복 자원 소비다.

## 구현과 보존 범위

- 같은 주차장/source에서 실제 생성할 최초 KST 날짜의00:00부터 현재 정렬 시각까지 `observed_at`만 한 번 읽는다. SQLite의 naive UTC는 aware UTC로 맞추고 이번에 추가하는 시각도 집합에 넣는다.
- 원래 순서대로 반시간 관측을 먼저 추가하므로 recent override가 같은 시각의 값을 덮어쓰지 않는다. 기존 ID·가격이 아닌 주차 관측 값·원문·실제 수집 run/source를 보존한다. 기존 미래 표본 삭제 조건(`collection_run_id IS NULL`, 미래 시각)과 범위 밖 과거 관측도 바꾸지 않는다.
- ORM 생성·검증·요금 처리·commit, 전체 표본 범위와 시험 수는 그대로다. 스키마·migration·운영 수집·API 계약·SDK·의존성 변경은 없다. 별도 Core bulk insert나 fixture 표본 축소도 넣지 않았다.
- workflow는 main push와 모든 PR, 명시적 workflow_dispatch를 유지한다. 기능 브랜치는 Draft PR에서 한 번 실행하며 기존 job 이름·전체 시험·수동 live E2E 조건은 그대로다. `pytest --durations=25`를 더해 다음 병목의 실제 시간을 남긴다. 이 후보의 시험 실행자는 CI 취소를 하지 않았다. 부모가 정산한 PR191 과거 소유 SHA의 중복 CI3건 취소와 최신03d9 실행은 별개 기록이다.

## 단일 health 시험 실측

고정 원본842883da와 후보에서 같은 시험용 PG18 이미지·기존 Python 환경/SDK·소유 tmpfs DB로 각각 기존 `test_api.py::test_health` 한 건을 실행했다. 시간은 단일 로컬 표본이며 GitHub runner 전체 개선율이나 p95를 뜻하지 않는다.

| 항목 | 원본 | 후보 |
|---|---:|---:|
| 실제 표본 함수 | 11.320초 | 0.651초 |
| 표본 SELECT 호출 | 6611 | 113 |
| 표본 INSERT 호출 | 6604 | 112 |
| 통계 함수 | 0.321초 | 0.409초 |
| fixture setup | 11.799초 | 1.220초 |
| health 본문 | 0.03755초 | 0.04041초 |

호출 수는 SQL 문장 실행 횟수이며 행 수가 아니다. 후보도 동일한 전체 표본을 생성한다. plugin은 원 함수를 그대로 await하고 종류별 SQL 횟수만 세며 SQL 원문/인자/환경/키를 출력하지 않았다.

## 의미 보존 회귀

- 원본842883da의 함수를 수정하지 않고 두 고정 시각에 실행해 공항·주차장·관측·요금4테이블의 모든 열(ID·JSON 포함)을 UTC 정규화한 SHA256을 발급했다. 새 구현의 SQLite와 PG18에서 같은 해시를 얻고 재실행 후에도 그대로임을 확인했다.
- 2026-11-13 03:20UTC: 공항4·주차장18·관측6510·요금72, SHA `333a87bc1abed519fac49af2327b455a07c6a0902f94b0ec7816a3f4245e03f0`.
- 2026-11-13 15:00UTC(KST 자정): 관측6078, 나머지 행 수 동일, SHA `8c1661ff4dffefe451539d5e8f1100c757aced360e8109b11e504f8e34d666cf`.
- 기존 동일 source/time의0값·ID·실제 run/원문, 다른 source 같은 시각의 병존,20일 이전 관측, run이 있는 미래 관측을 보존한다. run 없는 미래 표본만 기존처럼 제거하며 빠진 표본 한 시각을 복구한다. 생성/재실행의 관측 조회는 각각18회다.
- 초도 집중4개는 WSL SQLite4PASS/18.10초, WSL PG18 4PASS/4.76초, 전체 저장소를 mount한 Docker Compose PG18 4PASS/5.03초였다. 이 원장을 backend 이미지의 파일 배치 증거로 쓰지 않는다.
- 독립 검토 P1은 새 workflow 구조 거울 시험이 backend 이미지에 없는 `.github`를 읽는 것이었다. 그 시험1개만 제거하고 데이터 의미 회귀3개는 그대로 유지했다. YAML은 Git 밖에서 파싱해 허용한 trigger/옵션2곳 외 전체 구조가 원본과 같은지 대조했다. Dockerfile에 `.github`를 추가하거나 skip으로 숨기지 않았다.
- 후속 WSL PG18의 최종3개는4.48초, backend만 `/app`에 read-only mount한 Docker Compose PG18의 같은3개는4.57초로 PASS했다. 서로 겹치는 선행 시험은 합산하지 않는다. 기존 health 전후는 각각1PASS다. 문법·미정의/미사용 집중 Ruff와 diff 검사는0이다. 전체65분 pytest·이미지/생산 빌드·운영 배포는 하지 않았다.

## 원장과 한계

Git 밖 `C:/Users/digit/.codex/tmp/weather-transport-evilcharts-20261112/pr192-ci-duration-20261113/`에 `baseline/original-goldens.json`, `baseline/capture-sys-r2/{timing,receipt}.json`, `candidate/{timing,focused-receipt}.json`과 로그를 보존한다. P1 후속은 `candidate/backend-layout-r2/focused-receipt.json`, YAML 정적 대조는 `candidate/workflow-check.json`이다. 각 PG의 full CID/소유 UUID label을 확인한 뒤 해당 컨테이너만 제거했고 부모 실제 종료·잔여0을 확인했다.

첫 baseline은 `/mnt/c`의 FD capture 임시파일 오류로 health 실행 전 실패했다. 원 pytest1error와 종료 원장을 남기고 별도 고유 PG에서 기존 QA 방식인 `--capture=sys`로만 보정했다. 실패를 성공 시험 수에 합산하지 않는다. 후보 health의 원 `receipt.json`에 있는 `source_revision`은 복제한 runner의 기준842 필드이며 후보 commit을 뜻하지 않는다. 후보 실소스는 `focused-receipt.json`의 SHA와 최종 Git commit으로 연결한다.

새 CI의 전체 소요 시간·required context 수용은 push/PR 이후 별도로 관측해야 한다. 공유 시험 DB를 전역 TRUNCATE하므로 DB 격리 없이 xdist를 추가하지 않았다. 이번 변경은 실제 운영 API 지연이나 외부 수집 제한을 바꾼 증거가 아니다.
