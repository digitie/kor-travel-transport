# ADR-013: kor-travel-map에 OpiNet·KREX·공항 데이터를 토큰으로 닫힌 내부 export로 제공한다

- **상태**: accepted
- **날짜**: 2026-10-02
- **결정자**: agent + human
- **보완**: [ADR-005](005-versioned-rest-api-contract.md)가 미뤘던 "외부 소비자 인증"과
  "`docs/openapi.json` 최신 여부 CI 게이트"를 이 범위에서 처음 정한다.
- **개정 2026-10-23**(소유자 결정): 참조 데이터 export는 마지막 수집의 실패가 아니라 마지막
  **성공**의 나이로 판정한다(결정 3). 아래 "개정 2026-10-23" 절 참고.
- **개정 2026-11-24**(정책 변경 포함): export 503에 가산 `code`·`Retry-After`, export 경로의 일시 DB 불가·snapshot
  statement timeout은 500 대신 503, T2/T3 55P03 한 번 재시도, **유가 export stale 기준 24시간 → 27.5시간**.
  아래 "개정 2026-11-24 — 503 사유 code" 절 참고.

### 컨텍스트

kor-travel-map(Map)은 OpiNet 주유소·유가, 한국도로공사(KREX) 휴게소·휴게소 유가·돌발,
공항 메타데이터를 provider 라이브러리로 직접 받아 왔다. transport도 같은 원천을 이미 수집하거나
(오피넷 전국 주유소 약 1.2만 곳, 5분 돌발) 수집할 수 있는 테이블을 갖고 있었다(휴게소). 같은
원천을 두 서비스가 따로 호출하면 data.go.kr/OpiNet 일일 한도를 나눠 쓰고, 결과가 서로 어긋난다.
소유자 결정(2026-10-02): **Map에서 transport로 얻을 수 있는 것은 transport API로 바꾸고, 필요하면
transport API를 고친다.** OpiNet은 transport의 브라우저 수집본을 정본으로 쓴다.

기존 공개 지도 API(`/v1/transport/features/places` 등)는 marker 표시용이라 limit·균등 배분이 있고
provider 원본을 숨기며, 돌발은 "최근 24시간"이라 "지금 활성인 집합"을 표현하지 못한다.

### 결정

1. **내부 export 표면** `GET /v1/service/exports/{fuel-stations,rest-areas,rest-area-fuel-prices,
   highway-incidents/active,airports}`를 둔다. 모양은 kor-travel-concierge export와 같은 무-envelope
   `{items, next_cursor, has_more}` + `collection`(근거 수집의 마지막 성공·실패·stale) + `generated_at`.
   cursor는 불투명 문자열이고, 각 item은 안정 자연키와 원본 provider 행(`raw`)을 담는다.
2. **인증**: `X-Kor-Travel-Transport-Service-Token`(설정 `TRANSPORT_SERVICE_EXPORT_TOKEN`, 32자 이상,
   상수 시간 비교) **그리고** 접속한 peer 주소(`request.client.host`)가
   `SERVICE_EXPORT_ALLOWED_CLIENTS_CSV`(CIDR, 기본 `127.0.0.1/32,::1/128`) 안이어야 한다. 둘 중 하나라도
   어긋나면 404로 경로를 숨긴다. `Host` 헤더는 호출자가 정하는 값이라 쓰지 않는다(2026-10-02 리뷰 T1:
   `curl -H 'Host: 127.0.0.1' http://192.168.1.14:14001/...`가 통과했다). backend는 host network라 peer
   주소가 실제 접속 주소다. 공개 표면 셋은 이 경로를 전달하지 않는다 — 웹 프록시
   (`frontend/src/app/api/backend/[...path]`)와 관리자 API gateway
   (`deploy/transport-admin/api-gateway.conf.template`)는 경로 allowlist에 없고 토큰 헤더도 넘기지 않는다.
   standalone 개발에서 Map이 docker bridge(`host.docker.internal`)로 부르면 그 bridge 대역을
   `SERVICE_EXPORT_ALLOWED_CLIENTS_CSV`에 명시해 연다.
3. **현재 집합 의미와 신선도 계약(모든 dataset 공통)**: 200 응답의 `items`는 "마지막 성공 수집의 현재
   집합"이다 — 소비자는 거기 없는 행을 사라진 것으로 다뤄도 된다. 그래서 그 전제가 서지 않으면 200을
   주지 않는다: 근거 수집의 **이력이 없거나(`last_success_at` 없음), 마지막 성공이 stale 기준을
   넘었으면 503**이다(주유소 24시간 — 2026-11-24부터 27.5시간, 아래 개정 —, 휴게소 3일, 휴게소 유가 12시간). 참조 데이터는 마지막 성공이 기준
   안이면 **그 뒤의 시도가 실패했어도** 마지막 성공 수집의 집합을 200으로 낸다 — 실패한 시도는 저장
   transaction을 되돌려 그 집합을 바꾸지 않기 때문이다(2026-10-23 개정). 돌발 활성 집합은 "지금"의
   집합이라 마지막 수집이 **실패했거나** 30분을 넘으면 503이다. 수집이 꺼진
   dataset(`REST_AREA_COLLECTION_ENABLED=false`)도 이력이 없으니 503이다 — 빈 200을 주면 소비자가 전량
   삭제로 읽는다. 200 본문의 `collection`에서 `failed`·`stale`은 "이 집합을 낼 수 없다"는 503 사유라
   200이면 언제나 `failed=false`, `stale=false`다. 마지막 시도의 실패 사실은 `last_attempt_failed`
   (가산 필드)로 알린다 — 오류 문구는 내지 않는다. 상태 행과 데이터 행은 한 요청 안에서 REPEATABLE READ 한 snapshot으로 읽는다.
   참조 데이터(주유소·휴게소·휴게소 유가)는 마지막 성공 수집보다 3일 이전까지 재관측된 행을 현재
   집합으로 낸다(일부 지역 실패 한 번으로 사라지지 않게). 페이지는 요청마다 따로 판정하므로 페이지
   도중 stale 기준을 넘거나 돌발 수집이 실패하면 다음 페이지가 503이고, 소비자는 그 run 전체를 실패로
   다뤄야 한다(참조 데이터에서 실패한 시도는 집합을 바꾸지 않으므로 페이지 판정에 영향이 없다). 돌발은
   **마지막 성공 수집이 본 사건 전체**를 페이지 없이 한 번에 낸다. 이를 위해 돌발 수집은 상태의
   `last_success_at`을 재관측 행의 `collected_at`과 같은 값으로 남긴다.
4. **새 수집**: 휴게소 기준정보(data.go.kr `tn_pubr_public_rest_area_api`, 매일 03:40)와 휴게소 주유소
   현재 유가(EX `curStateStation`, 4시간마다)를 `rest_area_references`·`rest_area_fuel_prices`에 적재한다.
   두 원천은 전국 집합이므로 저장할 행이 0건인 수집은 성공이 아니라 실패로 남긴다
   (`EmptyRestAreaCollectionError`) — 그래야 export가 빈 200이 아니라 503이 된다.
   휴게소 자연키는 원천에 안정 ID가 없어 `name::route_name::direction`(strip→lower) — Map이 같은
   원천에서 쓰던 규칙과 같다. 기본 비활성(`REST_AREA_COLLECTION_ENABLED`)이다.
5. **공항**은 주차 수집 여부와 무관하게 `python-krairport-api` 번들의 운영 공항 전체(포항경주 KPO 포함)를
   ICAO·소재지·좌표와 함께 낸다. 주차 데이터 보유 여부는 `has_parking_data`로 표시한다.
6. **계약 정본**은 `docs/openapi.json`이고 CI가 `scripts/export_openapi.py --check`로 최신 여부를
   검사한다(transport 자신의 drift 방지). 이 export는 Map을 위해 있다 — Map에 필드·모양이 필요하면 이 API를
   그에 맞게 바꾼다(같은 PR 쌍, 버전·호환 층·옛 모양 shim 없음). Map은 이 파일을 pin·vendoring하지 않고
   응답을 런타임에 엄격히 검증한다(2026-10-03 소유자 결정, Map ADR-106).

### 개정 2026-10-23 — 참조 데이터는 마지막 성공의 나이로 판정한다

- **문제**: 옛 결정 3은 "마지막 수집이 실패했으면 503"이었다. 유가 수집이 실패하면 `next_due_at`이
  약 8시간 뒤로 밀리고, 그동안 `last_error`가 남아 `fuel-stations`가 계속 503이었다. odroid에서 브라우저
  수집이 시간 상한(당시 7,200초) 근처에서 연달아 실패하자 Map 적재가 약 32시간 끊겼다 — 그동안 저장된
  집합은 마지막 성공 그대로 멀쩡했다.
- **결정**: 참조 데이터(주유소·휴게소·휴게소 유가)는 마지막 성공이 stale 기준(24시간·3일·12시간) 안이면
  그 뒤 시도의 실패와 무관하게 마지막 성공 수집의 집합을 200으로 낸다. 기준을 넘으면 예전처럼 503이다.
  `collection.failed`는 "실패 때문에 집합을 낼 수 없다"는 뜻으로 좁히고(참조 데이터에서는 언제나 false),
  마지막 시도의 사실은 가산 필드 `collection.last_attempt_failed`로 낸다. 돌발 활성 집합은 바꾸지 않는다.
- **전제**: 실패한 시도는 마지막 성공의 집합을 바꾸지 않는다. 유가·휴게소 수집은 저장 실패·빈 집합·
  provider 오류 모두 저장 transaction을 되돌리고 `last_success_at`을 옮기지 않는다(회귀 테스트
  `test_fuel_station_export_grace_follows_a_real_failed_collection`,
  `test_an_empty_rest_area_collection_fails_so_the_export_goes_503`).
- **소비자(Map)**: Map은 `last_success_at` 없음·`failed`·`stale`만 다시 확인하고(`require_current_collection`)
  모르는 필드는 읽지 않으므로 바뀌는 것이 없다 — 유예 구간의 200을 그대로 적재한다.
- **공개 지도 API와의 차이**: 공개 유가 API의 신선도(`fuel_read_model_freshness`)는 화면 표시용이라
  여전히 마지막 시도 실패를 stale로 표시한다. export는 "집합을 낼 수 있는가"를, 공개 API는 "사용자에게
  오래됐을 수 있다고 알릴 것인가"를 판정하므로 의도적으로 다르다.
- **유가 주기(같은 날 후속 결정)**: 성공한 유가 수집의 다음 예정은 수집 **완료** + 8시간이었고 schedule은
  8시간 정각마다라, 수집이 1~2시간 걸리는 동안 다음 tick을 늘 건너뛰어 실제 주기가 16시간이었다. 그러면
  성공 뒤 첫 시도의 실패만으로 다음 시도가 24시간 유예를 넘겼다. 소유자 결정으로 다음 예정을 수집
  **시작** + 8시간(tick마다 다른 시작 지연을 덮도록 15분 당김, `FUEL_NEXT_DUE_START_SLACK`)으로 바꿔 8시간
  tick마다 돈다. **2026-11-24 정정**: 이 절의 처음 문장은 "실패 경로(실패 시각 + 8시간)는 그대로다"였지만, 실패
  경로도 claim 때 확정한 **시작** 기준 예약을 보존한다(`_mark_fuel_failure`, `transport_collection.py`). 그래서
  실패한 tick 뒤의 tick도 건너뛰지 않고 8시간마다 돈다(`test_eight_hourly_ticks_keep_one_failure_inside_the_export_grace`).
  남는 틈은 두 가지였다. (1) 유예는 첫 성공의 **완료** 시각 + 24시간에 끝나므로, 세 번째 시도가 첫 성공보다
  오래 걸리면 그 차이만큼(최대 약 2시간) 503이 났다 — 2026-11-24 개정으로 유예를 27.5시간으로 늘려 닫았다(아래).
  (2) 연속 실패 — 27.5시간 유예와 시작 기준 8시간 tick에서는 **연속 두 번 실패까지 200**이고(세 번째 tick이 시작 +
  24시간에 시작해 상한 3.5시간 안에 끝나면 유예 안), **세 번째 연속 실패부터 503**이다.
  하루 3회 상한은 Dagster에서는 8시간 tick(KST 00·08·16시)으로 지킨다. 다만 15분 당김 때문에 tick의 시작
  지연이 줄어드는 날에는 **연속 24시간 창**에 네 번째 시작이 최대 45분 안쪽으로 들어올 수 있다
  (00:45→08:30→16:15→다음 00:00). tick 없는 in-process scheduler는 성공 예약에만 당긴 폭을
  되돌리며, 대기와 재기동 후 수집 진입이 같은 유효 예정 시각을 사용해 시작 간격 8시간 이상을 지킨다.
  실패·진행 중 claim·과거 완료 기준 예약에는 추가 15분을 적용하지 않는다.

### 개정 2026-11-24 — 돌발 활성 집합의 0건은 성공이 아니다

KREX 실시간 문자정보가 `count=0`·빈 목록을 정상 응답으로 돌려준 수집을 성공으로 받아 활성 집합 export가 0건 집합 200을
37회 냈다(직전 167~351건). 전국 활성 돌발·공사 0건은 상류 이상으로 본다: 돌발은 완결 증거가 있어도 직전 성공 건수와
비교하고, 0건은 한 번 다시 조회해도 비면 실패로 기록해 마지막 성공 집합을 유지한다(export 503). 0건이 아닌 급감은 두 완결
응답이 같은 건수일 때만 받는다. 위 결정의 "빈 목록은 현재 돌발 없음" 해석은 이 개정으로 바뀐다(INCIDENT-EMPTY-SET-20261124).

### 개정 2026-11-24 — 503 사유 `code`·`Retry-After`, 일시 DB 불가 503, 유가 export 유예(정책 변경 포함)

Map 호출 감사(G1-F3·MC-01·T23-01·T23-10·RT-12·T1-07·RT-02·RT-04·WLH-09·G1-F4(a))의 생산자 쪽 변경이다. 결정 3의
현재 집합 의미와 돌발 정책(30분·실패 즉시 503·0건 정책)은 바꾸지 않는다. **바뀌는 정책은 세 가지다**: 유가 export
stale 기준(24시간 → 27.5시간), export 경로의 두 가지 500 → 503, T2/T3 55P03의 즉시 503 → 한 번 재시도.

- **503 사유 code**: transport 앱이 `/v1/service/exports/*`에서 내는 모든 503 problem 본문에 가산 확장 `code`
  (UPPER_SNAKE)를 싣고 HTTP `Retry-After: <정수 초>`를 함께 준다(형식은 [ADR-005 사실 갱신](005-versioned-rest-api-contract.md)).
  `type`/`title`/`status`/`detail`/`instance`와 한국어 `detail` 문장은 그대로다. 코드 사전·Retry-After·소비자
  처리는 [Map 인계 문서](../map-service-exports-handoff.md)의 "503 사유 code와 Retry-After" 절이 정본이다.
  `code`의 뜻이 계약이고 **`Retry-After` 값은 힌트**다(운영 중 바뀔 수 있고, 소비자가 정기 polling을 멈출 근거가 아니다).
  앞단 프록시가 만든 503은 이 계약 밖이다.
- **돌발 0건의 code**: #265(INCIDENT-EMPTY-SET) 뒤 0건 수집은 실패로 기록된다(`last_error`). 그래서 운영의
  0건은 `last_error` 분기로 **`EXPORT_INCIDENTS_NOT_CURRENT`**가 된다. `EXPORT_EMPTY_SET`은 상태가 현재(실패 없음,
  30분 안)인데 활성 행이 0건인 안전망 분기, 그리고 T3 기준정보의 완결 head membership이 0건인 경우에만 나온다.
- **T1 stale Retry-After(힌트)**: `EXPORT_SOURCE_NOT_CURRENT`는 수집 상태로 계산해 [60, 3600]초로 자른다 —
  진행 중인 수집(마지막 시작 > 마지막 성공, 그 뒤 실패 기록 없음)은 `시작 + 예상 수행 시간 − now`(넘겼으면 300),
  다음 예정이 미래면 `next_due_at − now + 예상 수행 시간`, 예정이 없거나 지났으면 1800. 예상 수행 시간은 유가 2시간,
  휴게소·휴게소 유가 10분, 공공 주차장 30분이다. 휴게소 계열은 성공 때 `next_due_at`을 비우므로(`rest_area_collection.py`)
  진행 중이 아니면 1800이다. 유가 claim은 `next_due_at`을 시작 + 7시간 45분으로 옮기므로 예정 시각만 쓰면 이미 도는 복구
  run을 몇 시간 넘겨 짚었다. 이력 없음(`EXPORT_NO_HISTORY`)은 5분 주기 집합(교통 current·주차장 current·돌발)이면
  300, 그 밖은 3600이다.
- **일시 DB 불가 503(상태 코드 변경)**: export 경로에서 pool checkout timeout(`sqlalchemy.exc.TimeoutError`)·접속
  실패/접속 timeout·PG 기동 중(57P03)·관리자 종료(57P01/57P02)·접속 수 초과(53300)·연결 예외(class 08, 단
  08P01 protocol_violation 제외)·끊긴 연결은 원인 불명 500 대신 503 `TRANSIENT_DB`(Retry-After 15)다. DNS 해석
  실패·TLS 오류는 설정 문제라 예전처럼 500이다. 원문(SQL·DSN·driver 문장)은 응답에 싣지 않고, 로그에는 예외 종류·원인
  종류/errno·SQLSTATE만 남긴다(처음 한 번과 그 뒤 60초마다 ERROR, 그 사이 WARNING). 판정은 export 경로에만 거는
  가장 안쪽 미들웨어(`app/core/export_guard.py`)가 한다 — **공개·관리 경로와 그 stream은 예전 그대로**(500, 같은
  예외 종류)다. 관리 유가 화면은 가격 이력 경로의 어떤 503이든 "수집 이력 없음"으로 보여 주기 때문이다
  (`fuel-station-history.tsx`). 그 밖의 DB 오류는 export에서도 500이다.
- **T4 가격 이력 문장 상한(#274)**: export 503에 `code=EXPORT_QUERY_TIMEOUT`(Retry-After 5)을 싣는다. native 504는 그대로다.
- **T2/T3 snapshot 안의 statement timeout(상태 코드 변경)**: `SET LOCAL statement_timeout`(10초, 재시도는 남은
  예산 이하)에 걸린 57014는 500 대신 503 `EXPORT_PREPARE_TIMEOUT`(Retry-After 60)이고 재시도하지 않는다.
- **55P03·40P01 한 번 재시도(정책 변경)**: 예전에는 admission 대기 lock_timeout(55P03)이 곧바로 503이었다
  (2026-11-19 artifact COPY 보고서에 적은 의도된 정책). 그때는 503에 사유가 없어 Map이 수 분 뒤 step 재시도로만
  다뤘고, 요청 안에서 다시 시도하면 시도마다 15초 예산을 새로 받아 Map read timeout(30초)을 넘길 수 있었다.
  이제 두 시도가 **첫 시도 시작부터 잰 15초 예산 하나**를 나눠 쓰고, 남은 예산이 `대기(0.3~1초) + lock_timeout(2초)
  + 여유(3초)` 이상일 때만 새 REPEATABLE READ로 한 번 더 시도해 앞 builder가 commit한 본문을 재사용한다. 재시도의
  statement_timeout은 남은 예산을 넘지 않는다. 예산이 모자라거나, 두 번째도 막히거나, 경합 뒤 재시도가 예산·
  statement timeout에 걸리면 503 `EXPORT_BUSY`(Retry-After 10)다. 교착(40P01)도 같다. RR 안의 advisory lock
  single-flight는 snapshot이 잡힌 뒤에 lock을 얻어 상대의 commit을 보지 못하므로 쓰지 않는다.
- **handler 전체 상한(보장 범위)**: 15초 예산은 본문 구성 몫이고 재시도의 pool checkout 대기(최대 10초)는 덮지
  않는다. 요청 전체는 **T2/T3/T4 handler 상한 25초**(`ExportDeadlineRoute`)가 끊는다 — 넘으면 본문 구성 중이면
  `EXPORT_PREPARE_TIMEOUT`, 그 밖(pool·pre-ping·멈춘 PG)이면 `TRANSIENT_DB`다. 그래서 보장하는 것은 "T2/T3/T4
  응답이 25초 안에 200이거나 code 있는 503"이고, 25초가 Map read timeout(30초)보다 작다. T1 handler의 상한은
  T1 export 작업(#279)이 따로 둔다. 연결이 반쯤 끊겨 cleanup(rollback)까지 멈추는 경우는 이 상한이 덮지 못한다
  (API 엔진에 클라이언트 `command_timeout` 없음).
- **API DB 엔진**: asyncpg 새 접속 상한 10초(기본 60초 > Map read 30초), pool checkout 상한 10초(기본 30초),
  `application_name`(`kor-travel-transport-api`/`kor-travel-transport-collector`)을 둔다. **pool checkout 상한은
  엔진 전체라 공개·관리 경로에도 적용된다** — 예전에 10~30초 기다려 성공하던 요청이 이제 10초에 500으로 끝난다.
  장소 지도 입장 제한(MUI-02, #273)이 들어오기 전에는 장소 지도 몰림이 pool을 채워 이 500이 늘 수 있다. 서버
  `lock_timeout`은 API 엔진에 두지 않는다 — 관리자 KRIC 매핑 저장은 기준 역 수집과 같은 advisory lock을, 관리자
  좌표 보정은 수집의 행 잠금을 의도적으로 기다린다. 짧은 대기가 맞는 경로는 이미 `SET LOCAL lock_timeout`을 둔다.
  `idle_in_transaction_session_timeout`·`transaction_timeout`은 어느 엔진에도 두지 않는다 — 공항·버스 기준정보·
  일반철도·KRIC 시간표의 세션 advisory lease 연결은 `pg_try_advisory_lock` 뒤 commit하지 않아 run 내내
  idle in transaction이다(`backend/app/db/session.py` 주석).
- **유가 export 유예(정책 변경, 소비자에게 보임)**: `REFERENCE_STALE_AFTER[opinet] = FUEL_STALE_AFTER(24시간) +
  FUEL_FETCH_TIMEOUT_SECONDS(3.5시간)` = 27.5시간. 위 "남는 틈 (1)"을 닫는다. 공개 화면의 유가 신선도
  (`FUEL_STALE_AFTER` 24시간)는 그대로이고, 27.5시간은 Map Valkey 데이터셋 max_age(48시간)보다 작다. 소비자에게는
  "마지막 성공 뒤 24~27.5시간 구간의 주유소 집합이 503 대신 200(`collection.last_attempt_failed=true`)"으로 보인다.
  Map ADR-106의 "24시간" 서술은 Map 쪽 후속 정정 대상이다.
- **배포 순서(강한 보류)**: `code`·`Retry-After`·`ProblemDetails.code` 선언은 순수 가산이다. 반면 export 경로의
  500→503 두 가지(`TRANSIENT_DB`, `EXPORT_PREPARE_TIMEOUT`)는 상태 코드 변경이라 **Map #1549(503 code 분류)가
  운영에 배포된 뒤에만** 이 변경을 운영에 배포한다([배포 런북](../runbooks/deployment.md)의 보류 항목). #1549 없이
  Map #1542(transport 503을 초록 `skipped=upstream_not_ready`로 건너뜀)만 들어가면 일시 DB 불가·준비 timeout이
  초록 건너뜀으로 숨는다.
### 근거

- 공개 marker API를 넓히는 대신 별도 표면을 둔 것은 둘의 계약이 다르기 때문이다. marker는 limit·
  bbox·표시 필드가 핵심이고, export는 전량·안정 키·원본 증거·"현재 집합" 의미가 핵심이다. 하나로
  합치면 공개 응답에 provider 원본을 내거나 export에 표시용 절단이 섞인다.
- 토큰만으로도 닫히지만 접속 주소 allowlist를 더하면 토큰이 새도 외부에서 원본 대량 조회가 불가능하다.
  Map은 같은 호스트의 host-network 컨테이너에서 `127.0.0.1:14001`로 부른다.
- 신선도를 플래그로만 알리고 200을 주는 대안은 버렸다. 소비자마다 플래그를 읽는 코드를 따로 지켜야
  하고, 한 곳이라도 빠지면 빈·낡은 집합이 삭제·종료로 번진다. 503은 읽지 않으면 실패하는 쪽으로
  기본값이 안전하다(Map은 플래그도 다시 확인한다 — Map ADR-106).
- 돌발 활성 집합을 페이지로 나누지 않는 것은 수백 건 규모이고, 페이지 사이에 수집이 끼면 집합이
  섞여 종료 판단이 틀어지기 때문이다.

### 결과 (긍정)

- 같은 원천을 한 번만 호출한다. Map은 OpiNet·KREX·krairport 의존과 키를 걷어낼 수 있다.
- 휴게소 기준정보·유가가 transport 지도에도 쓰일 수 있는 상태가 된다(`features/places?kind=rest_area`).
- `docs/openapi.json`이 처음으로 CI가 지키는 정본이 된다.

### 결과 (부정)

- Map의 해당 데이터가 transport 가용성에 묶인다. transport가 멈추면 Map 적재가 실패한다(오래된 값을
  새 값처럼 적재하지는 않는다).
- 토큰 하나가 export 전체 권한이다(읽기 전용). 범위별 토큰은 소비자가 둘 이상이 될 때 다시 본다.
- OpiNet 정본이 브라우저 수집(`opinet.experimental`)이라 공식 API보다 원천 변화에 약하다.


## 2026-10-23 추가: 요청 시 프록시하는 가격 이력(T4)

현재/참조 집합 계약의 예외로, 주유소 가격은 기존 이력 표에서 주유소·기간을 제한해 읽는 service API를 추가한다. Map은 요청 시 프록시하고 저장하지 않는다. token/peer 인증은 기존과 같으며 기존 endpoint/이력 저장은 바꾸지 않는다. 새 경로는 공통meta·ETag·gzip·keyset cursor와 수집 revision 재시작을 갖는다. 휴게소 이력은 저장하지 않아501이며 새 이력 표를 만들지 않는다. [세부 계약](../map-service-price-history.md).

## 개정 2026-11-24 (T1 전송)

Map 호출 감사(T1-03·T1-04·T1-05·T1-06·T1-08·T1-09·RT-04)에 따른 T1 5종(`fuel-stations`, `rest-areas`,
`rest-area-fuel-prices`, `highway-incidents/active`, `airports`)의 전송 방식 변경이다. JSON 본문(필드·순서·값)과
현재 집합 의미(결정 3), 200/503 판정은 바꾸지 않는다. 소비자가 볼 수 있는 차이는 아래 네 가지다.

- **gzip**: 요청의 `Accept-Encoding`이 gzip을 허용하고(q=0은 거절) 본문이 512B 이상이면 gzip level 1과
  `Content-Encoding: gzip`으로 보낸다. 모든 T1 200 응답에 `Vary: Accept-Encoding`이 붙는다. gzip을 받지 않는
  요청은 예전처럼 평문이다. Map httpx는 기본으로 gzip을 받고 자동으로 푼다.
- **cursor 범위**: `cursor`가 int4 PK 범위(0..2147483647) 밖이면 422다(예전에는 DB bind 오류로 500).
  서버가 준 `next_cursor`만 쓰는 소비자에게는 일어나지 않는다.
- **상한과 503**: 한 요청은 `REPEATABLE READ READ ONLY` snapshot 하나에서 읽고, 문장마다
  `statement_timeout` 20초·`lock_timeout` 3초, 요청 전체(DB 단계 + 본문 구성)에 25초 상한을 둔다(Map read
  timeout 30초 안). 넘으면 원인 불명 500 대신 503 problem+json과 `Retry-After`다 — 잠금 대기(55P03, 예: migration의
  AccessExclusive)와 본문 구성 slot 대기 5초 초과는 `Retry-After: 10`, 문장 상한(57014)과 요청 전체 상한은
  `Retry-After: 60`. 같은 날의 export 실패 계약(503 사유 `code`) 개정이 적용되면 이 503들의 `code`는 각각
  `EXPORT_BUSY`·`EXPORT_PREPARE_TIMEOUT`이다. 이 503은 "지금 집합을 낼 수 없다"는 일시 상태이며 소비자는 기존
  503 처리처럼 재시도하고 마지막 적재분을 지우지 않는다.
- **끊긴 요청**: 본문 구성 slot을 얻었을 때 소비자가 이미 연결을 끊었으면 본문을 만들지 않는다(받을 쪽이 없으므로
  소비자에게는 보이지 않는다. 접근 로그에는 499).

구현과 측정은 [performance](../architecture/performance.md)의 "Map T1 export 본문 구성과 연결 반납" 절이다.
