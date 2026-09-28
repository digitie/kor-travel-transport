# 데이터 소스

## 1. 한국공항공사 공항 주차장 정보

- 출처: [https://www.data.go.kr/data/15056803/openapi.do](https://www.data.go.kr/data/15056803/openapi.do)
- 용도:
  - 한국공항공사 계열 공항의 기본 실시간 주차 현황 수집
  - 총 주차면, 현재 주차대수 기반 잔여 주차면 계산
- 수집 주기 기준 스냅샷 저장
- provider 라이브러리: `python-krairport-api`(krairport)의
  `kac_raw_items("AirportParking", "airportparkingRT", ...)`를 통해 조회한다(`T-030`,
  [ADR-004](../adr/004-krairport-provider-library.md)). 파싱은
  여전히 `backend/app/services/parsers.py::parse_kac_parking`이 담당한다.

## 2. 한국공항공사 전국공항 주차장 혼잡도

- 출처: [https://www.data.go.kr/data/15063437/openapi.do](https://www.data.go.kr/data/15063437/openapi.do)
- 용도:
  - 공식 혼잡도 라벨 확인용 후보 소스
  - 현재는 실시간 기본 수집원으로 사용하지 않음

## 3. 인천국제공항공사 주차 정보

- 출처: [https://www.data.go.kr/data/15095047/openapi.do](https://www.data.go.kr/data/15095047/openapi.do)
- 용도:
  - 인천공항 주차장 현황 수집
  - 인천공항은 혼잡도/잔여 면수 조회에는 포함
  - `parking`, `parkingarea`, `floor`, `datetm` 형태의 응답을 파싱
  - `datetm`은 `yyyyMMddHHmmss.SSS` 형태로 내려올 수 있어 KST 관측 시각으로 해석한 뒤 UTC로 저장
- 운영 주의:
  - `.env` 또는 `.env.odroid`에서 `ENABLE_INCHEON_COLLECTION=true`여야 한다.
  - `AIRPORT_CODES_CSV`에 `ICN`이 빠져 있으면 인천공항은 대시보드/수집 대상에서 빠진다.
  - 한국공항공사 `15056803`이 한도 초과 상태여도 인천 전용 API는 별도 기관 API이므로 계속 시도한다.
- provider 라이브러리: krairport의
  `iiac_raw_items("StatusOfParking", "getTrackingParking", ...)`를 통해 조회한다(`T-030`).

## 4. 인천국제공항공사 주차요금 정보

- 출처: [https://www.data.go.kr/data/15095053/openapi.do](https://www.data.go.kr/data/15095053/openapi.do)
- 용도:
  - 인천공항 주차요금 계산
  - `charid`, `chardesc`, `datetime` 형태의 응답을 요금 규칙으로 변환
- 현재 매핑:
  - `FB00000001`, `NF00000001`: T1/T2 단기주차장
  - `FB00000002`, `NF00000002`: T1/T2 장기주차장
  - `FB00000003`, `NF00000003`: T1/T2 예약주차장
- 운영 주의:
  - `ENABLE_INCHEON_FEE_COLLECTION=true`일 때만 수집한다.
  - 실시간 주차장 이름이 `T1 단기주차장지하1층`처럼 층 정보를 포함하면, 요금 규칙은 `T1 단기주차장` 접두어 기준으로 연결한다.
- provider 라이브러리: krairport에 이 endpoint의 typed 지원은 없지만, 범용
  `iiac_raw_items("ParkingChargeInfo", "getParkingChargeInformation", ...)` escape hatch로
  조회한다(`T-030`). 파싱(`charid`/`chardesc` → 요금 규칙 변환)은 여전히
  `parsers.py::parse_incheon_fee`가 담당한다.

## 5. 한국공항공사 전국공항 주차요금

- 출처: [https://www.data.go.kr/data/15038474/openapi.do](https://www.data.go.kr/data/15038474/openapi.do)
- 용도:
  - 한국공항공사 관리 공항의 주차요금 계산
  - 소형/대형, 평일/주말/공휴일 요금 규칙 저장
- provider 라이브러리: krairport의 `kac_raw_items("AirportParkingFee", "parkingfee", ...)`를
  통해 조회한다(`T-030`). krairport의 typed `ParkingFee` model은 쓰지 않는다 — 휴일 요금과
  분당 추가요금 필드가 없고, 필드명(`parkingBasicM` 등)도 parking-radar가 실측 검증한 이름
  (`PARKING_BASIC_M` 등)과 다르다. `parsers.py::parse_kac_fee`가 raw item을 그대로 파싱한다.

## 6. 한국공항공사 실시간 항공편 운항 정보

- 출처: [https://www.data.go.kr/data/15113771/openapi.do](https://www.data.go.kr/data/15113771/openapi.do)
- 호출 URL: [https://api.odcloud.kr/api/FlightStatusListDTL/v1/getFlightStatusListDetail](https://api.odcloud.kr/api/FlightStatusListDTL/v1/getFlightStatusListDetail)
- 용도:
  - 선택 공항 기준 당일 출도착 비행편 조회
  - 하루 흐름 오버레이 차트의 0~24시 X축에 비행편 시간 마커 표시
  - 시간, 편명, 출발공항, 도착공항 표시
- 현재 호출 방식:
  - `cond[FLIGHT_DATE::EQ]=YYYYMMDD`
  - `cond[AIRPORT::EQ]=GMP` 같은 공항 코드
  - `page=1`, `perPage=1000`, `returnType=JSON`
- 현재 파싱 필드:
  - `AIR_FLN`
  - `AIRLINE_KOREAN`
  - `BOARDING_KOR`
  - `ARRIVED_KOR`
  - `FLIGHT_DATE`
  - `STD`
  - `ETD`
  - `IO`
  - `LINE`
  - `RMK_KOR`
- 주차 현황 수집과 별개로 조회하며 `parking_snapshots`에는 저장하지 않는다.
- 백엔드는 `/v1/flights/status`에서 응답을 정규화해 프론트에 전달한다.
- provider 라이브러리: `python-krairport-api`(`krairport`)의
  `kac_flight_status_detail_raw_items()`로 대체했다(`T-029`,
  [ADR-004](../adr/004-krairport-provider-library.md)). ODCloud
  `FlightStatusListDTL`은 KAC의 다른 서비스와 달리 `openapi.airport.co.kr`이 아닌
  `api.odcloud.kr` 호스트를 쓰는 별도 provider라 krairport의 기존
  `departures()`/`arrivals()`(`StatusOfFlights` 계열)로는 닿지 않는다 — krairport에
  이 endpoint 전용 raw-item escape hatch를 새로 추가했다. 파싱은 여전히
  `parse_kac_flight_detail_json`이 담당한다.

## 7. 인천국제공항공사 여객기 운항 정보

- 출처: [https://www.data.go.kr/data/15112968/openapi.do](https://www.data.go.kr/data/15112968/openapi.do)
- 사용 엔드포인트:
  - `getPassengerArrivalsDeOdp`
  - `getPassengerDeparturesDeOdp`
- 용도:
  - 인천공항(`ICN`) 선택 시 당일 출도착 비행편 조회
  - 하루 흐름 오버레이 차트의 0~24시 X축에 시간, 편명, 출발공항, 도착공항 마커 표시
- 현재 파싱 필드:
  - `flightId`
  - `airline`
  - `airport`
  - `scheduleDateTime`
  - `estimatedDateTime`
  - `remark`
  - `typeOfFlight`
- 주의:
  - 도착편은 `airport -> 인천`, 출발편은 `인천 -> airport`로 정규화한다.
  - 비행편 API는 주차 스냅샷 수집과 별개이며 `parking_snapshots`에는 저장하지 않는다.
  - provider 라이브러리: `python-krairport-api`(`krairport`)의
    `iiac_raw_items("StatusOfPassengerFlightsDeOdp", "getPassengerDeparturesDeOdp"/
    "getPassengerArrivalsDeOdp", ...)`로 대체했다(`T-029`,
    [ADR-004](../adr/004-krairport-provider-library.md)) — 기존
    endpoint와 정확히 일치해 krairport 쪽 수정 없이 바로 전환 가능했다.

## 8. 한국천문연구원 특일 정보

- 출처: [https://www.data.go.kr/data/15012690/openapi.do](https://www.data.go.kr/data/15012690/openapi.do)
- 호출 URL: [http://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo](http://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo)
- 용도:
  - 지난주/이번주/다음주 공휴일 문장 표시
  - 최근 7일 시계열 차트의 공휴일/토요일/일요일 날짜 배경 강조
  - 최근 8개 공휴일/토요일/일요일 날짜별 시간대 잔여 주차면 패턴 분석
- 현재 호출 방식:
  - `solYear=YYYY`
  - `solMonth=MM`
  - `numOfRows=50`
- 파싱 필드:
  - `dateName`
  - `isHoliday`
  - `locdate`
- 운영 주의:
  - 공휴일 정보는 주차 스냅샷 수집 대상이 아니다.
  - 백엔드는 월 단위로 조회하고 `HOLIDAY_CACHE_SECONDS` 동안 캐시한다.
  - 같은 날짜에 공휴일명이 여러 개 있으면 날짜별 표시에서는 이름을 묶어서 보여준다.
  - 주차 데이터가 없는 미래 특수일은 목록에는 표시될 수 있지만, 공휴일/토/일요일 패턴의 관측값은 비어 있을 수 있다.

## 수집 전략

- 주차 현황 원본은 n150 운영 기준 5분 주기로 수집한다. 외부 API rate limit이 관측되면
  backoff 설정이 우선하며, 실제 관측 시각은 수집 시각과 별도로 기록한다.
- 기본 주기 수집은 `15056803` 기반 `kac_parking`을 사용하고, 설정에 따라 `incheon_parking`, `incheon_fee`, `kac_fee`를 함께 시도한다.
- `15095047`, `15095053`, `15038474`는 별도 플래그를 켰을 때만 시도한다.
- `kac_parking`이 한도 초과 상태이면 한국공항공사 주차/요금 소스는 건너뛰지만, 인천 전용 소스가 켜져 있으면 인천 주차/요금 수집은 계속 진행한다.
- 비행편 API는 주기 수집 대상이 아니라 화면 조회 시 5분 캐시로 호출한다.
- 공휴일 API는 주기 수집 대상이 아니라 화면/분석 조회 시 월 단위로 호출하고 기본 1일 캐시를 사용한다.
- 원본 응답은 필요 시 추적할 수 있도록 저장한다.
- 분석 화면에서는 원본 수집 데이터에서 10분 단위 시계열을 다시 계산해 사용한다.
- 시계열 저장용 별도 테이블을 두기보다, 우선은 `parking_snapshots` 기반 집계를 사용한다.
- 인증키가 없는 개발 모드에서는 샘플 클라이언트가 동작할 수 있으므로, 실데이터 여부는 `client_mode`로 반드시 확인한다.

## 접근 상태 확인 메모

최종 수동 확인 기준:

- `2026-05-09`

운영 메모:

- 승인 직후에는 data.go.kr 활용신청 반영이 지연될 수 있다.
- 따라서 "승인됨"과 "즉시 호출 가능"을 같은 뜻으로 보면 안 된다.
- 수집원을 바꾸거나 플래그를 켜기 전에는 실제 호출 결과를 다시 확인한다.
- `2026-05-09` 기준 현재 서비스 키로 `15095047` 인천 주차 정보는 `resultCode=00`, `NORMAL SERVICE.`를 반환했다.
- `2026-05-09` 기준 현재 서비스 키로 `15095053` 인천 주차요금 정보는 `resultCode=00`을 반환했다.
- `2026-05-09` 기준 현재 서비스 키로 `15112968` 인천 여객기 운항 정보의 도착/출발 엔드포인트는 모두 `resultCode=00`을 반환했다.
- `2026-05-09` 기준 현재 서비스 키로 `15113771` 한국공항공사 실시간 항공운항 현황 정보 상세 조회 서비스는 정상 응답을 반환했다.
- 기존 `15000126` 계열 `FlightStatusList/getFlightStatusList`는 현재 서비스 키로 `resultCode=99`, `SERVICE ACCESS DENIED ERROR.`가 반환되어 live 호출에서 사용하지 않는다.

당시 기준 판단:

- `15056803`
  - 한국공항공사 공항 주차장 정보
  - 기본 실시간 수집원으로 사용
- `15063437`
  - 혼잡도 라벨 참고용 후보
  - 기본 수집원으로는 미사용
- `15038474`
  - 요금 데이터 용도
  - 주차 현황 수집과 분리해서 다룬다
- `15095047`
  - 인천공항 전용 소스
  - 기관이 달라 별도 접근 상태를 따로 본다
- `15095053`
  - 인천공항 요금 전용 소스
  - 단기/장기/예약 주차장 접두어 기준으로 요금 규칙을 연결한다
- `15112968`
  - 인천공항 비행편 마커용 조회 소스
  - 도착/출발 엔드포인트를 각각 호출해 하나의 응답으로 정규화한다
- `15113771`
  - 한국공항공사 공항 비행편 마커용 조회 소스
  - ODCloud JSON API이며 날짜/공항 조건으로 필터링해서 사용한다
  - 주차장 수집 제한과 분리해서 본다
- `15012690`
  - 한국천문연구원 특일 정보
  - `2026-05-09` 기준 현재 서비스 키로 `2026년 5월` 조회 시 `resultCode=00`을 반환했다.
  - 응답에는 `20260501 노동절`, `20260505 어린이날`, `20260524 부처님오신날`, `20260525 대체공휴일(부처님오신날)`이 포함되어 있었다.

관련 문서:

- [current-state.md](../current-state.md)
- [collection.md](collection.md)
