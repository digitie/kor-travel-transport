# 공항 주차 수집 뒤 분석 캐시 갱신 복구

## 2026-10-26 최종 코드 정산

정확 소스 `0a91260a2e7699de36403f4a94f2822ccca5896f`는 필수 CI와 James/Popper 최종 코드 PASS 뒤
[PR134](https://github.com/digitie/kor-travel-transport/pull/134)의 main `f5f96efa010f3bb77c220b1da6aa33a5601d2381`에 머지됐고 tree가 같다.
WSL1170통과/23건 건너뜀, backend CI1191통과/2건 건너뜀, 격리 PG 집중122개를 확인했다.
PG 전체는 정확 컨테이너의 독립 exit0 증거가 있으나 stdout은 완료 표시919에서 끊겼고 최종 pytest 건수·wrapper `full.exit`는 미회수다.
전체 건수를 다른 실행으로 추정하지 않는다. 원인 미확정과 운영 자연 tick의 대조는
[통합 수용·인계 원장](2026-10-26-parking-admin-integration-acceptance.md)에 남겼다.

## 범위와 재현

T-PARK-01/02의 코드 경로를 검증했다. 운영 DB의 원본·run·cache 시각은 아직 대조하지
않았으므로 운영 정지 원인 전체를 확정하거나 운영 데이터 수용 완료로 처리하지 않는다.
새 공항주차장 관리자 뷰는 별도 작업이며 이 변경은 기존 API 계약을 유지한다.

기존 `airport_collection_job`은 5분 일정이 이미 있으나 `CollectionService.collect`만
호출했다. 수동·in-process 수집은 새 스냅샷 뒤 `refresh_default_analytics_cache`를
호출했다. 네 기본 분석 API는 캐시 존재 여부만 보고 응답했다.

WSL의 격리 DB에서 실제 Dagster job을 두 번 실행했다. 첫 관측의 잔여면80으로 캐시를
만든 뒤 잔여면5인 다음 관측을 저장하면 `/v1/parking/current`는5를 반환하고
`/v1/parking/analytics/timeseries`는80에 머물렀다. 정상 성공과 인천 수집만 실패한
부분 성공 모두 같은 실패를 재현했다. 수정 전 두 회귀는 `80 == 5`로 실패했다.

## 변경 계약

- 기존 job·5분 일정·provider·스냅샷 중복 키·UTC 저장을 유지한다. 새 job·설정·테이블·인덱스를
  추가하지 않는다. 원본 수집 commit 후 같은 event loop에서 기존 네 분석 계산을 재사용한다.
- 새 스냅샷이 있거나 수집이 정상 성공했으면 기본 분석을 갱신한다. 동일 관측이 반복되어
  삽입0건인 정상 tick도 이전 캐시 실패·재시작으로 놓친 파생 결과를 복구한다.
- 부분 성공의 저장분도 분석에 반영한 뒤 기존 Dagster `Failure`를 유지한다. 캐시 갱신이
  실패하면 파생 transaction만 rollback하며 이미 저장한 원본·run 결과를 되돌리지 않는다.
  원본 성공 뒤 파생 실패는 별도 Dagster 실패로 표시하고 자동 재시도하지 않는다.
  부분 성공과 파생 실패가 겹치면 원래 부분 성공 실패를 유지하고 가린 캐시 원인을 metadata에 더한다.
- PostgreSQL의 재집계는 수집이 쓰는 기존 airport advisory key의 transaction 잠금을 먼저
  시도한다. 경합이면0건으로 건너뛰며 수집 실패로 바꾸지 않는다. 획득했으면 재집계 commit 또는
  rollback까지 보유한다. 기존 수집기의 전용 connection 잠금·소유권·게시 fence는 변경하지 않는다.
- 캐시의 `generated_at`은 잠금 획득 뒤 첫 원본 조회 전의 보수적 시각이다. 여러 metric과
  주차장 scope에 같은 시작 시각을 쓴다. `source_observed_at`은 실제 마지막 관측 시각으로 별도 유지한다.
  원본 적재가 시작된 뒤 cache가 읽히는 경합과 오래된 시각의 지연 관측을 이 둘의 혼동으로 숨기지 않는다.
- 캐시 조회는 같은 SQL 문장의 scope별 `collected_at > generated_at` 존재 조건으로 새 적재를
  확인한다. 새 관측 시각이 이전 최대 `observed_at`보다 오래되어도 캐시를 거부한다.
  생성이10분을 넘었거나 미래 시각이면 기존 직접 계산 경로로 돌아간다. 10분은5분 수집 두 주기이며,
  새 적재가 없을 때도 이동 기간의 탈락 관측을 캐시에 무기한 남기지 않기 위한 상한이다.
- 캐시의 빈 배열은 유효한 결과로 유지한다. 캐시 부재/만료와 원본0건, 정상 중복0건,
  수집 실패를 서로 바꾸지 않는다. API DTO·질의 기본값·7일 주차 시계열의 비행편 분리는 유지한다.

## 검증 원장

아래 경로는 저장소 밖의 테스트 증거이며 운영 데이터·비밀값을 포함하지 않는다.

| 검증 | 결과·증거 |
|---|---|
| 수정 전 실제 job→DB→동일 API | 정상·부분 성공2건 실패. `/tmp/codex-parking-analytics-red.log` |
| WSL 집중 회귀 | 사전 리뷰 보완 후102건 통과·PG 전용1건 건너뜀. 실제 job→개별4개/묶음 API, 파생 rollback·원본 보존·0건 복구·만료·지연 관측. `/var/tmp/codex-parking-analytics-tests.9Hb7tN/review-fixed-focused.log` |
| 격리 PostgreSQL16 + Compose | 사전 리뷰 보완 후122건 통과. 신규12건은 실제 PG 모델로 검증했다. `/tmp/codex-parking-analytics-pg.3c3ogm/review-fixed-focused.log` |
| PostgreSQL migration/check | 기존 head upgrade와 `alembic check` 통과. 같은 격리 project의 `migrate.log`, `alembic-check.log` |
| OpenAPI 정본 | `scripts/export_openapi.py --check` 통과. API DTO·공개 경로 변경 없음. |
| WSL 전체 백엔드 | 최종 소스1170통과/23건 건너뜀·exit0. `/var/tmp/codex-parking-analytics-final.94LKtZ/wsl-full.log`. 이전 중단 실행은 합산하지 않는다. |
| Compose PG 전체 백엔드 | 정확 실행 컨테이너의 독립 wait exit0. 최종 pytest 건수/summary와 wrapper 종료 파일은 미회수이며 전체 건수는 기재하지 않는다. 같은 폴더 `pg-tools-final/readonly-diagnosis-20261025.json`. |
| CI·독립 리뷰 | 최종 소스 CI1191통과/2건 건너뜀, James/Popper 최종 코드 PASS 뒤 PR134 머지. |
| 운영 시각 대조 | 자연5분 job의 원본/run/cache/API 연결은 미수용. 코드 머지로 T-PARK-01/02를 완료하지 않는다. |

격리 PG 테스트는 실제 `CollectionService`의 저장 flush 뒤 commit을 대기시켰다. 이때
cache 잠금 시도는0건을 반환하고 이전 정상 캐시를 덮지 않았다. 원본 commit 직후에도
수집 전용 잠금이 유지됨을 다른 connection의 잠금 시도로 확인했다. 수집이 반환한 뒤
API는 이전 캐시를 거부했다. 두 재집계의 경합, rollback 뒤 재획득도 확인했다.

첫 Docker 시도의 실패1건은 source mount가 compose 계약 파일을 가린 검증 환경 문제였다.
현재 전체 source를 읽기 전용으로 `/repo`에 마운트한 뒤 같은118건을 다시 통과했고,
사전 리뷰 보완 뒤122건도 별도로 통과했다.
임시 PG는 외부 port·새 bridge network 없이 `network_mode: none`으로 실행하고 테스트
backend만 같은 network namespace를 사용한다. 다른 프로젝트의 프로세스·DB를 조작하지 않는다.

첫 WSL 전체 실행의 backup 실패는 `/tmp` tmpfs의 여유851MiB가 기존 최소2GiB guard에
걸린 환경 문제였다. 같은 소스를 `/var/tmp`의 별도 basetemp에서 실행하면 해당 단독 사례는
통과했다. 실패/중단 로그는 보존하고 다른 에이전트 파일은 정리하지 않았다.

## 사전 리뷰의 재현 구분

Popper가 제기한 빈 `TimeoutError`의 Dagster 성공 오인 주장은 sanitizer를 단순 통과
lambda로 바꾼 AST 재현이었다. 실제 sanitizer는 빈 문자열을 입력 class명으로 바꿔,
같은 실제 job/DB의 정상·부분 성공6건에서는 실패 상태가 유지됐다. 이를 실제 P1 재현으로
보고하지 않는다. 이 확인 로그는 `popper-p1-red.log`이며 결과는6건 통과다.

대신 빈 `TimeoutError`·`RuntimeError`의 metadata가 모두 `str`이 되어 예외 종류를 잃는
문제는 실제 job/DB4건에서 재현했다(`blank-cause-red.log`). 원래 예외 객체를 기존
`_sanitize_op_error`에 넘겨 종류와 비밀값 가림을 보존한 뒤 길이를 제한한다. 실패 여부는
표시 문자열의 truthiness와 분리해 오류 키 존재로 판단한다. 원본 commit·부분 성공 우선·
재집계 rollback·0건 tick 복구 회귀와 함께102/122건을 다시 통과했다.
위 두 로그도 같은 `/var/tmp/codex-parking-analytics-tests.9Hb7tN`에 보존한다.

## 격리 PostgreSQL 비용

초기 제품 후보 `b70e412`에서 PostgreSQL16·backend CPU1개 제한의 같은 임시 project에 두 공항 각125,000개,
합계250,000개 스냅샷을 만들었다. 설치 의존성의 version·Git commit은 backend
`uv.lock` SHA256 `162153de878256e723a91a7f94a1c067b698b972370b0ae74145df9973fa2a95`와
일치했다. 이 표본은 운영 관측이나 운영 지연 달성 증거가 아니다.
후속 예외 표시/실패 판정 보완은 캐시 SQL과 정상 계산 경로를 변경하지 않았다.

| 단건 캐시 조회30회 | 이전 수용 조건 중위 | 신선도 검증 중위 / p95 |
|---|---:|---:|
| 새 적재 없음 |2.343ms |3.296ms /4.277ms |
| 다른 공항의 새 적재62,500개 |2.481ms |8.368ms /10.324ms |

`EXPLAIN ANALYZE`는 기존 `ix_parking_snapshots_collected_at`을 사용했다. 새 적재가
없으면 원본0행 탐색, SQL 실행0.103ms였다. 두 번째 표본은 인덱스에서 새62,500행을
검사해 다른 공항 행을 제외했고 SQL 실행8.454ms였다. 과거250,000행 전체를 순차 탐색하지
않았으나 새 적재량에 따른 비용은 존재한다. 기존 인덱스로 측정한 결과이며 새 인덱스를 추가하지 않았다.
16개 metric/scope 캐시의 생성은5.823초, 변경 뒤 복구는5.935초였다.

실제 FastAPI `TestClient`로 API까지 호출한5회 표본의 중위는 다음과 같다. 각 경로의
첫 요청은 워밍업으로 제외했다. 이전 조건은 메모리에서만 교체했고 소스를 변경하지 않았다.

| 조회 경로 | 기존 캐시 수용 | 현행 캐시 검증 | 기존 직접 계산 강제 miss | 만료 검증 후 직접 계산 |
|---|---:|---:|---:|---:|
| `/v1/parking/analytics/timeseries` |21.4ms |18.2ms |78.1ms |89.7ms |
| `/v1/dashboard/analytics` |323.3ms |246.6ms |2011.9ms |2047.4ms |

워밍업·병행 검증 부하를 포함하므로 현행 캐시 경로가 더 빠르다는 인과 결론으로 사용하지
않는다. 신선도 검증의 단건 SQL 비용과 전체 응답 비용을 구분한다. 정상 캐시 경로는 이 표본에서
1초 이내였지만 직접 계산 fallback은 약2초로 지연 목표를 충족하지 못했다. 원본이 commit되고
재집계가 끝나기 전 또는 캐시 재생성이 실패했을 때도 정확한 원본을 반환하는 대신 이 비용을
지불한다. 응답을 빠르게 보이게 하려고 이전 캐시를 최신으로 수용하지 않는다.

원시 계획·계측은 같은 project의 `benchmark.json`, `api-benchmark.json`에 보존한다.
첫 표본 생성의 timestamp 형 추론 오류는 명시적 `timestamptz` cast로 고친 테스트 준비 문제이며
제품 오류·통과 횟수에 합산하지 않는다.

## 남은 수용

운영의 최신 원본/run/cache/API 시각 대조와 실제5분 job 이후 동일 관측 반영은 별도 검증이다.
캐시를 검증하는 SQL 비용과 재집계 비용은 격리 PG 표본으로 측정하며 운영 지연 목표 달성으로
오인하지 않는다. 이 변경의 소스 머지 뒤에도 공항 주차 예측의 충분한 과거 표본·운영 일정의
실제 활성 상태·관리자 전체 뷰의 모바일 수용은 각각 남는다.
