# 내부 service export — 생산자 운영 계약

`/v1/service/exports/*`(kor-travel-map용 내부 export)의 생산자 쪽 세부다. 왜 이런 구조인지는
[ADR-013](../adr/013-internal-service-exports-for-map.md)이, 기계 계약은 `docs/openapi.json`(CI `scripts/export_openapi.py --check`)이
정본이다. 다른 문서가 이미 정본인 것은 여기서 되풀이하지 않고 링크한다.

| 주제 | 정본 |
|---|---|
| 503 사유 `code` 사전·`Retry-After` 힌트 표·소비자 처리("나이 기준 혼합")·로그 줄 | [Map 인계 "503 사유 code와 Retry-After"](../map-service-exports-handoff.md#503-사유-code와-retry-after-2026-11-24) |
| 휴게소 먹거리 item 필드 | [Map 인계 "휴게소 먹거리 T1"](../map-service-exports-handoff.md#휴게소-먹거리-t1-rest-area-food-2026-11-27) |
| T1 전송 구현(gzip·snapshot 상한·본문 구성 slot·rollback·측정) | [성능 기준 "Map T1 export 본문 구성과 연결 반납"](performance.md#map-t1-export-본문-구성과-연결-반납-2026-11-24) |
| T2/T3 고정 snapshot 계약 | [Map 인계](../map-service-exports-handoff.md), [T2/T3 설계](../design/map-current-reference-exports.md) |
| T4 가격 이력 | [가격 이력 계약](../map-service-price-history.md) |
| 503 상태 코드 변경의 배포 보류(해제됨) | [배포 런북](../runbooks/deployment.md#배포-보류해제됨-export-503-상태-코드-변경2026-11-24-pr-277) |

## 1. 표면과 인증 (ADR-013 결정 1·2)

- T1 경로: `GET /v1/service/exports/{fuel-stations,rest-areas,rest-area-fuel-prices,highway-incidents/active,airports,rest-area-food}`.
  모양은 kor-travel-concierge export와 같은 무-envelope `{items, next_cursor, has_more}` + `collection`(근거 수집의 마지막
  성공·실패·stale) + `generated_at`. cursor는 불투명 문자열이고 각 item은 안정 자연키와 원본 provider 행(`raw`)을 담는다.
- 인증: 헤더 `X-Kor-Travel-Transport-Service-Token`(설정 `TRANSPORT_SERVICE_EXPORT_TOKEN`, 32자 이상, 상수 시간 비교)
  **그리고** 접속한 peer 주소(`request.client.host`)가 `SERVICE_EXPORT_ALLOWED_CLIENTS_CSV`(CIDR, 기본 `127.0.0.1/32,::1/128`)
  안이어야 한다. 하나라도 어긋나면 404다. 토큰이 비면 export 전체가 404다.
- `Host` 헤더는 호출자가 정하는 값이라 쓰지 않는다(2026-10-02 리뷰 T1: `curl -H 'Host: 127.0.0.1' http://192.168.1.14:14001/...`가
  통과했다). backend는 host network라 peer 주소가 실제 접속 주소다.
- 공개 표면은 이 경로를 전달하지 않는다 — 웹 프록시(`frontend/src/app/api/backend/[...path]`)와 관리자 API gateway
  (`deploy/transport-admin/api-gateway.conf.template`)는 경로 allowlist에 없고 토큰 헤더도 넘기지 않는다.
- standalone 개발에서 Map이 docker bridge(`host.docker.internal`)로 부르면 그 bridge 대역을 `SERVICE_EXPORT_ALLOWED_CLIENTS_CSV`에
  명시해 연다. Odroid 운영의 allow-list 규칙은 [ADR-014](../adr/014-odroid-host-and-deploy-host-flag.md) 결정 4다.
- 공항(결정 5): 주차 수집 여부와 무관하게 `python-krairport-api` 번들의 운영 공항 전체(포항경주 KPO 포함)를 ICAO·소재지·좌표와
  함께 내고, 주차 데이터 보유 여부는 `has_parking_data`로 표시한다.

## 2. 현재 집합과 신선도 (ADR-013 결정 3)

| dataset | 200을 막는 조건(503) | stale 기준 | 현재 집합 |
|---|---|---|---|
| `fuel-stations` | 이력 없음, 마지막 **성공**이 기준 초과 | 27.5시간(2026-11-24 전 24시간, 4절) | 마지막 성공보다 3일 이전까지 재관측된 행 |
| `rest-areas` | 같음 | 3일 | 같음 |
| `rest-area-fuel-prices` | 같음 | 12시간 | 같음 |
| `rest-area-food` | 같음 | 3일(`REFERENCE_STALE_AFTER`) | 마지막 성공 수집이 본 행 그대로(6절) |
| `highway-incidents/active` | 이력 없음, 마지막 **시도** 실패, 30분 초과 | 30분 | 마지막 성공 수집이 본 사건 전체, 페이지 없음 |

- 근거 수집이 꺼진 dataset(`REST_AREA_COLLECTION_ENABLED=false`)도 이력이 없으니 503이다 — 빈 200을 주면 소비자가 전량 삭제로 읽는다.
- 200 본문의 `collection.failed`·`stale`은 "이 집합을 낼 수 없다"는 503 사유라 200이면 언제나 `false`다. 마지막 시도의 실패
  사실은 가산 필드 `collection.last_attempt_failed`로만 알리고 오류 문구는 내지 않는다.
- 상태 행과 데이터 행은 한 요청 안에서 REPEATABLE READ 한 snapshot으로 읽는다.
- 참조 데이터의 3일 재관측 여유는 일부 지역 실패 한 번으로 행이 사라지지 않게 하기 위함이다.
- 페이지는 요청마다 따로 판정한다. 페이지 도중 stale 기준을 넘거나 돌발 수집이 실패하면 다음 페이지가 503이고, 소비자는
  그 run 전체를 실패로 다룬다(참조 데이터에서 실패한 시도는 집합을 바꾸지 않으므로 페이지 판정에 영향이 없다).
- 돌발 수집은 상태의 `last_success_at`을 재관측 행의 `collected_at`과 같은 값으로 남겨, export가 "마지막 성공 수집의 활성
  집합"을 정확히 고르게 한다.

## 3. 참조 데이터는 마지막 성공의 나이로 판정한다 (2026-10-23 개정)

- **문제**: 옛 결정 3은 "마지막 수집이 실패했으면 503"이었다. 유가 수집이 실패하면 `next_due_at`이 약 8시간 뒤로 밀리고,
  그동안 `last_error`가 남아 `fuel-stations`가 계속 503이었다. odroid에서 브라우저 수집이 시간 상한(당시 7,200초) 근처에서
  연달아 실패하자 Map 적재가 약 32시간 끊겼다 — 그동안 저장된 집합은 마지막 성공 그대로 멀쩡했다.
- **결정**: 참조 데이터(주유소·휴게소·휴게소 유가)는 마지막 성공이 stale 기준 안이면 그 뒤 시도의 실패와 무관하게 마지막 성공
  수집의 집합을 200으로 낸다. 기준을 넘으면 예전처럼 503이다. `collection.failed`는 "실패 때문에 집합을 낼 수 없다"는 뜻으로
  좁혔고(참조 데이터에서는 언제나 false), 마지막 시도의 사실은 `collection.last_attempt_failed`로 낸다. 돌발은 바꾸지 않았다.
- **전제**: 실패한 시도는 마지막 성공의 집합을 바꾸지 않는다. 유가·휴게소 수집은 저장 실패·빈 집합·provider 오류 모두 저장
  transaction을 되돌리고 `last_success_at`을 옮기지 않는다(회귀 테스트
  `test_fuel_station_export_grace_follows_a_real_failed_collection`, `test_an_empty_rest_area_collection_fails_so_the_export_goes_503`).
- **소비자(Map)**: Map은 `last_success_at` 없음·`failed`·`stale`만 다시 확인하고(`require_current_collection`) 모르는 필드는
  읽지 않으므로 바뀌는 것이 없다 — 유예 구간의 200을 그대로 적재한다.
- **공개 지도 API와의 차이**: 공개 유가 API의 신선도(`fuel_read_model_freshness`)는 화면 표시용이라 여전히 마지막 시도 실패를
  stale로 표시한다. export는 "집합을 낼 수 있는가"를, 공개 API는 "사용자에게 오래됐을 수 있다고 알릴 것인가"를 판정하므로
  의도적으로 다르다.

## 4. 유가 수집 주기와 export 유예

- **주기(2026-10-23 소유자 결정)**: 성공한 유가 수집의 다음 예정은 수집 **완료** + 8시간이었고 schedule은 8시간 정각마다라,
  수집이 1~2시간 걸리는 동안 다음 tick을 늘 건너뛰어 실제 주기가 16시간이었다. 그러면 성공 뒤 첫 시도의 실패만으로 다음
  시도가 24시간 유예를 넘겼다. 그래서 다음 예정을 수집 **시작** + 8시간(tick마다 다른 시작 지연을 덮도록 15분 당김,
  `FUEL_NEXT_DUE_START_SLACK`)으로 바꿔 8시간 tick마다 돈다.
- **2026-11-24 정정**: 처음 기록은 "실패 경로(실패 시각 + 8시간)는 그대로다"였지만, 실패 경로도 claim 때 확정한 **시작** 기준
  예약을 보존한다(`_mark_fuel_failure`, `transport_collection.py`). 그래서 실패한 tick 뒤의 tick도 건너뛰지 않고 8시간마다 돈다
  (`test_eight_hourly_ticks_keep_one_failure_inside_the_export_grace`).
- **남은 틈**: (1) 유예는 첫 성공의 **완료** 시각 + 24시간에 끝나므로, 세 번째 시도가 첫 성공보다 오래 걸리면 그 차이만큼(최대
  약 2시간) 503이 났다 — 2026-11-24 유예 연장으로 닫았다(아래). (2) 연속 실패 — 27.5시간 유예와 시작 기준 8시간 tick에서는
  **연속 두 번 실패까지 200**이고(세 번째 tick이 시작 + 24시간에 시작해 상한 3.5시간 안에 끝나면 유예 안), **세 번째 연속
  실패부터 503**이다.
- **하루 3회 상한**: 오피넷 호출은 하루 3회가 소유자 제한이고 Dagster에서는 8시간 tick(KST 00·08·16시)으로 지킨다. 다만 15분
  당김 때문에 tick의 시작 지연이 줄어드는 날에는 **연속 24시간 창**에 네 번째 시작이 최대 45분 안쪽으로 들어올 수 있다
  (00:45→08:30→16:15→다음 00:00). tick 없는 in-process scheduler는 성공 예약에만 당긴 폭을 되돌리며, 대기와 재기동 후 수집
  진입이 같은 유효 예정 시각을 사용해 시작 간격 8시간 이상을 지킨다. 실패·진행 중 claim·과거 완료 기준 예약에는 추가 15분을
  적용하지 않는다. 경보에 따른 추가 run을 두지 않는 이유는 [Dagster 복구 런북](../runbooks/dagster-recovery.md)에 있다.
- **export 유예(2026-11-24, 정책 변경)**: `REFERENCE_STALE_AFTER[opinet] = FUEL_STALE_AFTER(24시간) +
  FUEL_FETCH_TIMEOUT_SECONDS(3.5시간)` = 27.5시간. 위 틈 (1)을 닫는다. 공개 화면의 유가 신선도(`FUEL_STALE_AFTER` 24시간)는
  그대로이고, 27.5시간은 Map Valkey 데이터셋 max_age(48시간)보다 작다. 소비자에게는 "마지막 성공 뒤 24~27.5시간 구간의 주유소
  집합이 503 대신 200(`collection.last_attempt_failed=true`)"으로 보인다. Map ADR-106의 "24시간" 서술은 Map 쪽 후속 정정 대상이다.

## 5. 돌발 활성 집합의 0건 (2026-11-24 개정, INCIDENT-EMPTY-SET-20261124)

KREX 실시간 문자정보가 `count=0`·빈 목록을 정상 응답으로 돌려준 수집을 성공으로 받아 활성 집합 export가 0건 집합 200을
37회 냈다(직전 167~351건). 전국 활성 돌발·공사 0건은 상류 이상으로 본다: 돌발은 완결 증거가 있어도 직전 성공 건수와
비교하고, 0건은 한 번 다시 조회해도 비면 실패로 기록해 마지막 성공 집합을 유지한다(export 503). 0건이 아닌 급감은 두 완결
응답이 같은 건수일 때만 받는다. 옛 결정의 "빈 목록은 현재 돌발 없음" 해석은 이 개정으로 바뀌었다. 수집 쪽 세부는
[수집 기준](collection.md)에 있다.

## 6. 휴게소 계열 수집 (ADR-013 결정 4)

- **휴게소 기준정보**: data.go.kr `tn_pubr_public_rest_area_api`, 매일 03:40 → `rest_area_references`.
- **휴게소 주유소 현재 유가**: EX `curStateStation`, 4시간마다 → `rest_area_fuel_prices`.
- 두 원천은 전국 집합이므로 저장할 행이 0건인 수집은 성공이 아니라 실패로 남긴다(`EmptyRestAreaCollectionError`) — 그래야 export가
  빈 200이 아니라 503이 된다.
- 휴게소 자연키는 원천에 안정 ID가 없어 `name::route_name::direction`(strip→lower) — Map이 같은 원천에서 쓰던 규칙과 같다.
- 기본 비활성(`REST_AREA_COLLECTION_ENABLED`)이다.

### 휴게소 먹거리 `rest-area-food` (2026-11-27, KREX 0615·0502)

Map ADR-127(휴게소·고속도로 주유소 상세의 한국도로공사 메뉴)을 위한 T1 export다.

- **수집**: `rest_area_food_collection_job`(매일 03:50 KST, source `krex_rest_area_food`, `KEX_EX_API_KEY`)이 0615 휴게소코드정보
  (1회, 전체)와 0502 휴게소 푸드메뉴(99행 페이지, 2026-11-27 74페이지)를 **한 transaction**으로 저장한다. 다음이면 실패로 남기고
  마지막 성공 집합을 그대로 둔다(그 집합의 나이가 3일 안이면 export 200):
  - 어느 한쪽이 0건,
  - 직전 성공 대비 코드 90%·메뉴 80% 미만(상류 일부 응답). 직전 집합 50행 미만이거나 마지막 성공이 36시간보다 오래면 보지
    않는다 — 원천이 정당하게 크게 줄면 하루 실패한 뒤 다음날 수집이 새 집합을 받는다(3일 stale 전에 풀린다),
  - 원문 행 합계가 `count`와 다름, 또는 krex 엄격 파서가 버린 행이 1%를 넘음(그 아래면 그 행만 빼고 경고).
- **현재 집합은 이 데이터셋만 다르다**: 3일 재관측 여유를 두지 않고 마지막 성공 수집이 본 행 그대로를 낸다. 두 원천은 매 수집이
  전체를 주고 한 transaction으로 바뀌므로 "부분 수집으로 행이 사라진 것처럼 보이는" 경우가 없고(위 비율 하한이 막는다), 3일
  여유를 두면 원천에서 내려간 메뉴가 사흘 동안 Map 화면에 남는다.
- **남은 위험**: 0502는 74번에 나눠 읽는 동안 원천 snapshot이 아니다. 건수가 같은 채 행이 밀리면(삭제 하나 + 추가 하나) 한 행이
  하루 빠질 수 있다 — 화면에서 메뉴 하나가 다음 수집까지 보이지 않는 정도다. 원천 갱신 시각은 미확인이다(`lsttmAltrDttm`이 조회
  당일로 온다).
- **소비자 규칙**: 페이지마다 `collection.last_success_at`이 같아야 한 세대다. 다르면 처음부터 다시 받는다(Map
  `fetch_transport_rest_area_food`가 확인한다). Map 적재 job은 05:07 KST로 수집과 겹치지 않는다.

## 7. 503 실패 계약의 생산자 쪽 세부 (2026-11-24 개정)

Map 호출 감사(G1-F3·MC-01·T23-01·T23-10·RT-12·T1-07·RT-02·RT-04·WLH-09·G1-F4(a))의 생산자 쪽 변경이다. 결정 3의 현재 집합 의미와
돌발 정책(30분·실패 즉시 503·0건 정책)은 바꾸지 않았다. 바뀐 정책은 세 가지다: 유가 export stale 기준(24 → 27.5시간, 4절),
export 경로의 두 가지 500 → 503, T2/T3 55P03의 즉시 503 → 한 번 재시도. code 사전·힌트 값·소비자 처리는
[Map 인계](../map-service-exports-handoff.md#503-사유-code와-retry-after-2026-11-24)가 정본이고, 아래는 그 표에 없는 생산자 세부다.

- **형식**: transport 앱이 export에서 내는 모든 503 problem 본문에 가산 확장 `code`(UPPER_SNAKE)를 싣고 `Retry-After: <정수 초>`를
  준다(형식은 [ADR-005](../adr/005-versioned-rest-api-contract.md)). `type`/`title`/`status`/`detail`/`instance`와 한국어 `detail`
  문장은 그대로다. `code`의 뜻이 계약이고 `Retry-After` 값은 힌트다. 앞단 프록시가 만든 503은 이 계약 밖이다.
- **돌발 0건의 code**: 0건 수집은 실패로 기록되므로(`last_error`) 운영의 0건은 `EXPORT_INCIDENTS_NOT_CURRENT`다. `EXPORT_EMPTY_SET`은
  상태가 현재(실패 없음, 30분 안)인데 활성 행이 0건인 안전망 분기와 T3 완결 head membership 0건에서만 나온다.
- **`EXPORT_SOURCE_NOT_CURRENT`의 Retry-After 계산**: 수집 상태로 계산해 [60, 3600]초로 자른다. 진행 중인 수집(마지막 시작 > 마지막
  성공, 그 뒤 실패 기록 없음)은 `시작 + 예상 수행 시간 − now`(넘겼으면 300), 다음 예정이 미래면 `next_due_at − now + 예상 수행
  시간`, 예정이 없거나 지났으면 1800. 예상 수행 시간은 유가 2시간, 휴게소·휴게소 유가 10분, 공공 주차장 30분이다
  (`public_parking_routes.py`·`service_exports.py`). 휴게소 계열은 성공 때 `next_due_at`을 비우므로(`rest_area_collection.py`) 진행
  중이 아니면 1800이다. 유가 claim은 `next_due_at`을 시작 + 7시간 45분으로 옮기므로 예정 시각만 쓰면 이미 도는 복구 run을 몇 시간
  넘겨 짚었다 — 그래서 진행 중 분기를 먼저 본다. `EXPORT_NO_HISTORY`는 5분 주기 집합이면 300, 그 밖은 3600이다.
- **일시 DB 불가 → 503 `TRANSIENT_DB`(상태 코드 변경)**: export 경로에서 pool checkout timeout(`sqlalchemy.exc.TimeoutError`)·접속
  실패/접속 timeout·PG 기동 중(57P03)·관리자 종료(57P01/57P02)·접속 수 초과(53300)·연결 예외(class 08, 단 08P01 제외)·끊긴 연결은
  원인 불명 500 대신 503이다. DNS 해석 실패·TLS 오류는 설정 문제라 500이다. 원문(SQL·DSN·driver 문장)은 응답에 싣지 않고, 로그에는
  예외 종류·원인 종류/errno·SQLSTATE만 남긴다. 판정은 export 경로에만 거는 가장 안쪽 미들웨어(`app/core/export_guard.py`)가 한다 —
  **공개·관리 경로와 그 stream은 예전 그대로**(500)다. 관리 유가 화면은 가격 이력 경로의 어떤 503이든 "수집 이력 없음"으로 보여
  주기 때문이다(`fuel-station-history.tsx`). 그 밖의 DB 오류는 export에서도 500이다.
- **T4 문장 상한(#274)**: export 503에 `EXPORT_QUERY_TIMEOUT`을 싣는다. native 504는 그대로다.
- **T2/T3 snapshot 안의 statement timeout(상태 코드 변경)**: `SET LOCAL statement_timeout`(10초, 재시도는 남은 예산 이하)에 걸린
  57014는 500 대신 503 `EXPORT_PREPARE_TIMEOUT`이고 재시도하지 않는다.
- **55P03·40P01 한 번 재시도(정책 변경)**: 예전에는 admission 대기 lock_timeout(55P03)이 곧바로 503이었다(2026-11-19 artifact COPY
  보고서의 의도된 정책). 그때는 503에 사유가 없어 Map이 수 분 뒤 step 재시도로만 다뤘고, 요청 안에서 다시 시도하면 시도마다 15초
  예산을 새로 받아 Map read timeout(30초)을 넘길 수 있었다. 이제 두 시도가 **첫 시도 시작부터 잰 15초 예산 하나**를 나눠 쓰고, 남은
  예산이 `대기(0.3~1초) + lock_timeout(2초) + 여유(3초)` 이상일 때만 새 REPEATABLE READ로 한 번 더 시도해 앞 builder가 commit한
  본문을 재사용한다. 예산이 모자라거나 두 번째도 막히거나 재시도가 예산·statement timeout에 걸리면 `EXPORT_BUSY`다. 교착(40P01)도
  같다. RR 안의 advisory lock single-flight는 snapshot이 잡힌 뒤에 lock을 얻어 상대의 commit을 보지 못하므로 쓰지 않는다.
- **handler 전체 상한**: 15초 예산은 본문 구성 몫이고 재시도의 pool checkout 대기(최대 10초)는 덮지 않는다. 요청 전체는 T2/T3/T4
  handler 상한 25초(`ExportDeadlineRoute`)가 끊는다 — 본문 구성 중이면 `EXPORT_PREPARE_TIMEOUT`, 그 밖(pool·pre-ping·멈춘 PG)이면
  `TRANSIENT_DB`다. 보장하는 것은 "T2/T3/T4 응답이 25초 안에 200이거나 code 있는 503"이고 25초는 Map read timeout(30초)보다 작다.
  T1의 상한(25초)·55P03·57014 503은 8절의 T1 전송 개정이 둔다. 연결이 반쯤 끊겨 cleanup(rollback)까지 멈추는 경우는 이 상한이
  덮지 못한다(API 엔진에 클라이언트 `command_timeout` 없음).

### API DB 엔진 설정

- asyncpg 새 접속 상한 10초(기본 60초 > Map read 30초), pool checkout 상한 10초(기본 30초), `application_name`
  (`kor-travel-transport-api`/`kor-travel-transport-collector`). **pool checkout 상한은 엔진 전체라 공개·관리 경로에도 적용된다** —
  예전에 10~30초 기다려 성공하던 요청이 이제 10초에 500으로 끝난다. 장소 지도 입장 제한(MUI-02, #273)이 장소 지도 몰림을 줄인다.
- 서버 `lock_timeout`은 API 엔진에 두지 않는다 — 관리자 KRIC 매핑 저장은 기준 역 수집과 같은 advisory lock을, 관리자 좌표 보정은
  수집의 행 잠금을 의도적으로 기다린다. 짧은 대기가 맞는 경로는 이미 `SET LOCAL lock_timeout`을 둔다.
- `idle_in_transaction_session_timeout`·`transaction_timeout`은 어느 엔진에도 두지 않는다 — 공항·버스 기준정보·일반철도·KRIC
  시간표의 세션 advisory lease 연결은 `pg_try_advisory_lock` 뒤 commit하지 않아 run 내내 idle in transaction이다
  (`backend/app/db/session.py` 주석).

## 8. T1 전송 (2026-11-24 개정)

Map 호출 감사(T1-03·T1-04·T1-05·T1-06·T1-08·T1-09·RT-04)에 따른 T1 5종의 전송 방식 변경이다. JSON 본문(필드·순서·값)과 현재 집합
의미, 200/503 판정은 바꾸지 않았다. 소비자가 볼 수 있는 차이는 네 가지다.

- **gzip**: `Accept-Encoding`이 gzip을 허용하고(q=0은 거절) 본문이 512B 이상이면 gzip level 1과 `Content-Encoding: gzip`. 모든 T1
  200 응답에 `Vary: Accept-Encoding`. gzip을 받지 않는 요청은 평문이다.
- **cursor 범위**: int4 PK 범위(0..2147483647) 밖이면 422(예전에는 DB bind 오류로 500).
- **상한과 503**: 한 요청은 `REPEATABLE READ READ ONLY` snapshot 하나에서 읽고, 문장마다 `statement_timeout` 20초·`lock_timeout`
  3초, 요청 전체에 25초 상한을 둔다. 잠금 대기(55P03)와 본문 구성 slot 대기 5초 초과는 `EXPORT_BUSY`(`Retry-After: 10`), 문장
  상한(57014)과 요청 전체 상한은 `EXPORT_PREPARE_TIMEOUT`(`Retry-After: 60`)이다. 소비자는 기존 503처럼 재시도하고 마지막 적재분을
  지우지 않는다.
- **끊긴 요청**: 본문 구성 slot을 얻었을 때 소비자가 이미 끊었으면 본문을 만들지 않는다(접근 로그 499).

구현과 측정은 [성능 기준](performance.md#map-t1-export-본문-구성과-연결-반납-2026-11-24)이다.

## 9. 배포 순서 기록 (2026-11-24 → 2026-11-25 해제)

`code`·`Retry-After`는 순수 가산이지만 export 경로의 500→503 두 가지(`TRANSIENT_DB`, `EXPORT_PREPARE_TIMEOUT`)는 상태 코드 변경이라,
소유자가 정한 "나이 기준 혼합" 정책을 가진 Map #1549가 운영에 배포되고 Map #1542도 같은 규칙을 유지할 때에만 배포하도록 보류했다.
2026-11-25 Map #1542(e2e7e66)가 #1549의 code 분류와 나이 기준 혼합을 흡수해 머지됐고 소유자가 보류를 해제했다. 상세는
[배포 런북](../runbooks/deployment.md#배포-보류해제됨-export-503-상태-코드-변경2026-11-24-pr-277)이다.

## 개정 이력

| 날짜 | 바뀐 것 | ADR-013 |
|---|---|---|
| 2026-10-02 | 최초 결정(T1 5종, 토큰 + peer, 현재 집합 503 계약) | 결정 1~6 |
| 2026-10-03 | Map은 OpenAPI를 pin·vendoring하지 않고 런타임에 엄격 검증(Map ADR-106) | 결정 6 |
| 2026-10-23 | 참조 데이터는 마지막 성공의 나이로 판정, `last_attempt_failed` 추가(3절). 유가 다음 예정을 시작 기준으로(4절) | 결정 3 |
| 2026-10-23 | T4 가격 이력 요청 시 프록시 | "2026-10-23 추가" |
| 2026-11-24 | 돌발 활성 집합 0건은 실패(5절) | 결정 3 |
| 2026-11-24 | 503 `code`·`Retry-After`, 일시 DB 불가 503, 55P03 재시도, 유가 유예 27.5시간, API 엔진 상한(4·7절) | 결정 3 |
| 2026-11-24 | T1 전송: gzip·cursor 422·snapshot 상한 503·끊긴 요청(8절) | 결정 1 |
| 2026-11-24 | 유가 실패 경로도 시작 기준 예약을 보존한다는 사실 정정(4절) | — |
| 2026-11-25 | 503 상태 코드 변경 배포 보류 해제(9절) | — |
| 2026-11-27 | `rest-area-food` 추가, 이 dataset만 재관측 여유 없음(6절) | 결정 1·3 |
