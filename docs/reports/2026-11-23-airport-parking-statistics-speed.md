# 공항 주차장 통계 화면·API 속도 개선 — 2026-11-23

소유자 보고: 공항주차장 통계(관리 `/parking?view=analytics`, 공개 parking-radar 분석 탭) 화면과 API가 느리다.
두 화면 모두 `GET /v1/dashboard/analytics` 한 묶음(+ 과거조회 탭의 `parking/analytics/timeseries`)을 부른다.
UI의 N+1 호출은 없다(묶음 1회 + 60초 주기 재조회).

## 운영 측정(읽기 전용, odroid)

공개 URL `https://pr.digitie.mywire.org/api/backend/v1/...`을 인증 없이 curl로 쟀다(odroid load 22~28, 4코어 —
같은 호스트의 다른 빌드·weather 작업이 겹친 상태).

| 요청 | 시간 |
| --- | ---: |
| `dashboard/analytics?airport_code=ICN` | 504(10초 프록시 상한) / 6.4초 / 19.6초(로그 최대) |
| `dashboard/analytics?airport_code=GMP` | 2.0~5.0초 |
| `parking/analytics/holiday-patterns?airport_code=ICN` | 5.8초, 로그 12.0초 |
| `parking/analytics/by-weekday-hour?airport_code=ICN`(캐시 miss) | 3.7초, 로그 45.6초 |
| `threshold-events`/`threshold-insights`(캐시 hit) | 0.2~0.4초 |
| `dashboard/bootstrap` | 0.45초 |

백엔드 slow_request 로그(24시간) `/dashboard/analytics` p50 6.3초·최대 19.6초.

## 원인

1. **특수일(공휴일·주말) 패턴은 캐시가 없다.** 묶음이 캐시 hit여도 매번 최근 8개 특수일의 원본 관측(ICN 약 2.7만 행)을
   중복 제거해 Python으로 옮겨 계산했다. 묶음 hit 시간의 대부분이 이 부분이다.
2. **DB 분석 캐시가 절반 이상 무효다.** 캐시는 "생성 10분 이내 + 생성 뒤 같은 범위 새 적재 없음"일 때만 쓴다. Dagster 공항 수집은
   약 10분 주기(5분 cron, 실행이 4~9분이라 합쳐짐), 수집 commit 뒤 캐시 재생성이 약 5분 걸린다(2026-11-23 09:30:03 생성
   → 09:34:58 step 종료). 그 동안 모든 범위가 miss이고, miss마다 네 분석이 각자 21·14·14·7일 원본을 따로 읽었다(ICN 4회, 약 22만 행).
3. **원본 행 변환 비용.** compact loader가 행마다 `SimpleNamespace(**row._mapping)`을 만들었다. 프로파일에서 분석 계산보다
   `Row._mapping`/`keys()`가 더 비쌌다. `build_time_series`는 lot×bucket 반복마다 `ensure_tz`를 불렀다.
4. (기여) `parking_snapshots`는 통계 reset 뒤 VACUUM이 없었다(`relallvisible` 5,985/9,021). 최근 며칠 페이지가 all-visible이
   아니라 ICN 14일 index-only scan이 47,291행 중 42,972행을 heap에서 다시 읽었다. 통계(ANALYZE)는 최신이고 캐스트·인덱스 누락은
   없었다(`ix_parking_snapshots_history_cover` 사용). 이번 PR은 스키마를 바꾸지 않는다 — 아래 후속 참고.
5. (기여) API 프로세스 안의 30일 주차 이력 캐시 재빌드(`/parking/history`용)가 수집마다 84~122초 CPU를 쓴다. 같은 프로세스라
   이 동안 모든 요청이 느려진다. 별도 기능이라 이번 범위에서 바꾸지 않았다.

pg_stat_statements(11-17 이후): compact 원본 SELECT 14,089회 평균 451ms·최대 14초, 캐시 행 전체 SELECT 1,007회 평균 1.1초.

## 수정(결과 동일)

- 특수일 패턴: PostgreSQL에서 같은 소스 우선순위 중복 제거 → 같은 관측 시각 합계 → 현지 날짜·시별 개수/합/최소/최대만 받는다
  (`aggregate_special_day_hours`, 날짜×24행 이하). Python 경로와 같은 조립 함수(`build_special_day_patterns_from_aggregates`)를
  쓴다. 평균은 `statistics.mean`과 값·타입(정수 평균이면 int)이 같은 정수 나눗셈이다. SQLite는 기존 Python 경로.
- 대시보드 묶음 miss: 가장 긴 기간(21일+10분)을 **한 번** 읽고 각 route와 같은 `observed_at >= cutoff`로 잘라 단독 route와 같은
  계산 함수로 만든다. 결과는 프로세스 안 memo에 두고, DB 캐시와 같은 재사용 조건(생성 10분 이내, 생성 뒤 같은 범위 새 적재 없음)을
  매 요청 확인한다. 같은 범위의 동시 miss는 하나로 합친다(128개 LRU). 수집기는 `collected_at`을 삽입 때 찍고 실행 끝에
  commit하므로, 그 사이 계산한 memo는 `collected_at` 검사로는 무효화되지 않는다 → 계산 전 보이던 `parking_snapshots` 최대 id도
  같아야 재사용한다(적대 리뷰 지적, 늦은 commit 시험으로 고정). memo 재사용 결과는 DB 캐시 hit와 같은 계약이다: 기간 경계·
  `generated_at`이 생성 시각 기준이라 최대 10분 동안 그 시각의 결과를 돌려준다(DB 캐시 hit와 같고, 매번 새로 계산하던 miss 경로보다는
  최대 10분 오래된 경계).
- compact 행은 위치 기반 `NamedTuple`(`CompactSnapshot`), `build_time_series`는 같은 알고리즘의 루프 정리(bisect·미리 계산한 UTC 시각),
  요일×시 평균은 정수 평균.

## 측정(n150, 동일 합성 표본 A/B)

prod 모양 합성 표본(14공항·44주차장, 40일, 28.2만 행, migration 중복 포함), PostgreSQL 18(2 CPU), 앱 1 CPU, 같은 프로세스의
이력 캐시 재빌드 동작 중, 시계 고정. 기준 = main(d4bb920), 후보 = 이 PR. **응답 31종(generated_at 제외)이 byte 단위로 같다.**

| 요청(중앙값) | main | 이 PR |
| --- | ---: | ---: |
| dashboard ICN, DB 캐시 hit | 0.643초 | 0.132초 |
| dashboard GMP, DB 캐시 hit | 0.127초 | 0.105초 |
| holiday-patterns ICN | 0.632초 | 0.169초 |
| dashboard ICN, DB 캐시 miss(첫 계산) | 4.774초 | 1.644초 |
| dashboard GMP, DB 캐시 miss(첫 계산) | 1.143초 | 0.343초 |
| 같은 범위 miss 재요청(memo) | (매번 첫 계산과 같음) | DB 캐시 hit와 같은 수준 |
| refresh_default_analytics_cache 전체 | 5.5초 | 5.0초 |

운영 ARM은 n150보다 몇 배 느리고 부하가 크다. hit·memo 경로는 원본을 읽지 않아 1초 안쪽이 목표이고, 수집 직후 범위별 첫 요청만
원본 계산을 한다. 배포 뒤 운영 재측정이 필요하다.

## 시험

- `test_parking_analytics_equivalence.py`: main의 계산 함수를 그대로 옮긴 참조 구현과 요일×시·시계열(미래 bucket·anchor·naive 시각)·
  특수일 패턴을 무작위 표본 139경우에서 JSON(정수/실수 구분 포함)으로 비교. 비교 조건을 일부러 바꾼 변이 3개는 모두 실패로 잡혔다.
- `test_parking_analytics_compact.py`: 차가운 묶음이 원본을 한 번만 읽고 단독 route와 같은 값, memo가 같은 범위 새 적재·10분 경과로
  무효화되고 다른 범위 적재로는 무효화되지 않음, 다른 공항 소속 주차장 범위, PostgreSQL 특수일 집계 SQL 모양.

## 후속(이번 PR 밖)

- `parking_snapshots`에 `autovacuum_vacuum_insert_scale_factor`(예: 0.02) — 최근 페이지를 all-visible로 유지해 heap 재조회를 없앤다.
  migration이 필요해 별도 PR로 둔다. 그 전에 운영에서 한 번 `VACUUM (ANALYZE) parking_snapshots`는 비차단이라 안전하다.
- API 프로세스 안 30일 이력 캐시 재빌드(84~122초)를 프로세스 밖이나 증분으로.
- 캐시 refresh의 Python 비용(공항 14개×범위 58개, 5분) — 범위별 commit은 refresh의 잠금·transaction 계약을 바꾸므로 별도 설계.
