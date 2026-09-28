# ADR-006: 공휴일 데이터는 `python-kasi-api`(kasi)를 provider 라이브러리로 사용한다

- **상태**: accepted, 구현 완료
- **날짜**: 2026-08-23
- **결정자**: agent + human
- **컨텍스트**: `backend/app/services/holidays.py`의 `LiveHolidayClient`는 한국천문연구원
  (KASI) 특일 정보 API(`SpcdeInfoService/getRestDeInfo`, `15012690`)를 `httpx` + 수동
  XML/JSON 파싱으로 직접 재구현하고 있었다. 같은 KASI API 계열(특일, 음양력, 출몰시각,
  태양고도, 월령, 천문현상)을 하나의 타입 있는 client로 묶은 형제 라이브러리
  `python-kasi-api`(Python 패키지명 `kasi`)가 `F:\dev\python-kasi-api`에 이미 존재한다.
  소스 대조 결과 kasi의 `holidays()`(`SpcdeInfoService/getRestDeInfo`)는 parking-radar가
  실제 호출하던 endpoint와 정확히 동일했다. `SpecialDay` typed model은
  `locdate`/`is_holiday`/`date_name` 필드와 함께 원본 API 응답 키(`dateName`,
  `isHoliday`, `locdate`)를 그대로 보존하는 `raw` mapping도 제공해, parking-radar의
  기존 `parse_holiday_response`/`_parse_holiday_fields` 로직을 그대로 재사용할 수 있었다
  ([ADR-004](004-krairport-provider-library.md)의
  krairport와 동일한 provider 라이브러리 원칙).
- **결정**: parking-radar의 공휴일 조회는 `python-kasi-api`(`kasi`)의
  `AsyncKasiClient.holidays()`를 사용한다. 직접 구현한 HTTP 호출은 이 라이브러리 호출로
  대체하되, 파싱은 kasi가 반환하는 각 item의 `raw` mapping(JSON 직렬화한 뒤)을
  parking-radar 자체 `parse_holiday_response`에 그대로 넘겨 기존 XML/JSON 파싱 로직을
  재사용한다(krairport 마이그레이션과 동일한 패턴 — raw item list 경로 추가).
  `kasi`에 없는 기능이나 버그가 필요하면 parking-radar 안에 우회 로직을 추가하지 않고
  `F:\dev\python-kasi-api`(로컬 체크아웃 우선)를 직접 고친 뒤 그 라이브러리를 소비한다.
- **근거**: 이미 검증된 KASI 특일 API 파싱(XML/JSON 양쪽, 서비스키 처리, 오류 코드 매핑)을
  중복 구현하지 않는 것이 회귀 위험과 유지보수 비용을 줄인다. `kasi`는 `KasiAuthError`/
  `KasiRateLimitError`/`KasiServerError` 등 구조화된 예외 계층을 이미 갖추고 있어,
  parking-radar가 직접 `resultCode` 문자열을 파싱해 오류를 분류하던 코드가 필요 없어진다.
- **결과 (긍정)**: `holidays.py`의 HTTP 호출·serviceKey 주입 코드가 사라져 fetch 계층이
  단순해졌다. 이 조사 과정에서 실제로 필드명/endpoint 불일치 같은 새 버그는 발견하지
  않았다 — krairport 때와 달리 이번 마이그레이션은 순수 provider 교체였다.
- **결과 (부정)**: parking-radar가 또 하나의 외부(로컬) 라이브러리에 의존하게 됐다.
  `kasi`도 PyPI에 게시되지 않은 git 의존성(commit SHA 고정)이라, 버전을 올리려면
  `backend/pyproject.toml`의 `rev`를 직접 갱신해야 한다.
- **후속**:
  - `backend/pyproject.toml`에
    `python-kasi-api @ git+https://github.com/digitie/python-kasi-api@51c39c1b0dd5b169b748552e81b9b9a55e86b9a1`
    PEP 508 direct reference로 의존성을 추가했다(krairport와 동일한 이유로 `[tool.uv.sources]`
    대신 direct reference 사용). `backend/Dockerfile`의 `git` 패키지는 krairport
    마이그레이션에서 이미 추가돼 있어 추가 변경이 필요 없었다.
  - `holidays.py`의 `KasiHolidayClient`가 `AsyncKasiClient.holidays()`로 fetch를
    대체했고, `parse_holiday_response`에 raw item list(`[` 시작) 분기를 추가했다.
    `FixtureHolidayClient`(sample 모드)는 변경하지 않았다 — 여전히 XML envelope를
    직접 생성한다.
  - WSL 1차 `pytest 82 passed`(신규 kasi 테스트 3개 포함), Docker 2차 `pytest 79 passed`
    (`test_cutover_guards.py` 3개 제외 — `T-031`, 이 PR과 무관한 사전 버그).
  - hostile review(Popper)가 지적한 비대칭: `CollectionService`(주차, `collection.py`)는
    `is_upstream_rate_limit_error`/backoff를 명시적으로 처리하지만, `HolidayService`는
    `KasiRateLimitError`를 다른 upstream 오류와 동일하게 `upstream_error`로만 처리하고
    별도 backoff 스케줄링이 없다. 의도적 범위 선택이다 — 공휴일은 `HOLIDAY_CACHE_SECONDS`
    (기본 1일)로 캐시돼 호출 빈도가 주차 수집(5분)보다 훨씬 낮아 rate limit 위험이 낮다.
    실제로 문제가 되면 별도 task로 다룬다.
