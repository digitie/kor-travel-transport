# 주변 유가 MCP Apps UI

## 목적과 범위

OpenAI의 [MCP 서버에 UI 추가하기](https://developers.openai.com/ko-KR/plugins/build/chatgpt-ui)와 MCP Apps 표준을 따라 기존 읽기 전용 유가 MCP에 인라인 웹 UI를 연결한다. 기존 fuel 화면의 Transport 팔레트와 비교 작업 흐름을 사용한다. API·수집·원본·영구 통계 정책과 서비스 인증은 유지한다.

화면은 현재 위치 동의 또는 직접 입력 좌표, 반경1~50km, 다섯 유종, 가격순/직선거리순 상위20곳, 전체 반경의 평균·최저, 지도·목록·선택 주유소 가격과 위치, 시군구/전국 비교를 제공한다. 최근30일 그래프·브랜드/편의 필터 등 공개 fuel 전체 기능을 모두 이식했다고 주장하지 않는다. 추가 탐색은 기존 fuel 웹으로 연결한다.

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
