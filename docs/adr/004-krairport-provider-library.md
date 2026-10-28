# ADR-004: 비행편·주차 현황·주차요금 데이터는 `python-krairport-api`(krairport)를 provider 라이브러리로 사용한다

## 2026-10-28 보완: KAC 요금 typed 모델 소비

아래의 2026-08-23 raw 경로 선택은 당시 모델 부족에 따른 이력이다. 새 소비자는 형제 SDK
PR #13의 머지 commit `e60b5280462803d00575cf9a16911681057d5ea6`의
`parking_fees(airport_code=...)`와 완전한 nullable `ParkingFee`를 사용한다. 실제 주차장명·
양 차종의 평일/휴일 무료·기본·추가·최대요금 필드와 0/결측 의미는 라이브러리가 책임진다.
Transport는 저장 도메인 변환과 주차장 연결·정책 계산만 담당한다. 원 항목은 감사용으로 보존하고,
기존 KAC raw 파서는 오프라인 fixture 호환 경로에만 남긴다. IIAC의 설명문 요금 endpoint는
아직 typed 지원이 없어 기존 raw 경로를 유지한다. 신규 provider wrapper를 추가하지 않는다.
조사와 불완전 응답·정확 주차장·24시간 계산 경계는
[주차요금 조사](../research/2026-10-28-parking-fee-policy.md)에 기록했다.

## 최초 결정과 구현 이력

- **상태**: accepted, 구현 완료 (주차 현황/요금 — `T-030`; 비행편 — `T-029`)
- **날짜**: 2026-08-23 (비행편 결정) / 2026-08-23 갱신 (주차 현황·요금으로 범위 확장 + 구현) /
  2026-08-23 갱신 (비행편 구현 완료 — `T-029`)
- **결정자**: agent + human
- **컨텍스트**: `backend/app/services/flight_status.py`(비행편)와
  `backend/app/services/collection.py`(주차 현황·주차요금)는 한국공항공사(KAC)/인천국제공항공사(IIAC)
  공개 API를 `httpx` + 수동 XML/JSON 파싱으로 각각 직접 재구현하고 있었다. 같은 두 기관
  API를 하나의 타입 있는 client로 묶은 형제 라이브러리 `python-krairport-api`
  (Python 패키지명 `krairport`)가 `F:\dev\python-krairport-api`에 이미 존재하고, KAC/IIAC
  provider 경계 분리, XML/JSON 양쪽 파싱, `UnsupportedAirportError`, 동기/비동기 client,
  오프라인 fixture 기반 테스트를 갖추고 있다. 실제로 조사해 보니 krairport는 주차
  현황(`kac_raw_items("AirportParking", "airportparkingRT", ...)`, IIAC
  `iiac_raw_items("StatusOfParking", "getTrackingParking", ...)`)과 KAC 주차요금
  (`kac_raw_items("AirportParkingFee", "parkingfee", ...)`)의 실제 upstream endpoint를
  parking-radar가 이미 검증한 것과 정확히 동일하게 호출한다. IIAC 주차요금
  (`ParkingChargeInfo/getParkingChargeInformation`)은 typed 지원이 없지만 같은
  `iiac_raw_items` 범용 escape hatch로 도달 가능하다. 반면 KAC 비행편은 krairport가
  지원하는 `StatusOfFlights/getDepFlightStatusList` 계열과 parking-radar가 실제 사용하는
  ODCloud `FlightStatusListDTL`(`15113771`)이 서로 다른 endpoint라 krairport 쪽에 코드
  추가가 필요하다(T-029 참고). `kor-travel-map` 생태계(`AGENTS.md`)는 형제 `python-*-api`
  라이브러리를 provider adapter 없이 직접 사용하고, 로컬 체크아웃을 우선 조회하는 정책을
  이미 채택하고 있다(해당 정책은 kor-travel-map `AGENTS.md`/`SKILL.md` 본문에 있으며, 그
  문서가 인용하는 특정 ADR 번호는 kor-travel-map 쪽 `docs/adr/README.md` 기준으로 존재를
  확인하지 않았으므로 여기서는 정책 내용만 참고하고 번호는 인용하지 않는다).
- **결정**: parking-radar의 비행편·주차 현황·주차요금 조회는 `python-krairport-api`
  (`krairport`) client를 사용한다. 직접 구현한 HTTP 호출·XML/JSON 파싱은 이 라이브러리
  호출로 대체한다. `krairport`에 없는 endpoint나 버그가 필요하면, parking-radar 안에 우회
  wrapper/shim을 만들지 않고 `F:\dev\python-krairport-api`(로컬 체크아웃 우선)를 직접
  수정해 개선한 뒤 그 개선된 라이브러리를 parking-radar가 소비한다. 다만 krairport의
  typed model(예: `ParkingFee`)이 parking-radar가 실제로 필요한 필드(휴일 요금, 분당
  추가요금)를 담지 못하거나 검증된 필드명과 다르면, typed model 대신 `kac_raw_items`/
  `iiac_raw_items` 범용 escape hatch로 원본에 가까운 item dict를 받아 parking-radar 자체
  파싱 로직(`parsers.py`)을 그대로 쓴다 — typed model을 억지로 맞추거나 krairport의
  model 자체를 확장하는 것보다 회귀 위험이 낮다.
- **근거**: 이미 검증된 provider 파싱 로직(XML/JSON 양쪽, KAC/IIAC 경계, 서비스키 처리)을
  중복 구현하지 않는 것이 회귀 위험과 유지보수 비용을 줄인다. 데이터 정합성(필드 의미,
  provider별 응답 형태)의 1차 책임을 provider 라이브러리에 두면, 다른 프로젝트(`kor-travel-map`
  계열)와 동일한 수정이 한 곳에서 공유된다.
- **결과 (긍정)**: 비행편/주차 관련 버그 수정·신규 endpoint 지원이 `krairport`에 쌓이고
  parking-radar는 이를 그대로 소비할 수 있다. `collection.py`가 직접 유지하던 XML/JSON
  envelope 파싱·serviceKey 주입 코드가 사라져 fetch 계층이 단순해졌다.
- **결과 (부정)**: parking-radar가 외부(로컬) 라이브러리에 의존하게 되어, `krairport`의
  breaking change가 parking-radar에 영향을 줄 수 있다. `krairport`는 PyPI에 게시되지 않은
  git 의존성(commit SHA 고정)이라, 버전을 올리려면 `backend/pyproject.toml`의 `rev`를
  직접 갱신해야 한다. `RawApiResponse.body_text`가 더 이상 업스트림 원문 그대로가 아니라
  krairport가 파싱한 item 목록의 JSON 직렬화로 바뀌었다 — krairport가 raw HTTP 응답
  텍스트를 공개 API로 내려주지 않기 때문이며(디버그 fixture 전용 경로만 있음), 감사
  목적상 "업스트림이 실제로 보낸 값"은 여전히 확인 가능하지만 바이트 단위로 동일하지는
  않다.
- **후속**:
  - **완료(주차 현황·주차요금, T-030)**: `backend/pyproject.toml`에
    `python-krairport-api @ git+https://github.com/digitie/python-krairport-api@<sha>`
    PEP 508 direct reference로 의존성을 추가했다(`[tool.uv.sources]`는 Docker 빌드가
    plain `pip install -e ".[dev]"`를 쓰기 때문에 인식되지 않아 폐기 — PEP 508 direct
    reference는 pip/uv 양쪽에서 동작한다). `backend/Dockerfile`에 `git` 패키지를
    추가했다(pip의 git+https 설치에 필요). `collection.py`의 `KrairportPublicDataClient`가
    `kac_raw_items`/`iiac_raw_items`로 4개 fetch(KAC 주차현황/요금, IIAC 주차현황/요금)를
    모두 대체했고, `parsers.py`는 입력 형태만(XML/JSON envelope → 사전 추출된 item
    list) 넓혔을 뿐 파싱 로직은 그대로다. WSL 1차(72 passed)와 Docker 2차(69 passed,
    `test_cutover_guards.py` 3개 제외 — 아래 참고) 모두 통과했다.
  - **완료(비행편, T-029)**: `flight_status.py`의 `LiveFlightStatusClient`를
    `KrairportFlightStatusClient`로 교체했다. KAC ODCloud(`FlightStatusListDTL`)는
    krairport에 지원이 없었으므로, `openapi.airport.co.kr`이 아닌 `api.odcloud.kr`
    호스트를 쓰는 `KacClient.flight_status_detail_raw_items()`(sync/async 둘 다)를
    krairport 쪽에 새로 추가하고 `KrairportClient`/`AsyncKrairportClient` facade에
    `kac_flight_status_detail_raw_items()`로 노출했다
    (`python-krairport-api` PR [#7](https://github.com/digitie/python-krairport-api/pull/7),
    `cbe4d13`). IIAC는 기존 `iiac_raw_items("StatusOfPassengerFlightsDeOdp",
    "getPassengerDeparturesDeOdp"/"getPassengerArrivalsDeOdp", ...)`가 endpoint와
    정확히 일치해 krairport 쪽 수정 없이 바로 전환했다. `parse_incheon_flight_status_json`에
    krairport의 사전 추출된 raw item list를 받는 분기(`_incheon_flight_section_items`)를
    추가했다 — `parse_kac_flight_detail_json`은 이미 `{"data": [...]}` 형태를 그대로
    파싱하므로 변경이 필요 없었다. 죽은 코드였던 `_fetch_legacy_kac_status`(한 번도
    호출되지 않던 구 XML endpoint)와 `_raise_for_upstream_status`/
    `MAX_UPSTREAM_ERROR_BODY_LENGTH`(httpx 직접 호출 전용)도 함께 제거했다.
    hostile review(Popper)가 지적한 rate-limit backoff 비대칭(`CollectionService`는
    DB 기반 backoff 상태를 갖지만 `FlightStatusService`는 없었다 — 비행편은 페이지
    조회 시마다 즉시 호출되므로 5분 주기 수집보다 이 공백이 더 위험하다는 지적)을
    반영해, `krairport.exceptions.KrairportRateLimitError`를 별도 `status:
    "rate_limited"`로 구분하고 `Settings.upstream_rate_limit_backoff_seconds`
    동안 `FlightStatusService._cache`에 캐시하도록 고쳤다 — `CollectionService`처럼
    DB에 상태를 영속화하지는 않지만(프로세스 재시작 시 초기화), 같은 프로세스
    안에서는 반복 페이지 조회가 rate limit 창을 계속 갱신하는 것을 막는다.
  - **관련 없는 발견**: 이번 검증 중 `backend/tests/test_cutover_guards.py`가 Docker
    컨테이너 안에서 `ModuleNotFoundError: No module named 'observe_cutover'`로 깨지는
    것을 발견했다 — `Path(__file__).parents[2]`가 로컬 디렉터리 깊이(`.../parking-radar/backend/tests/`)
    기준으로 계산되어 있어, Docker의 `/app/tests/`(한 단계 얕음) 구조에서는 `/scripts`를
    가리키게 되는 사전 존재 버그다(krairport 마이그레이션과 무관, 커밋 `481cb78`부터
    있었다). 이 ADR/PR에서는 고치지 않았다 — 별도 task로 등록이 필요하다.
  - **live smoke test로 발견하고 고친 문제 2건 (2026-08-23)**: 사용자가 로컬에 실제
    `DATA_GO_KR_SERVICE_KEY`가 있다고 알려줘서, fixture가 아닌 실제 upstream으로 전체
    파이프라인을 검증했다. fixture만으로는 절대 못 잡는 문제 두 개가 나왔다.
    1. **krairport의 KAC 호출이 전부 깨져 있었다**: krairport가 `https://openapi.airport.co.kr`로
       호출하는데, 이 게이트웨이는 `http://`로만 정상 응답하고(같은 요청을 https로 보내면
       요청 내용과 무관하게 전부 `resultCode=99 "NO OPENAPI SERVICE ERROR."`) — KAC 주차
       현황·요금뿐 아니라 krairport의 모든 KAC endpoint(운항, 시설, 버스, 택시 포함)가
       영향받는 host-level 버그였다. `python-krairport-api` PR
       [#6](https://github.com/digitie/python-krairport-api/pull/6)로 고쳐서 머지했고
       (`88d47ca`), parking-radar의 pin을 그 커밋으로 갱신했다.
    2. **parking-radar의 KAC 요금 파서가 애초에 잘못된 필드명을 기대했다**: `parse_kac_fee`와
       `_kac_fee_sample_items`, `tests/fixtures/kac_fee_gmp.xml`이 전부
       `PARKING_BASIC_ACCOUNT`(SCREAMING_SNAKE_CASE) 형태를 가정했는데, 실제 API는
       `parkingBasicAccount`(camelCase)를 반환한다. `_append_fee_rule`의 조기 return
       가드(`if basic_account_key not in item and unit_fee_key not in item: return`)
       때문에 실제 API 응답에서는 규칙이 하나도 안 만들어졌을 것이다 — 즉 **이 마이그레이션
       이전부터 KAC 주차요금 live 수집이 조용히 빈 배열만 반환하고 있었을 가능성이 높다**
       (krairport 도입과 무관한, 훨씬 오래된 버그). 실제 필드명으로 파서·sample
       데이터·fixture를 모두 고쳤다.
    두 문제 모두 고친 뒤 `CollectionService.collect()`를 실제 서비스키로 end-to-end 실행해
    확인했다: `status=success`, `raw_response_count=6`, `snapshot_count=30`,
    `fee_rule_count=56`, `errors=[]`.
