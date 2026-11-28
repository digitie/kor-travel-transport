# ADR-004: 비행편·주차 현황·주차요금 데이터는 `python-krairport-api`(krairport)를 provider 라이브러리로 사용한다

- **상태**: accepted
- **날짜**: 2026-08-23 (최초 결정, 주차 현황·요금으로 범위 확장) / 2026-10-28 (KAC 요금 typed 모델 소비)
- **결정자**: agent + human
- **컨텍스트**: `backend/app/services/flight_status.py`(비행편)와 `backend/app/services/collection.py`
  (주차 현황·주차요금)는 한국공항공사(KAC)/인천국제공항공사(IIAC) 공개 API를 `httpx` + 수동 XML/JSON 파싱으로
  각각 직접 재구현하고 있었다. 같은 두 기관 API를 하나의 타입 있는 client로 묶은 형제 라이브러리
  `python-krairport-api`(Python 패키지 `krairport`)가 이미 있었고, KAC/IIAC provider 경계 분리, XML/JSON 양쪽
  파싱, 동기/비동기 client, 오프라인 fixture 시험을 갖추고 있었다. 조사해 보니 krairport는 주차 현황·KAC
  주차요금의 실제 upstream endpoint를 parking-radar가 검증한 것과 같게 호출했고, IIAC 주차요금은 typed 지원
  없이 범용 `iiac_raw_items`로 도달할 수 있었다. KAC 비행편(ODCloud `FlightStatusListDTL`)만 krairport 쪽 추가가
  필요했다. `kor-travel-map` 생태계도 형제 `python-*-api` 라이브러리를 provider adapter 없이 직접 쓰고 로컬
  체크아웃을 우선하는 정책이다(kor-travel-map `AGENTS.md`/`SKILL.md` 본문 기준 — 그쪽 ADR 번호는 확인하지 않아
  인용하지 않는다).
- **결정**:
  1. 비행편·주차 현황·주차요금 조회는 `krairport` client를 사용한다. 직접 구현한 HTTP 호출·XML/JSON 파싱은 이
     라이브러리 호출로 대체한다.
  2. 필드 의미와 공급자 응답 정규화(0/결측의 뜻 포함)는 라이브러리의 **typed 모델**이 책임진다. Transport는
     정규화된 값을 저장 도메인으로 옮기고 주차장 연결·요금 정책 계산만 한다. typed 지원이 아직 없는 endpoint
     (IIAC 설명문 요금 `ParkingChargeInfo`)만 `iiac_raw_items` 범용 경로 + Transport 파서를 유지하고, typed 지원이
     생기면 옮긴다. 원 항목은 감사용으로 보존한다.
     _(2026-08-23 최초 결정은 typed 모델이 필요한 필드를 담지 못하면 raw 경로 + 자체 파서를 쓰게 했다. 형제 SDK
     PR #13이 `ParkingFee`를 보완한 2026-10-28부터 KAC 요금은 typed 모델을 쓴다 — 기존 KAC raw 파서는 오프라인
     fixture 호환 경로에만 남는다.)_
  3. `krairport`에 없는 endpoint나 버그는 Transport 안에 우회 wrapper/shim을 만들지 않고 형제 저장소(로컬 체크아웃
     우선)를 직접 고친 뒤 그 개선을 소비한다. 신규 provider wrapper를 추가하지 않는다.
  → 세부: [데이터 소스](../architecture/data-sources.md)(endpoint별 소비 방식),
  [krairport 전환 이력](../architecture/data-sources.md#krairport-전환-이력adr-004)(구현·live smoke 발견),
  [주차요금 조사](../research/2026-10-28-parking-fee-policy.md)(불완전 응답·정확 주차장·24시간 계산 경계)
- **근거**: 검증된 provider 파싱(XML/JSON, KAC/IIAC 경계, 서비스키 처리)을 중복 구현하지 않는 편이 회귀 위험과
  유지보수 비용을 줄인다. 데이터 정합성(필드 의미, provider별 응답 형태)의 1차 책임을 provider 라이브러리에 두면
  다른 프로젝트(`kor-travel-map` 계열)와 같은 수정을 한 곳에서 공유한다. 최초 결정에서 raw 경로를 허용한 것은
  당시 typed 모델을 억지로 맞추는 것보다 회귀 위험이 낮았기 때문이고, 모델이 보완된 뒤에는 그 이유가 사라졌다.
- **결과 (긍정)**: 비행편/주차 관련 버그 수정·신규 endpoint 지원이 `krairport`에 쌓이고 Transport는 그대로
  소비한다. `collection.py`가 유지하던 XML/JSON envelope 파싱·serviceKey 주입 코드가 사라져 fetch 계층이
  단순해졌다. 실제로 라이브러리 쪽 host-level 버그(KAC https)를 한 곳에서 고쳐 모든 KAC endpoint가 함께 나았다.
- **결과 (부정)**: `krairport`의 breaking change가 Transport에 영향을 준다. `krairport`는 PyPI에 없는 git
  의존성(commit SHA 고정)이라 버전을 올리려면 `backend/pyproject.toml`의 PEP 508 direct reference를 직접
  갱신해야 한다. `RawApiResponse.body_text`는 업스트림 원문이 아니라 krairport가 파싱한 item 목록의 JSON
  직렬화다 — krairport가 raw HTTP 응답 텍스트를 공개 API로 내리지 않기 때문이며, "업스트림이 보낸 값"은 확인할
  수 있지만 바이트 단위로 같지는 않다. 비행편 rate-limit backoff는 프로세스 cache에만 있어 재시작 시 초기화된다.
- **후속**: 형제 SDK pin을 올릴 때 live smoke로 실제 필드명을 확인한다(fixture만으로는 필드명 오해를 못 잡는다 —
  위 이력 참고). IIAC 요금 typed 지원이 생기면 raw 경로를 옮긴다(`docs/tasks.md`).
