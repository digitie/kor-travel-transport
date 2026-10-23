# ADR-013: kor-travel-map에 OpiNet·KREX·공항 데이터를 토큰으로 닫힌 내부 export로 제공한다

- **상태**: accepted
- **날짜**: 2026-10-02
- **결정자**: agent + human
- **보완**: [ADR-005](005-versioned-rest-api-contract.md)가 미뤘던 "외부 소비자 인증"과
  "`docs/openapi.json` 최신 여부 CI 게이트"를 이 범위에서 처음 정한다.
- **개정 2026-10-23**(소유자 결정): 참조 데이터 export는 마지막 수집의 실패가 아니라 마지막
  **성공**의 나이로 판정한다(결정 3). 아래 "개정 2026-10-23" 절 참고.

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
   넘었으면 503**이다(주유소 24시간, 휴게소 3일, 휴게소 유가 12시간). 참조 데이터는 마지막 성공이 기준
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
  tick마다 돈다. 실패 경로(실패 시각 + 8시간)는 그대로다. 그래서 성공 → 다음 tick 실패 → 그다음 tick은
  예약으로 건너뜀 → 세 번째 tick(마지막 성공 tick에서 24시간 뒤)이 다시 돌고, 그때 마지막 성공은 아직
  유예 안이다(`test_eight_hourly_ticks_keep_one_failure_inside_the_export_grace`). 남는 틈은 두 가지다.
  (1) 유예는 첫 성공의 **완료** 시각 + 24시간에 끝나므로, 세 번째 시도가 첫 성공보다 오래 걸리면 그 차이만큼
  (최대 약 2시간) 503이 난다. (2) 실패가 연달아 두 번 이상이면 예전처럼 503이 된다.
  하루 3회 상한은 Dagster에서는 8시간 tick(KST 00·08·16시)으로 지킨다. 다만 15분 당김 때문에 tick의 시작
  지연이 줄어드는 날에는 **연속 24시간 창**에 네 번째 시작이 최대 45분 안쪽으로 들어올 수 있다
  (00:45→08:30→16:15→다음 00:00). tick 없는 in-process scheduler는 성공 예약에만 당긴 폭을
  되돌리며, 대기와 재기동 후 수집 진입이 같은 유효 예정 시각을 사용해 시작 간격 8시간 이상을 지킨다.
  실패·진행 중 claim·과거 완료 기준 예약에는 추가 15분을 적용하지 않는다.

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
