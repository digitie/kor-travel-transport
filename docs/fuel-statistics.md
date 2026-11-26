# 유가 통계

유가 원본 수집이 정상 종료하면 원본 가격·최신 가격·성공 상태를 먼저 commit한다. 그다음 별도 savepoint에서 통계 세대를
준비하고, 마지막에 짧은 원천별 공개 잠금 안에서 일별 집계와 공개 state를 전환한다(#104 이후, 경계는
[유가 저장과 통계 공개의 병행성](architecture/fuel-publication-concurrency.md)). 발행이 미뤄지면 유가 op가 가린 한 줄
원인을 Dagster event log에 넘기고 output metadata `fuel_statistics_published=false`로 표시한다(2026-10-27). 오피넷은 전국·시도·시군구별, 한국도로공사는 고속도로 전체·노선별·노선/방향별로 나눈다. 두 원천의 주유소를 합산하지 않아 중복 집계를 피한다. 방향은 공급자가 제공한 방향명을 그대로 사용한다.

`fuel_statistics_states`는 원천별 성공 발행 시각, `fuel_statistics_points`는 지도 집계용 최신 가격, `fuel_statistics_daily`는 KST 일별 마지막 정상 수집의 범주별 지표를 저장한다. 일별 기록은 영구 보존하고 조회 창만 공개된 마지막 집계일 포함 30일이다. 같은 날 재수집은 해당 날짜의 마지막 성공본을 교체한다. 과거 기록을 추정하거나 빈 날짜를 보간하지 않는다. 설치 전 이력을 자동 전수 스캔하지 않으며 최초 발행 이후 일별 기록을 축적한다.

평균은 유효한 양수 가격의 주유소별 단순 평균이다. 유종별 개수·평균·최저·최고·최고-최저 차이·모표준편차·50L 평균 대비 최저가 절감액을 제공한다. 최저가 동률은 안정적으로 한 주유소를 대표 표시하고 동률 개수도 제공한다. 정상 세대의 각 범주·유종에는 가격과 station_key 순으로 최대 10곳의 이름·주소·좌표·가격을 metrics_json에 함께 보존한다. 누적기는 범주별 10곳만 유지하며 원본 조회 중에 처리하므로 공개 잠금 범위는 늘리지 않는다. 좌표 미등록 주유소도 전국 통계에 포함하고 지도 통계에서는 제외한다. 2026-11-02 사용자가 선택한 기준에 따라 오피넷은 최신 읽기 모델 중 `collected_at`이 이번 성공 수집 시각과 같은 가격만 집계한다. 이전 수집 가격·주유소·원본을 삭제하지 않으며, 이번 수집에서 확인되지 않은 가격을 새 통계에 포함하지 않는다. 고속도로도 해당 성공 수집에서 확인된 주유소만 사용한다.

`GET /v1/transport/fuel/statistics?scope=nationwide&product_code=B027`은 작은 일별 통계 테이블만 읽는다. scope는 nationwide, sido, sigungu, highways, highway, highway_direction이다. scope_key로 추이 범주를 지정한다. product_code=ALL은 같은 공개 세대의 모든 유종을 한 SQL snapshot에서 반환한다. items와 history에 product_code를 포함하며 선택 범주의 history는 30일이다. history의 minimum_price·maximum_price·cheapest_station은 해당 날짜에 저장된 값만 반환한다. 과거 값이 없으면 null이며 현재의 극값이나 주유소로 채우지 않는다. cheapest_stations와 ranking_complete는 선택 범주의 현재 세대에만 제공하고 나머지 범주는 빈 배열/false다. 이전 집계에 10곳 순위가 없으면 이미 알려진 cheapest_station과 minimum_price 한 곳은 유지하되 나머지 순위를 추정하지 않는다. 지역·노선 키는 문자열 배열의 JSON 표현이며 코드의 선행 0을 보존한다.

`GET /v1/transport/features/places`에 `include_fuel_statistics=true`와 완전한 bbox를 주면 현재 화면 전체의 유종별 통계를 함께 반환한다. 종류·출처·검색·유종 필터를 적용하며 마커 limit과 클러스터 수에는 영향을 받지 않는다. 최신 통계 가격만 한 SQL로 집계하고 세대별 최대 64개/10초 캐시로 반복 조회를 줄인다. 브라우저 기존 지도 요청/캐시를 재사용해 별도 왕복을 추가하지 않는다.

통계 작성은 500행 스트리밍/배치 저장으로 메모리를 제한한다. 원천별 PostgreSQL 트랜잭션 잠금으로 동시 발행을 직렬화한다. 통계 실패는 savepoint로 격리해 원본 수집 성공과 이전 통계 세대를 보존한다. 통계 페이지는 최신 수집보다 통계가 오래되었으면 반영 대기를 표시한다. 다음 정상 수집이 재시도한다.

관리 UI `/fuel`은 지도 범위 통계, `/fuel/statistics`는 30일 평균·최저·최고 그래프와 가격순 최대 10곳·주소 링크를 제공한다. 전체 유종이 기본이며 휘발유→경유→고급유→LPG→등유 순서의 표와 하나의 그래프를 보여 준다. 기존 요약 박스는 통계 페이지에서 제거하고 그래프를 먼저 둔다. 범위·유종·추이 범주는 같은 제어 행에 두며 모바일에서는 줄바꿈한다. 필터 요청 중에는 이전 범주의 지표를 숨긴다. 공식 EvilCharts Apache ECharts line 소스와 native custom series whisker를 사용하며, 날짜/수집 시각·평균/최저/최고·그 날짜 최저가 위치는 hover/터치/키보드 및 표로 확인한다. 날짜가 비면 실제 시간축의 선을 끊는다. 차트 엔진은 실제 유가 그래프가 필요할 때만 지연 적재하여 철도·해운 상세의 초기 경로에 추가하지 않는다. 공식 소스·MIT·설치 SHA와 접근성 변형은 admin frontend vendor/evilcharts-fuel.json에 기록한다.

배포 후 `python scripts/rebuild-fuel-statistics.py`를 backend 컨테이너 안에서 실행하면 원천별 마지막 정상 수집 시각으로 최신 통계를 초기화한다. 공급자를 재호출하지 않는다. 더 최신 통계와 이미 같은 시각·같은 가격 집합의 통계는 덮어쓰지 않는다. 오피넷의 현재 공개 세대가 이전 관측값을 포함한 구 모집단이면 같은 성공 원본으로 원자 정정한다. 정정 실패 시 savepoint가 기존 공개 세대를 보존하며 이전 날짜·세대의 영구 요약은 바꾸지 않는다. 특정 원천만 처리하려면 `--source opinet_browser` 또는 `--source krex_rest_area_fuel`을 지정한다. 이 스크립트의 오래된 지도 point 정리는 영구 지역 이력과 별개다. 정리를 금지한 운영 정정에서는 기존 `publish_fuel_statistics`만 호출하고 cleanup은 실행하지 않는다.

검증은 `backend/tests/test_fuel_statistics.py`와 admin의 `fuel-statistics.test.tsx`에서 가격/동률/보관/실패 격리를 확인한다. 격리 브라우저는 `E2E_FUEL_STATISTICS=true`, 실제 로그인/API/DB 검증은 `E2E_FUEL_STATISTICS_LIVE=true E2E_TRANSPORT_UI_PASSWORD=... E2E_BASE_URL=... npx playwright test e2e/fuel-statistics-live.spec.ts`로 실행한다. 실제 검증은 API 응답을 대체하지 않으며 조회와 로그인만 수행한다.

현재 범주 목록과 선택 범주의 이력은 한 SQL snapshot에서 읽어 동시 발행 시에도 세대가 일치한다. 지도 응답의 각 유종 `update_pending`은 현재 원본 수집이 통계보다 앞선 경우 true이며 캐시와 별도로 매 요청 계산한다. 같은 범위/유종의 추이 범주 변경은 선택 UI와 비교표를 유지해 키보드 포커스를 보존한다. 결측 날짜는 실제 날짜 간격을 유지하며 차트 선을 연결하지 않는다. 운영 브라우저 검증에 `E2E_FUEL_MAP_CAMERA=true`를 추가하면 실제 VWorld 지도 확대2회·키보드 이동에 따른 bbox 재조회까지 검증한다.

## 장기 추이

상태 갱신(2026-11-26, 소유자 요청 "지역 평균 등 통계는 수집 완료 시 저장, 긴 기간 가격 추이"): 일별 기록은 처음부터 영구 보존했지만
읽는 길이 30일 페이지뿐이었고, 그 행의 `metrics_json`은 가격순 10곳까지 담아(시군구 230곳·유종 4~5개면 하루 약 1MB) 몇 달·몇 년을
그대로 읽기에 무거웠다.

- **저장**: `fuel_statistics_history`(0049)는 일별 행과 같은 키에 평균·최저·최고·주유소 수·세대 시각·이름만 typed 열로 둔다.
  `publish_fuel_statistics`가 일별 행·지역 요약·공개 state와 **같은 transaction**에서 그날 행을 지우고 다시 넣는다(같은 날 재수집은
  그날 마지막 성공본으로 교체, 지난 날짜는 영구 보존). 하루의 첫 공개는 직전 공개 날짜를 일별 행(정본)에 다시 맞춘다 — 0049 배포 중
  옛 이미지가 migration 뒤에 공개한 날은 일별 행만 바뀌기 때문이다(이미 같으면 쓰지 않는다). 한 해 약 58만 행·약 180MB(행+기본키,
  하루 약 1,600행 기준; 일별 표는 같은 기간 약 0.7GB)다.
- **기존 자료**: 0049가 기존 일별 행의 `metrics_json`에서 31일 창씩 옮긴다. 평균·주유소 수가 숫자가 아니거나 0 이하인 행은 옮기지 않고,
  최저·최고가 없던 옛 행은 null로 둔다(채우지 않는다).
- **회당(하루 안) 지역 요약은 노출하지 않는다**: `fuel_region_summaries`는 성공 세대마다 시도·시군구 값을 영구 보존하지만 이력 API를
  두지 않았다. 오피넷 공개는 하루 3회(8시간 cron)뿐이라 하루 안 변화가 장기 추이에서 거의 보이지 않고, 같은 날 여러 세대를 섞으면
  "그날 마지막 정상 수집"이라는 일별 정의가 깨진다. 고속도로는 같은 표에 행이 없다. 필요해지면 그 표를 읽는 별도 API로 더한다.

`GET /v1/transport/fuel/statistics/history?scope=&scope_key=&product_code=&from=&to=&bucket=`:

- `scope`는 통계 페이지와 같다. `scope_key`는 페이지의 `items[].scope_key`(nationwide·highways는 생략하면 `all`, 그 밖은 필수 — 없으면 422).
  `product_code`는 유종 또는 `ALL`(유종별 점, 휘발유→경유→고급유→LPG→등유 순).
- `from`·`to`는 KST 날짜(포함). `to`가 없거나 공개 세대 날짜보다 늦으면 공개 세대 날짜로 낮춘다. `from`이 없으면 첫 기록일부터다.
  공개 state와 추이 행을 **한 SELECT**로 읽고 `day ≤ state.day`·`generated_at ≤ state.generated_at`인 행만 낸다(공개 전환과 섞이지 않고,
  아직 공개되지 않은 날짜는 보이지 않는다).
- `bucket`: `day`·`week`(ISO 주, 월요일 시작)·`month`·`auto`(기본). 유종 하나의 점은 최대 400개(일 약 13개월·주 약 7.7년·월 약 33년).
  점 수는 실제 기록 범위(첫 기록일 이후)로 센다. 지정한 bucket으로 400개를 넘으면 422(problem+json), `auto`는 400개 안에 드는 가장 작은
  단위를 고르고 응답 `bucket`에 적는다. `from`~`to`가 400개월을 넘거나 `from > to`도 422다.
- **버킷 값의 뜻(`average_method: mean_of_daily_averages`)**: 평균은 그 버킷에 기록이 있는 날짜들의 일별 평균을 **같은 비중**으로
  평균한다(주유소 수 가중 아님 — 날마다 모집단 크기가 달라도 하루 값이 같은 무게다). 최저·최고는 일별 최저의 최저·일별 최고의 최고(없던
  날은 빼고, 모두 없으면 null), `station_count`는 일별 주유소 수 평균(반올림), `generated_at`은 버킷 마지막 기록일의 세대, `first_day`·
  `last_day`·`day_count`는 실제 기록일이다. 빈 날짜·버킷은 만들지 않는다.
- 응답에는 weak ETag와 `Cache-Control: private, no-cache`가 붙고 `If-None-Match`가 같으면 304다. 공개 gateway(12301·12307)와 공개 유가
  BFF(`/api/public/fuel/statistics/history`), 관리 BFF 허용 목록에 이 경로 하나만 더했다.

관리 UI `/fuel/statistics`는 범위·유종 옆에 **기간**(30일·90일·1년·전체)을 둔다. 30일은 예전 그대로 페이지 응답의 이력(날짜별 최저가
주유소 포함)을 쓴다. 90일·1년은 페이지가 고른 범주(`history_scope_key`)와 공개 세대 KST 날짜(`to`)로 `bucket=day`, 전체는
`bucket=auto`를 읽어 같은 ECharts 차트·표로 보인다. 주·월 점은 점 간격(7일·31일)보다 먼 빈 기간에서만 선을 끊고, 넉 달 넘는 범위는
x축을 연.월로 쓴다. 장기 추이 실패는 그 자리에서만 알리고 현재 범주·순위 표는 그대로 둔다. 공개 유가 웹에는 통계 화면이 없어 이번에
더하지 않았다(gateway·BFF 경로는 열어 두었다).

## 통계 페이지 시군구 읽기 (2026-11-26)

**증상(운영 공개 GET, 2026-11-26)**: `/v1/transport/fuel/statistics?scope=sigungu`가 유종과 무관하게 1.7~3.4초였다. 응답이 없는 유종
(`product_code=ZZZZ`, 158바이트)도 2.6~3.0초라 응답 크기·Python이 아니라 SQL이다. 같은 요청의 시도는 0.15~0.27초, 고속도로·방향은
0.12~0.38초였다.

**원인**: 현재 범주 읽기(`fuel_current_keys` CTE와 본 SELECT의 현재 세대 가지)가 `(source, scope, day=공개일, product_code)`로 찾는데
기본키는 `(source, scope, scope_key, product_code, day)`라 day가 scope_key 뒤에 있다. PostgreSQL 18은 이를 기본키 skip scan으로 풀고
범주마다 색인을 다시 내려간다. 시군구는 범주가 230개이고 표의 약 90%라, 400일 합성 데이터(39만 행, PostgreSQL 18)에서 한 번에 Index
Searches 461·공유 버퍼 3,494(B027), 921·8,421(ALL), 응답 없는 유종도 231·1,765였다. 버퍼 하나하나가 작은 공유 캐시의 ARM에서는
무작위 읽기라 운영 시간이 여기서 난다고 본다(운영 EXPLAIN은 이 작업 권한 밖이라 직접 확인하지 못했다 — 배포 뒤 같은 공개 GET으로 확인).
시도(16범주)·고속도로는 같은 계획이라도 찾기 횟수가 적다. 기록이 쌓일수록 기본키 앞부분이 길어져 계속 나빠지는 구조다.

**수정(0050)**: `ix_fuel_statistics_daily_current (source, scope, day, product_code)`. 같은 문장(응답 바이트까지 동일, 회귀
`tests/test_fuel_statistics.py`)이 공개일 항목만 한 번 찾는다. 같은 400일 데이터에서 Index Searches 1, 공유 버퍼 361(B027)·916(ALL)·14(없는
유종), 계획 비용 2,042→21(없는 유종). 로컬 x86 서비스 시간은 sigungu B027 42.9→36.4ms, ALL 86.6→70.4ms(대부분 응답 조립). 회귀
`tests/test_fuel_statistics_history.py::test_postgres_page_reads_only_the_published_day_for_many_categories`가 PostgreSQL 계획에 이
인덱스와 "Index Searches ≤ 2"를 확인한다(인덱스를 지우면 실패). 측정 스크립트 `backend/tests/benchmarks/fuel_statistics_page.py`
(`--hold-snapshot`은 오래된 snapshot으로 죽은 행 정리를 막아 운영의 재공개 잔여 버전도 흉내 낸다 — 36일·하루 3회·죽은 행 2배에서도 예전
계획은 로컬 22ms라 죽은 행만으로는 운영 시간을 설명하지 못했다).

## 원본 가격의 품질

집계는 양수인 원본 가격을 보존하며 임의의 정상 가격 구간으로 잘라내지 않는다. 2026-10-21 운영 대조에서 EX `B00067` 사천(부산)주유소의 휘발유 가격은 저장값184, `raw_item_json.gasolinePrice`도 `184원`이었다(관측03:32:56 UTC). 공급자 이상값은 최저가·가격 차이·50L 절감액에 영향을 준다. 이를 집계나 provider 파서의 오류로 단정하거나1840원으로 자동 보정하지 않는다. 원천 정정 추적은 별도 백로그에 남긴다.


## 주유소 상세의 30일 관측

`GET /v1/transport/fuel/stations/{id}/price-history?source=opinet_browser&days=30`은 최대 720시간의 실제 저장 가격을 읽는다. API 기본값 7일은 기존 소비자와 호환하고 상한만 30일로 넓혔다. 브라우저는 30일을 명시하며 같은 창과 revision의 모든 cursor 페이지를 읽는다. revision 충돌 재시작·실패·미지원 원천을 성공이나 빈 정상 이력으로 바꾸지 않는다. 없는 날짜/유종을 생성하지 않고 원본·과거 집계를 재작성하거나 provider를 재호출하지 않는다.

상태 갱신(2026-11-24, 감사 T4-08·T4 deadline): 지도 상세 패널은 `include_latest=false`로 부른다. 패널은 `items`만 쓰므로 별도 현재 가격 조회를 생략하고 `latest`는 빈 배열이다(현재 가격이 없다는 뜻이 아니다). 생략하면 기본값 true로 이전 응답과 같다. 주유소 행(id·원천·자연키·상표)은 이력 조회의 첫 주유소 조회에서 함께 읽고 응답 조립 때 다시 조회하지 않는다. 이력 transaction은 `SET LOCAL statement_timeout`(`FUEL_PRICE_HISTORY_STATEMENT_TIMEOUT_MS`, 기본 3초)을 건다. 넘으면 연결을 바로 반환하고 500이 아니라 504 problem + `Retry-After: 5`로 끝내며 SQLSTATE·경로를 경고 로그로 남긴다. 503은 계속 '성공한 수집 이력 없음'과 `include_latest=true`에서 저장 유종 수 상한(64) 초과만 뜻한다. 화면은 504와 브라우저 30초 상한을 '가격 이력 조회가 제시간에 끝나지 않았습니다. 잠시 후 다시 조회해 주세요.'로 안내한다. `가격 이력 다시 조회` 버튼은 `Retry-After`초(최대 60초) 동안 남은 초를 보이며 비활성이고, 누르면 초점이 구역 제목으로 간다. 503은 수집 이력 부재로 안내한다.

현재 저장 가격은 제목 없이 한 줄로 표시하고 바로 아래에 30일 차트를 둔다. 폭이 좁으면 가격 행 안에서만 가로로 이동할 수 있다. 각 가격의 i 안내에 관측 시각과 7일 이전 관측 경고를 보존하며, 연락처·위치 근거 다음 마지막에 관측값 표를 둔다. 키보드 날짜 선택은 native Button으로 제공한다. 세부 검증과 현재 한계는 [30일 차트 구현 원장](reports/2026-11-13-fuel30-evilcharts.md)을 따른다.

## 시군구 가격 분포·주유소 상대 위치 (공개 유가 화면 전용, 2026-11-22)

공개 유가(`TRANSPORT_UI_MODE=fuel`, fuel-web) 화면에만 붙인다. 관리(transport) UI는 바뀌지 않는다
(`publicFuel` 조건에서만 렌더하고 `fuel-price-distribution.test.tsx`가 관리 화면 미노출을 확인한다).

- **화면 안 시군구**: `GET /v1/transport/features/places?...&include_viewport_sigungu=true`(공개 gateway의
  `/v1/transport/fuel/places`가 그대로 전달)는 `fuel_viewport_sigungu`(주유소 수 내림차순 최대 40곳)와
  `fuel_viewport_sigungu_total`을 더한다. 행정 경계가 아니라 **지금 화면 안에 실제로 있는 공개 세대 주유소**를
  시군구로 묶는다(지도 통계와 같은 모집단·같은 유종/검색/출처 필터). 경계 폴리곤 교차보다 싸고, 사용자가 보는
  주유소와 칩이 어긋나지 않는다. 요청하지 않은 소비자(관리 지도)의 응답에는 두 필드가 없다.
  범위 요약은 이 목록 전체가 아니라 **지역 칩 하나**만 보인다(2026-11-22 소유자 지시 "지역 목록은 선택한 곳만"):
  지역 이동에서 고른 시군구가 있으면 그것(지도를 옮겨도 다른 곳을 고르거나 해제할 때까지 유지, 화면 밖이면 주유소 수 없이 이름만),
  고르기 전에는 **지도 중심 시군구**(아래 "지도 중심 시군구"), 중심을 정하지 못하면 화면 안에서 주유소가 가장 많은
  시군구 1곳(서버 목록 1순위)(정본 `lib/fuel-price-distribution.ts` `displayedRegion`).
- **분포 API**: `GET /v1/transport/fuel/price-distribution?product_code=B027&sido_value=..&sigungu_value=..`
  또는 `&station_id=..`(그 주유소의 시군구 사용). 공개 세대(`fuel_statistics_points`+`fuel_statistics_states`)만 읽는다.
  응답: 시군구 `station_count·minimum/average/maximum_price`, `histogram`(1·2·5×10^k원 폭, 약 10구간, [start,end)),
  `quantiles`(0·10·…·100% 선형 보간 = `percentile_cont`), 시도·전국 최저/평균/최고, `generated_at`, `update_pending`,
  `minimum_sample`(3), `grade_rule`, 그리고 주유소면 `station.comparisons`(시군구·시도·전국별 가격 차이·백분위·등급).
  유종을 팔지 않거나 이번 세대에 가격이 없으면 `station.price=null`, `comparisons=[]`이다.
  시군구 표본이 3곳 미만이면 `sufficient=false` — 화면은 그래프 대신 안내 문구를 보이고 그 범위의 등급은 null이다.
- **등급 규칙(정본: `backend/app/services/fuel_price_distribution.py` `GRADE_RULE`)**:
  `percentile = 100 × (더 싼 곳 + 0.5 × 같은 가격 곳) / 전체`(중간 순위, 0에 가까울수록 쌈, 자기 자신 포함).
  `<10` A+ 제일싸요 · `<25` A 저렴해요 · `<40` B+ 조금 싸요 · `<60` B 평범해요 · `<75` C+ 조금 비싸요 ·
  `<90` C 비싸요 · 그 밖 D 제일 비싸요. 차이는 `가격 − 범위 평균`(원).
- **화면**: 대화상자 제목 "{시군구} {N}개 {유종} 값 통계", 부제 최저·평균·최고와 통계 세대 시각(KST).
  주황 선 = 낮은 가격부터 정렬한 가격 곡선(가로 0~100%), 회색 막대 = 가격 구간별 주유소 수(오른쪽 축).
  `분포(%)`는 막대를 백분율로, `전국 대비`는 전국 최저(파랑)·평균(초록)·최고(빨강) 점선을 더하고 가격축을 넓힌다.
  주유소 상세는 가격·시군구·시도·전국 등급 원과 평균 대비 차이를 보이고, 버튼으로 같은 그래프에 핀을 꽂아 연다.
  여러 유종을 파는 주유소는 가격 줄마다 그 유종의 시군구 등급 안내("A 저렴해요", 표본 부족이면 "비교 부족")를 붙인다.
  같은 한 번의 요청 응답 `station.product_grades`(파는 유종마다 같은 시군구·같은 필터 안 위치, 요청 유종 먼저, 한 SQL)에서 오며
  유종마다 따로 부르지 않는다. 옛 API(필드 없음)는 빈 목록으로 읽어 안내를 생략한다. PC(가로 1024px 이상)에서 상세는 지도
  오른쪽 위, 좁은 화면은 범위 요약 아래 오른쪽이다.
  화면 읽기용 요약 문장과 "가격 구간 표"가 그래프와 같은 내용을 준다. 차트(ECharts bar+line)는 대화상자에서만 지연 적재한다.
- **사전집계를 두지 않은 이유(측정)**: n150 전용 PostgreSQL 18에 합성 오피넷 11,500곳·가격 32,200행 한 세대를 공개하고
  30회 잰 값(`backend/tests/benchmarks/fuel_price_distribution.py`): 시군구 분포 median 16ms/p95 22ms, 주유소 분포+세 범위 백분위
  27/33ms, 화면 안 시군구 — 도시 화면 5/7ms, 전국 화면 65/90ms(같은 세대·같은 화면 10초 재사용 시 0.5ms). 전국 화면 목록은 처음
  가격 행 전체를 주유소와 조인해 182ms였고, 화면 안 주유소 id를 먼저 한 번씩 뽑는 형태로 바꿔 줄였다. 이 정도면 새 사전집계 테이블과
  갱신 배선의 정합성 비용이 이득보다 크다. 응답의 모든 SELECT는 처음 읽은 공개 세대(`generated_at`)에 고정해 발행과 겹쳐도 세대가 섞이지 않는다.

## 공개 세대 조인과 통계 (2026-11-23, places 504·가격 분포 수 초)

**증상(운영 odroid, release 90fe4500)**: 공개 유가 zoom 7 places에 유종 여럿 + 상표 + 셀프와 `include_viewport_sigungu=true`
(모바일 첫 화면)를 주면 30초 gateway 504(3/3). 가격 분포는 주유소 기준 7.5~10초, 시군구 기준 0.4~7.9초.
합성 데이터(한 세대·ANALYZE 직후)에서는 16~27ms라 재현되지 않았다.

**원인(읽기 전용 EXPLAIN·pg_stat_statements)**:
1. `fuel_statistics_points`는 1.56M 행·54세대(세대당 약 3만 행)이고 마지막 자동 ANALYZE(11-20)가 공개 세대(11-22)보다 앞섰다.
   `generated_at`의 MCV 52개가 표 전체를 덮어 **통계에 없는 새 세대는 "1행"으로 추정**된다(실제 11,671행). 새 세대는 늘
   공개 직후가 가장 많이 읽히므로 이 상태가 구조적으로 반복된다(자동 ANALYZE 문턱 10% = 약 5세대).
2. point→주유소 조인이 `station_key = CAST(fuel_stations.id AS VARCHAR)`라 주유소 기본키를 못 쓴다. 1행 추정 때문에 계획기가
   중첩 루프를 고르면 안쪽이 **point마다 fuel_stations 전체 Seq Scan**(1.2만 행×1.2만 행)이 된다.
   pg_stat_statements: 분포 시군구 SELECT 평균 13.8초(최대 34초, 39회), 필터 켠 화면 안 시군구 평균 4.4초(최대 10.6초),
   필터 없는 같은 문장도 평균 3.0초. 504 URL은 이 시군구 문장에서 막혔다(`include_viewport_sigungu=false`면 1~2초).

**수정**:
- `point_station_id`/`station_for_point`(`fuel_station_filters.py`): 오피넷 point 키를 `CASE WHEN source='opinet_browser'
  THEN station_key::integer END`로 정수화해 `fuel_stations.id`와 조인. 추정이 틀려도 안쪽이 기본키 조회라 비용이 point 수에
  비례한다. CASE가 원천을 먼저 보므로 고속도로 point(문자 키)는 정수 변환을 시도하지 않는다(오피넷 키는 `str(id)`로만 저장).
  운영 낡은 통계 그대로의 EXPLAIN ANALYZE(2026-11-23, 상수 세대·정수 조인): 필터 켠 화면 안 시군구 0.90초(예전 평균 4.4초·504),
  분포 전국 가격 0.54초. 같은 운영에서 세대를 InitPlan으로 넘기면 추정은 맞지만(4,505 vs 실제 5,532) 0047 없이는 기본키 skip scan
  (9.2초)과 차가운 fuel_stations Seq Scan(0.79초)을 골랐다 — 그래서 InitPlan과 0047을 함께 둔다.
- `fixed_generation`: 한 응답이 읽는 세대 시각을 상수 대신 값이 보이지 않는 InitPlan 매개변수로 넘긴다. 계획기는
  "세대 하나 = 전체 / 세대 수"로 추정하고 세대마다 행 수가 거의 같아 실제와 맞는다(통계 신선도와 무관). 읽는 세대는 상수와 똑같이
  고정된다. 공개 시 ANALYZE는 넣지 않았다(적대 리뷰: 공개 트랜잭션 안 ANALYZE는 SHARE UPDATE EXCLUSIVE를 commit까지 쥐어 수집기
  `lock_timeout=5s`와 부딪칠 수 있고 ARM에서 비싸다).
- 인덱스 0047 `ix_fuel_statistics_points_generation_product (source, generated_at, product_code)`(CREATE INDEX CONCURRENTLY):
  추정이 맞으면 계획기가 유종 조건 때문에 PostgreSQL 18 skip scan으로 기본키(source, station_key, product_code, generated_at)를
  골랐다. 운영 EXPLAIN ANALYZE에서 전국 B027 가격 읽기가 9.2초였다(기존 세대 인덱스에는 유종이 없다). 범위 통계 후보 CTE의
  운영 최대 104초(pg_stat_statements)도 같은 부류로 본다.
- 가격 분포: 세대·유종·필터별 전국 가격을 한 SELECT로 읽어 시도·시군구로 나눈 정렬 색인을 프로세스에 둔다(10분, 16개, 키별 single-flight). 분포·백분위·
  등급은 이 색인과 이분 탐색으로 계산한다(정의는 그대로: 중간 순위 백분위, `percentile_cont` 분위). 주유소 가격은 기본키 앞부분
  `(source, station_key)`로 읽고 세대는 코드에서 고른다.
- 시도 화면 이름 통일: 오피넷 원문 시도 이름이 같은 코드 안에서 짧은/정식으로 섞여 있다(서울특별시 코드 454행 "서울" + 5행 "서울특별시").
  `SIDO_DISPLAY_NAMES`(정식→짧은 이름) 하나로 지역 이동 목록·지도 중심·화면 안 시군구·분포 제목·지역 카드를 맞추고, 화면 안 시군구는
  이름이 아니라 코드로 묶는다(이름까지 묶어 한 시군구가 두 줄로 갈리던 것).

**회귀**: `tests/test_fuel_public_query_plans.py`가 낡은 통계 상태(지난 세대로 ANALYZE → ANALYZE 없이 새 세대 공개)를 만들고 실제
문장의 계획에 "중첩 루프 안쪽 fuel_stations 전체 읽기"와 "문자열 id 조인"이 없음, 고정 세대 추정이 실제 행 수의 1/3~3배임을 본다.
같은 상태에서 예전 문자열 조인 문장은 반드시 걸리는지(검출기 생존)와 추정 전제(상수 세대 추정 ≪ 실제)도 함께 확인한다. 같은 세대
시각의 고속도로(문자 키) point와 함께 실제로 실행하고, 모든 `fuel_*` 서비스에 문자열 id 조인이 없음을 소스에서 확인한다.
벤치: `backend/tests/benchmarks/fuel_public_places.py`(운영 모양: 1.19만 곳·53+1세대·낡은 통계, HTTP 경로 그대로).

## 지도 중심 시군구 (공개 유가 화면 전용, 2026-11-22)

- 소유자 지시: 지역 칩의 기본값은 "화면에서 주유소가 가장 많은 시군구"가 아니라 **지도 중심의 시군구**.
- **API(추가 전용)**: places에 `center_longitude`·`center_latitude`(둘 다 주거나 둘 다 생략, 하나만이면 422)를 주면
  `fuel_center_sigungu: {sido_value, sido_name, sigungu_value, sigungu_name, method:"nearest_station", distance_m} | null`을 더한다.
  주지 않은 소비자(관리 지도 등)의 응답에는 필드가 없다(바이트 불변, `test_fuel_center_sigungu.py`). 공개 gateway·BFF는
  places query를 그대로 넘기므로 **새 공개 경로·gateway 변경 없음**. migration 없음.
- **판정 = 근사**: 저장소에 시군구 경계가 없고, 주소 provider(VWorld·Kakao, `fuel_search_location`)는 외부 호출이라 지도를 옮길 때마다
  부르는 공개 경로에 쓰지 않는다. 그래서 **중심에서 가장 가까운 오피넷 주유소의 시군구**를 쓴다(모집단 = "지역 이동" 목록과 같은
  오피넷 주유소, 유종·필터와 무관). 시군구 경계 근처에서는 이웃 시군구가 나올 수 있다. 반경 약 33 km 안에 주유소가 없으면(바다)
  `null`이고 화면은 예전 규칙(주유소가 가장 많은 시군구)으로 되돌아간다. 옛 API(필드 없음)도 같은 대체 경로라 배포 순서에 안전하다.
- **검색**: 공간 인덱스(PostGIS·KNN)가 없어 `ix_fuel_stations_map_coordinates`(longitude, latitude) B-tree로 중심 주변 상자
  (위도 반경 0.02° → 0.08° → 0.3°, 경도 폭은 ÷cos 위도)를 읽고 평면 거리순 1곳을 고른다. 상자에 내접한 원 안의 결과만 받아
  "상자 밖이 더 가깝다"를 배제한다(정본 `backend/app/services/fuel_center_sigungu.py`). 같은 10 m 격자 중심은 60초 재사용.
- **화면**: 중심은 조회 범위(정밀도 격자로 바깥 반올림한 범위)의 가운데라 실제 중심과 반 칸 이내이고, 범위에서만 나오므로
  요청 수·응답 캐시 키가 늘지 않는다. 지도가 첫 이동을 알리기 전 기본 범위(124~132, 32~39)는 카메라 중심과 대칭이 아니라
  묻지 않는다. 칩 그룹 이름은 근거를 알린다: "지도 중심 지역 가격 통계" / 대체 경로 "지도 대표 지역 가격 통계" / 고른 곳 "선택한 지역 가격 통계".
- **측정(n150, PostgreSQL 18 tmpfs, 합성 오피넷 11,500곳, 30회, 매 호출 캐시 비움)**:
무작위 육지 중심 median 1.3 ms · p95 2.6 ms · max 3.7 ms, 바다(상자 3개 모두 비어 null) median 3.5 ms · p95 3.6 ms,
  같은 격자 재요청(캐시) 0.0 ms. 계획은 두 상자 모두 `Bitmap Index Scan on ix_fuel_stations_map_coordinates`
  (반경 0.02° 실행 0.23 ms·버퍼 5, 0.3° 실행 1.18 ms·후보 374행 top-N). 같은 실행의 기존 경로 비교: 화면 안 시군구(전국) median 63.6 ms,
  시군구 분포 16.2 ms — 중심 판정은 places 응답 시간에 한 자릿수 ms만 더한다. (`tests/benchmarks/fuel_price_distribution.py`)

## 지역 이동·주유소 필터 (공개 유가 화면 전용, 2026-11-22)

- **맨 위 줄(2026-11-22 개편)**: 범위 요약 맨 위 한 줄에 지역 이동 아이콘 버튼(글자 없음, 접근성 이름·툴팁 "지역 이동")과
  유종·필터 선택 하나만 둔다. "지도 범위" 제목 글씨는 없다(영역 이름 "현재 지도 범위 유가 통계"는 `aria-label`로만 남는다).
  따로 있던 "필터" 버튼과 오른쪽 서랍은 없앴고, 그 내용(유종 여럿, 지도 최저가, 주유소 조건·품질인증, 상표·전체 선택, 초기화)은
  유종·필터 트리거가 여는 한 팝오버(체크박스 묶음, 모달 초점 가둠, 닫으면 트리거로 초점 복귀)에 들어 있다. 초기화는 유종과 필터를 함께 되돌린다.
  트리거 접근성 이름은 "유종·필터: {유종}, 조건 N개 적용 중"(N은 실제로 서버에 보내는 조건 수)이다.
- **가격 상태 아이콘(2026-11-23)**: 유종·필터 오른쪽의 아이콘 하나가 예전 "오래됨" 글자와 "업데이트" 버튼(지도 왼쪽 아래 업데이트
  아이콘 포함)을 대신한다. 가격이 오래되면 빨간 시계(!)이고, 업데이트할 수 있으면 눌러 지도에 보이는 주유소(1~9곳) 가격을 갱신한다.
  최신이면 회색 시계, 누를 수 없으면(최신·필터 사용 중·보이는 주유소가 1~9곳이 아님·이 실행에 갱신 경로 없음) `aria-disabled`인
  포커스 가능한 비활성 단추로 접근 이름과 툴팁(터치는 누르면 열림)에 이유를 쓴다. 툴팁에는 늘 마지막 가격 갱신 시각(KST)이 있다.
  그래서 가격이 최신일 때 보이는 주유소 9곳 이하를 다시 갱신하던 지도 위 업데이트 버튼은 없어졌다(개별 주유소 상세의 업데이트는 그대로).
  신선도는 전역 값이라 필터·유종을 바꿔 다시 조회하는 동안에도 마지막으로 받은 값을 유지한다. 아직 한 번도 받지 못했으면
  "가격 상태 확인 중"(조회 중)·"가격 상태 확인 못 함"(실패)으로 말하고 "최신"이라 하지 않는다. 조회 중·실패로 범위를 모르면
  이유도 "1~9곳" 대신 "불러오는 중"·"불러오지 못함"이다. 가격이 오래되면 숨김 status 문구("가격이 오래됐습니다")로 알린다.
- **장소 정보 영역(2026-11-23)**: 가격 상태 줄을 맨 위 줄로 합치고 유종마다 이름·평균·최저를 한 줄로 줄였다(지역 칩은 누르는 크기 44px 유지).
  사용자가 고른 지역 칩은 파랑(brand)으로 채워 자동(지도 중심) 칩과 구별하고, 그 칩의 통계 대화상자와 "지역 이동" 대화상자(확인 버튼 옆,
  고른 지역이 있을 때만)에 "해제"가 있어 누르면 자동 지역으로 돌아간다.
- **지역 이동**: 맨 위 지역 아이콘 → "지역 이동" 대화상자(시/도 | 구/군/시 두 열, 지금 보이는 지역 칩의 시군구가 선택된 채 열림. 칩이 없으면(places 실패·대기) 지금 지도 중심을 담는 시군구, 없으면 가장 가까운 시군구).
  확인하면 그 시군구가 범위 요약의 지역 칩(하나)이 되고, 칩 옆 해제 버튼으로 자동 표시(화면 대표 시군구)로 되돌린다.
  확인 버튼 이름이 고른 지역("충북 옥천군")이며 누르면 그 시군구 주유소 좌표 범위로 지도를 맞춘다(최대 줌 14).
  목록은 `GET /v1/transport/fuel/area-catalog`(오피넷 주유소의 시도·시군구 코드와 좌표, 20곳 이상은 경·위도 2~98% 분위로 자른 범위,
  10분 캐시)다. 행정 경계 데이터는 쓰지 않는다.
- **필터(서버 적용)**: places·price-distribution query `brands`(SKE,GSC,HDO,SOL,ALT=RTO+RTE,NHO,RTX,NCO,SKG,E1G,ETC=그 밖·미제공),
  `open_24h`, `self_only`, `carwash`, `maintenance`, `cvs`, `kpetro`, `near_min`(10~200원 단계). 정본은
  `backend/app/services/fuel_station_filters.py`. 근거 필드는 오피넷 지도 화면 응답의 typed 컬럼(`SEL24_YN`, `SELF_DIV_CD`, `CWSH_YN`,
  `MAINT_YN`, `CVS_YN`, `KPETRO_YN`, `POLL_DIV_CO/CD`)뿐이다. 마커·묶음·개수(`kind_totals`)·범위 통계·지역 카드·시군구 칩·
  시군구 가격 분포가 같은 조건을 쓴다. 필터가 켜지면 지역 카드는 사전집계 대신 같은 공개 세대 point를 필터 조건으로 다시 묶는다.
- **지도 최저가 ~N원**: 지금 화면(다른 필터 적용) 공개 세대에서 고른 유종 최저가 + N원 이하인 주유소만. 유종 하나일 때만 쓸 수 있고
  (그 밖은 422), 화면이 없는 가격 분포에는 적용하지 않는다(응답 `filters_applied`에 적용한 필터 이름).
- **제공하지 않는 필터**: 직영(직영/자영 구분 필드가 원천에 없다 — 상호명 추정 금지), 면세유 판매·화물차 우대(주유소 단위 필드 없음),
  믿음·스마트·'직영·믿음·스마트' 묶음(소유자 지시로 구분하지 않음). 테마(LIGHT/DARK/SYSTEM)는 소유자 지시로 두지 않는다.
- 상표 아이콘은 이미 저장소에 있는 오피넷 원본 아이콘(`public/fuel-brands/README.md` 출처)만 쓴다. LPG 충전 전용 상표(SK가스·E1)는
  LPG가 아닌 유종을 고르면 비활성이다. 필터는 브라우저 `localStorage`(`transport.public-fuel.filters`)에 저장한다.

## 이전 세대 정리 (2026-11-23, FUEL-PRUNE-BACKLOG-20261123)

**증상(운영 odroid, 읽기 전용)**: `fuel_statistics_points` 오피넷 53세대(1,558,120행)·고속도로 1세대, 461 MB. 가장 오래된 세대(10-24)만
일부(20,198행) 지워진 상태였고 표의 누적 삭제는 28,512행, 자동 VACUUM 기록 없음.

**원인**: 정리는 수집 뒤 `cleanup_fuel_statistics`(15초 예산)가 `prune_fuel_statistics`를 반복했다. 한 배치는 키 2,000개를 SELECT한 뒤
`(source, station_key, product_code, generated_at) IN ((...) × 2,000)`(매개변수 8,000개) DELETE로 다시 보냈다. 이 문장의 계획만 운영에서
3.2초였고(행 튜플 IN이 기본키 탐색 2,000개의 BitmapOr가 된다. `pg_stat_statements`는 계획 시간을 세지 않아 실행 평균 0.5초로만 보였다)
SQLAlchemy 컴파일·asyncpg prepare까지 더해 첫 배치가 예산을 다 썼다. 11-17 통계 초기화 뒤 오피넷 정리 SELECT·DELETE가 수집마다 정확히
1회(각 2,000행)였다 — 세대 하나 약 3만 행을 수집마다 2,000행으로 따라갈 수 없다.

**수정**: 후보 선택과 삭제를 한 문장(`DELETE … WHERE (키) IN (SELECT … ORDER BY generated_at LIMIT 5000 FOR UPDATE SKIP LOCKED)`)으로.
운영 EXPLAIN: 계획 88 ms(예전 3,217 ms), 세대 색인 순서 읽기 + 기본키 중첩 루프, 후보 5,000행 읽기 0.27초. 매개변수는 행 수와 무관하게
원천·한도 몇 개다. 배치마다 commit하므로 잠금은 짧고, 공개 세대·준비 중 세대(공개 시각 이후)는 후보가 아니어서 수집 쓰기와 행이 겹치지
않는다. 수집 한 번의 정리 예산은 60초(배치 사이에서만 확인, 한 배치는 수집 엔진 `statement_timeout` 60초보다 훨씬 짧다). 0047 인덱스는
정리에 필요 없다(기존 `(source, generated_at)` 색인이 순서를 준다).

**따라잡기**: 자동 정리만으로도 수집 몇 번 안에 줄어든다. 즉시 줄이려면 backend 컨테이너에서
`python scripts/prune-fuel-statistics.py --source opinet_browser --budget-seconds 1800`(배치·commit 동일, 수집과 동시 실행 가능, 전후 세대·행
수 출력). 지운 공간은 자동 VACUUM 뒤 재사용되며 파일 크기는 줄지 않는다(VACUUM FULL은 표 잠금이라 하지 않는다).

