# ADR-012: kor-travel-map에 OpiNet·KREX·공항 데이터를 토큰으로 닫힌 내부 export로 제공한다

- **상태**: accepted
- **날짜**: 2026-10-02
- **결정자**: agent + human
- **보완**: [ADR-005](005-versioned-rest-api-contract.md)가 미뤘던 "외부 소비자 인증"과
  "`docs/openapi.json` 최신 여부 CI 게이트"를 이 범위에서 처음 정한다.

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
   상수 시간 비교) **그리고** 요청 Host가 `SERVICE_EXPORT_ALLOWED_HOSTS_CSV`(기본 `127.0.0.1,localhost`)
   중 하나여야 한다. 둘 중 하나라도 어긋나면 404로 경로를 숨긴다. 공개 표면 셋은 이 경로를 전달하지
   않는다 — 웹 프록시(`frontend/src/app/api/backend/[...path]`)와 관리자 API gateway
   (`deploy/transport-admin/api-gateway.conf.template`)는 경로 allowlist에 없고, 외부 reverse proxy
   (`pr-api`)를 거친 요청은 Host로 닫힌다.
3. **현재 집합 의미**: 참조 데이터(주유소·휴게소·휴게소 유가)는 마지막 성공 수집보다 3일 이전까지
   재관측된 행만 낸다. 돌발은 **마지막 성공 수집이 본 사건 전체**를 페이지 없이 한 번에 내고, 수집이
   실패했거나 30분 넘게 성공하지 못했으면 503이다 — 오래된 집합을 주면 소비자가 사라진 사건을 해소로
   오판한다. 이를 위해 돌발 수집은 상태의 `last_success_at`을 재관측 행의 `collected_at`과 같은 값으로
   남긴다.
4. **새 수집**: 휴게소 기준정보(data.go.kr `tn_pubr_public_rest_area_api`, 매일 03:40)와 휴게소 주유소
   현재 유가(EX `curStateStation`, 4시간마다)를 `rest_area_references`·`rest_area_fuel_prices`에 적재한다.
   휴게소 자연키는 원천에 안정 ID가 없어 `name::route_name::direction`(strip→lower) — Map이 같은
   원천에서 쓰던 규칙과 같다. 기본 비활성(`REST_AREA_COLLECTION_ENABLED`)이다.
5. **공항**은 주차 수집 여부와 무관하게 `python-krairport-api` 번들의 운영 공항 전체(포항경주 KPO 포함)를
   ICAO·소재지·좌표와 함께 낸다. 주차 데이터 보유 여부는 `has_parking_data`로 표시한다.
6. **계약 정본**은 `docs/openapi.json`이고 CI가 `scripts/export_openapi.py --check`로 최신 여부를
   검사한다. Map은 이 파일을 SHA와 함께 vendoring한다.

### 근거

- 공개 marker API를 넓히는 대신 별도 표면을 둔 것은 둘의 계약이 다르기 때문이다. marker는 limit·
  bbox·표시 필드가 핵심이고, export는 전량·안정 키·원본 증거·"현재 집합" 의미가 핵심이다. 하나로
  합치면 공개 응답에 provider 원본을 내거나 export에 표시용 절단이 섞인다.
- 토큰만으로도 닫히지만 Host allowlist를 더하면 토큰이 새도 외부에서 원본 대량 조회가 불가능하다.
  Map은 같은 호스트의 host-network 컨테이너에서 `127.0.0.1:14001`로 부른다.
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
