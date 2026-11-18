# 장소 CPU 후속과 TRN03 요청별 관측

기준은 실제 배포된 `4584ee95291d6e34a90b2c65de090d9737decbb0`이다.
운영 places의 동일 데이터 3표본은 4.8008/3.1976/2.5967초, SQL 6개였다.
철도 warm304 p95 89.3ms는 300ms 목표를 충족했지만 페이지 구성·지문 계산은
기존 헤더에서 관측할 수 없었다. 이 기록은 부모가 전달한 관측이며 이 후속에서
SSH·운영 GET·배포를 다시 실행하지 않았다. TRN04는 INCONCLUSIVE를 유지한다.

## 장소 입력의 정확한 일치에만 검증 결과 재사용

다중 종류 PostgreSQL 경로도 기존 유가 지도용 `ValidatedFuelMapItems`의
전체 바이트 대조·동일 DTO 검증·직렬화 결과 재사용을 쓴다. DB 조회·정렬·필터·종류별
할당량·최신 관측 선택은 매 요청 그대로 실행한다. 가격·좌표·설명·날짜·수동 위치
revision 등 항목 입력이 바뀌면 다시 검증한다. 총계·출처·신선도·`generated_at`은
항목 캐시 밖에서 매 요청 검증한다. 기존 공유 상한 32MiB·8개를 유지하며 TTL은 없다.
원문 투영이나 공개 속성을 줄이지 않았다.

같은 로컬 PostgreSQL 합성 DB·같은 시각 경계에서 기준과 후보를 교대로 실행했다.
각 warm 6회 중앙값이며 운영 데이터 사본·ARM 측정이 아니다. 2,670개 항목,
총 32,348개, 본문 약 2.016MB다. `generated_at`을 제외한 데이터 SHA256은
양쪽 모두 `b8f41bd111b45821aab08309a3efbbce8bd1146753a01bbb8212ed6a43e8b9af`다.

| 항목 | 기준 | 후보 |
| --- | ---: | ---: |
| HTTP 요청 완료 | 277.5ms | 256.7ms |
| 프로세스 CPU | 98.5ms | 73.6ms |
| SQL 수 | 6 | 6 |
| SQL 시간 | 198.6ms | 198.4ms |
| warm 검증·직렬화 CPU | 31.08ms | 9.11ms |
| cold 검증·직렬화 CPU | 28.65ms | 38.36ms |

cold 또는 항목 변경·LRU 퇴출 시 입력 JSON 생성으로 CPU가 약 10ms 늘었다.
변경이 잦은 응답에는 이 비용이 반복될 수 있다. 위 DTO 변경 자체는 SQL 병목을 바꾸지 않았으며
**운영 1초 목표 달성은 입증하지 못했다.** 소수 정밀도·전체 DTO 속성·UTC microseconds·
좌표 쌍 정규화와 필터·순서·할당량·총계의 기존 응답 동등성을 집중 시험했다.

## 요청별 Server-Timing 두 계수

`app.core.read_timing._current`의 `ContextVar[ReadTiming | None]`가 요청마다 새
`ReadTiming` 객체를 보유한다. 아래 hook은 이 객체만 증가시키고 요청 밖에서는
아무 일도 하지 않는다. 공유 전역 누적값의 차이를 쓰지 않는다. 동시 요청을 교차
실행해 각 헤더가 자기 작업만 담고 종료 뒤 context가 복원되는지 검증한다.

- `page_builds;desc="N"`: `export_references.build_reference_export_router()` 내부
  `read_page()`가 304 분기를 지난 뒤 페이지 행을 읽고 `spec.page_model`을 구성하려는
  시도 수다. membership 검증 실패나 재시도도 실제 작업 시도로 집계한다.
- `fingerprint_calculations;desc="N"`: 큰 입력·본문을 순회해 지문을 만드는 시도 수다.
  `reference_export_revision.reference_payload_revision()`의 revision memo miss 뒤
  `UNION ALL`/`string_agg` SQL, `reference_artifacts.prepare_artifact()`의 신규 본문
  canonical digest 순회, `export_references._freeze_reference()`의 legacy fallback
  canonical digest 순회에 각각 한 번 더한다. 행별 hash 수가 아니다.
- `read_page()`의 `semantic` 목록 SHA256은 저장 digest와 페이지·상태·만료 metadata만
  다루는 작은 ETag hash이므로 위 지문 계수에 넣지 않는다. revision memo의 작은
  head/cache key hash도 넣지 않는다.

실제 지원 PostgreSQL 경로의 첫 200은 두 계수가 양수, 기존 본문의 다음 200은
페이지 1·지문 0, warm304는 페이지 0·지문 0이다. 입력 변경 뒤에는 다시 200과
양수 계수가 된다. `release_sha="unknown"`인 legacy 경로는 304여도 전체 본문을
다시 hash하므로 지문 1을 정직하게 노출한다. 상태코드만 보고 0으로 만들지 않는다.
기존 JSON·ETag·304 본문·신선도·손상 검증 계약은 그대로다. 새 헤더를 운영에서
관측하기 전 기존 UNOBSERVABLE 증거를 소급하여 0으로 처리하지 않는다.

## 집중 검증과 다음 범위

- 장소 회귀: WSL PostgreSQL 43개(39.99초), Docker PostgreSQL 43개(44.65초) 통과.
  WSL 뒤 신규 시험의 import·dict literal만 Ruff로 정리했고 최종 파일은 Docker에서 검증했다.
- TRN03 계수: 신규 3개와 기존 timing·warm304 회귀 3개만 실행해 WSL 6개(7.17초),
  Docker 6개(8.20초)가 통과했다. 첫 응답/재사용/입력 변경/legacy304/동시성·context 복원을 검사했다.
- OpenAPI는 기준과 동일하다. 변경 Python의 문법·이름 오류, 신규 시험·검증 모듈·timing
  모듈의 Ruff와 diff 공백 검사를 수행한다. 전체 시험·추가 적대 리뷰를 반복하지 않는다.
- 로컬 실행 원문·교대 benchmark와 재현 스크립트는 저장소 밖
  `transport-places-runtime-followup-work/`에 둔다. 운영 1초 수용과 새 계수의 실제 관측,
  정확 PR CI·정상 빌드·적용은 부모 작업에서 정산한다.


## 추가 SQL 후속 — 전체 이력 출처의 index walk

부모의 별도 READ ONLY·문장 15초 상한 실제 계획에서 `available_sources`는
9,383.6ms였고 돌발 이력의 `ix_highway_incidents_source_collected`를 전체 순회했다.
표시값은 10개지만 해당 index scan은 2회 loop당 187,152행, shared read 26,075블록,
약 8,307ms였다. 같은 진단의 장소 count/page는 3,551.8ms였으며 최신 돌발 순위는
15,843행·289개 ID, 메모리 sort 1.6MiB·임시 파일 없음이었다. 이 cold 계획을 앞선
HTTP의 SQL 1.38초와 비교해 개선율을 계산하지 않는다. 원문은 저장소 밖
`transport-places-runtime-followup-work/production-plan-4584.json`에 있다.

`place_sources()`의 PostgreSQL `highway_incident` 분기만 SQLAlchemy recursive CTE로
바꿨다. 기존 source 선두 B-tree에서 `ORDER BY source LIMIT 1`로 시작하고
`source > 이전 값`의 첫 행으로 이동한다. 최신 24시간 제한·캐시·TTL·DDL은 없다.
다른 종류와 마지막 전체 DISTINCT는 기존 그대로다. 빈 표는 빈 집합이며, nullable
column이면 NULL 옵션도 한 번 보존한다. 현재 돌발 source는 NOT NULL이므로 이
추가 NULL 탐색은 실행하지 않는다. 과거에만 존재하는 출처·빈 문자열·Unicode·
중복과 다음 요청의 새 출처를 이전 전체 DISTINCT 결과와 대조했다.

기존 로컬 합성 이력 355,935행을 재사용한 교대 warm 4회씩의 source 조회 중앙값은
25.60→8.51ms, 프로세스 CPU 1.40→1.77ms였다. 출처 6개의 SHA256은 양쪽 모두
`6adae7127594bb04e808ba54a88fd011d7c6df5edd6ccc6513b07447ad37b491`다.
별도 ANALYZE 실행은 33.29→7.90ms, 계획 전체 shared hit 1,274→684블록이었다.
돌발 index의 처리 tuple은 355,935→1개와 마지막 빈 탐색으로 줄었고 해당 index의
shared hit은 580→7블록이었다. 양쪽 shared read는 0으로 warm 로컬 표본이다.
운영·HTTP 개선이나 1초 목표 달성을 뜻하지 않는다. 컴파일된 운영 검토용 SQL과
원 계획·표본은 같은 작업 폴더의 `candidate-available-sources.sql`,
`sources-benchmark.json`에 둔다. 운영 후보 EXPLAIN은 부모의 별도 범위다.

출처 SQL 집중 검증은 신규 4개와 기존 다중 종류 동등성 6개·marker 계약 1개만
실행해 WSL PostgreSQL 11개(21.06초), Docker PostgreSQL 11개(22.46초)가 통과했다.
변경 source와 신규 시험의 Ruff·문법·diff 검사를 통과했다. 전체 시험은 반복하지 않았다.
