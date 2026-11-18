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
변경이 잦은 응답에는 이 비용이 반복될 수 있다. SQL 병목은 바꾸지 않았으며
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
