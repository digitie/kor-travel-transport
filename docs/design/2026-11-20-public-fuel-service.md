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
