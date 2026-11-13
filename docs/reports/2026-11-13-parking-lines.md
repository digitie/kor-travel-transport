# 주차 이력·하루 흐름 ECharts 전환

## 범위와 계약

공유 주차 UI의 `history-chart.tsx`, `daily-flight-overlay-chart.tsx`의 실제 SVG 데이터 선을 공식 EvilCharts Apache ECharts line 엔진으로 바꾼다. 원 공항 PR189의 제품은 수정하지 않은 별도 후속이며 운영 API·수집·스키마·배포·생산 빌드·키 설정 변경은 없다.

- 최근 주차 이력은 API가 준 버킷 범위만 그린다. 새 미래 축이나 항공편을 섞지 않는다. 6시간 KST 눈금, 실제 마지막 관측 시각, 공휴일/토·일요일 띠를 유지한다.
- `lot_observations <= 0`인 버킷은 `null`로 전달해 선/면을 끊는다. 관측된 잔여 0대는 유효한 0이다. 원 history의 고립 관측점을 유지한다. 원 daily는 결측 버킷을 제거해 이웃 선을 연결했으므로, 이번에는 명시적인 null 단절로 고친다. API에 없는 버킷을 생성하거나 다른 날의 수치를 복사하지 않는다.
- 하루 흐름은 KST 0~24시의 고정 축과 최근 7개 관측 날짜를 유지한다. 날짜별 토글/고정 색, 휴일 점선과 말단 표시, 4배 확대, 출발·도착 토글을 유지한다. 비행편은 `scheduled_at`/`estimated_at`으로 다시 추측하지 않고 원 DTO의 `marker_at`을 KST로 배치한다.
- 항공편 hover/click은 ECharts Graphic의 실제 이벤트와 기존 native 비행편 버튼을 연결한다. 버튼은 포커스/Enter/터치로 같은 선택 정보를 제공한다. history의 native range에는 현재 시각·잔여/결측을 `aria-valuetext`로 제공하고 선택 위치로 스크롤한다.
- 두 native 수치표는 details를 열 때만 행을 생성한다. 이력의 빈 화면은 엔진을 마운트하지 않으며 Canvas 모듈은 실제 그림이 필요할 때만 동적 적재한다. history 포인터/키보드 선택은 DOM cursor/tooltip만 이동하며 memo 경계의 시계열 전체를 다시 게시하지 않는다.
- 새 CSS 변수 해석은 실제 차트 조상에서 읽어 공개/관리자 주차 테마를 모두 존중한다. 수치 형식과 제공 상태의 의미를 바꾸지 않는다.

## 원천

공식 저장소/registry와 MIT 라이선스, 재사용 commit `f4cc5aad07ce2650fc74366622d5081d16f02667`, 원문·설치 SHA와 상대 import 변형은 [별도 provenance](../../frontend/vendor/evilcharts-parking-lines.json)에 고정했다. ECharts6.1.0/Motion14.12.0/React와 기존 공통 chart·tooltip·legend는 유지한다. 패키지/lockfile/SDK 설치 규약을 바꾸지 않는다.

## 검증 기록

원문은 Git 밖 `C:/Users/digit/.codex/tmp/weather-transport-evilcharts-20261112/parking-lines-*`에 보존한다. 서로 겹치는 반복 시험을 합산하지 않는다.

- 공개 UI `parking-lines-qa-r7`: TypeScript, 전체 ESLint, full/no-cache Doctor78파일 warning0. 관리자 `parking-lines-admin-qa-r2`: TypeScript, 전체 ESLint, full/no-cache Doctor232파일 warning0. Next typegen만 실행했으며 생산 빌드는 없다.
- 최종 `parking-lines-final-tests-r3`는 WSL 21개 실제0 뒤 network:none Docker 21개 실제0으로 순서대로 통과했다. 선행 반복 결과와 합산하지 않는다. 소유 QA 컨테이너 잔여0, 자기 이름/label/연결0을 확인한 빈 시험 network만 제거했고 fixture12383포트도 비어 있다.
- Chromium156.0.8078.4 `parking-lines-browser-r6` PC1440/mobile375: 실제 canvas 높이280/320, 336개 버킷과 명시적 null/관측0, 공휴일·주말3개 띠, 실제 KST 0~1440축/7개 날짜, keyboard/hover/click/mobile tap/날짜·방향·4배축, 조상 CSS 변수 갱신, 표 DOM의 지연 생성, 실제 unmount dispose를 확인했다. history 키보드 선택 동안 전체 시계열 `setOption` 호출0도 검산했다. 두 캡처를 직접 검토했고 페이지 오류/console warning/외부 요청/문서 가로 overflow0, browser/server/부모0이다. 제조한 fixture이며 운영 데이터/운영 화면 수용은 아니다.
- 관리자는 `npm ci` 때 복사한 옛 `file:` 패키지를 계속 보유해 최초 타입 검사에서 옛 `findLast` 오류가 나왔다. 현재43파일을 `npm pack`해 이 작업 소유 node_modules만 갱신했고 주요5파일의 source/installed bytes 동일을 확인했다. archive SHA `e39d4b3425717489f50c9378b6c5e4fab7c7a4f345d513aba1b9f3fe3df1cc8c`; 다른 의존성/lockfile 변경과 SDK 재설치는 없다.

## 보존한 실패와 보정

- 최초 WSL21 통과 후 타입 검사에서 CSS module 선언/ES2023 `findLast` 호환성 오류가 드러났다. 기존 ES2022 계약을 유지해 reverse/find와 해당 CSS module 선언으로 고쳤다. 치환 보조 스크립트의 잘못된 `line.[...points]` 구문도 타입/Vite 원문을 보존하고 고쳤다.
- 최초 fixture 엔진 높이0: 부모 높이뿐 아니라 공유 컴포넌트 내부 mount의 height도 CSS module에서 보장했다. 실제 DOM은 부모280/320인데 Tailwind `h-full` mount가0인 상태였으므로 소비 앱의 utility 탐색 범위에 기대지 않도록 했다.
- actual Graphic hover 실패: ZRender hit가 flight circle 대신 series path에 잡히고 callback이 호출되지 않는 상태를 재현했다. group의 z만 믿지 않고 line/circle primitive의 z10/11을 명시했다. 선택 상태는 DOM overlay로 표현하고 stable 옵션/memo 경계로 포인터 아래 Graphic을 재게시하지 않는다.
- full Doctor의 history/daily 제어 흐름 복잡도 경고는 작은 native 컨트롤/표 표현으로 분리했다. 미사용 padding 상수 lint 오류는 제거했다. 전역/vendor 제외나 gate 예외 추가는 없다.
- fixture favicon404는 시험 HTML에 data favicon을 넣어 해결했다. console error를 필터링해 통과시키지 않았다.
- `final-tests-r2` Docker는 컨테이너/시험 시작 전에 address pool 고갈로 실제1이었다. 공용 network/daemon/prune를 변경하지 않고 외부 통신이 필요 없는 후속 QA만 Compose `network_mode:none`으로 격리했다. 이 실패를 제품 테스트 실패/성공으로 바꾸지 않는다.
- jsdom SSR 경로는 native canvas text metric 미구현 경고를 남긴다. 실제 픽셀/hover/touch 증거는 별도 실제 Chromium fixture다. 기존 Vitest native config-loader 권고도 원문에 보존한다.

## 남은 수용

소유 QA와 실제 반환값을 정산했다. 새 코드/테스트/문서만 feature branch와 stacked Draft PR로 부모에 전달한다. CI/두 독립 리뷰/머지는 부모 범위다. 운영 배포·수집 최신화·제공기관 응답 정상화·성능 p95/전국 보장으로 확대하지 않는다.
