# 2026-10-27 주차 영구 통계 선행 저장

## 범위

사용자는 주차 원본을 이틀만, 통계자료를 영구 보존하도록 확정했다. 이 변경은 그 정책의 **1단계**다. `0036` 영구 통계 테이블과 수동 DB 전용 Dagster job을 추가하고, 원본 정리 진입은 항상 차단한다. 현재 분석/API/UI 읽기, 원본, provider, 자동 수집/schedule은 바꾸지 않는다. 전체 48시간 정책의 적용 완료나 운영 배포가 아니다.

[보존 설계·조사·남은 전환](../architecture/parking-retention.md)과 [ADR-015](../adr/015-parking-raw-and-statistics-lifetimes.md)를 따른다. 문서를 두 번 정리해 원본/통계/캐시 수명, source 탐색/검산, 첫 단계/최종 정책의 범위를 구분했다.

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

첫 순수 테스트의 합계 기대값 오기(130→120)는 수정했으며 실패 원본을 남겼다. SQLite의 첫 등가 조회는 type 없는 문자열 `+`가 산술로 번역되어 두 회귀가 실패했다. String type을 명시해 수정했다. 같은 실행의 OpenAPI 두 실패는 QA에서 저장소 전체 계약 파일을 복사하지 않은 문제였으며 전체 Git 원본+현재 변경으로 보완했다. 원래 로그/시험 결과는 지우지 않았다. 초기 `min` 후보 계획의 전체 Hash Anti Scan도 `lookup-plan-r1.json`으로 남겼고 현재는 정렬 인덱스와 LIMIT를 쓴다.

최초 집중 시험 기준은 main `1f6a970`과 Common `e746e4b8`다. 전체 시험 시작 전에 main `abd4084`의 Common `c289b462`를 통합했고 journal의 두 작업 기록을 모두 보존했다. 주차 제품 소스는 최초 후보와 동일하며 새 pin을 별도 런타임에 설치한 뒤 정확 통합 후보로 검증한다. 앞선 집중 결과를 새 pin 통과라고 바꾸지 않는다. CI·전체 WSL/Docker·두 독립 리뷰·운영 수용과 후속 읽기 전환/48시간 삭제는 이 문서 작성 시점에 미완이다. 영구 통계의 원본 삭제 뒤 재생성 가능성을 주장하지 않는다. 오래된 백업 복원·수동 lot 삭제/ID 재사용의 통계 정합도 최종 정리 활성화 전 수용 목록에 남긴다.
