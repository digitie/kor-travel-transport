# 공개 유가 전용 서비스

## 경로와 역할

공개 UI https://fuel.digitie.mywire.org 는 12308, 읽기 gateway
https://fuel-api.digitie.mywire.org 는 12307을 사용한다.
docker-compose.fuel.yml의 별도 프로젝트 kor-travel-transport-fuel에는
fuel-web과 fuel-api-gateway만 둔다. 기존 Transport API 12302의 저장 reader를
호출하며 DB, 수집기, scheduler, migration 역할을 추가하지 않는다.

gateway는 GET·HEAD·OPTIONS만 허용한다. /health, /v1/transport/fuel/places,
/v1/transport/fuel/stations, /v1/transport/fuel/statistics,
/v1/transport/fuel/stations/{positive-id}/price-history 외의 경로는 닫는다.
places는 기존 /v1/transport/features/places에 마지막 kind=fuel_station을
고정한다. 반복·인코딩된 kind도 연료 외 종류를 선택할 수 없으며 kinds 혼용은
기존 reader의 422 거절을 유지한다. bbox·zoom은 그대로 전달한다. limit은 공개 UI(300)와 관리 지도(900)
범위 안으로 묶는다. 생략은 900, 900 초과 정수는 900, 1~900 정수가 아니면 422 problem+json이며 판정 값을 upstream query
끝에 붙인다(2026-11-24, [요청 소요 시간 로그 읽기](../runbooks/request-timing-logs.md#공개-gateway-가드레일)).
places 목록 200 응답의 `X-Limit-Applied`가 실제 적용 limit을 알리고 CORS `Access-Control-Expose-Headers`로 노출한다
(낮은 축척 요약에는 없다, 2026-11-25).
places는 동시 처리 상한이 있다(2026-11-25). 같은 호스트의 공개 UI BFF(127.0.0.1) 16건, 그 밖의 직접 호출 8건을
따로 세고, 넘으면 gateway가 `429` + `Retry-After: 2` problem+json(type·title·status·detail·instance, CORS header 포함)을
준다. 이 `instance`는 gateway 경로 `/v1/transport/fuel/places`이고, backend가 내는 places 오류(입장 거절 429·시한 504·
검증 422)의 `instance`는 upstream 경로 `/v1/transport/features/places`다. 둘은 access log `uct=-`(gateway)와
`ust=429`(backend)로 구분한다. backend 응답은 gateway가 바꾸지 않는다. 10초 동안 읽지 않는 클라이언트는 끊는다.
HEAD도 기존 GET reader를 쓰고 nginx가 응답 body를 생략한다.

CORS 허용 origin은 정확히 https://fuel.digitie.mywire.org 이며 credentials는
허용하지 않는다. upstream으로 Cookie·Authorization·X-Forwarded-For를 전달하지
않고 응답 Set-Cookie도 제거한다. preflight는 gateway에서 끝낸다.

## 실제 지도 축척

연료 단독 선택은 실제 zoom 0~9에서 기존 지역·셀 요약을 사용하고 10부터 개별
주유소·가격을 반환한다. 혼합 종류와 다른 종류는 기존 경계 12를 유지한다.
zoom을 보정하거나 가짜 값을 보내지 않는다. 기존 bbox 필터, 정렬, 통계, 전체
개수, limit·truncated 계약과 밀도 제어는 유지한다. 지역 정보는 places 응답의
fuel_regions를 사용하며 별도 /regions API는 만들지 않는다.

## UI 연동과 배포

UI는 기존 admin frontend Dockerfile의 정상 빌드를 사용하되 실행 환경을
TRANSPORT_UI_MODE=fuel, BACKEND_INTERNAL_URL=http://127.0.0.1:12307로 분리한다.
공개 경로 /public/fuel과 /api/public/fuel BFF를 같은 통합 변경에 구현한다.
전용 실행의 루트는 공개 지도로 rewrite하며 관리자·로그인·범용 API 경로는 열지 않는다.
BFF는 cookie·인증 정보 없이 고정된 유가 gateway만 호출하고 본문16MiB·30초 상한,
ETag·304·실패 상태와 재시도 안내를 유지한다.
기존 core/admin CURRENT와 일반 admin 인증은 별도로 유지한다.
Manager·ingress 구현 및 실제 배포는 담당자가 통합된 정확한 source/image 증거를
확인해 수행한다. gateway와 UI image는 검증된 정상 빌드 참조를 필수로 받는다.

## 지역별 유가 통계 (/statistics)

2026-11-27(FUEL-HISTORY-PUBLIC-UI). fuel 실행에서 `/statistics`를 `/public/fuel/statistics`로 rewrite한다(그 밖의 경로는 여전히 404,
GET·HEAD만). 지도 왼쪽 아래 "내 위치" 옆 통계 아이콘(접근 이름 "지역별 유가 통계")이 입구이고, 지도에서 유종을 골랐으면 그 유종으로 연다.

- 조건: 범위(전국·시도·시군구·고속도로), 지역(시도 하나 / 시도→시군구 두 단계 / 고속도로 "전체 노선"·노선), 유종(휘발유·경유·고급유·LPG·등유),
  기간(30일·90일·1년·전체). 모두 라디오 묶음·native select이고 터치 목표 44px. 화면 상태는 URL query(`scope`·`region`·`product`·`period`,
  기본값 생략)에 `replaceState`로 남아 공유·새로고침에 같은 화면이다. 서버가 query를 읽어 첫 렌더부터 같은 조건을 그린다.
- 읽기: 공개 BFF `/api/public/fuel/statistics?scope=&product_code=`(현재 값·선택지) 하나, 고속도로 전체 노선이면 `highways`를 하나 더,
  그리고 `/api/public/fuel/statistics/history`(30·90일·1년은 공개 세대 KST 날짜까지 `bucket=day`, 전체는 `auto`). 시군구 목록은
  sigungu 응답의 scope_key(`["시도","시군구"]`)로 묶어 따로 읽지 않는다. URL의 지역이 응답에 없으면 서울(없으면 이름순 첫 항목)로 둔다.
- 현재 값: 평균·최저·최고(원/L)·집계 주유소 수, 최저가 주유소 이름·동률 수·주소, 한국 안 좌표면 공개 지도 `/?longitude=&latitude=`
  링크("지도에서 보기", 관리 `/fuel`이 아니다). 통계 기준 시각(KST), `update_pending`은 "반영 중" 안내, 세대가 36시간보다 오래되면 경고.
- 추이: 관리 화면과 같은 `FuelPriceChart`(평균 선, 40점 초과면 최저·최고 점선). 기간 요약은 최근 평균, 기간 변화(첫 점 대비 원·%),
  기간 최저가·최고가(제공된 값만, 날짜 표시). 기록이 요청 기간보다 짧으면 "가격 기록은 …부터" 안내. 표는 펼칠 때만 그린다.
- 상태: 현재 값과 추이는 따로 조회 중·실패·빈 상태를 보인다. 응답은 화면이 쓰는 필드만 zod로 확인하고 다르면 조회 실패로 보인다.
  429·503(Retry-After 5초 이하)은 한 번 자동으로 다시 묻고 그동안 "조회가 몰려…"를 보인다(`lib/place-retry.ts` 규칙 공유). 그 밖의
  실패는 서버 한국어 안내(없으면 혼잡·시한·일반 문구)와 "다시 조회" 버튼이며 Retry-After(최대 60초) 동안 남은 초를 보이고 막는다.
  브라우저 요청 상한은 40초(BFF 30초 뒤 502까지 포함).
- gateway·BFF·CORS는 바꾸지 않았다. `statistics`·`statistics/history`는 #300에서 12307 허용 목록과 BFF 허용 목록에 이미 있고(계약 시험
  `test_fuel_public_gateway_contract.py`), BFF는 `content-type`·`etag`·`retry-after`를 그대로 전달한다. 브라우저는 같은 origin BFF만 부른다.

## 검증과 한계

실제 nginx fixture에서 경로·method·preflight·CORS·credential 제거·반복 query를
39개 사례로 검증했다. upstream은 로컬 stub이므로 운영 이미지 수락 증거는 아니다.
전용 PostgreSQL DB에서 42개 집중 테스트가 통과했다. 9·10·11·12 경계, 종류 분리,
bbox·limit·가격·통계, 반복/인코딩 query, 읽기 중 DML·수집 부재와 기존 연료
JSON codec·가격 이력·cursor 계약을 포함한다. OpenAPI 생성 및 최신성 검사와
fixture 입력을 사용한 compose config 해석도 통과했다.
운영/provider 호출, 실제 서비스 시작, ingress 변경은 이 소스 작업에서 수행하지 않았다.

이 변경은 backend·gateway·compose 소유 파일만 커밋하며 frontend/BFF 소유 변경과
하나의 통합 PR에서 검증한다. journal·resume 통합 기록은 통합 담당자가 함께 반영한다.

## 명시적 정상 빌드 역할

scripts/build-images.py는 명시한 fuel-api-gateway만 전용 Dockerfile로 빌드한다.
fuel-web은 transport-admin-web artifact의 alias이므로 둘을 함께 요청해도 같은 정상
admin 이미지 하나만 만든다. 공개 입력은 기존 admin의 VWorld·Dagster URL 그대로이며
gateway는 공개 입력을 받지 않는다. gateway도 기존 image release 환경변수 검증을
통과하도록 RELEASE_SHA를 보존한다. 기본 core 역할·legacy 집합·검증기는 바꾸지 않는다.
실제 정상 image/source/native 증거는 통합 source가 확정된 뒤 생성해야 한다.
