# kor-travel-map·PinVi 교통 feature 계약

## 목표

`kor-travel-transport`는 원본 교통정보의 수집·저장·조회 책임을 갖고,
`kor-travel-map`과 PinVi가 여행 화면에서 재사용할 수 있는 feature 형태의 REST 응답을
제공한다. 이 문서는 `kor-travel-map`의 `Feature`/`PlaceDetail`/`NoticeDetail`/
`PriceValue` 계약을 그대로 따르기 위한 구현 기준이다. Map DB를 이 서비스가 직접 쓰거나
cross-schema FK를 만드는 것은 금지한다.

## feature 매핑

| 원본 | feature kind | category / place_kind | 제공 정보 |
| --- | --- | --- | --- |
| 공항, 공항 주차장 | `place` | `06050000` / `airport`, `06010000` / `parking` | 위치·연락처·편의/주차 요금, 최신 주차 현황 |
| KRIC 역사 | `place` | `06030300` / `train_station` | 좌표·주소·역 전화·시간표/편의정보 |
| 여객항구·터미널 | `place` | 교통 category 확정 후 `port` | 주소·전화·실시간 운항시간표 |
| 고속도로 휴게소 | `place` | `06040101` / `rest_area` | 방향·노선·편의시설·가격 |
| 주유소 | `place` | `06020000` / `fuel_station` | 주소·좌표·브랜드·셀프/24시간/세차 등 |
| KREX 돌발/통제 | `notice` | `traffic`, `traffic_accident`, `road_closure`, `roadwork` | 발생시각·노선·위치·처리상태 |
| 주유소/휴게소 가격 | `price` | `fuel` / product key | `observed_at`, 금액, `KRW/L`, 원천 유종 코드 |

시간표와 편의정보는 공통 JSON 구조를 사용한다.

```json
{
  "source": "python-kric-api",
  "fetched_at": "2026-09-21T00:00:00Z",
  "items": [{"kind": "timetable", "service_date": "2026-09-21", "departure_time": "0830", "arrival_time": null, "destination": "...", "status": null, "raw": {}}]
}
```

`kind`는 `timetable` 또는 `facility`이며, 제공하지 않는 필드는 `null`로 유지한다. 원본에
타임존이 없으면 임의 UTC 변환을 하지 않고 문자열·원본 날짜를 보존한다.

## 내부 일괄 export (ADR-013, 2026-10-02)

Map은 marker API가 아니라 `/v1/service/exports/*`를 읽는다. 토큰(`X-Kor-Travel-Transport-Service-Token`)과
주소 allowlist가 모두 맞아야 한다 — backend는 접속한 peer 주소(`Host` 헤더가 아님, 기본 loopback)를, Odroid 운영에서는
API gateway export location이 소비자 CIDR을 검사한다. 토큰·peer가 어긋나면 404, gateway CIDR 거부는 403이다
([service export 계약 §1](service-exports.md#1-표면과-인증-adr-013-결정-12)). `fuel-stations`·`rest-areas`·`rest-area-fuel-prices`는
`{items, next_cursor, has_more, collection}` 페이지, `highway-incidents/active`는 마지막 성공 수집의 활성
사건 전체(수집 실패·30분 정체면 503), `airports`는 krairport 번들의 운영 공항 전체다. 참조 데이터 셋은
마지막 성공이 stale 기준(주유소 27.5시간(2026-11-24 전 24시간)·3일·12시간) 안이면 그 뒤 시도가 실패해도 마지막 성공 집합을 200으로 내고
`collection.last_attempt_failed=true`로 알린다(2026-10-23 개정). 503은 가산 `code`·`Retry-After`로 사유를 가른다
([503 사유 code](../map-service-exports-handoff.md#503-사유-code와-retry-after-2026-11-24), 2026-11-24). 기계 정본은
`docs/openapi.json`(CI `--check`). 아래 "단계별 API"의 `/notices`·`/prices` 계획은 이 export가 대체한다.

## 단계별 API

1. 저장 기준정보를 읽는 `/v1/transport/features/places`, `/notices`, `/prices`를 추가한다.
2. 공항 주차 현황·주차요금은 place 상세에 저장된 최신 snapshot/규칙으로 포함한다.
3. 항구 시간표는 `/v1/transport/ports/{port_id}/timetable?date=YYYY-MM-DD`에서만 실시간
   provider 호출로 제공한다. DB와 `raw_api_responses`에 시간표 본문을 적재하지 않는다. 같은
   항구·날짜는 cache TTL 동안 한 번만 호출하고, provider 호출 제한은 `Retry-After`가 포함된 429로
   변환해 backoff 동안 다시 호출하지 않는다.
4. Map import는 이 REST 응답 또는 `kortravelmap.providers`의 async 변환을 사용한다. PinVi는
   Map API를 HTTP로만 호출하고 이 서비스의 DB에는 직접 의존하지 않는다.

지도 marker는 `GET /v1/transport/features/places`로 제공한다. 전체 종류 조회는 요청 `limit`을
다섯 종류에 균등 배분해 한 종류가 모든 marker 예산을 독점하지 않도록 한다. `airport`는 저장된 공항
주차 수집 기준정보와 `python-krairport-api` 번들 WGS84 좌표를 결합하며, 최신 관측별 주차장 수·가용면·
전체면·관측시각을 함께 제공한다. 지도 요청마다 외부 provider를 호출하지 않는다. `fuel_station`에는 브랜드와 최신 유가, `rail_station`에는 운영 노선,
`ferry_port`에는 항만가이드라인 좌표 출처·원본 점 수, `rest_area`에는 고속도로 노선·방향을 포함한다. 항만가이드라인 점은 터미널 중심점으로 추정하지 않으며 UI도
안내 지점임을 표시한다.

`features/places`는 입장 제한을 거친다. 혼잡하면 계산을 시작하지 않고 즉시 `429` + `Retry-After: 2`를, 전체
시한(기본 25초)을 넘기면 계산을 취소하고 `504` + `Retry-After: 10`을 준다(둘 다 `application/problem+json`).
호출자는 `Retry-After`가 지나기 전에 같은 요청을 반복하지 않는다. 클라이언트가 연결을 닫으면 backend는 그 요청의
계산을 멈춘다([성능 기준](performance.md)의 "장소 지도 입장 제한·시한·연결 반납" 절).
항구의 당일 운항은 `GET /v1/transport/ports/{port_id}/timetable`에서 한 항구·한 날짜만 비동기로
provider 호출하고 저장하지 않는다.

관리 지도는 현재 bbox의 선택 종류를 한 요청으로 읽는다. 종류당 최대 300곳, 요청 합계 최대 900곳
(`transport-map.tsx`의 `perKindLimit = min(300, floor(900 / 종류 수))`, `limit = min(900, perKindLimit × 종류 수)`)을
클러스터 입력으로 읽는다. 공개 gateway(12301·12307)도 places `limit`을 900 이하로 고정한다(생략 900, 900 초과는 900,
정수가 아니면 422). backend 직접 상한은 5000이며 관리 목록 검색만 이 값을 쓴다. places 목록 200 응답(`clustered=false`)에는
`X-Limit-Applied: <정수>`(backend가 실제로 적용한 합계 limit, 여러 종류면 종류마다 나눠 읽는다)가 있다. 낮은 축척 요약
(`clustered=true`)은 limit을 쓰지 않으므로 없다. 읽는 법: 요청한 `limit`보다 작으면 상한에 묶인 것이다. `limit`을 생략하면
기본값(gateway 900, backend 직접 1000)이라 상한과 구별할 수 없다. 실제로 잘렸는지는 본문 `truncated`·`kind_totals`로 본다.
브라우저에서 읽을 수 있는 곳은 fuel-api(12307, CORS `Access-Control-Expose-Headers`)와 같은 출처 BFF(공개 유가·관리)다.
12301에는 CORS가 없다. 같은 bbox·예산은 60초 동안 브라우저
메모리에서 재사용한다. 주유소 marker에는 유종과 최신 가격을 함께 표시하고, 공항·철도역·항구·휴게소는
서로 다른 SVG 아이콘으로 구분한다.
