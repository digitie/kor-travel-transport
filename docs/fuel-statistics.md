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

## 원본 가격의 품질

집계는 양수인 원본 가격을 보존하며 임의의 정상 가격 구간으로 잘라내지 않는다. 2026-10-21 운영 대조에서 EX `B00067` 사천(부산)주유소의 휘발유 가격은 저장값184, `raw_item_json.gasolinePrice`도 `184원`이었다(관측03:32:56 UTC). 공급자 이상값은 최저가·가격 차이·50L 절감액에 영향을 준다. 이를 집계나 provider 파서의 오류로 단정하거나1840원으로 자동 보정하지 않는다. 원천 정정 추적은 별도 백로그에 남긴다.


## 주유소 상세의 30일 관측

`GET /v1/transport/fuel/stations/{id}/price-history?source=opinet_browser&days=30`은 최대 720시간의 실제 저장 가격을 읽는다. API 기본값 7일은 기존 소비자와 호환하고 상한만 30일로 넓혔다. 브라우저는 30일을 명시하며 같은 창과 revision의 모든 cursor 페이지를 읽는다. revision 충돌 재시작·실패·미지원 원천을 성공이나 빈 정상 이력으로 바꾸지 않는다. 없는 날짜/유종을 생성하지 않고 원본·과거 집계를 재작성하거나 provider를 재호출하지 않는다.

현재 저장 가격은 제목 없이 한 줄로 표시하고 바로 아래에 30일 차트를 둔다. 폭이 좁으면 가격 행 안에서만 가로로 이동할 수 있다. 각 가격의 i 안내에 관측 시각과 7일 이전 관측 경고를 보존하며, 연락처·위치 근거 다음 마지막에 관측값 표를 둔다. 키보드 날짜 선택은 native Button으로 제공한다. 세부 검증과 현재 한계는 [30일 차트 구현 원장](reports/2026-11-13-fuel30-evilcharts.md)을 따른다.

## 시군구 가격 분포·주유소 상대 위치 (공개 유가 화면 전용, 2026-11-22)

공개 유가(`TRANSPORT_UI_MODE=fuel`, fuel-web) 화면에만 붙인다. 관리(transport) UI는 바뀌지 않는다
(`publicFuel` 조건에서만 렌더하고 `fuel-price-distribution.test.tsx`가 관리 화면 미노출을 확인한다).

- **화면 안 시군구**: `GET /v1/transport/features/places?...&include_viewport_sigungu=true`(공개 gateway의
  `/v1/transport/fuel/places`가 그대로 전달)는 `fuel_viewport_sigungu`(주유소 수 내림차순 최대 40곳)와
  `fuel_viewport_sigungu_total`을 더한다. 행정 경계가 아니라 **지금 화면 안에 실제로 있는 공개 세대 주유소**를
  시군구로 묶는다(지도 통계와 같은 모집단·같은 유종/검색/출처 필터). 경계 폴리곤 교차보다 싸고, 사용자가 보는
  주유소와 칩이 어긋나지 않는다. 요청하지 않은 소비자(관리 지도)의 응답에는 두 필드가 없다.
  범위 요약은 5곳 칩 + `+N`(더 보기 시 최대 40곳, 그 밖은 확대 안내)을 보인다.
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
  화면 읽기용 요약 문장과 "가격 구간 표"가 그래프와 같은 내용을 준다. 차트(ECharts bar+line)는 대화상자에서만 지연 적재한다.
- **사전집계를 두지 않은 이유(측정)**: n150 전용 PostgreSQL 18에 합성 오피넷 11,500곳·가격 32,200행 한 세대를 공개하고
  30회 잰 값(`backend/tests/benchmarks/fuel_price_distribution.py`): 시군구 분포 median 16ms/p95 22ms, 주유소 분포+세 범위 백분위
  27/33ms, 화면 안 시군구 — 도시 화면 5/7ms, 전국 화면 65/90ms(같은 세대·같은 화면 10초 재사용 시 0.5ms). 전국 화면 목록은 처음
  가격 행 전체를 주유소와 조인해 182ms였고, 화면 안 주유소 id를 먼저 한 번씩 뽑는 형태로 바꿔 줄였다. 이 정도면 새 사전집계 테이블과
  갱신 배선의 정합성 비용이 이득보다 크다. 응답의 모든 SELECT는 처음 읽은 공개 세대(`generated_at`)에 고정해 발행과 겹쳐도 세대가 섞이지 않는다.

## 지역 이동·주유소 필터 (공개 유가 화면 전용, 2026-11-22)

- **지역 이동**: 범위 요약의 "지역" 버튼 → "이동하세요…" 대화상자(시/도 | 구/군/시 두 열, 지금 화면의 첫 시군구가 선택된 채 열림).
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
