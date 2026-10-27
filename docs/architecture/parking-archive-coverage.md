# 주차 보존 2A: 전국 통계와 검산 보류·현재 요약

이 단계는 [원본48시간·통계영구 설계](parking-retention.md)의 저장 보완이다. 기존 분석·현재·history API는 아직 원본을 읽으며 `prune_parking_raw`는 항상 거절한다. 자동 schedule이나 운영 삭제를 활성화하지 않는다. **2A만으로 원본48시간 정책이 완료되지 않는다.**

## 전국 동시각 통계

`parking_global_statistics_buckets`는 UTC10분 `bucket_at` PK의 일반 logged 테이블이다. 같은 lot/관측시각의 중복은 기존 `analytics.py:deduplicate_snapshots`와 동일하게 live·최근 적재·큰id 순으로 정리한다. 그 뒤 전국의 정확히 같은 관측시각 잔여면 합계를 하나의 표본으로 삼아 count/sum/min/max만 영구 보존한다. 여기서 전국은 기존 무범위 API와 같이 이 DB에 저장된 모든 공항이며, 수신하지 못한 공항의 값을0으로 만들지 않는다.

공항A의 두 시각 값이0/100이고 공항B가100/0이면 전국 최소·최대는100/100이다. 공항별 최소합0·최대합200으로 대체할 수 없다. 이 별도 충분통계는 기존 전국 공휴일·주말 API를 유지하기 위해 필요하며 새 UI를 추가하는 기능이 아니다. 개별 관측의 배열이나 timestamp별 값을 모두 저장하지 않는다. 최대144행/일이다.

한 행은 전국 raw 수량·선택 표본수·최대id·정규화 raw 지문·통계 지문 및 `airport_proofs_json`을 함께 보관한다. 공항 proof에는 해당 공항의 기존 영구통계 raw/count/hash와 통계 hash가 들어간다. raw가 존재한 모든 공항을 먼저 `verify_bucket`으로 검산한 뒤에만 전국 행을 생성한다. 어느 공항의 통계가 아직 없으면 partial/deferred이며 부분 공항 집합을 전국 완료로 발행하지 않는다.

행의 존재가 그10분 범위의 seal이다. 기존 행은 `verify_global_bucket`으로 검산하며 append나 overwrite하지 않는다. 원본 일부만 남았거나 동일 관측이 새id/적재시각으로 재삽입돼도 기존 지문·count·공항 membership이 달라 검산을 거절한다. 원본을 지우기 전에는 이 전국 검산도 반드시 필요하다. 삭제 자체는 이번 단계에서 실행하지 않는다.

새id 탐색은 UTC date_bin과 전국 PK 등가 조건으로 하루 범위만 읽는다. 이는 전체 역사 재검산이 아니다. 새 행이 없을 때의 `no_new_rows/coverage_status=not_audited`, 처리한 배치의 `partial` 의미를 유지한다. 같은id 수동 수정이나 사라진 과거 raw를 매번 전체 탐색해 감시한다고 주장하지 않는다.

공항·전국 후보 탐색은 아직 seal되지 않은 bucket 전체에 최근48시간 적재가 있으면 그 bucket을 보류하고,
다음 날짜의 적격 bucket을 찾는다. 가장 오래된 보류 때문에 그 뒤의 모든 날짜가 계속 멈추지 않는다.
보류만 남으면 `deferred/partial`과 최초 pending 시각을 반환한다. 이때 `deferred_buckets=1`은
`deferred_count_scope=first_pending_bucket`의 최소 확인 범위이며 전체 미집계 건수로 해석하지 않는다.
기존 seal에 새id가 생긴 경우는 최근 적재라도 충돌 검산에서 제외하지 않는다.

Python의 `bucket_start`와 지문/추이점 시각은 timezone을 단순 부착하지 않고 UTC로 변환한 뒤10분 floor한다.
`+05:45`처럼 offset이10분 배수가 아닌 경우에도 PostgreSQL date_bin과 같은 UTC 경계를 사용한다.
이는 c7 독립 리뷰에서 발견한 두 P2의 후속 해소이며, c7 통과 원장이나 원본 소스를 고친 것으로 세지 않는다.

## 보류 상태와 job

`parking_archive_issues`는 scope/bucket별 reason·발견 최대id·최초/마지막 발견시각만 담는다. 원문이나 원관측 배열은 저장하지 않으며, 같은 원본을 다시 발견했다고 관측수를 가산하지 않는다.

수집의 정상 INSERT 뒤에 이미 sealed인 과거 범위의 새id가 보이면 `late_source_rows`로 기록한다. 현재 단계는 이 raw INSERT를 차단하거나 과거 통계를 교정하지 않는다. HTTP 원문·현재 API의 기존 동작을 유지한 채, sealed 통계를 다시 쌓거나 덮지 못하도록 보류를 드러내는 선행 장치다. 지연 관측을 무손실 교정할 수 있다고 주장하지 않는다.

공항 집계가 충돌하면 savepoint만 되돌리고 보류 상태를 별도 outer transaction에서 commit한다. 전국 검산 충돌도 같은 방식으로 통계 원문을 보존한다. 활성 보류가 있으면 다음 실행도 blocked이며, 지금 단계에는 자동 해소/force 경로가 없다. 보류를 무시해 원본이48시간 안에 정리됐다고 보고하지 않는다. 실제 활성화 전에는 지연자료 처리·보류 해소·scope별 정리 진행과 초과 보유량의 운영 수용이 필요하다.

기존 수동 `parking_statistics_archive_job`은 같은 collector transaction lease 아래 현재 seed→공항 집계→전국 seal을 수행한다. 상태 commit이 끝난 뒤 blocked 결과는 Dagster 실패로 표시한다. 녹색 job으로 coverage 성공을 위장하지 않는다. provider 호출·수집 실행 추가·자동 schedule·삭제는0이다.

공항/전국 집계는 같은 실행 UTC 시각과48시간 cutoff를 쓰되 서로 다른 날짜 창을 선택할 수 있다.
기존 선택/검산/발행 scalar는 `verification_domain=airport_statistics`이고 전국은 `global_` 접두사로
별도 표시한다. `airport_status`/`global_status`와 각각의 coverage도 분리한다. 전국의 `no_new_rows`가
이번 공항의 실제 신규 발행을 덮어 전체 무처리로 바꾸지 않는다. Dagster output metadata·INFO 로그와
blocked failure metadata에는 정해진 scalar만 남기며 raw payload를 넣지 않는다. batch 충돌 내부 sentinel은
실제 관측 시각처럼 표시하지 않는다. 두 영역의 extrema 모두 연속 coverage·삭제 허용을 뜻하지 않는다.

2A 초기9fb 집중은166 PASS/7 FAIL·actual exit1이었다. 새 무FK 테이블의 시험 초기화 누락으로6건,
job action 기대1건이 실패했고 일부 통과도 잔존 상태 영향을 배제하지 못한다. 원본 로그/DB/JUnit은
보존하고 초기화·action·관측 통합을 보완한 새 소스를 별도 nonce DB에서 다시 검증하기 전 수용하지 않는다.

## 현재 요약과 참조 보호

`parking_latest_states`는 lot별 한 행의 파생 현재 상태다. public current의 기존 `observed_at desc/id desc`를 그대로 보존한다. 분석의 live 우선 규칙이나 Map의 별도 SDK 현재 집합으로 대체하지 않는다. 같은시각 live id1/마이그레이션 id9의 기존 current는 id9다.

원래 관측·적재 시각과 수량·혼잡도만 남기며 snapshot FK/raw payload/collection run FK는 없다. `snapshot_order`는 같은시각 id 순서의 숫자 watermark이고 원본 참조가 아니다. 늦게 저장한 옛 관측은 현재 수량을 덮지 않지만 `latest_ingested_at`은 따로 갱신한다. 이 값을 원래 관측점의 `collected_at`에 덮어쓰지 않는다.

현재 행이 없는 lot만 기본512개씩 seed한다. 원본이 없는 lot은 상한을 적용하기 전에 제외하므로 빈 기준정보가 선두를 점유해 뒤의 유효 lot을 영원히 막지 않는다. seed는 raw JSON 없이 기존 latest 선택과 lot별 최대 적재시각을 읽는다. 이후 정상 수집 INSERT와 같은 transaction에서 갱신한다. API reader 전환은2B에 남긴다.

lot/airport 복합 FK는 RESTRICT이고, 최신 요약만 있는 DB에도 legacy PK 덮어쓰기를 거절한다. 통계가 없다는 이유로 현재 lot 의미를 바꾸지 않는다. 새 세 표에 데이터가 있으면 migration downgrade도 거절한다. 같은 schema의 옛 전체 dump가 통계를 되돌리는 복원 문제는 여전히 별도의 활성화 전 수용 항목이며, pre-restore backup의 존재만으로 해결됐다고 표시하지 않는다.

## 검증 경계

DB를 사용하지 않는 전국 동시각·중복·current 선택·raw 변조·부분 유실·삭제 후 재삽입 검산 회귀와 실제 DB ingestion/seed/lease 회귀는 분리한다. 후자의 새 nonce DB 검증 전에는 전자만으로 migration·transaction·FK·조회계획을 수용하지 않는다. 기존 API/48시간 history/cursor/cache/Map snapshot/해상도 전환과 실제 prune는2B·3단계의 별도 수용이다.

## 영구 seal 후보 계획의 추가 P2

707의 기능 집중 두 실행은 각237 PASS+6 subtests PASS였지만, 소유 합성 DB의10000통계/900원본
계획은 적격 후보의 별도 seal EXISTS를 hash용 전체 PK 읽기로 바꿨다. 실행한 Index Only Scan의
10000행/loops1이므로 index 이름만으로 bounded라고 수용하지 않는다. pending은 구간별900회 PK였다.
공항·전국의 해당 EXISTS에 OFFSET0 fence를 넣어 결과는 유지하고 상관 구간별 PK 탐색을 보존한다.
회귀는 통계 유무×scope 둘 다 실제 실행한 통계 scan의 bucket_at 등가 Index Cond·행수<=1을 검사한다.
실행하지 않은 대안 노드의 표시를 실제 전체 읽기로 오인하지 않는다. 원707 증거는 고치지 않으며
새 계획/집중/다운그레이드 GREEN과 독립 리뷰 전에는 이 P2나 전체48시간 정책을 완료로 표시하지 않는다.

## 99 후속 검산 결과와 다음 gate

99de06f의 관련9파일은 WSL152 PASS+6 subtests/44.24초·Docker152 PASS+6 subtests/55.12초,
F/E/skip0·actual0·Docker wait0이다. 기존707의17파일237+6 결과와 새query delta 검증을 구분한다.
통계 유무×공항/전국의 새 실제 PG 계획 회귀가 모두 통과했다.707 RED와 동일 DB의 read-only 재조회와
별도 fresh10000통계/900원본의 pending/eligible는 모두 실행한 통계 scan이 PK등가·Rows1×900이다.
세 추가 테이블은 각각 데이터가 있을 때 downgrade 실제exit1이며 행수10000/1/1과schema37을 유지했다.
829파일/locked106/Git10 검산과 실제 child·Docker 종료를 회수했다. source/DB/log·이전 실패는 보존한다.

이는 집중 수용이며 source 전체·CI·두 독립 리뷰·실제 운영 적용의 gate는 남는다. 기존48시간 밖 raw가
현재 API/history에서 사라졌다고 표시하지 않으며, reader 전환과 검증 후 prune를 붙이기 전 원본 삭제는0이다.
