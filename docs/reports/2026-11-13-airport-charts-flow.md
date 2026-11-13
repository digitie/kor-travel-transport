# 공항 주차 차트·항공편·고속도로 갱신 정산

## 변경

- 공항 주차 현황과 항공편 페이지에 공식 EvilCharts ECharts 파이를 적용한다. 잔여/사용/전체 원수치와 관측 시각을 함께 유지한다. 동일 터미널에서 명시적으로 P1/P2처럼 번호만 다른 시설은 바깥쪽부터 동심원으로 표시한다. 서로 다른 터미널이나 번호 없는 동명 시설을 합치지 않는다.
- 총면수 0·범위 밖 잔여면·사용면 불일치 등은 유효한 파이로 만들지 않는다. 실제 잔여 0은 만차로 보존한다. 갱신 지연과 시각 오류도 별도로 표시한다.
- 요일/시간대 및 공휴일/토/일요일 패턴은 ECharts 직교좌표 히트맵으로 표시한다. 평균·최저·최고 잔여면, 관측 수를 호버/클릭/터치로 확인한다. 소수 평균을 반올림하지 않는다. 관측 없는 칸과 실제 0을 구별하고 기존 수치 표는 접어서 제공한다. 리뷰 P1을 반영해 각 유효 셀의 native details/summary에서 같은 평균·최저·최고·관측 수를 키보드/스크린리더로도 모두 얻을 수 있게 했다.
- 공항·주차장 변경이나 탭 이탈 시 분석 요청의 AbortSignal도 취소한다. 이전 응답의 화면 적용 차단과 함께 불필요한 진행 중 HTTP 요청을 줄인다. 읽기 신선도/TTL/원본 보존 정책은 바꾸지 않는다.
- 항공편 필터와 표시 시각을 같은 함수로 통일한다. 유효한 변경 예정 시각은 그대로 우선하고, 빈/잘못된 변경 시각만 유효한 원래 예정 시각으로 대체한다. UTC/KST 오프셋에 추가 시간을 더하지 않는다. 실제 앞당긴 시각을 원래 시각으로 되돌리지 않는다.
- 고속도로 통계 화면은 기존에 최초/수동/노선 변경 때만 저장 자료를 읽고, 60초 타이머는 시계만 갱신했다. 장시간 열린 화면에서 새 수집이 있어도 옛 관측이 15분 기준에서 빠질 수 있었다. 표시 중 60초마다 교통 관측 저장 API만 재조회하고 숨은 화면에서는 멈추며 복귀 시 다시 읽는다. 무거운 전체 통계 기반 노선 선택지는 최초/수동 갱신에만 조회해 유가 등 무관한 집계를 매분 반복하지 않는다. 실패 시 기존 수치를 보존하고 오류를 표시한다. 제공기관을 직접 호출하거나 수집을 기동하지 않는다.

## 기존 수정 확인과 남은 외부 제약

- main의 기존 공항 캐시는 10분 상한, 새 collected_at 무효화, 지연된 과거 관측 무효화, 파생 캐시 실패와 원본 commit 분리, 정상 중복 tick의 캐시 복구를 이미 구현했다. 이 구조를 다시 만들지 않고 격리 PostgreSQL의 수집→캐시→API 회귀로 확인한다.
- 고속도로 5분 집계는 수집 트랜잭션에서 최근 2시간과 과거 정정 bucket을 갱신한다. 제공기관 실패/제한과 결측 속도를 0으로 바꾸지 않는다. 화면의 15분 유효 관측 기준을 없애거나 영구 집계를 현재 교통 상태로 위장하지 않는다.
- 정상 backend FlightStatusItem.estimated_at은 datetime 또는 null이다. 이번 빈 문자열/잘못된 시각 처리는 UI 경계의 방어 수정이며 실제 제공기관 빈 결과의 원인이라고 단정하지 않는다. KAC/인천 응답, 수집일, quota/인증/비활성 상태를 운영에서 다시 호출하거나 설정을 활성화하지 않았다. 원래 운영의 빈 항공편/수집 지연이 모두 해결됐다는 증거는 아니다.
- 원본 48시간 목표/영구 통계/prune OFF와 운영 수집·환경은 변경하지 않는다. 자동 archive/backfill/재수집/이미지 빌드/배포는 수행하지 않았다.

## 벤더 출처

`frontend/vendor/evilcharts-parking.json`에 공식 registry payload·원문·로컬 파일 SHA256를 기록한다. MIT LICENSE를 배포 패키지에도 포함한다. 공통 UI helpers는 Weather PR228(main 179e4a9)의 정밀 숫자 tooltip 수정을 유지하고 상대 import로 재배치한다. strict 접근성 lint가 발견한 원본 클릭 div 범례는 클릭 가능할 때만 native button/aria-pressed로 좁게 수정하고 비클릭 범례는 정적 div로 유지한다. 공식 calendar heatmap의 chartOptions 확장점으로 시간×요일 행렬을 구성하며 선택 콜백은 native dataIndex를 받도록 좁게 확장한다. 화면에 가짜 날짜를 생성하지 않는다. echarts 6.1.0, motion 14.12.0을 고정한다.

## 검증

- 격리 PostgreSQL 18 마이그레이션과 공항 캐시/지연 관측/실패 후 복구·고속도로 집계/독립 소스 commit 회귀: WSL 16개, Docker 16개 통과. 각 실행은 PostgreSQL 경로 15개와 기존 SQLite 전용 사전집계 조회 1개이며 같은 시험을 합산하지 않는다. 정확한 CID/task label을 검산한 테스트 DB만 종료·제거했다. Docker 읽기 전용 pytest cache 경고 1건을 보존한다.
- public frontend 소스/시험 TypeScript와 관리자 TypeScript 검사 통과. 변경 파일 lint, 관리자 공통 의존성/산출물 검사는 통과했다.
- public WSL 첫 forks 실행은 API/Context 26개 통과 후 worker 시작/종료 응답 timeout 3건으로 CLI 1이었다. R2는 API 13·취소/선택 훅 17·주차 차트 5개 통과, 변경된 AbortSignal 인자를 반영하지 않은 기존 분석 기대값 2개 실패와 Context worker 시작 timeout 1건으로 CLI 1이었다. 원문을 보존하고 기대값을 수정했다.
- public R3은 분석 7·Context 13·주차 차트 5개, 합계 25개로 CLI 0이다. R4의 공식 범례 키보드/파이/행렬 6개와 vendor 포함 strict lint도 CLI 0이다. 서로 겹친 차트 시험은 합산하지 않는다. 범례 전체 표시 상태의 aria-pressed와 정상 DTO 토글을 포함한 후속 검증은 아래 Docker/fixture 결과로 확인했다.
- 관리자 WSL은 항공편 시각 6·기존 journey 상태 4·고속도로 갱신 2개, 합계 12개 통과다. 자동 갱신의 무관한 통계 재조회를 제외한 고속도로 2개와 정상 DTO 항공편 토글 1개는 후속 WSL에서 통과했다(기존 12개와 겹쳐 합산하지 않음). Docker UI 첫 실행은 읽기 전용 mount 아래에 없는 .vite-temp tmpfs mountpoint를 만들지 못해 두 컨테이너 모두 프로세스 시작 전 CLI 1이었다. 실패와 잔여 컨테이너 0을 보존하고 Git 밖 소유 node_modules에 빈 mountpoint만 만든 별도 R2는 public 56개/관리자 13개 모두 CLI 0으로 완료됐다(제품 197418c 기준).
- 실제 ECharts SVG 엔진의 동심원/행렬 옵션 렌더도 포함한다. jsdom의 native canvas 문자 측정 미지원 경고를 보존하며 실제 브라우저 픽셀 검증으로 사용하지 않는다.
- 비공개 키는 source/staged/new log에서 값을 출력하지 않고 부재 검사했다. 후속 커밋도 같은 방식으로 다시 확인한다.
- Chromium 156 fixture의 PC 1440/mobile 375에서 실제 파이 2개 원·두 히트맵의 canvas 크기/정밀 숫자·0/결측·호버/터치 상세·범례 Enter/Space를 확인했다. 원 첫 fixture는 브라우저 actual 0이나 dev server SIGTERM 143을 부모가 실패로 분류해 CLI 1이었다. 원 143/실패를 보존하고 잔여 프로세스 0을 확인했다.
- P1 후속은 WSL 13개/시험 TypeScript/lint 0이다. 별도 fixture R2는 키보드 Enter로 외부 수치표와 각 셀 상세를 열어 평균 0.125/최저 0/최고 1/관측 8개를 읽고 1440/375 모두 overflow/pageerror/외부 요청 0을 확인했다. 브라우저 0·HTTP 정상 종료한 dev server 0이며 캡처도 직접 검토했다. P1 집중 Docker도 동일 13개/CLI 0이다. 선행 56개와 겹치는 시험을 합산하지 않는다.
- 앱/제품 이미지 빌드·운영 배포는 수행하지 않았다. 위 브라우저는 제조된 시험 자료의 독립 fixture이며 운영 화면/API 수용이 아니다.

## 원 CI 실패와 후속 수정

- 제품197418c의 CI43329668779/frontend job131570919657 원문은 새 React Doctor warning 5개로 실패했다. 두 공식 차트의 full-motion import 2개, compound 선언 크기 2개, 새 주차 파이 래퍼의 render Date.now 1개다. 기존 코드 실패로 돌리거나 원 실패를 PASS로 바꾸지 않는다.
- full-motion factory는 LazyMotion/domAnimation + motion/react-m의 m 요소로 바꿨다. useReducedMotion과 원 로딩 애니메이션은 보존한다. compound renderer/slot/observer/cleanup 구조를 재작성하지 않도록 정확한 두 export 선언의 no-giant-component만 Doctor 전용 주석으로 예외 처리했다. 파일 전체/디렉터리/전역 규칙 제외나 CI gate 완화는 없으며 원문/로컬 SHA와 변형 근거는 vendor manifest에 있다.
- 시간에 따라 SSR/첫 hydration 문자열이 달라지는 원인은 서버 snapshot 0과 구독 후에만 갱신되는 useSyncExternalStore 시계로 고쳤다. 원 관측 시각/15분 기준은 보존하고 15초마다 지연 표시를 갱신하며 unmount에 timer를 정리한다.
- 시각 경계 hydration/늦은 관측 표시/타이머 정리와 기존 차트 검산은 WSL 8개와 Docker 8개 모두 CLI0이며 TypeScript/lint도 통과했다. 선행/P1 시험과 겹치는 차트 검산은 합산하지 않는다.
- 최종 React Doctor0.9.22는 --scope full --blocking warning --no-cache로 70파일 오류0/경고0/CLI0이다. 제품 production build는 로컬에서 추가하지 않았다. 수정 후 실제 CI 수용은 부모 작업이 최신 HEAD에서 확인한다.
- Chromium156 별도 fixture R3의 1440/375에서는 기존 pointer/touch/키보드 수치표/범례/0·결측·정밀 숫자와 overflow/pageerror/외부 요청0을 재확인했다. LazyMotion 파이·히트맵 로딩 표시가 실제로 나타나고 닫은 뒤 각 ECharts instance가 dispose되는 것도 확인했다. browser/server 부모는 실제0이며 원 실패/143은 별도로 보존했다.

## 별도 후속

기존 `history-chart.tsx`와 `daily-flight-overlay-chart.tsx`의 자체 SVG 시계열은 이 패치에서 변경하지 않았다. 사용자 전체 차트 전환 요청의 남은 범위이며 별도 후속에서 공식 EvilCharts line으로 옮긴다. 최근 7일 실제 관측 구간/공휴일 밴드/일별 흐름에서만 항공편 표시/날짜 토글/호버·클릭 계약을 보존해야 한다.
# main 빌드 계약 통합 후속

PR189의 제품cf905ac5에 main4b24e0d(#187)를 정상 병합했다. 충돌은 journal/resume/tasks
세 문서뿐이며 양쪽 이력을 보존했다. 앱 소스는 cf905와 동일하고 public/admin lock 설치
그래프도 동일하다. scripts·Node22.23.1/npm12.0.1·strict 설치·nonroot Dockerfile·workflow·
빌드 helper는 main을 유지한다. public/admin 공통 의존성 검사와 public/시험/admin 타입은0이다.
원문은 Git 밖 `airport-main-merge-source.json`, `airport-main-integration-qa-20261113/results.json`이다.
기존 기능 시험을 반복 합산하거나 빌드 실행으로 쓰지 않는다. 새 통합 head의 실제 CI는 아직 별도다.

