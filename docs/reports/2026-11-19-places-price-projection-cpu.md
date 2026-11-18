# 장소 입력 revision과 안전한 조기 재사용 — 2026-11-19

## 실제 기준과 수용 경계

기준 소스는 defc4a7e3141f7b5ea4a83a5a4b70c7fc46526d8, 실제 운영 DB는 0044다.
부모의 quiet 측정에서 places limit5000 중앙값2544.42ms는1초 미달,
rail304 p95106.896ms는300ms 충족, TRN04는 재구축 밖 기준 미입증으로 INCONCLUSIVE다.
이번 변경은 로컬 후보다. 운영·DDL·이미지 빌드/배포·성능 수용은 실행하지 않았다.

초기 가격 Row 반복 접근 보정은 유지한다. 그 로컬 CPU 약11% 개선만으로 운영1초를
달성했다고 보지 않고, 아래 완전한 입력 증명을 통해6회 DB 읽기와 item 조립 이전에
이미 완료한 DTO/직렬화 결과를 재사용한다. 요청 generated_at은 매번 새로 만든다.

## 입력 감사와 0045

일반 비클러스터·include_fuel_statistics=false 경로에만 적용한다.
통계/클러스터는 기존 경로를 유지하므로 그 별도 입력을 이 캐시의 권한으로 삼지 않는다.

| 표 | 포함하는 실제 의존성 |
|---|---|
| fuel_stations | 이름·좌표·브랜드·시설·필터·정렬·출처 등 모든 열 |
| fuel_latest_prices | 현재 유종/NULL/가격·시각·전체 가격 존재 여부 등 모든 열 |
| rail_station_references | 시설 raw5개 키를 포함한 모든 열 |
| ferry_ports / bus_terminal_references | 수동 위치 revision·좌표·명칭 등 모든 열 |
| airports | code·명칭·source·updated_at 등 모든 열 |
| rest_area_references | 좌표·시설·노선 등 모든 열 |
| public_parking_lots | 현재 성공 집합의 시설·요금·좌표·정렬 등 모든 열 |
| highway_incident_snapshots | 최신 identity 선택·관측/수집시각·24시간 범위 등 모든 열 |
| transport_collection_states | 주차장 last_success_at 집합 선택과 유가 성공/실패·신선도 |

위10개 표마다 INSERT/UPDATE/DELETE/TRUNCATE statement trigger를 둔다.
0043의 기존 counter 표에 places.<table>별10행을 추가하며, 모든 UPDATE를 보수적으로
무효화한다. 기존 참조 export component 의미와 값은 유지한다.
CollectionRun 자체는 places SELECT의 입력이 아니며 실제 선택은 collection state다.
공항 provider 번들의 실제 좌표/출처·조회 함수와 release도 키에 넣는다.

- head는 0045_places_input_revision(32자 이하), 0044→0045이며 새 데이터 표/색인은 없다.
- 일반 transaction DDL, lock_timeout2초·statement_timeout120초다.
- 초기 공통 counter 한 행은 실제 두 writer 대조에서 fuel TX가 열린 동안 airports가
  205.34ms 뒤55P03으로 막혔다. 최종 표별 vector는 같은 대조에서4.38ms에 완료됐다.
  두 실험 모두 rollback했으며 기존 collector TX를 나누지 않았다.
- fuel 성공 state는 원본/최신 가격 저장 뒤 _mark_fuel_success에서 flush한다.
  component는 표별이므로 첫 station write가 다른 종류 전체를 잠그는 새 전역 counter는 없다.
  같은 입력 표/collection-state counter 사이의 동시 쓰기 잠금은 여전히 존재한다.

## 재사용 권한과 시간/동시성

첫 SELECT 전에 RR을 시작하고 같은 snapshot의10개 epoch/revision vector를 읽는다.
engine·실제 public 관계 OID·trigger DDL anchor·release·provider·모든 검증된 조회 조건이 키다.
SELECT는 payload 없이 vector/catalog와 다음 돌발 시간 경계를 한 SQL로 읽는다.

실제 trigger의 각 이벤트 tgtype, 빈 tgattr, tgqual 없음, statement/AFTER,
함수·enabled·무인자 및 shadow 관계를 확인한다. UPDATE OF/WHEN/다른 이벤트/disabled는
재사용하지 않는다. trigger 복원도 catalog anchor 변경으로 기존 page와 구분한다.
own XID·미반영 ORM write·READ COMMITTED·unknown release도 재사용 권한이 아니다.
vector 행 누락은503이며, downgrade/up 또는 epoch 교체도 과거 key를 재사용하지 않는다.

- 돌발: 미래 collected_at의 진입과 collected_at+24시간 이탈 중 다음 실제 경계까지만 쓴다.
  경계 시각을 포함해 다시 구성하므로 BETWEEN의 양끝 포함과 직후 이탈을 보존한다.
- 유가: 기존24시간 stale의 엄격한 초과 조건을 유지하고 경계에서 다시 계산한다.
- 시간 역행은 page 구성 시각보다 앞선 page를 재사용하지 않는다. 임의 TTL은 없다.
- 같은 RR에서 vector를 읽은 뒤 writer가 commit한 실제 race 시험은 첫 요청의 옛 snapshot,
  다음 요청의 새 vector/행, 이후 warm 재사용을 확인한다.
- 페이지와 기존 입력 bytes LRU가 합계32MiB/8항목을 공유한다.
  초기 DTO 검증·완전한 입력 bytes 검산은 유지하고 잠금 밖에서 실행한다.

## 로컬 대형 응답과 작업량 증거

운영 복제가 아닌 전용 로컬 PostgreSQL 합성 fixture다.
limit5000에서 반환4379개·2835863바이트이며, per-kind quota와 고정 순서를 그대로 따른다.
first·canonical·warm5개의 전체 JSON은 generated_at 외 동일하다.
현재 fixture의 본문 SHA256은 1355d6bc8fe7d1ad891e7047cd2107e730e3cc449f7d4c42633b3078326f1e7c다.

| 경로 | SQL | page_builds | HTTP 벽시계 | CPU |
|---|---:|---:|---:|---:|
| 첫 후보 요청 | 7 | 1 | 별도 first 원문 참조 | 별도 first 원문 참조 |
| 조기 재사용을 끈 동일 full 경로 | 6 | 1 | 133.15ms | 80.98ms |
| warm5개 중앙값 | 매회1 | 매회0 | 38.98ms | 16.33ms |

계수는 실제 Server-Timing 원문을 first/full/각 warm별로 저장했다.
두 경로 시간 모두 client의 JSON 재파싱은 제외하고 본문 동등성은 별도로 검사했다.
fingerprint_calculations는 이 경로의 판단 근거로 사용하지 않는다.
초기 별도 표본39.63ms와 최종 계수 보존 표본은 모두 로컬 증거이며 운영 개선율/1초 수용이 아니다.

## 검증과 다음 단계

- 관련158개 PASS(191.10초). 이어 lifespan8개와 큰 응답 증거 재확인1개 PASS
  (중복 없는 총166개; 큰 응답1개를 두 번 세지 않는다).
- 실제10표×4종 변경, rail raw5개, 성공 집합/실패 복구, clock 경계/역행,
  제한 trigger, epoch/누락, engine/shadow, own-write, RR writer race를 포함한다.
- 실제0045 up/down·DDL lock 실패 전체 rollback, 기존0044의9개 데이터/정렬 경계,
  independent writer와 cache 합계 용량/동시성을 검증했다.
- Alembic check·OpenAPI 정본 PASS. 원문은 저장소 밖 transport-places-dto-followup-work의
  final-focused.xml/log, warm-work-and-lifespan.xml, warm-work-summary.json,
  scalar-two-writers.json, vector-two-writers.json에 보존한다.
- 전체 로컬 suite/새 Docker2차/운영 측정은 미실행이다. 정확 PR CI와 부모/Banach의
  최종 delta 검토 후 수용한다. 추가 리뷰 체인을 만들지 않는다.
- 후속 ops는 확인된 Manager efda42f8453acd5a13be21f3906442c928eb99c8과
  실제 SDK609 바인딩을 사용한다. SDK 예외나 이전 UI의 재태깅은 하지 않는다.
  frontend/GDAL 입력이 같음을 대조하고 보존 builder의 정상 빌드에서 실제 CACHED를 확인한다.
  실제 역할별 새 source/OCI 증거와 tested normal build 전에는 운영 DDL을 하지 않는다.
