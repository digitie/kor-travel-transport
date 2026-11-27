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
장기 유가 추이(`/v1/transport/fuel/statistics/history`)도 동시 처리 상한이 있다(2026-11-27). BFF·직접 호출을 합쳐 4건(places와 다른
zone, backend 공개 줄 상한 6 = 12307 4 + 12301 2)이고, 넘으면 같은 `429` + `Retry-After: 2` problem+json(CORS 포함, `instance`는 같은
경로)이다. 공개 BFF는 상태·`Retry-After`를 그대로 전달하므로 공개 화면은 429를 재시도 가능한 혼잡으로 다룬다.
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

공개 지도에는 목록 보기가 없다(`mapOnly`). 배경지도 알림은 "지도 타일 오류"·"지도 키 없음"·"지도 표시 불가"로만 쓰고 관리 지도의
"· 목록 보기" 안내를 붙이지 않는다(2026-11-27). 이 알림은 범위 요약 위 줄(`.map-feedback`)에 생기므로 나타나는 순간 요약이 그만큼
내려간다. 격리 e2e(`E2E_PUBLIC_FUEL=true`, `TRANSPORT_UI_MODE=fuel` 서버)가 요약 위치를 전후로 잴 때는 배경지도 타일을 성공 이미지로
채운다 — 외부 요청을 막아 두면 VWorld 키로 빌드한 서버에서는 첫 idle 뒤 이 알림이 생겨 요약이 34.5px 밀리고, 키 없이 빌드하면
"지도 키 없음"이 처음부터 있어 통과한다(빌드 키에 따라 결과가 갈렸다, FUEL-PUBLIC-MAP-RETRY-E2E).

## 지역별 유가 통계 (/statistics)

2026-11-27(FUEL-HISTORY-PUBLIC-UI). fuel 실행에서 `/statistics`를 `/public/fuel/statistics`로 rewrite한다(그 밖의 경로는 여전히 404,
GET·HEAD만). 지도 왼쪽 아래 "내 위치" 옆 통계 단추(아이콘+"통계", 접근 이름 "지역별 유가 통계")가 입구이고, 지도에서 유종을 골랐으면
그 유종으로 연다. 단추 주소에는 `from=map`이 붙고 통계 화면은 첫 렌더에 읽은 뒤 주소에서 지운다. 그렇게 열린 화면의 "유가 지도"는
뒤로 가기라 지도 위치·선택이 그대로다(새로고침·외부 링크로 연 화면은 지도를 새로 연다 — 다른 사이트로 뒤로 가지 않는다).

공개 지도 주소의 유종(`?product=`, 2026-11-27 FUEL-MAP-LEFTOVERS): 통계 화면에서 지도로 가는 링크("지도에서 보기"·같은 최저가 목록의
"지도", 지도에서 오지 않은 화면의 "유가 지도")는 지금 보는 유종 코드를 `product`로 싣는다(통계 화면 query와 같은 이름·코드, 휘발유도 생략하지 않는다 —
저장한 선택이 경유여도 휘발유로 연다). 지도는 `useSearchParams`로 읽어(서버 렌더도 같은 값) 아는 유종 코드면 그 유종 하나로 연다. 모르는
값·소문자·없으면 지금처럼 이 브라우저에 저장한 선택(`transport.public-fuel.products`)을 쓴다 — 옛 링크(`/?longitude=&latitude=`)는 그대로다.
- 이 유종은 **이번 지도에만** 쓴다: 저장한 선택을 덮어쓰지 않는다. 통계를 잠깐 보러 간 사람의 평소 유종이 바뀌지 않게 하려는 것이다.
- 지도에서 유종·필터 선택으로 유종을 고르면 평소대로 저장하고, 주소에서 `product`만 지운다(`replaceState`, 좌표는 남긴다). 그래서 그 뒤의
  새로고침·지도 → 통계 → "유가 지도"(뒤로 가기) 흐름은 링크 유종이 아니라 고른 유종을 다시 그린다. 고르지 않았으면 뒤로 돌아온 지도는
  열렸던 그대로(링크 유종)다 — `from=map` 흐름과 위치·지역 선택 복원은 바뀌지 않는다.

- 조건: 범위(전국·시도·시군구·고속도로), 지역(시도 하나 / 시도→시군구 두 단계 / 고속도로 "전체 노선"·노선), 유종(휘발유·경유·고급유·LPG·등유,
  고속도로에서는 고급유·등유를 고를 수 없다 — 그 유종으로 고속도로를 고르거나 그런 링크를 열면 휘발유로 바꾸고 알린다), 기간(30일·90일·1년·전체). 라디오 묶음·native select, 터치 목표 44px.
  화면 상태는 URL query(`scope`·`region`·`product`·`period`, 기본값 생략)에 `replaceState`로 남는다. 첫 렌더와 뒤로 가기로 돌아온 화면은
  `useSearchParams`로 그 주소의 조건을 그린다. URL의 지역은 **실제로 보이는 지역**이다.
- 읽기: 공개 BFF `/api/public/fuel/statistics?scope=&product_code=&include_history=false`(현재 값·선택지, 30일 이력 생략), 고속도로
  "전체 노선"이면 `highways`를 먼저 읽고 끝난 뒤 노선 목록(`highway`)을 읽는다. 추이는 목록이 끝난 뒤
  `/api/public/fuel/statistics/history`(30·90일·1년은 공개 세대 KST 날짜까지 `bucket=day`, 전체는 `auto`)를 읽는다 — 한 사용자가 같은
  gateway 경로에 동시에 두 요청을 두지 않는다. `from`이 그 세대 날짜에 묶이므로 현재 값 다음이다. 시군구 목록은 sigungu 응답의 scope_key(`["시도","시군구"]`)로 묶는다.
- 재사용·재검증(`lib/public-fuel-statistics-client.ts`): 같은 경로를 1분 안에 다시 고르면 메모리 응답을 쓴다(시군구 목록 약 146KB).
  추이는 저장한 weak ETag를 `If-None-Match`로 보내 304면 저장본을 쓴다(BFF가 304·ETag를 전달). "다시 조회"는 메모리 재사용만 건너뛴다.
  응답이 10분보다 오래되면(탭을 다시 볼 때, 보이는 동안은 1분마다 확인) 현재 값과 추이를 다시 읽는다. 같은 경로를 다시 읽는 동안과
  그 다시 읽기가 실패해도 직전 값을 그대로 보인다(열어 둔 표·차트가 닫히지 않고, 잠에서 깬 직후 네트워크 오류가 값을 지우지 않는다).
- 지역이 응답에 없을 때(유종을 바꾸니 그 시군구에 LPG 주유소가 없음, 오래된 링크): 같은 시도의 첫 시군구(시도는 서울, 노선은 전체 노선)를
  보이고 "서울 마포구에는 LPG 통계가 없어 서울 강남구 값을 보여 드립니다"처럼 알린다(role=status). 이름은 앞서 받은 응답에서 찾은
  표시 이름만 쓰고, 모르면 "링크의 지역을 찾지 못해 …"라고 쓴다 — URL 글자를 안내에 넣지 않는다. 원천의 "노선 미제공"은
  "노선 정보가 없는 휴게소"로 보인다.
- 현재 값: 평균·최저·최고(원/L)·주유소(휴게소) 수, 최저가 주유소 이름·같은 가격 수·주소, 한국 안 좌표면 "지도에서 보기"
  (`/?longitude=&latitude=&product=`, 지도가 첫 렌더에 주소의 좌표를 읽으므로 앱 안 이동이 아니라 새로 연다. 유종은 위 "공개 지도 주소의 유종"). 좌표가 없으면(고속도로 휴게소 전부)
  그렇다고 쓴다. 같은 최저가가 여럿이면 "같은 최저가 N곳 보기"를 펼칠 때 그 범주로 가격순 목록(최대 10곳)을 읽는다(응답의 목록은 고른
  범주에만 실려 오므로). 10곳보다 많으면 그렇다고 쓴다. 통계 기준 시각, `update_pending` 안내, 36시간 넘은 세대 경고.
- 추이: 관리 화면과 같은 `FuelPriceChart`. 기본은 평균 선만 그린다 — 최저·최고를 같이 그리면 y축이 그 폭(전국 휘발유 1,600~2,600원)으로
  넓어져 평균 변화가 평평해 보인다. "그래프에 그날의 최저·최고도 함께 보기"를 켜면 같이 그린다(40점 초과면 점선). 기간 요약은 최근 평균, 기간 변화(첫 점 대비 원·%),
  기간 최저가·최고가(날짜). **이상값**: 평균의 70% 미만 최저·160% 초과 최고는 원천 입력 오류로 보고 차트와 기간 최저·최고에서 빼고
  건수를 알린다(표에는 원래 값). 운영 고속도로 자료에 평균 1,830원인 날 최저 184원·1,037원이 있었다. 2026-11-27 운영 공개 통계 전체의
  실제 범위는 최저/평균 0.83 이상, 최고/평균 1.38 이하였다. 현재 값의 최저가가 이 기준에 걸리면 지표와 최저가 주유소 옆에
  "입력 오류일 수 있음"을 붙인다. 360px 미만에서는 지표를 한 줄에 하나씩 둔다(숫자가 잘리지 않게).
- 상태: 현재 값과 추이는 따로 조회 중·실패·빈 상태를 보이고 **따로 다시 조회**한다(추이만 실패하면 목록을 다시 받지 않는다). 현재 값을
  기다리는 동안 추이 자리는 같은 높이로 둔다. 다시 조회하면 초점을 그 구역 제목으로 옮긴다. 응답은 화면이 쓰는 필드만 zod로 확인한다.
  429·503(Retry-After 5초 이하, 없으면 3~6초 뒤)은 한 번 자동으로 다시 묻는다. 그 밖의 실패는 "다시 조회" 버튼이며 Retry-After(초·
  HTTP-date, 최대 60초, 혼잡·시한·502는 최소 5초) 동안 남은 초를 보이고 막는다. 서버 한국어 안내는 429·503·504에만 그대로 쓰고
  (422 등 개발자용 안내는 일반 문구), BFF 502(30초 상한·연결 실패)는 "응답이 늦거나 연결되지 않았습니다", 200인데 JSON이 아닌 본문은
  형식 오류로 알린다. 브라우저 요청 상한 40초.
- 화면 읽기: 조회 중 문구는 알리지 않고(aria-busy), 새 값이 들어오면 "서울 강남구 휘발유 평균 …원"을 한 번 읽는다. 실패만 alert.
- gateway·BFF·CORS는 바꾸지 않았다. `statistics`·`statistics/history`는 #300에서 12307 허용 목록과 BFF 허용 목록에 이미 있고(계약 시험
  `test_fuel_public_gateway_contract.py`), BFF는 `content-type`·`etag`·`retry-after`를 전달한다. 브라우저는 같은 origin BFF만 부른다.
  gateway가 추이 경로에 동시 상한을 두면 429에 `Retry-After`(5초 이하)를 붙여야 이 화면이 그 시각을 지킨다(없으면 3~6초 흩어 한 번).
  backend `GET /v1/transport/fuel/statistics`에 `include_history`(기본 true)를 더했다. 옛 backend는 이 query를 무시하고 30일 이력을 그대로 준다.

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
