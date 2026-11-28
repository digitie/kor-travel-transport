# 주변 유가 MCP Apps UI

## 목적과 범위

OpenAI의 [MCP 서버에 UI 추가하기](https://developers.openai.com/ko-KR/plugins/build/chatgpt-ui)와 MCP Apps 표준을 따라 기존 읽기 전용 유가 MCP에 인라인 웹 UI를 연결한다. 기존 fuel 화면의 Transport 팔레트와 비교 작업 흐름을 사용한다. API·수집·원본·영구 통계 정책과 서비스 인증은 유지한다.

화면은 현재 위치 동의 또는 직접 입력 좌표, 반경1~50km, 네 유종(휘발유·경유·고급휘발유·LPG), 가격순/직선거리순 상위20곳, 전체 반경의 평균·최저, 지도·목록·선택 주유소 가격과 위치, 시군구/전국 비교를 제공한다. 최근30일 그래프·브랜드/편의 필터 등 공개 fuel 전체 기능을 모두 이식했다고 주장하지 않는다. 추가 탐색은 기존 fuel 웹으로 연결한다.

## 도구와 UI 경계

- 기존 `search_nearby_fuel`, `get_regional_fuel_prices`는 UI 없이 계속 사용한다.
- `list_nearby_fuel_stations`는 유종별 최대20곳을 SQL에서 정렬·제한한다. 평균·최저·건수·최저 동률 수는 전체 반경 모집단이다.
- `query_fuel_widget`은 앱 전용(`_meta.ui.visibility=["app"]`) 갱신 도구다. 위젯을 다시 마운트하지 않는다.
- `render_fuel_widget`에만 `_meta.ui.resourceUri=ui://transport-fuel/v1.html`을 연결한다. 좌표가 없으면 빈 위치 동의 UI부터 열고 DB/제공자를 호출하지 않는다.
- 같은 `/mcp`의 `resources/list`, `resources/read`가 `text/html;profile=mcp-app` 번들을 반환한다. 원 인증·대역 제한을 그대로 통과해야 한다.
- UI는 공식 `@modelcontextprotocol/ext-apps`로 초기화·알림·도구 호출을 처리한다. 브라우저에 서비스 토큰이나 VWorld 키를 넣지 않는다.

## 데이터·상태·개인정보

같은 성공 공개 세대와 원래 REPEATABLE READ/READ ONLY·문장5초·도구20초·동시4개 경계를 유지한다. 새 migration·가격 캐시·수집 실행은 없다. 원본이나 이전 성공 가격을 집계에 섞지 않는다. 가격0/null, 정상 빈 반경, 공개 세대 부재를 구분한다. 갱신 중/지연/최근 실패를 숨기지 않으며 지역 비교의 집계 시각이 다르면 그대로 알린다.

입력 좌표를 추측하지 않는다. 기기 위치는 버튼을 누르고 호스트/브라우저 권한이 허용될 때만 요청한다. 위치가 거부되면 직접 좌표를 입력한다. UI는 위치를 localStorage나 분석 로그에 저장하지 않는다. 기존 시군구 주소 판정은 저장 캐시 또는 기존 VWorld/Kakao resolver를 사용한다. OSM 배경 타일은 지도 화면을 열 때 OpenStreetMap에서 읽으며 출처를 표시한다. 새 UI는 공용 키가 필요한 지도를 추가하지 않는다.

새 조회가 실패하면 이전 성공 결과를 보존하되 이전 결과임을 알린다. 늦게 끝난 이전 요청·취소된 요청은 새 위치를 덮지 않는다. 호스트/도구 응답은 검증하고 사용자 문자열은 textContent로 출력한다. 오류 원문·임의 HTML/URL·비밀 필드는 전달하지 않는다. iframe의 allow-forms가 없어도 조회가 동작하며, 서로 겹친 지도 가격은 묶고 최대 확대에서도 주유소 목록으로 선택한다.

## 기존 개인 플러그인 중계

연결된 개인 플러그인의 기존 Sites 중계에도 같은 무비밀 HTML과 UI 도구/리소스를 연결한다. 소스·공개 범위·런타임 토큰은 기존 것을 유지한다. 새 Transport 앱 전용 도구가 실제 도구 목록에 있을 때만 native SQL 목록을 사용한다. 미배포 상태이면 기존의 공개 목록/정식 MCP 통계 교차 검산 경로를 사용한다. 인증·조회 실패를 도구 부재로 오판해 다른 자료로 바꾸지 않는다.

호환 경로는 전체 후보를 받은 뒤 반경·성공 수집분을 확인하고 정렬한다. 거리순에서도 최저·평균은 전체 모집단이며 표시20곳의 평균이 아니다. 공개 목록과 MCP 통계는 별도 요청임을 `atomic_snapshot=false`로 유지한다. 현재 Sites 배포·Transport 이미지 배포는 각각 별도 원장으로 확인하며 코드 구현만으로 완료 처리하지 않는다.

## 빌드·검증

Ubuntu-26.04 WSL2 ext4의 독립 checkout에서 Node26.13.1/npm12.0.1로 `make fuel-mcp-ui-install` 후 `make fuel-mcp-ui-check`를 실행한다. `npm test`는 타입/응답 검증과 요청 수명 단위 시험, `node node_modules/@playwright/test/cli.js test`는 엄격한 sandbox의 표준 MCP Apps 브리지와320/375/414/768/1440px 검증이다. 브라우저 fixture 가격/타일은 운영 자료가 아니다.

Backend Dockerfile은 BUILDPLATFORM Node stage에서 HTML을 만들고 Python 이미지에 결과만 복사한다. 운영에 Node 서비스나 새 포트를 추가하지 않는다. CI도 동일 번들을 만든 뒤 backend resource 시험에 전달한다. `backend/uv.lock`, SDK/provider 핀과 기존 Python runtime stage를 유지한다. 로컬 Docker context와 캐시는 WSL ext4이며 n150 빌드는 없다.

집중 WSL/Docker·PostgreSQL·브라우저·패키징 결과와 실패/정정은 작업 원장에 기록한다. 최종 CI·James/Popper 검토·머지 및 Sites 게시 결과는 PR/배포 원장을 정본으로 한다. 원 Python 테스트 경고를 경고0으로 주장하지 않는다.


## 주유소 공유와 지도 앱

UI 목록과 앱 전용 입력에서는 등유를 제외한다. 기존 데이터 도구의 다섯 유종 계약은 유지한다. 목적지 링크는 네이버지도 자동차 길찾기, 카카오맵 목적지, Google 지도 자동차 길찾기, Apple 지도 자동차 길찾기다. 네이버 앱 호출 실패 시 웹 검색으로 전환한다. 이름·주소는 URL 인코딩한다.

주유소 상세 공유 주소는 기존 공개 fuel 루트의 `station`·목적지 좌표·유종만 포함한다. 사용자의 출발 위치·반경·가격·인증값을 넣지 않는다. 링크 수신 화면은 기존 인증 없는 BFF의 고정 `fuel/places` GET으로 저장 행과 좌표를 대조하고 네 유종·수집 시각·지연 상태를 표시한다. 지도 타일이나 기기 위치 권한을 요구하지 않는다. 이 새 상세 화면은 별도 fuel web 이미지 적용 뒤 활성화된다. 이전 배포 화면에서는 같은 목적지 좌표의 유가 지도가 열린다.

마이현대는 차량 API로 자동 전송하지 않는다. `마이현대로 위치 공유`는 주유소 이름·주소와 장소 링크를 OS 공유창에 전달하고 사용자가 마이현대를 선택한다. 공식 공개 전용 deep link 규격은 확인되지 않았으므로 임의 scheme이나 차량 계정 연동은 추가하지 않았다. Android/iOS 실제 마이현대가 공유 자료를 받아 지도에 표시하는 동작은 실기기 미검증이다. OS 공유는 앱을 자동으로 지정하지 못하며, 공유 대상에 마이현대가 없으면 주소를 복사해 앱 지도에서 검색한다. `다른 앱으로 공유`는 공개 상세 링크를 전달한다. 복사가 거부되면 입력값 선택으로 수동 복사하고, 공유 취소 시 이전 성공 안내를 남기지 않는다.

## 후속 검증 원장

최신 UI 단위23개와 PostgreSQL18 MCP·SQL18개를 WSL/Docker에서 각각 통과했다. 공개 상세는 parser·컴포넌트18개를 WSL/Docker 각각 통과했고 타입·lint·프로덕션 빌드도 통과했다. 같은 시험을 합산하지 않는다. 엄격 sandbox MCP Apps 브라우저는 기존11개 통과 뒤 공유 사례의 비동기 관측/Playwright 인자 오류를 수정해 마지막1개를 통과했다. 이 하네스 실패 이력은 원장에 보존하며 제품 실패로 바꾸지 않는다. 최종 CI가 전체12개를 다시 실행한다.

n150의 Chromium에서375/1440px 공개 상세의 네 유종·목적지 링크·복사·OS 공유 mock 자료·고정GET1회·위치권한0·타일0·overflow0/pageerror0과 실제 캡처를 확인했다. n150에는 로컬 산출물과 브라우저 실행 스크립트만 전달했으며 빌드하지 않았다. 시험가격은 운영 가격이 아니며 mock 공유 성공은 실제 앱 수신 성공이 아니다. 기존 MCP Apps 반응형·실제 OSM 타일·위치 거부 뒤 직접 입력 복구 증거도 별도로 보존한다.

최종 HTML은870305byte/SHA256 `e9df6f0aba45cc3938c64d6e826098fb99950442ff640681e6e1c3468d9b9428`이며 local WSL과 local Docker ARM64 export의 bytes가 같다. Python runtime·SDK/provider·의존성 핀은 그대로다. Sites에 같은 HTML을 전달했고 중계46개와 Worker 빌드를 통과했다. 게시 성공 전에는 게시 완료로 취급하지 않는다.

첫 CI46080211943의 Node 정책 검사 실패는 실제 Node stage 투영으로 수정했다. 이전 후보33bfff59의 CI46081004852는 backend3199통과/2생략/62subtest를 포함해 전체 필수 작업 성공이었다. 새 공유 변경은 별도 최종 CI 결과를 기다린다. James/Popper 독립 검토의 응답 불일치·도구 탐색·포커스·위치 상태·공유 fallback/취소·지연 표시 지적을 수정하고 재확인했다. 최종 CI·머지·개인 Site 게시 상태는 PR/배포 원장을 정본으로 한다. Transport 운영 API·fuel web 이미지 배포·실제 MyHyundai 수신은 별도 후속이다.
