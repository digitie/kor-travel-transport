# ADR-005: 백엔드 REST API를 `/v1` 버저닝 + RFC7807 에러로 정식 계약화한다

- **상태**: accepted (버저닝·에러 포맷·OpenAPI export는 구현 완료; `{data,meta}` envelope는
  범위 밖 — "후속" 참고)
- **날짜**: 2026-08-23
- **결정자**: agent + human
- **컨텍스트**: parking-radar backend는 처음부터 frontend 전용으로 설계된 FastAPI 앱이라
  `/parking/*`, `/dashboard/*` 등 경로에 버전이 없고, 에러 응답 형태가 라우트마다
  FastAPI 기본값(`{"detail": "..."}`)에 의존했다. `kor-travel-map`은 전 표면을 `/v1`로
  버저닝하고(`/health`·`/version`만 비버저닝 고정), 응답 envelope과 RFC7807
  `application/problem+json` 에러 형식을 계약으로 고정한 뒤, `packages/kor-travel-map-api/
  openapi.json`을 기계 정본으로 커밋해 둔다. parking-radar도 같은 백엔드를 frontend와
  외부 소비자가 함께 쓸 수 있는 "제대로 계약화된 API"로 만들 필요가 있었다.
- **결정**:
  1. `/health`를 제외한 모든 라우트를 `APIRouter(prefix="/v1")`로 이동한다(무-호환
     clean cut — 구 unprefixed 경로는 남기지 않는다).
  2. 모든 `HTTPException` 에러 응답을 RFC7807 `application/problem+json`
     (`type`/`title`/`status`/`detail`/`instance`)으로 통일한다. `detail` 필드는 유지해
     기존 frontend(`frontend/src/lib/api.ts::readErrorMessage`)가 그대로 동작한다.
  3. `scripts/export_openapi.py`로 `docs/openapi.json`을 정적 export해 기계 정본으로
     커밋한다(kor-travel-map의 `export_openapi.py` 관행).
  4. Next.js same-origin 프록시(`frontend/src/app/api/backend/[...path]/route.ts`)는 경로를
     그대로 전달하는 순수 pass-through로 유지한다 — 버저닝 로직은 `frontend/src/lib/api.ts`가
     각 경로에 `/v1/`을 붙이는 한 곳에만 존재한다. 이렇게 해야 `NEXT_PUBLIC_API_BASE_URL`로
     프록시를 우회해 백엔드에 직접 붙는 경우(현재는 미사용, 향후 외부 소비자 시나리오)에도
     같은 `api.ts` 클라이언트가 그대로 동작한다.
- **근거**: `/v1` 버저닝과 에러 포맷 통일은 breaking하지 않고도(프록시가 항상 존재하는
  현재 배포 모델에서는) 격리해서 끝낼 수 있는 범위였다. 반면 kor-travel-map의
  `{data, meta}` envelope(성공 응답 body 자체를 감싸는 것)은 23개 라우트의 반환 타입,
  `frontend/src/lib/types.ts`의 모든 응답 타입, `frontend/src/lib/api.ts`의 모든
  `getJson<T>` 호출부, 그리고 그 타입에 의존하는 프론트 컴포넌트/테스트 전부를 같은 PR
  안에서 바꿔야 하는 규모라 — 이번 범위에서는 제외하고 후속으로 미뤘다(질문 시
  사용자에게도 이 경계를 명시하고 "기존 API를 kor-travel-map 스타일로 정식 계약화"
  옵션으로 진행 승인을 받았다).
- **결과 (긍정)**: 외부 소비자가 붙을 수 있는 실제 버저닝된 계약이 생겼다. 에러 응답이
  라우트마다 다르지 않고 예측 가능해졌다. `docs/openapi.json`으로 계약 변경을 diff로
  추적할 수 있다.
- **결과 (부정)**: `/v1` 없는 구 경로로 오는 요청은 전부 404다(무-호환 clean cut이므로
  의도된 동작). `docs/openapi.json`은 수동 재생성이 필요하고, CI가 최신 여부를 검사하지
  않는다(kor-travel-map처럼 `--check` 게이트를 두지 않음 — 후속 과제).
- **후속**:
  - **범위 밖(명시적으로 미룸)**: `{data, meta}` 응답 envelope, cursor pagination
    (`meta.page`), 인증(`ServiceToken` 류) — 지금 이 API는 frontend 전용 same-origin
    소비만 있고 외부 인증 요구가 없어 시기상조로 판단했다. 실제 외부 소비자가 생기면
    별도 ADR로 다시 다룬다.
  - `docs/openapi.json`을 CI에서 `scripts/export_openapi.py --check` 형태로 최신 여부
    검사하는 게이트를 추가할지는 별도 task로 검토한다.
  - DTO/라우트가 바뀌면 `scripts/export_openapi.py`를 재실행하고 `docs/openapi.json`을
    같은 커밋에 포함한다.

### 사실 갱신 2026-11-24 — problem+json 확장 멤버 `code`

- **배경**: kor-travel-common 표준 `docs/standards/openapi.md` M3는 모든 4xx/5xx problem 본문에 확장
  멤버 `code`(UPPER_SNAKE)·`request_id`·`errors[]`를 두는 것을 생태계 표준으로 정했다(Transport는 Common
  task T-482, additive). 같은 날 Map 호출 감사(G1-F3·MC-01)는 `/v1/service/exports/*` 503이 사유를 한국어
  `detail` 문장으로만 실어 소비자가 수 시간짜리 stale과 수 초짜리 경합을 가르지 못한다고 지적했다.
- **결정(이번 범위)**: RFC 7807 본문(`type`/`title`/`status`/`detail`/`instance`)과 한국어 `detail`은 그대로
  두고, 기계 판독 사유가 있는 응답에만 가산 확장 멤버 `code`(UPPER_SNAKE 문자열, 패턴 `^[A-Z][A-Z0-9_]*$`)를
  싣는다. 사유가 "잠시 뒤 다시"인 503은 HTTP `Retry-After: <정수 초>`를 함께 준다. 구현은
  `backend/app/core/problems.py`(`CodedHTTPException`, `problem_body`)이고 공용 `HTTPException` handler는
  `code`가 있을 때만 본문에 더한다 — `code`가 없는 응답은 키 집합까지 예전과 같다.
  `docs/openapi.json`의 `ProblemDetails`에 선택(optional) 속성 `code`를 선언하고, 내부 export 경로의 503에
  `Retry-After` 헤더를 선언한다. 지금 `code`를 내는 곳은 `/v1/service/exports/*` 503뿐이다(코드 사전과
  의미는 [ADR-013 개정 2026-11-24](013-internal-service-exports-for-map.md)과
  [Map 인계 문서](../map-service-exports-handoff.md)).
- **소비자 규칙**: `code`가 없거나, 모르는 값이거나, 공통 사전의 기본값(예: `SERVICE_UNAVAILABLE`)이면 예전과
  같은 뜻(상태 코드만의 의미)으로 다룬다. 새 code를 더하는 것은 additive이고 있는 code의 뜻을 바꾸는 것은
  계약 변경이다.
- **충돌 없음**: parking-radar 웹의 Next.js 프록시는 이미 소문자 `code`(`backend_busy`·`backend_timeout`·
  `backend_unavailable`, `frontend/src/lib/full-history-proxy.ts`)를 낸다. 그 경로는 프록시가 만든 본문이고
  backend `code`와 값 공간(소문자 vs UPPER_SNAKE)이 겹치지 않으므로 이번 변경에서 건드리지 않는다.
- **남은 것(T-482)**: 모든 4xx/5xx의 기본 `code`(공통 S7.1 사전), `request_id`, `errors[]{field,message}`,
  `HTTPValidationError` 제거, `default` 응답 선언은 Common T-482에서 따로 정렬한다.
