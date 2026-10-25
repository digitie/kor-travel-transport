# 공항 주차 수집 뒤 분석 캐시 갱신 복구

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
| WSL 집중 회귀 |98건 통과. 실제 job→개별4개/묶음 API, 파생 rollback·원본 보존·0건 복구·만료·지연 관측. `/tmp/codex-parking-analytics-green.log` |
| 격리 PostgreSQL16 + Compose |118건 통과. `/tmp/codex-parking-analytics-pg.3c3ogm/focused.log` |
| PostgreSQL migration/check | 기존 head upgrade와 `alembic check` 통과. 같은 격리 project의 `migrate.log`, `alembic-check.log` |
| WSL 전체 백엔드 | 진행 중. `/tmp/codex-parking-analytics-local-full.log` |
| CI·독립 리뷰·운영 시각 대조 | 미완료. 원본 주차 수집·운영 job 실행·스케줄 변경·배포를 하지 않았다. |

격리 PG 테스트는 실제 `CollectionService`의 저장 flush 뒤 commit을 대기시켰다. 이때
cache 잠금 시도는0건을 반환하고 이전 정상 캐시를 덮지 않았다. 원본 commit 직후에도
수집 전용 잠금이 유지됨을 다른 connection의 잠금 시도로 확인했다. 수집이 반환한 뒤
API는 이전 캐시를 거부했다. 두 재집계의 경합, rollback 뒤 재획득도 확인했다.

첫 Docker 시도의 실패1건은 source mount가 compose 계약 파일을 가린 검증 환경 문제였다.
현재 전체 source를 읽기 전용으로 `/repo`에 마운트한 뒤 같은118건을 다시 통과했다.
임시 PG는 외부 port·새 bridge network 없이 `network_mode: none`으로 실행하고 테스트
backend만 같은 network namespace를 사용한다. 다른 프로젝트의 프로세스·DB를 조작하지 않는다.

## 남은 수용

운영의 최신 원본/run/cache/API 시각 대조와 실제5분 job 이후 동일 관측 반영은 별도 검증이다.
캐시를 검증하는 SQL 비용과 재집계 비용은 격리 PG 표본으로 측정하며 운영 지연 목표 달성으로
오인하지 않는다. 이 변경의 소스 머지 뒤에도 공항 주차 예측의 충분한 과거 표본·운영 일정의
실제 활성 상태·관리자 전체 뷰의 모바일 수용은 각각 남는다.
