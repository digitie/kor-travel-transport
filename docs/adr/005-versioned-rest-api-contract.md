# ADR-005: 백엔드 REST API를 `/v1` 버저닝 + RFC7807 에러로 정식 계약화한다

- **상태**: accepted
- **날짜**: 2026-08-23 / 2026-11-24 (결정 5)
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
  5. (2026-11-24 추가) RFC7807 다섯 항목과 한국어 `detail`은 그대로 두고, 기계 판독 사유가 있는 응답에만 **가산
     확장 멤버 `code`**(UPPER_SNAKE)를 싣는다. `code`가 없거나 모르는 값이면 소비자는 상태 코드만의 뜻으로 다룬다.
     새 code 추가는 가산 변경이고, 있는 code의 뜻을 바꾸는 것은 계약 변경이다. kor-travel-common 표준
     `docs/standards/openapi.md` M3(Common T-482)의 Transport 쪽 첫 적용이다.
     → 세부: [에러 응답 계약](../architecture/architecture.md#에러-응답-계약problemjson)(구현 위치·`Retry-After`·
     프록시 `code`와의 구분·남은 정렬), [Map 인계 문서](../map-service-exports-handoff.md)(code 사전)
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
  의도된 동작). `docs/openapi.json`은 수동 재생성이 필요하다(최신 여부는 이후 CI
  `scripts/export_openapi.py --check`가 검사한다 — [ADR-013](013-internal-service-exports-for-map.md) 결정 6).
- **후속**:
  - **범위 밖(명시적으로 미룸)**: `{data, meta}` 응답 envelope, cursor pagination
    (`meta.page`), 인증(`ServiceToken` 류) — 지금 이 API는 frontend 전용 same-origin
    소비만 있고 외부 인증 요구가 없어 시기상조로 판단했다. 실제 외부 소비자가 생기면
    별도 ADR로 다시 다룬다.
  - DTO/라우트가 바뀌면 `scripts/export_openapi.py`를 재실행하고 `docs/openapi.json`을
    같은 커밋에 포함한다.

### 사실 갱신 2026-11-24 — problem+json 확장 멤버 `code`

위 결정 5로 접었다. 기계 판독 사유가 있는 응답에만 가산 확장 멤버 `code`(UPPER_SNAKE)를 싣고, "잠시 뒤 다시"인 503은
`Retry-After`를 함께 준다. 지금 `code`를 내는 곳은 `/v1/service/exports/*` 503뿐이다.
→ 세부: [에러 응답 계약](../architecture/architecture.md#에러-응답-계약problemjson)
