# 유가 통계

유가 원본 수집이 정상 종료하면 같은 트랜잭션에서 최신 통계를 발행한다. 오피넷은 전국·시도·시군구별, 한국도로공사는 고속도로 전체·노선별·노선/방향별로 나눈다. 두 원천의 주유소를 합산하지 않아 중복 집계를 피한다. 방향은 공급자가 제공한 방향명을 그대로 사용한다.

`fuel_statistics_states`는 원천별 성공 발행 시각, `fuel_statistics_points`는 지도 집계용 최신 가격, `fuel_statistics_daily`는 KST 일별 마지막 정상 수집의 범주별 지표를 저장한다. 오늘 포함 7일을 유지하며 같은 날 재수집은 교체한다. 과거 기록을 추정하거나 빈 날짜를 보간하지 않는다. 설치 전 이력을 자동 전수 스캔하지 않으며 최초 발행 이후 일별 기록을 축적한다.

평균은 유효한 양수 가격의 주유소별 단순 평균이다. 유종별 개수·평균·최저·최고·최고-최저 차이·모표준편차·50L 평균 대비 최저가 절감액을 제공한다. 최저가 동률은 안정적으로 한 주유소를 대표 표시하고 동률 개수도 제공한다. 좌표 미등록 주유소도 전국 통계에 포함하고 지도 통계에서는 제외한다. 오피넷 최신 가격은 기존 지도와 같은 최신 읽기 모델을 사용하고, 고속도로는 해당 성공 수집에서 확인된 주유소만 사용한다.

`GET /v1/transport/fuel/statistics?scope=nationwide&product_code=B027`은 작은 일별 통계 테이블만 읽는다. scope는 nationwide, sido, sigungu, highways, highway, highway_direction이다. scope_key로 추이 범주를 지정한다. 지역·노선 키는 문자열 배열의 JSON 표현이며 코드의 선행 0을 보존한다.

`GET /v1/transport/features/places`에 `include_fuel_statistics=true`와 완전한 bbox를 주면 현재 화면 전체의 유종별 통계를 함께 반환한다. 종류·출처·검색·유종 필터를 적용하며 마커 limit과 클러스터 수에는 영향을 받지 않는다. 최신 통계 가격만 한 SQL로 집계하고 세대별 최대 64개/10초 캐시로 반복 조회를 줄인다. 브라우저 기존 지도 요청/캐시를 재사용해 별도 왕복을 추가하지 않는다.

통계 작성은 500행 스트리밍/배치 저장으로 메모리를 제한한다. 원천별 PostgreSQL 트랜잭션 잠금으로 동시 발행을 직렬화한다. 통계 실패는 savepoint로 격리해 원본 수집 성공과 이전 통계 세대를 보존한다. 통계 페이지는 최신 수집보다 통계가 오래되었으면 반영 대기를 표시한다. 다음 정상 수집이 재시도한다.

관리 UI `/fuel`은 지도 범위 통계, `/fuel/statistics`는 범주 비교표·7일 추이·최저가 주유소를 제공한다. 필터 요청 중에는 이전 범주의 지표를 숨기며 차트는 별도 라이브러리 없이 SVG와 접근 가능한 표로 표시한다.

배포 후 `python scripts/rebuild-fuel-statistics.py`를 backend 컨테이너 안에서 실행하면 원천별 마지막 정상 수집 시각으로 최신 통계를 초기화한다. DB 마이그레이션 이후 실행하며 공급자를 재호출하지 않는다. 이미 같은 시각 또는 더 최신 통계가 있으면 덮어쓰지 않는다. 특정 원천만 처리하려면 `--source opinet_browser` 또는 `--source krex_rest_area_fuel`을 지정한다.

검증은 `backend/tests/test_fuel_statistics.py`와 admin의 `fuel-statistics.test.tsx`에서 가격/동률/보관/실패 격리를 확인한다. 격리 브라우저는 `E2E_FUEL_STATISTICS=true`, 실제 로그인/API/DB 검증은 `E2E_FUEL_STATISTICS_LIVE=true E2E_TRANSPORT_UI_PASSWORD=... E2E_BASE_URL=... npx playwright test e2e/fuel-statistics-live.spec.ts`로 실행한다. 실제 검증은 API 응답을 대체하지 않으며 조회와 로그인만 수행한다.
