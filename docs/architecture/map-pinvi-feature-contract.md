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
네 종류에 균등 배분해 한 종류가 모든 marker 예산을 독점하지 않도록 한다. `fuel_station`에는 브랜드와 최신
유가, `rail_station`에는 운영 노선, `ferry_port`에는 항만가이드라인 좌표 출처·원본 점 수,
`rest_area`에는 고속도로 노선·방향을 포함한다. 항만가이드라인 점은 터미널 중심점으로 추정하지 않으며 UI도
안내 지점임을 표시한다.
항구의 당일 운항은 `GET /v1/transport/ports/{port_id}/timetable`에서 한 항구·한 날짜만 비동기로
provider 호출하고 저장하지 않는다.

관리 지도는 현재 bbox를 종류별로 요청한다. 전국 기본 뷰에서는 종류별 400곳, 지역 뷰에서는
750곳, 상세 뷰에서는 1,000곳을 클러스터 입력으로 읽는다. 같은 bbox·예산은 60초 동안 브라우저
메모리에서 재사용한다. 주유소 marker에는 유종과 최신 가격을 함께 표시하고, 철도역·항구·휴게소는
서로 다른 SVG 아이콘으로 구분한다.
