# ADR-004: 비행편·주차 현황·주차요금 데이터는 `python-krairport-api`(krairport)를 provider 라이브러리로 사용한다

- **상태**: accepted
- **날짜**: 2026-08-23 (비행편 결정, 주차 현황·요금으로 범위 확장) / 2026-10-28 (KAC 요금 typed 모델 소비 보완)
- **결정자**: agent + human
- **컨텍스트**: `backend/app/services/flight_status.py`(비행편)와
  `backend/app/services/collection.py`(주차 현황·주차요금)는 한국공항공사(KAC)/인천국제공항공사(IIAC)
  공개 API를 `httpx` + 수동 XML/JSON 파싱으로 각각 직접 재구현하고 있었다. 같은 두 기관
  API를 하나의 타입 있는 client로 묶은 형제 라이브러리 `python-krairport-api`
  (Python 패키지명 `krairport`)가 이미 존재하고, KAC/IIAC provider 경계 분리, XML/JSON 양쪽 파싱,
  `UnsupportedAirportError`, 동기/비동기 client, 오프라인 fixture 기반 테스트를 갖추고 있다. 조사해 보니
  krairport는 주차 현황(KAC `AirportParking/airportparkingRT`, IIAC `StatusOfParking/getTrackingParking`)과
  KAC 주차요금(`AirportParkingFee/parkingfee`)의 실제 upstream endpoint를 parking-radar가 이미 검증한 것과
  정확히 동일하게 호출한다. IIAC 주차요금(`ParkingChargeInfo/getParkingChargeInformation`)은 typed 지원이
  없지만 같은 `iiac_raw_items` 범용 escape hatch로 도달 가능하다. KAC 비행편은 parking-radar가 실제 사용하는
  endpoint가 krairport 지원 범위와 달라 krairport 쪽에 코드 추가가 필요했다(T-029). `kor-travel-map`
  생태계(`AGENTS.md`)는 형제 `python-*-api` 라이브러리를 provider adapter 없이 직접 사용하고, 로컬 체크아웃을
  우선 조회하는 정책을 이미 채택하고 있다(해당 정책은 kor-travel-map `AGENTS.md`/`SKILL.md` 본문에 있으며,
  그쪽 ADR 번호는 확인하지 않았으므로 정책 내용만 참고하고 번호는 인용하지 않는다).
- **결정**:
  1. parking-radar의 비행편·주차 현황·주차요금 조회는 `krairport` client를 사용한다. 직접 구현한 HTTP 호출·
     XML/JSON 파싱은 이 라이브러리 호출로 대체한다.
  2. krairport의 typed model이 parking-radar가 실제로 필요한 필드를 충분히 담으면 typed model을 쓴다. typed
     model이 필요한 필드를 담지 못하거나 검증된 필드명과 다르면, typed model을 억지로 맞추지 않고
     `kac_raw_items`/`iiac_raw_items` 범용 escape hatch로 원본에 가까운 item dict를 받아 parking-radar 자체 파서
     (`parsers.py` 등)를 쓴다. 2026-11-28 코드 기준으로 KAC 주차요금(2026-10-28부터, 형제 SDK PR #13의 `parking_fees`·`ParkingFee`)과
     KAC 비행편(`kac.flight_status`)은 typed model을, KAC·IIAC 주차 현황, IIAC 주차요금, IIAC 비행편은 raw 경로를
     쓴다. typed model을 쓰는 곳에서 필드 의미와 0/결측 해석은 라이브러리가 책임지고, parking-radar는 저장 도메인
     변환과 주차장 연결·정책 계산만 한다. 원 항목은 감사용으로 보존한다.
  3. `krairport`에 없는 endpoint나 버그가 필요하면 parking-radar 안에 우회 wrapper/shim을 만들지 않고
     `python-krairport-api`(로컬 체크아웃 우선)를 직접 수정한 뒤 그 개선된 라이브러리를 소비한다. 신규 provider
     wrapper를 추가하지 않는다.
  → 세부: [데이터 소스](../architecture/data-sources.md)(endpoint별 소비 방식),
  [krairport 전환 이력](../architecture/data-sources.md#krairport-전환-이력adr-004)(구현·live smoke 발견),
  [주차요금 조사](../research/2026-10-28-parking-fee-policy.md)(불완전 응답·정확 주차장·24시간 계산 경계)
- **근거**: 이미 검증된 provider 파싱 로직(XML/JSON 양쪽, KAC/IIAC 경계, 서비스키 처리)을 중복 구현하지 않는
  것이 회귀 위험과 유지보수 비용을 줄인다. 데이터 정합성(필드 의미, provider별 응답 형태)의 1차 책임을 provider
  라이브러리에 두면, 다른 프로젝트(`kor-travel-map` 계열)와 동일한 수정이 한 곳에서 공유된다. typed model이
  부족할 때 raw 경로를 쓰는 것은 typed model을 억지로 맞추거나 krairport의 model 자체를 확장하는 것보다 회귀
  위험이 낮기 때문이다.
- **결과 (긍정)**: 비행편/주차 관련 버그 수정·신규 endpoint 지원이 `krairport`에 쌓이고 parking-radar는 이를
  그대로 소비할 수 있다. `collection.py`가 직접 유지하던 XML/JSON envelope 파싱·serviceKey 주입 코드가 사라져
  fetch 계층이 단순해졌다.
- **결과 (부정)**: parking-radar가 외부(로컬) 라이브러리에 의존하게 되어, `krairport`의 breaking change가
  parking-radar에 영향을 줄 수 있다. `krairport`는 PyPI에 게시되지 않은 git 의존성(commit SHA 고정)이라, 버전을
  올리려면 `backend/pyproject.toml`의 의존성 참조를 직접 갱신해야 한다. `RawApiResponse.body_text`가 더 이상
  업스트림 원문 그대로가 아니라 krairport가 파싱한 item 목록의 JSON 직렬화로 바뀌었다 — krairport가 raw HTTP
  응답 텍스트를 공개 API로 내려주지 않기 때문이며, 감사 목적상 "업스트림이 실제로 보낸 값"은 여전히 확인
  가능하지만 바이트 단위로 동일하지는 않다.
- **후속**: 구현·검증 이력과 live smoke로 발견한 문제는 [krairport 전환 이력](../architecture/data-sources.md#krairport-전환-이력adr-004)에 있다.
