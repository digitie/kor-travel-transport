# 2026-10-27 주차 영구 통계 선행 저장

## 범위

사용자는 주차 원본을 이틀만, 통계자료를 영구 보존하도록 확정했다. 이 변경은 그 정책의 **1단계**다. `0036` 영구 통계 테이블과 수동 DB 전용 Dagster job을 추가하고, 원본 정리 진입은 항상 차단한다. 현재 분석/API/UI 읽기, 원본, provider, 자동 수집/schedule은 바꾸지 않는다. 전체 48시간 정책의 적용 완료나 운영 배포가 아니다.

[보존 설계·조사·남은 전환](../architecture/parking-retention.md)과 [ADR-015](../adr/015-parking-raw-and-statistics-lifetimes.md)를 따른다. 문서를 두 번 정리해 원본/통계/캐시 수명, source 탐색/검산, 첫 단계/최종 정책의 범위를 구분했다.

후속 최소 보완은 영구 통계가 있는 DB의 legacy 이관 덮어쓰기를 차단한다. SQLite의 PK upsert와 HTTP 원본 수정/중복 삭제는 실제 존재하는 경로다. HTTP 조회 전과 첫 쓰기 전 검사, 원천/통계와 같은 transaction lease, SQLite sequence 조정까지 단일 commit으로 보호한다. 통계가 없는 정상 이관은 유지하며 force 옵션·새 UI는 추가하지 않는다.

## 구현

- 주차장별 충분통계·용량 양수 전망 표본, 경계/최신 추이점과 최신 기준 시각, 공항 동일 timestamp 합산 통계, 원관측 10/50 이벤트와 직전 시각을 10분 범위로 보존한다.
- 원본 개별 배열·JSON을 복사하지 않고 행 수·SHA-256과 재계산한 통계 checksum을 검증한다. 이미 발행한 구간의 원본 재수신/변경이 발견되면 덮지 않는다.
- `no_new_rows`/`not_audited`는 새 id가 없다는 뜻이다. 같은 id 변조·행 누락까지 검사했다는 주장이 아니다. 선택된 범위만 검산하고 삭제 직전에는 모든 후보를 다시 검산해야 한다.
- 원천 collector와 같은 PostgreSQL transaction advisory lock, 제한된 하루 범위/기본144개 버킷, 최근 48시간에 적재된 오래된 관측의 보류, caller commit/rollback을 사용한다.
- 통계는 TTL·retention이 없고, 공항 FK는 RESTRICT다. 데이터가 든 migration downgrade는 차단한다. 되돌림은 schema36 호환 앱 후보를 준비해야 하며 예전 이미지만 교체하거나 영구 통계를 지우면 안 된다.

## 확인한 것

모든 로컬 데이터는 `codex-parking-archive-a37e` 소유의 전용 PostgreSQL/DB 또는 테스트별 SQLite다. 운영·rail 전용 자원·타 컨테이너를 사용하거나 변경하지 않았다. WSL 런타임은 Python3.12.13, 현재 branch의 `uv.lock --frozen --extra dev` 106개 설치다.

- PostgreSQL 신규 DB의 base→0036 migration과 `alembic check` 통과.
- 최종 PostgreSQL 집중·API/lifespan 22개 통과. 표본 가중 평균, source 중복, 같은 시각 공항 합산, 양수 용량 전망, 원관측 이벤트/직전 상태, 배치 재개/rollback, 실제 lock 경합, 기존 공개 API 값 보존을 포함한다.
- SQLite 집중·API/lifespan은 최신 metadata 추가 전 21개 통과·PostgreSQL 전용1개 건너뜀을 확인했다. 최종 소스의 전체 WSL/Docker는 별도 진행하며 이 결과로 대신하지 않는다.
- 원본 삭제 후 같은 과거 관측 재수신을 테스트 DB에서 모사해 기존 통계가 그대로 보존되고 충돌하는 것을 확인했다. 같은 id 수정·원본 누락도 `not_audited`와 명시 검산 실패로 구분한다.
- 10,000개 합성 통계·900개 원본의 기본 PostgreSQL 계획에서 시각 인덱스→Nested Loop Anti→PK `(airport_id,bucket_at)` 등가 탐색, inner Plan Rows1을 확인했다. `EXPLAIN ANALYZE`는 실행하지 않았고 planner 설정도 바꾸지 않았다. 실제 운영 성능 결과가 아니다.
- 합성 통계10,000개가 든 실제 DB의 downgrade는 exit1이며 schema36/행10,000개를 유지했다. 전용 합성 데이터를 비운 후 empty downgrade35와 다시 upgrade36은 각각 exit0이다.

증거 루트는 `/var/tmp/codex-parking-retention-20261027-a37e/`다. `postgres-focused-final-r1.xml`, `sqlite-focused-final-r2.xml`, `lookup-plan-r2.json`, `migration-proof-r1.json`에 각 결과를 분리했다.

## 실패·한계와 남은 게이트

### 589 전체 시험의 QA 무효화

`589eac1`/Common `c289b462`의 전체 두 실행은 **통과가 아니다**. 본인 QA PostgreSQL을 512MiB/tmpfs로 구성해 메모리가 503.8MiB(98.4%)에 도달했고 cgroup `oom_kill=1`, 12:39 UTC의 PostgreSQL child SIGKILL·재초기화와 연결 오류를 확인했다. 메모리 조건을 실행 도중 바꾸지 않고 본인 pytest 두 개에만 SIGINT 각1회로 중단했다. 부모·다른 프로세스·PG에는 신호를 보내지 않았다.

| 실행 | 실제 exit | JUnit testcase 요소 수 | 주요 실패/오류 | 분류 |
|---|---:|---:|---|---|
| WSL | 1 | 1,246 | service exports 1실패·9오류 | `INVALIDATED_QA_OOM` |
| Docker | 1 | 1,100 | deploy host20·remote3·manager2실패, KRIC1실패·10오류 | `INVALIDATED_QA_OOM` |

두 로그의 KeyboardInterrupt, 실제 exit/result, JUnit과 runner/pytest/compose 종료·초기 자식 잔여0을 회수했다. 초기 start proof에는 startticks가 없었으므로 그 사실을 남기고 PID/PPID/argv/CWD/DB/보존stdoutFD·label/CID·시작 UTC와 boot 기준 birth를 함께 대조한 뒤 신호를 보냈다. 기존 PG는 stop·조건변경 없이 보존했고 세 테스트 DB의 custom dump도 각각 exit0으로 보관했다. 운영 변경은 없다.

Docker의 앞선 deploy 실패는 minimal PATH에 `python3`가 없는 별도 QA 문제였다. Node가 없다고 단정하지 않고 실제 Node37개 통과와 deploy 첫 실패를 분리 재현했다. 동일 인터프리터의 `/usr/bin/python3` 별칭만 둔 새 r4 이미지에서 deploy 관련84개 통과·1개 건너뜀을 확인했다. 기존 실행 컨테이너를 고치지 않았다.

### 보완과 R2 준비

새 UUID 프로젝트 `codex-parking-archive-r2-7db4aacf`는 internal `10.254.247.16/28`, 포트 없음, 2GiB·디스크 기반 소유 named volume을 사용한다. 이전 tmpfs·DB·실패 이미지/로그/입력을 재사용하거나 없애지 않는다. 새 runtime과 WSL/Docker 전용 DB를 만들고 schema36까지 각각 적용했다. 해당 자원에서 legacy·원본 archive·이력·lifespan/health 집중52개가 통과했다. 같은 세 entry 회귀를 실제589 이관 스크립트에 적용하면3개가 실패하는 RED도 별도 DB에서 보존했다. 이 결과를 전체 R2 통과라고 확대하지 않는다.

공식 복원 flags의 합성 DB 검증은 schema35→36 거절/통계 보존과, 같은 schema36 옛 dump의 통계2→1 손실 가능성을 각각 확인했다. 첫 검증 client의 stdin 전달 누락 원본은 보존하고 새 DB와 명시 stdin 전달로 재검증했다. API pre-backup은 이 실험에서 실행하지 않았고 운영 복원도 아니다.

R2 증거 루트는 `/var/tmp/codex-parking-retention-r2-20261027-7db4aacf/`다. `guard-focused-r2.xml`, `legacy-scripts-589-red.xml`, `restore-r2-boundaries-proof-r1.json`을 분리했다. 최종 소스·runtime·DB·프로세스/메모리·manifest 사전 확인 뒤에만 전체 R2를 시작하며, 두 독립 리뷰·정확 head CI·운영 수용과 최종 읽기/삭제 전환은 아직 미완이다.

첫 순수 테스트의 합계 기대값 오기(130→120)는 수정했으며 실패 원본을 남겼다. SQLite의 첫 등가 조회는 type 없는 문자열 `+`가 산술로 번역되어 두 회귀가 실패했다. String type을 명시해 수정했다. 같은 실행의 OpenAPI 두 실패는 QA에서 저장소 전체 계약 파일을 복사하지 않은 문제였으며 전체 Git 원본+현재 변경으로 보완했다. 원래 로그/시험 결과는 지우지 않았다. 초기 `min` 후보 계획의 전체 Hash Anti Scan도 `lookup-plan-r1.json`으로 남겼고 현재는 정렬 인덱스와 LIMIT를 쓴다.

최초 집중 시험 기준은 main `1f6a970`과 Common `e746e4b8`다. 전체 시험 시작 전에 main `abd4084`의 Common `c289b462`를 통합했고 journal의 두 작업 기록을 모두 보존했다. 기존 통계 service/model·db session·Dagster·0036·통계 회귀6파일은 최초 후보/589와 같고, 새 legacy guard·두 이관 entry·회귀는 별도 보완이다. 새 pin을 별도 런타임에 설치했으며 앞선 집중 결과를 새 pin 통과라고 바꾸지 않는다. CI·전체 R2·두 독립 리뷰·운영 수용과 후속 읽기 전환/48시간 삭제는 미완이다. 영구 통계의 원본 삭제 뒤 재생성 가능성을 주장하지 않는다. 오래된 백업 복원·수동 lot 삭제/ID 재사용의 통계 정합도 최종 정리 활성화 전 수용 목록에 남긴다.
