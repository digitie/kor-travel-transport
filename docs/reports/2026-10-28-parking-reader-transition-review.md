# 주차 보존 2단계: 읽기 전환 및 반례 검토

- 기준: `c7c6852d1ca55cef18923910cedbdc906f93ccde`, PR156의 1단계 동결 소스.
- 이 문서는 c7 동결 소스 조사에서 정리한 후속 reader/API 수용 설계다. c7 원본과 전체 실행 입력은 보존했다.
- 1단계는 영구 통계와 삭제 차단을 마련한 선행 단계다. **원본 48시간 정책은 아직 완료되지 않았다.**
- 본 문서는 다음 구현의 범위와 수용 조건이다. 미구현 항목을 현재 보장으로 읽으면 안 된다.
- 후속2A의 실제 저장 모델·현재 범위는 [coverage 설계](../architecture/parking-archive-coverage.md)에 둔다.

## 1. 실제 조회와 변경할 파일·함수

| 파일·함수 | 기존 조회 범위·표본 | 필요한 전환 |
| --- | --- | --- |
| `backend/app/main.py:parking_by_hour`, `parking_by_weekday`, `parking_by_weekday_hour`, `_load_snapshots` | 기본14일, 1~60일. 주차장·공항·전국. 원본의 lot/observed 중복 제거 후 각 관측의 잔여면 평균 | `analytics.py`의 요약 병합 함수로 count/sum/min/max를 합산. 공항끼리 평균을 다시 평균 내지 않음. 통계 경계와 최근 원본을 배타적으로 선택 |
| `main.py:parking_time_series`, `_load_timeseries_snapshots`, `_aggregate_timeseries_between_local_dates`, `_load_timeseries_snapshots_between_local_dates` | 상대7일(1~30), 명시 날짜범위최대90일. interval10~60의 모든 정수 허용. 미래0~12시간. 명시 범위는 공항/주차장 필수. 상대는 전국도 가능 | 10분 경계의 상태 복원과 임의 간격의 해상도 손실을 구분. PostgreSQL 날짜범위 SQL에도 archive를 반영. 원본이 없어 `has_snapshot=None`이라는 이유로 archive 결과를 빈 배열로 반환하면 안 됨 |
| `main.py:holiday_patterns`, `_load_snapshots_on_local_dates`; `analytics.py:build_special_day_patterns` | 최근 특수일 기본8/최대16개, lookback=max(90,limit*14) → 최대224일. KST 날짜/시간, **동일 observed_at에서 여러 lot의 잔여면 합계**를 하나의 표본으로 삼음 | lot scope는 lot sufficient stats, airport scope는 airport_cohorts, 전국 scope는 별도 global cohort sufficient stats. 날짜 단위의 무의미한 lot 평균 대체 금지 |
| `main.py:threshold_events`, `_load_snapshot_rows`; `analytics.py:detect_threshold_events` | 기본14일(1~60), limit20(1~100). lot별 원관측 전후10/50 상하향 교차 | archive의 원관측 event와 최근 raw event를 합치되 이전 상태·교차 시각으로 중복 제거. 각 lot의 시작 이전 마지막 상태를 읽어 경계 교차를 연결. 기존 구현은 창 시작 이전 상태를 읽지 않으므로 이 변경의 경계 의미를 문서화 |
| `main.py:threshold_insights`; `analytics.py:build_threshold_insights`, `detect_threshold_events_from_time_series` | 기본21일(3~90), interval10~60. **합산 시계열**에서 날짜별 첫10/50 하향 교차→요일별 시각 중앙값, 최근30개 날짜 이력 | 위 원관측 lot event와 다른 분석이다. archive event를 그대로 대체 투입하지 않음. 범위별 시계열 복원 후 계산하고, 관측 없는 구간의 숫자0을 실제 만차로 취급하지 않음 |
| `backend/app/services/parking_outlook.py:parking_outlook` | 기본28일(7~60). 오늘은 제외, 입차 예정 시각과 같은 요일/시간 1시간 창. capacity>0인 중복 제거 관측만 | 각 날짜에 positive_capacity sum/count→날짜 평균을 만든 뒤 **날짜 평균을 같은 가중치로** 평균. full_days는 해당 날짜 min=0 여부, sample_days는 관측 있는 날짜 수. lot 활성 조건과 min/max capacity, latest 시간 보존 |
| `backend/app/services/analytics_cache.py:refresh_default_analytics_cache`, `refresh_scope_analytics_cache`, `_refresh_scope_from_snapshots`, `load_cached_analytics`, `_load_latest_observed_at` | 재계산 캐시4종:7일 시계열,14일 요일시간,14일 원관측 event,21일 insights. TTL10분. 현재 원본만 읽음 | archive+raw를 같은 reader로 읽도록 전환. backfill/집계 버전·coverage 변화도 캐시 무효화 근거에 포함. 캐시 TTL을 영구 보존 근거로 쓰지 않음 |
| `main.py:dashboard_analytics` | 위5개 분석을 묶어 반환 | 개별 API와 동일 reader/해상도/coverage 사용. aggregate bundle만 동작하고 개별 API가48h만 반환하는 분리 금지 |
| `main.py:parking_history` | 현재 default3/max30일, offset 없는 signed cursor. 서명에 cutoff/관측시간/lot/필터/days/max_id 고정 | default2/max2일의 **원관측 이력**. 현재 보존 cutoff보다 옛 커서는 명시적 만료(410 권장), 새 첫 페이지의 실제 raw cutoff 명시. 과거 archive를 HistoryPoint로 위장해 채우지 않음 |
| `backend/app/services/parking_history_cache.py:load_snapshot`, `refresh_once`, `ParkingHistorySnapshot.render`, `response_body`, `usable_snapshot` | 현재30일 원본을 메모리·압축 바이트로 유지 | DB만 지워도 프로세스 캐시에48h 밖 raw가 남을 수 있음. 캐시 적재/렌더 모두 실제48h cutoff 적용, cutoff 변화로 prepared bytes key/만료 처리. 응답 schema를 우회하는 직접 JSON에도 metadata 적용 |
| `main.py:parking_current`, `dashboard_bootstrap`, `_load_latest_snapshot_metadata`, `_load_collection_run_statuses` | current는 각lot 최대 observed_at/id. collector 최신/최초 시각과 실행별 row count를 원본에서 계산 | 최근 raw가 없는 lot의 마지막 **파생 현재 상태**는 남겨 정확한 기존 시각과 stale 의미 유지. raw 범위와 통계 조회 가능 범위를 별도로 노출. 삭제로 run row count가 줄어든 것을 과거 수집 실패로 표시하지 않음 |
| `backend/app/services/parking_exports.py:store_parking_current`; `export_references.py:_parking_payload_batches` 및 snapshot endpoint | Map용 별도 typed ParkingCurrent+성공 membership, immutable DTO snapshot15분과 cursor | raw FK가 없어 prune 직접 참조 단절은 없지만, 원본 삭제 후에도 source/scope/generation/member_ids·고정 페이지 digest·15분 TTL/cursor 그대로 검산. raw를 근거로 reference metadata/집합을 삭제하는 우회 금지 |
| `backend/app/services/parking_statistics_archive.py:_previous_by_lot`, backfill/verify/prune | 현재 직전 상태도 raw에서만 읽고 prune는 항상 거절 | 직전 archive last와 raw를 결합. sealed bucket 재삽입/변조 감지와 삭제 직전 지문·count·통계·event 검산. 1단계 max_id 발견 query를 전체 검산이라고 부르지 않음 |
| `backend/app/services/collection.py` 원본 저장, `main.py` 백업 복원, `backend/app/services/backup_restore.py` | snapshot과 parking source body 별도, collection_run 공유. pg_dump 전체/pg_restore 전체 | late replay·coverage 상태와 restore 안전 경계 필요. fee/rail/bus/fuel/weather 및 collection metadata는 삭제 범위에서 제외. 동일schema 오래된 dump가 영구 통계를 되돌리는 실제 손실 경로를 prune 전에 막음 |

## 2. archive만 남았을 때 실제로 가능한 것과 불가능한 것

### 정확한 충분통계

1. lot 관측을 표본으로 하는 시간/요일/요일시간 평균·min·max·관측수는 **완전한10분 bins**에 대해 count/sum/min/max 병합으로 정확하다. KST 정시·날짜 경계는 UTC10분 경계와 일치한다.
2. airport 공휴일/주말 통계는 기존 `airport_cohorts` count/sum/min/max로 정확하다. `lots.available`의 count를 더하면 동일시각 공항합계 표본수가 아니므로 틀린다.
3. outlook은 정시 한시간 bins의 positive_capacity 충분통계로 기존 값을 재현할 수 있다. 원본 총capacity0 관측은 일반통계에는 포함되지만 outlook에는 제외된다.
4. 저장한10/50 event는 원본 관측 전후의 교차 기록이다. 그 시각이 실제 임계값을 통과한 물리적 순간을 의미하지는 않는다. 긴 관측 공백에 대해서도 이전/새 관측의 변화라는 기존 의미를 숨기지 않는다.

### 현재 통계만으로 정확히 복원할 수 없는 것

- **전국 동일시각 상관:** 공항A의 (0,100), B의 (100,0) 표본이 같은 두 시각이면 전국합은 (100,100)이다. 각 공항 min합0/max합200은 전국 min/max100과 다르다. 시각이 서로 다르면 전국 관측수도 달라진다. 단계2에서 raw를 삭제하기 전에 global10분 cohort count/sum/min/max와 source/airport coverage digest를 작게 추가 보존한다. PK bucket_at, 하루최대144행, 연52,560행 수준이다. 이 저장소의 실제 nationwide holiday API 호환을 위한 것이며 신규 UI를 늘리지 않는다.
- **임의 interval/offset:** bin00:10~00:20의 값이 00:10=60, 00:14=20, 00:19=90이면 first/last만 남아 00:15의 기존 LOCF=20을 알 수 없다. 00:19의 미래값90을 골라서는 안 된다. 현재 계약은15·17·29분도 허용한다. interval을 몰래10분 배수로 제한하거나 같은 정확도를 주장하지 말고,10분 통계 해상도·요청 간격·재구성 여부를 DTO/문서에 표시한다. 안전한 보수적 이전 point 선택도 원본과 같다고 부르지 않는다.
- **상대 days의 첫10분 bin 절단:** now=14:07의14일 cutoff는14:07이다. 해당 과거 bin14:00~14:10의2표본 중14:02는밖/14:08은안인데 sum/count만으로 내부만 추출할 수 없다. 전체bin을 포함하면 요청 밖 표본이 섞이고, 전체bin을 제외하면 첫3분이 빠진다. 유효 조회 시작을ceil10분으로 노출하는 명시적 부분범위와 최근 raw 정밀 구간을 구분해야 한다.
- **현재 상태 tie:** public current는 observed_at desc/id desc이고 archive 중복 정리는 live→migration/collected/id다. 같은시각 live id1/마이그레이션 id2라면 현재 응답과 archive last가 다를 수 있다. 기존 ParkingCurrent는 provider SDK의 초단위 값·membership용으로 raw parser의 분단위 public current와도 다를 수 있다. 따라서 기존 current를 Map current로 단순 대체할 수 없다. 삭제 전 현재 상태의 선택규칙을 검산해 필요한 작은 latest 파생상태를 보존하거나, 규칙 통합을 명시적 호환 변경으로 검토한다. raw 행을 영구 보존하는 우회는 하지 않는다.

## 3. 읽기 소유권·경계·공백 계약

- sealed archive bin과 raw bin은 각 조회에서 **하나만** 합산한다. archive가 존재한다는 이유로 같은 bin의 raw를 두 번 더하지 않고, 일부 raw가 prune된 bin을 남은raw만으로 재생성하지 않는다.
- observed_at48h cutoff와 collected_at48h 보류는 별개다. 오래된 관측을 방금 수신한 경우 집계 검증/late정책을 마칠 때까지 raw가 남을 수 있다. raw 보류량·최고경과시간·충돌 사유를 보이게 해야48h 정책 실패가 조용히 영구화되지 않는다.
- sealed bin 원본을 지운 뒤 같은 observed/source가 다시 들어오면 unique constraint가 막지 못한다. 기존 통계의 append·덮어쓰기를 모두 금지하고 검증 불가 late/correction으로 상태를 드러낸다. 원문 전체 복사 없이 임의 과거교정을 무손실 지원할 수 있다고 주장하지 않는다.
- archive가 없고 raw도 없다는 것만으로 **정상 관측0건** 또는 완료된 공백이라고 증명할 수 없다. backfill 미완료, 미수집, prune완료, 충돌을 coverage/watermark로 구분한다. 최소한 unknown/partial/complete와 실제 가용기간을 전달한다. 비어 있는 성공 배열만 내어 수집 장애를 숨기지 않는다.
- `TimeSeriesPoint`의 기존 숫자0은 lot_observations0이면 관측 공백이다. 실제 잔여0은 lot_observations>0이다. chart는 이미 이 필드로 선을 끊으므로 같은 구조를 유지한다. threshold-insights도 동일 기준으로 공백을 거르고 장기 공백을 연결해 가짜 하향/상향 교차를 만들지 않도록 보완한다.
- 기본10분/정시 재표본화는 각 경계 전 bin last와 경계에 정확히 존재하는 다음bin first를 골라 원본의 양끝 포함/최대interval 신선도 규칙을 보존한다. 범위 끝 이후 point는 사용하지 않으며 명시 날짜범위의 trailing gap을 마지막관측으로 덮지 않는다.
- list 응답(by-hour/by-weekday/by-weekday-hour/threshold-events)은 기존 배열 형태를 유지할 필요가 있다. envelope를 일괄 바꾸기 전에 HTTP 응답 header의 통계 해상도/유효기간·coverage와 OpenAPI 문서, 기존 dashboard object의 additive metadata 조합을 검토한다. 객체형 timeseries/outlook/holiday/history/insights에는 동일한 additive metadata가 가능하다. metadata를 응답 item마다 반복해 UI 공간을 늘리는 방식은 피한다.
- 캐시 결과와 cold fallback, dashboard bundle과 직접 API 모두 같은 정확도/범위 정보를 전달한다. raw JSON을 보내는 경로와 aggregate DTO를 이름만 같게 혼용하지 않는다.

## 4. 필수 소비 경로와 UI 영향

| 경로 | 실제 확인 | 필수 수정 |
| --- | --- | --- |
| `frontend/src/lib/api.ts:buildApiClient` | current, analytics bundle/개별 통계, timeseries 기본7일·10분, insights21일. **raw history를 읽는 메서드는 현재 없음** |7일 그래프는 영구통계 reader 유지. 객체 metadata 타입 반영, 오류/부분자료 구분. SDK라는 이유로 없는 raw 메서드를 새로 만들지 않음 |
| `frontend/src/components/pages/history-view.tsx` | collectorStatus.earliest_snapshot_observed_at으로 달력 최소날짜 결정, api.getTimeSeries로 실제조회 | raw earliest와 archive 통계 earliest 분리. raw삭제 후 과거 날짜를 선택 불가로 만드는 회귀 방지. 최대90일 구간은 유지 |
| `frontend/src/components/history-chart.tsx`, `daily-flight-overlay-chart.tsx` | lot_observations>0 필터, 공백 분리, 날별 overlay | 관측없는 숫자0을 점으로 표시하지 않음. archive 저해상도를 실제 원관측으로 표시하지 않음. 비행편은 별도 하루 overlay 유지 |
| `frontend/src/lib/types.ts`, `dashboard-context.tsx`, `hooks/use-analytics-data.ts` | collector 최신 observed/collected 변화로 갱신 판단 | raw prune 때문에 그래프의 가용기간이나 fresh상태를 잃지 않도록 분리 metadata/generation 반영 |
| `packages/kor-travel-transport-admin/frontend/components/airport-parking.tsx` | `@kor-travel/parking-ui`는 `file:../../../frontend/src` 의존성. current/분석/과거조회/요금 화면 재사용 | 공용 parking-ui 수정으로 admin/public 동시 반영. 별도 UI 복제 금지. 안내는 기존 InfoButton 활용 |
| `packages/.../components/flight-journey.tsx` | `parking/outlook`28일 소비 | 빈 배열을 예측0/가능으로 보지 않음. positive sample수·날짜범위·저장통계 metadata 반영 |
| `frontend/src/app/api/backend/[...path]/route.ts` | raw history 대용량 proxy 특수 경로 | 계약이48h가 되어도 응답/오류/압축/취소 처리가 일치하는지 검증. proxy가 old response를 영구 유지하지 않음 |
| `frontend/e2e/live-dashboard.spec.ts`, `frontend/tests/backend-proxy-route.test.ts` | raw history를 days=30으로 직접 검증하는 소비/시험 | 해당 요청은2일로 전환하고 과거7일/90일은 analytics로 검증. 오래된 cursor의410/실제 cutoff 검증 추가 |
| Python SDK | Transport repo와 로컬 Common 코드에서 별도 parking raw-history SDK 메서드를 찾지 못함 | 발견되지 않은 SDK 수정으로 scope를 넓히지 않음. 외부 소비 SDK가 추가 확인되면 실제 기본days/metadata에 한해 연동 |

## 5. 삭제 전 반드시 필요한 호환 회귀

아래는 모두 **원본을 지운 별도 fixture DB**와 혼합 기간 DB에서 cold/cache/bundle/API를 비교해야 한다. 현재 phase1 focused test를 이 수용의 완료 증거로 쓰지 않는다.

1. **7/14/21/90일:** archive-only 해당 전체기간이 반환되고, 기존2일 raw만 반환하는 축소 없음.90일 날짜조회는 실제 요청 start/end 고정, 첫/마지막 날짜 공백 유지.
2. **평균 가중치:** binA값0 한개, binB값100 아홉개 → 평균90/count10. bin별 평균의 평균50은 RED. 전국 by-hour도 lot/관측 가중치 유지.
3. **시간/요일/KST:** UTC14:59:59와15:00:00을 서로 다른 KST 날짜로 집계. 월요일 자정/공휴일 경계 및 특정lot필터 일치.
4. **공휴일 동시성:** A/B anti-correlated 예시→전국 min/max100. 같은시각 일부lot/공항 결측, 서로 다른수집시각 → 기존 동일timestamp cohort count/평균 일치. 글로벌 검산 전 어느 공항 raw도 삭제 불가.
5. **정각·임의간격:** exact10분의 양끝 관측, 바로 전/후1µs, interval15/17/29/40/50, anchor offset. 미래값을 과거point에 쓰지 않음. 정보가 소실된 경우 metadata가 reconstructed/partial임을 보이고 exact 주장하지 않음.
6. **범위절단:** 상대14일 cutoff가bin중간, 현재48h 경계가bin중간, 명시범위 종료빈이 빈 경우. archive/raw 중복0·경계누락은 유효범위 metadata와 일치.
7. **공백/실제0:** 30→관측없음→30은 가짜10/50event0. 실제30→0은 정당event. chart는 lot_observations0 구간을 끊음. 완전미집계와 정상무관측의 status가 다름.
8. **원관측event:** 하루 내 여러번10/50 상하향, bin경계 교차, 창 시작 이전마지막50→창첫5, 긴공백의observed_transition, source동시각중복. 순서/limit/이름/공항scope 유지.
9. **insights:** lot event는 없지만 공항합계가 threshold를 넘는 사례, 여러lot의 교차시각 차이, 날짜별첫하향 하나, 요일 중앙값·최근30개 일치. archive event 복사대체는 RED.
10. **outlook:** 날짜A표본1평균0, 날짜B표본9평균100 → 날짜동일가중평균50(90은RED), sample_days2/observations10/full_days1/50%. capacity0 제외, capacity변경 min/max, inactive lot 제외, 오늘 제외, latest 시각 보존.
11. **history48h:** default2/max2, days3/30 명시검증오류, exactcutoff포함/이전제외, 원본항목만 반환. 기간을 넘은 signed oldcursor410 및 cutoff metadata, filter위변조422. prune 후page중간자료손실도 빈정상종료로 위장하지 않음.
12. **history 캐시:** 48h 직전 캐시 준비→시간이흘러 경계통과→DBprune. gzip/br/identity·legacy무limit·paged 모두 만료원본을 유출하지 않음. 메모리 snapshot invalidation과 preparedbyteskey 검증.
13. **현재상태:** 48h동안 새수집 없는 lot도 마지막상태·originalobserved/collected/혼잡도 표시, stale로 정직하게. sameobserved live/migration id tie·lateoldobserved replay·MapSDK초단위 차이·공항합계부분stale 모두 삭제 전후 비교.
14. **Map export:** 성공generation/member_ids/자연키/좌표/숫자/시각 동일. prune 직전 첫page→prune→다음cursorpage는 immutable DTO로 동일, TTL만료시410. source실패상태·범위가 다른 pointer를 raw삭제로 없애지 않음.
15. **sealed replay:** 과거bin2표본집계→raw모두삭제→동일observed/source 재수신(newcollected/newid)→기존통계 유지, 추가합산0, subset덮어쓰기0, 충돌/보류가시화. 임의수정값 replay도같음.
16. **검산/중단:** 같은id raw값/JSON변조·raw누락·통계JSON변조·원본count mismatch·globalcoverage누락은 prune0. 검산후 delete 직전 지연commit은 collector동명lease/트랜잭션 경계로 차단. 배치중실패/재시작 멱등.
17. **원문body:** `kac_parking`/`incheon_parking` source·run·endpoint·received_at별 검산; 다른source fee/rail/bus/fuel/weather/unknown error·collection metadata 남김. 실패파싱·미집계 body 처리와48h보류사유를 먼저 정의하고 무차별 삭제하지 않음.
18. **운영표시/복구:** raw이력범위와 통계가용범위 구분, run의 저장당시count와현재보유count 구분, archive/backfill실패가 fresh성공으로 보이지 않음. same-schema 구dump 복원으로 통계가2→1 감소하는 R2 실제반례를 차단/보존하는 경로를 검증. pre-restore백업파일이 있다는 사실만으로 영구통계보존을 주장하지 않음.

## 6. 작은 의존 PR 순서

1. **2A 저장 보완:** global cohort 충분통계·coverage/sealing/late상태, 전역 삭제 guard. 원본삭제 계속0. current tie와 raw/통계 기간 metadata 수용방식 확정. 임의분간격 손실은 명시한다.
2. **2B reader 전환:** 충분통계 병합·시계열 복원·outlook·event/insights·cache·직접API/묶음API, 기존과 같은 화면에서 metadata·달력만 필요한 만큼 반영. raw history48h/cursor/cache/proxy 계약을 함께 변경. 삭제 계속0.

3. **3 삭제 연결:** 완전 backfill→위반례 검산→bounded batch prune와 보류상태. backup/restore/기준정보/현재state/export 보호를 포함한다. 모든 read 수용 전에 raw삭제가 활성화되는 commit은 만들지 않는다.

1단계PR을 머지해도 사용자 정책 전체 완료가 아니다. 위 reader와 prune가 함께 검증된 뒤에만 원본48h·통계영구 정책 완료라고 보고한다.

### 2B 첫 내부 단위: 세 pattern의 동등성

`parking_archive_reader.read_pattern_statistics`는 DB/API를 전환하지 않는 순수 함수다.
입력의 공항/lot와 반열린 UTC 기간에 대해 count/sum/min/max를 병합해 기존 by-hour,
by-weekday, by-weekday-hour 배열을 만든다. 전국 scope도 이 세 분석에서는 lot 관측 가중치를
유지한다. 공휴일의 동일시각 합산 cohort나 outlook의 날짜 동일 가중치와 혼용하지 않는다.

동일 공항/10분 버킷은 archive가 소유하므로 남은 원본을 중복 합산하지 않는다. 버전·통계 지문·
표본·범위를 검산하고, 원본 전체가 전달된 버킷은 count/raw 지문도 대조한다. 봉인 이후 새 id의
지연 재수신은 영구 통계에 덧붙이거나 덮어쓰지 않고 conflict로 거절한다. 입력에 일부 원본만
남은 경우 그것만으로 전체 raw 지문이 검산됐다고 표시하지 않는다.

범위 경계나 시간대의 hour 경계가 요약 내부를 자르면 해당 공항/버킷의 필터 전 원본 전체와
지문이 일치할 때만 정확한 raw로 나눈다. 복구할 수 없으면 `ParkingArchivePrecisionUnavailable`
예외의 metadata에 사유·요청 기간·버킷·10분 해상도를 제공한다. 이 예외를 기존 API의 빈 배열로
바꾸는 연결은 없다. 최종 API의 유효 범위/header·객체 metadata 처리는 다음 연결 단위에서 정한다.

정확도는 `exact_for_included_observations`, 전체 기간 coverage는 `unknown`으로 구분한다.
이 함수에 없던 버킷이 실제 무관측인지 누락인지 알 수 없기 때문이다. 빈 입력도 관측0의
정상 완전 구간이라고 보증하지 않는다. 요청은 반열린 기간인 반면 현재 일부 API는 하한만
적용하므로, 이 내부 계약을 실제 API 응답 변경 없이 그대로 대체했다고 표시하지 않는다.

DB 없는 실제 archive builder 기반11개 순수 회귀(7/14/21/28/90일×전국/공항/lot×archive-only/
혼합/중복 포함45경우, 평균 가중치, KST 날짜, Kathmandu 경계, 변조·재수신·공백)는 WSL
`unittest`에서11 PASS/0.602초·actual0이었다. 같은 제품/회귀의783 Docker 순수 실행도 네트워크 없이
11 PASS/0.657초·actual0·독립wait0,832파일/106패키지·Git10·원 child/CID 종료를 확인했다.
첫 사전 이미지 준비는 FROM의 raw sha를 registry 이름으로 해석해 실패했고 테스트 실행은0이었다.
그 원본 로그를 보존하고 기존 로컬 tag의 immutable ID를 전후 검산한 새 root에서 준비·실행했다.
이는 전체/실제 DB/API/cache/bundle 검증이 아니며 해당 연결과 독립 리뷰는 여전히 미완 gate다.
