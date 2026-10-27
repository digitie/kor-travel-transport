# 주차 원본 48시간과 영구 통계

## 확정 정책과 현재 구현 범위

사용자 요청으로 주차 원본은 최근 48시간, 집계 통계는 영구 보존한다. 이 문서의 목표 정책을 이미 운영에 적용한 것으로 읽지 않는다. 첫 단계는 영구 통계 저장·검산·수동 backfill만 추가한다. 원본·원천 응답 삭제, 기존 조회 결과 변경, 자동 schedule, 운영 backfill은 모두 수행하지 않는다. `prune_parking_raw`는 항상 예외로 차단된다. TTL 캐시를 영구 보관하는 방식으로 대체하지 않는다.

| 단계 | 구현·수용 기준 | 현재 상태 |
|---|---|---|
| 1 | 추가 전용 통계 모델·migration·멱등 backfill·삭제 및 legacy 덮어쓰기 차단 | c7 전체/CI 통과, 독립 리뷰 정산 중 |
| 2A | 전국 동시각 충분통계·coverage/seal/보류·작은 최신 상태와 backfill P2 해소 | 후속 구현·집중 검증 중 |
| 2B | 모든 분석/전망/현재/내부 export 읽기 전환, API 해상도·coverage·48시간 history 계약 | 미구현 |
| 3 | 기존 원본 backfill·공항/주차장별 수량·hash·값·이벤트 대조 후 48시간 정리와 운영 상태 표시 | 미구현 |

2A의 구체 모델은 [전국 통계·보류·현재 요약](parking-archive-coverage.md), 실제 파일·함수·소비 경로와
18개 반례 수용 항목은 [읽기 전환 조사](../reports/2026-10-28-parking-reader-transition-review.md)에 둔다.
1단계 통과는 원본48시간 활성화 완료가 아니다.

## 실제 의존 경로 조사

| 소비 경로 | 현재 원본 의존과 전환 시 지켜야 할 계약 |
|---|---|
| `analytics_cache.py`, `main.py` 분석 loader | 7/14/21일 기본값과 비기본 기간, 10~60분 임의 간격, 최대 90일 명시 날짜 범위 |
| 시간·요일·요일×시간 | 주차장 표본별 평균·최소·최대·관측 수. 버킷 평균을 단순 평균하면 표본 수가 달라 오답이다. |
| 공휴일·주말 | 같은 원관측 timestamp의 주차장 잔여면 합산을 먼저 하고 시간별 평균·최소·최대 계산. 비동시 표본을 같은 시각으로 위장하면 안 된다. |
| 원관측 임계 이벤트 | 10/50 양방향 교차, 원관측 시각·직전 관측 시각·값. 조회 시작보다 앞의 predecessor와 공백 기준을 명시해야 한다. |
| 임계 시간 인사이트 | 10분 추이의 교차 시각·요일별 중앙값. 원관측 이벤트와 다른 지표다. |
| `parking_outlook.py` | 과거 같은 요일·시각 1시간 표본. 용량>0만 포함한 일별 평균을 먼저 만든 뒤 날짜별 동일 가중 평균, 가득 찬 날짜 비율·범위 |
| `/v1/parking/history`, `parking_history_cache.py` | 현재 최대 30일 원관측 이력과 커서. 48시간 밖을 통계로 위장해 같은 endpoint 정확도라고 반환하지 않는다. 후속 API에서 제한과 실제 cutoff를 명시한다. |
| `/v1/parking/current` | 원본별 최신 행에 의존한다. 48시간 넘게 새 자료가 없는 주차장도 마지막 관측 시각을 현재값처럼 갱신하거나 조용히 누락하면 안 된다. |
| Map용 `parking_current`/내부 export | typed pointer에는 원본 FK가 없지만 발행 membership·고정 세대·TTL·cursor는 별도 계약이다. 재발행·삭제 이전에 모든 연결을 확인한다. |
| 수집 상태·백업/복원·legacy import | 관측 수/최초·최신 시각이 원본 범위라는 사실을 명시하고 통계 coverage와 구분. 수집 실행/오류·Dagster run·기준정보·요금/공휴일은 주차 원본 정리 대상으로 묶지 않는다. |

원본 범위는 `parking_snapshots.raw_item_json`과 해당 개별 관측, `raw_api_responses`의 정확한 KAC/인천 주차 endpoint 응답 본문이다. `collection.py`의 요금 endpoint·`unknown` 오류·외부 교통 도메인과 source만 같은 응답을 함께 지우지 않는다. 후속 구현에서 endpoint allowlist·source·완료 run·snapshot coverage를 함께 검증한다. 첫 단계는 이 테이블들을 읽기만 한다.

## 영구 모델과 정확도

`parking_statistics_buckets`의 PK는 `(airport_id, bucket_at)`, 범위는 UTC `[bucket_at, bucket_end)` 10분이다. 일반 logged PostgreSQL 테이블이며 TimescaleDB가 있다고 가정하지 않는다. 공항 FK는 `RESTRICT`다. 통계가 든 migration downgrade는 차단한다. 통계 JSON에는 개별 관측 배열이나 provider 원문을 넣지 않는다.

- `lots[].available`: 같은 lot/time 중복을 live → 최근 `collected_at` → 큰 id로 정리한 표본의 `sum/count/min/max`.
- `lots[].positive_capacity`: 용량>0 표본만의 충분통계·용량 범위·마지막 유효 관측 시각. 전망의 0 용량 제외를 유지한다.
- `lots[].first/last`: 해당 10분 구간의 첫/마지막 관측 시각·수량. 마지막 점의 적재 시각·혼잡도는 최신 상태의 기준 시각을 새 시각으로 위조하지 않도록 함께 보존한다. 정각 경계와 추이 재표본화에 사용하며 관측 없는 구간을 보간하지 않는다.
- `airport_cohorts`: 같은 정확한 원관측 timestamp의 공항 잔여면 합산을 표본으로 한 `sum/count/min/max`. 주차장별 평균 통계와 교환할 수 없다.
- `events`: 원관측 기준 임계값 10/50의 양방향 교차. `previous_at`, `crossed_at`, 이전/현재 값·주차장 ID를 보존한다. 기존 이벤트 계산처럼 공백 뒤 교차도 기록하되 두 시각을 보존해 연속 관측이라고 오해하지 않게 한다.
- `raw_count`, `selected_count`, `max_snapshot_id`, `raw_sha256`, `statistics_sha256`: 원본 수량·집계에 쓰는 값·`raw_item_json`을 포함한 정규화 지문과 중복 제거 표본 수 및 결과 검산. 원본 JSON은 지문 계산에만 사용한다. 이 지문은 HTTP 응답 원문 바이트나 수집 run FK까지 검사하는 값이 아니므로 원천 응답 정리는 별도의 run/source/endpoint 검증이 필요하다.

10분 이전의 내부 변화, 동일 버킷 안의 중간 관측, 임의 offset의 정확한 이전 값은 복원할 수 없다. 후속 DTO는 원본/집계 구간, 최소 해상도, 부분 버킷·coverage, 원본 유지 경계를 명시한다. 임의 간격/offset의 집계 재표본화 결과를 원관측과 같다고 표시하지 않는다. 시간대/날짜 경계가 10분에 맞는 충분통계는 sum/count를 합치며, rolling cutoff가 버킷 안에 있으면 그 부분은 근사 또는 제외임을 계약으로 명시한다.

## 멱등성과 보류

### Dagster에서 실행 결과 확인

수동 job의 SUCCESS는 op 실행이 끝났다는 뜻이며 전체 집계 검산 완료를 뜻하지 않는다.
`status`·`coverage_status`, 선택/검산/신규 발행/보류/삭제 수량은 STEP_OUTPUT metadata와 INFO 로그에 남긴다.
busy와 `no_new_rows/not_audited`도 강제 실패로 바꾸지 않고 미실행·미검산임을 명시한다.

- `checked_at`, `raw_cutoff_at`, `complete_before`: 이번 평가 시각·48시간 원본 유지 경계·완결 bucket 경계다.
- `selection_start_at`~`selection_end_exclusive`: 실제 raw SELECT의 최대 하루 창이다.
  `selected_observed_min_at`·`selected_observed_max_at`, `selected_snapshots`·`selected_buckets`는 그 창에서 읽은 실제 원본 범위/수량이다.
- `verified_buckets`와 `verified_min_bucket_at`·`verified_max_bucket_at`: 기존 또는 신규 통계를 실제 검산한 bucket 수와 양끝값이다.
  `archived_buckets`와 `archived_min_bucket_at`·`archived_max_bucket_at`는 이번에 새로 발행한 부분만 뜻한다.
- `verification_scope=selected_bucket_subset`는 선택 창 안의 일부 검산이다. 양끝값이 같거나 넓다는 이유로
  그 사이 모든 시각/공항을 검산했다고 해석하지 않는다. 전체 coverage는 계속 partial 또는 not_audited다.
- busy/무신규에서는 검산 범위가 none, 선택 범위는 null, 선택/검산/발행 수량은0이다.

metadata는 이 scalar 필드만 허용하며 원문이나 provider 비밀값을 로그에 추가하지 않는다.
기존 query·집계값·API reader·자동 schedule·원본 삭제는 이 관측 보완으로 바꾸지 않는다.
가장 오래된 보류의 후속 날짜 정체와 비10분 offset UTC floor P2는 별도2A에서 해소할 활성화 전 필수 항목이다.

`parking_statistics_archive_job`은 provider 호출 없는 수동 Dagster job이다. 자동 schedule은 아직 없다. 공항 수집과 같은 PostgreSQL transaction advisory lock을 즉시 시도하고 경합 시 `busy`/변경0을 반환한다. 48시간보다 오래된 **완결 버킷**만 후보로 잡고, 한 실행은 최대 하루 범위·기본 144개 공항 버킷으로 제한한다. `observed_at`이 오래돼도 최근 48시간에 `collected_at`이 들어온 표본이 있으면 그 버킷은 보류한다. 현재 상태/최신값을 억지로 변경하지 않는다.

신규 행 탐색은 append-only 수집의 `max_snapshot_id`와 UTC `date_bin`의 PK 등가 조회를 사용한다. **이 탐색은 전체 과거 검산이 아니다.** 새 id가 없으면 `no_new_rows`/`coverage_status=not_audited`를 반환하고 전체 coverage 완료나 삭제 가능 상태로 표시하지 않는다. 같은 id의 값·JSON 수정이나 원본 누락은 이 탐색으로 발견하지 못한다. 실제 선택된 하루 범위에서 만난 기존 버킷만 원본 지문·행 수·통계를 다시 계산해, 다르면 `ParkingArchiveConflict`로 전체 transaction을 rollback한다. 신규 버킷 발행은 `batch_complete`/`coverage_status=partial`이며 전체 수용이 아니다. 삭제 전에는 후보 버킷마다 `verify_bucket`로 원본 전체·직전 상태를 다시 검산해야 한다.

같은 과거 관측을 원본 삭제 후 재수신하면 unique 원본 행이 다시 생길 수 있다. 남은 행으로 기존 통계를 재생성하거나 append하면 손실·이중 가산이므로 자동 교체를 거부한다. 첫 단계의 검증에는 재수신·같은 id 변조·원본 삭제를 전용 테스트 DB에서 모사하며, `no_new_rows`가 검산 완료를 뜻하지 않는지도 확인한다. 후속 정리는 immutable sealed bucket과 운영 보류 상태를 존중해야 한다.

캐시/원본을 지운 뒤 통계가 유일한 과거 정본이 되므로 검사 실패를 경고만 남기고 삭제하는 fallback은 금지한다. 취소·실패 시 backfill과 나중의 정리는 caller transaction rollback으로 중단하고 기존 발행은 유지한다. 최초 backfill은 sourcecount/hash와 재계산 통계를 검산하지만 원본을 정리하지 않는다. 저장 공간을 확보하려는 목적으로 검산을 생략하지 않는다.

## 영구 참조·백업 경계의 좁은 조사

운영 앱에서 `ParkingLot`을 하드 삭제하는 서비스 경로는 찾지 못했다. 수집은 기준정보를 갱신하고, sample seed의 정리는 미래 sample snapshot만 지운다. 그러나 `migrate_sqlite_to_postgres.py`는 PK 기준으로 공항/주차장 identity를 덮을 수 있고, HTTP 이관은 원본 upsert와 `migration_` 중복 삭제를 수행한다. 통계 테이블을 직접 지우지 않더라도 통계의 참조 의미와 원본 지문을 깨뜨릴 수 있다.

두 이관 entry는 영구 통계가 하나라도 있으면 쓰기를 거절한다. 원천 collector·통계와 같은 transaction advisory lock 아래 검사하고 upsert/delete를 수행하며, SQLite 이관의 sequence 조정까지 중간 commit 없이 보호한다. HTTP 이관은 외부 조회 전에 먼저 거절하고 네트워크 동안 lock을 반환한다. 읽는 사이 통계가 생긴 경우도 첫 쓰기 전에 다시 거절한다. 통계가 빈 DB의 정상 이관·sequence 조정은 지원한다. 우회/force 설정은 두지 않는다. 직접 SQL 수정·lot ID 재사용은 안전하다고 가정하지 않으며 후속 읽기 전환의 영구 참조 수용은 계속 필요하다.

`backup_restore.py`는 테이블 allowlist 없이 전체 DB의 `pg_dump -Fc`와 `pg_restore`를 사용하므로 새 통계를 백업에서 누락하는 명시 목록은 없다. 전용 합성 DB에서 실제 서비스와 같은 `--clean --if-exists --no-owner --no-acl --single-transaction --exit-on-error`로 경계를 확인했다. 통계 테이블이 없는 schema35 dump는 새 FK가 공항 PK 제거를 거절해 exit1/통계1개 보존이었다. 같은 schema36의 옛 dump는 정상 exit0이지만 이후 쌓인 통계가 2개→1개로 줄었다. 모든 과거 dump가 같은 방식으로 안전하게 거절되는 것은 아니다.

실제 API는 pre-restore backup을 먼저 만들지만 통계 세대 단조성 검사는 없다. 이 검증은 `pg_restore` 경계이며 API pre-backup 전체 수용이 아니다. 원본 삭제 뒤 유실 통계는 재생성할 수 없으므로 통계 보존을 확인하는 복원 guard는 후속 읽기/삭제 활성화 전 수용 항목이다. 이 단계에서 기존 복원 동작을 몰래 바꾸지 않는다.

Map 주차 current는 `ParkingCurrent`와 `ReferenceExportState`의 source/scope/generation/member IDs를 읽고, export는 DTO를 `ServiceExportSnapshotItem`에 고정한다. 원본 snapshot FK나 본문을 읽지 않는 경로임을 소스로 확인했다. 기존 snapshot TTL은 15분이며, 실제 원본 삭제 전후 current·membership·고정 세대·커서의 독립 회귀는 여전히 필요하다.

## 후속 수용 목록

1. 기존 7/14/21일 화면·특수일·전망·비기본 날짜 범위를 영구 통계+최근 원본으로 전환한다. 두 구간 중복/경계 누락·평균의 평균 오류·0 용량·빈 구간·동일시각 source 우선순위를 회귀로 확인한다.
2. 현재값과 Map current/export의 고정 세대·커서/TTL·membership를 원본 삭제 전후 실제 DB로 검증한다. 다른 도메인 export나 collection metadata를 삭제해 통과시키지 않는다.
3. 원본 history를 48시간으로 제한하고 응답 cutoff와 통계 해상도·coverage를 공개 DTO/OpenAPI/SDK/UI에 반영한다. 기본 days·최대값과 함께 과거 cutoff를 담은 기존 cursor의 만료/부분 범위도 명시한다. 오래된 cursor를 빈 정상 결과로 위장하지 않는다. 실제 admin/public/SDK 원본 history 소비의 기본 기간을 전환하고 7일 그래프는 영구 통계로 읽는다. 기존 UI 틀은 유지한다.
4. 공항/주차장별 통계·이벤트 coverage/count/hash 대조, 늦은 수신·중복·취소/재시작·충돌을 검증하고 보류 사유·48시간 초과 원본을 운영 API/Dagster에서 확인하게 한다.
5. 정확한 주차 endpoint만 본문 정리하고 요금·기준정보·수집/Dagster 메타데이터·다른 교통 원본을 보존한다. 집계가 없는 기간은 삭제하지 않는다.
6. WSL/Docker·두 적대 리뷰·실제 UI/외부 API 수용, 운영 자연 실행 후에만 48시간 정리 정책 전체 완료를 선언한다.
