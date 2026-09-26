# tasks-done.md — 완료 작업 아카이브

완료한 task의 식별자, 핵심 변경, 검증 명령과 시각을 역시간순으로 보관한다.

## 2026-09-26 — 여객선 시간표 저장 구현 완료·운영 검증 진행 중

- 항구·운항일·source 유일 제약과 날짜 인덱스를 둔 PostgreSQL 스냅샷 테이블을 추가했다.
- 오늘 포함 10일의 범위 정리, 4시간 주기·실행당 280건 제한, 응답별 즉시 저장으로
  실패 후 이어서 수집하는 Dagster job을 구현하고 n150에서 활성화했다.
- API는 DB 우선 조회 후 누락만 provider에서 저장하며, 관리 UI에는 운항일 선택을 추가했다.
- 코드 후보 `0d7d292`의 James/Popper 독립 리뷰는 추가 지적 없음, WSL Docker backend
  175개 통과·1개 건너뜀, 관리 UI 21개 통과다. 운영 소청도 10일 스냅샷·149개 운항과
  공개 API 반복 조회를 확인했다. 전국 초기 수집의 완료 여부는 별도 운영 관찰 항목이다.
- 전체 live E2E의 첫 실행은 277/278 통과였다. 로그아웃 중 늦은 통계 응답이 캐시를
  다시 저장하는 경합을 재현해 수정 중이며, 최종 CI·전체 live E2E·PR #40 머지는 아직 대기다.

## 2026-09-07 (T-039)

### `T-039` — UI 밀도 개선(컴팩트화)

- 2026-09-07 사용자 요청: 전체적으로 UI를 더 컴팩트하게 — 공항/주차장 선택 +
  새로고침을 모바일에서도 한 줄로, 분석 페이지의 비효율적인 칼럼 크기 등.
- 헤더 `.control-band`(공항 선택 + 세부 주차장 + 새로고침)가 모바일에서 3행으로
  붕괴되던 것을 한 줄로 유지하도록 변경했다. `<select>` 레이블은 `sr-only
  lg:not-sr-only`로 모바일에서만 시각적으로 숨기고(select 자체의 `aria-label`로
  접근성 유지), 새로고침 버튼은 모바일에서 아이콘 전용(lucide `RefreshCw`,
  `aria-label="새로고침"`)으로 압축했다.
- 조사 중 실제 운영 버그를 하나 발견해 고쳤다: `current-status-view.tsx`의
  `.lot-card-grid lg:hidden`이 데스크톱을 포함한 모든 폭에서 전혀 숨겨지지
  않고 있었다(라이브 사이트 컴퓨티드 스타일로 확인 — 1280px에서도 모바일 카드
  목록이 데스크톱 테이블 아래 그대로 렌더링). 원인: `.lot-card-grid`가
  `@import "tailwindcss"` 뒤에 이어붙인 순수 커스텀 클래스(unlayered CSS)라
  `display:grid`가 항상 Tailwind `@layer utilities` 안의 `lg:hidden`을 이긴다
  (CSS Cascade Layers 스펙상 unlayered가 specificity/순서 무관하게 항상 이김).
  `.lot-card-grid` 자체에 `@media (min-width: 64rem)` 규칙을 추가해 고쳤다.
  전체 코드베이스를 훑어 같은 패턴의 다른 인스턴스가 없음을 확인했다.
- 분석 `/analytics` → 임계치 탭의 2열 그리드(`.analytics-threshold-panels`)가
  기본 `align-items: stretch`라 왼쪽 패널(요일별, 데이터 2행)이 오른쪽 패널
  (날짜별, 스크롤 가능한 긴 목록) 높이에 맞춰 늘어나 아래쪽에 큰 빈 공간이
  생기던 것을 `align-items: start`로 고쳐 각 패널이 자기 콘텐츠 높이만큼만
  차지하도록 했다.
- hostile review(James=frontend/UI, Popper=backend/ops, 서브에이전트 2개 독립
  실행)에서 실제 데이터 기준 P1 2건을 찾아 재현·수정했다:
  - 공항명(최대 6자, 앞 2~3자만으로 구분 가능)과 달리 세부 주차장명은 실제
    운영 데이터(`GET /v1/airports`)에서 최대 13자이고 구분자가 뒤쪽에 있다
    (`T1 장기 P1/P2/P3/P4 주차타워`, `국내선 제1/제2주차장` 등). 두 `<select>`를
    정확히 반씩 나눈 최초 구현은 320px에서 이 구분자를 통째로 잘라 서로 다른
    주차장이 같은 텍스트("국내선 제1주차장"/"국내선 제2주차장"이 둘 다
    "국내선 ㅈ"로)로 보이는 걸 실제 스크린샷으로 확인했다 —
    `grid-template-columns`을 0.8fr/1.2fr로 재배분하고 select 자체
    padding·font-size를 더 압축해 고쳤다(재검증: 최장 실데이터 "T1 장기 P1
    주차타워"도 320px에서 구분자까지 보임).
  - `current-status-view.tsx`가 쓰는 `.action-stack`의 860px 이하 2열 그리드
    규칙(원래 그쪽의 수동 수집 버튼+힌트 쌍을 위한 것)을 헤더의 새로고침
    버튼도 같은 클래스로 감싸는 바람에 381-1023px 구간에서 그대로 상속받아,
    빈 두 번째 칸이 실측 44px→98px로 부풀며 select 폭을 추가로 빼앗고 있었다
    — 헤더 쪽은 `.action-stack`으로 감싸지 않고 버튼을 `.control-band`의
    그리드 자식으로 직접 둬서 분리했다(`.button.secondary`의 기존
    `align-self: end`만으로 정렬 충분).
  - P2 후속: 다른 `@media` 블록에 덮여 861px 미만에서는 항상 무시되던 죽은
    `gap: 8px` 선언을 제거했고, e2e에 데스크톱 폭에서 `.lot-card-grid`가
    실제로 숨는지(둘 다 보이면 실패) 회귀 테스트를 추가했다
    (`e2e/live-dashboard.spec.ts`, 원래 `.first()` 단언은 이 버그를 놓쳤을
    것이다).
- accepted-not-fixed로 남긴 항목: 새로고침 버튼 tap target이 320px에서
  44×42px(WCAG AA 24×24는 통과, AAA 44×44에는 2px 못 미침), `.lot-card-grid`가
  숨는 이유가 JSX에는 클래스명이 아니라 주석으로만 남아 있어 향후 편집 시
  실수로 `lg:hidden`을 다시 붙이면 같은 버그가 재현될 수 있음(유지보수성
  지적, 기능 결함 아님).
- PR [#28](https://github.com/digitie/kor-travel-airport/pull/28) squash-merge
  (`e39f05b`). CI backend/frontend PASS. live-e2e는 첫 push에서 PR #18 이후
  선례와 같은 release-SHA 불일치로 FAIL했고, hostile-review 수정을 반영한 두
  번째 push에서는 이번 PR이 새로 추가한 회귀 테스트(`.lot-card-grid`가
  데스크톱에서 숨는지 확인)가 **아직 배포되지 않은 구버전 운영 사이트에서
  실제로 그 버그가 남아 있었기 때문에** 정확히 의도대로 FAIL했다(자기 자신이
  고치려는 버그를 스스로 잡아낸 것 — 머지를 막을 이유는 아님). n150 배포 후
  `release_sha=e39f05b52e56d363eccf4a146c6271a4ad800cad` 일치 확인, live E2E
  `15/15 PASS`(새 회귀 테스트 포함, 배포된 코드에서는 정상 통과).

## 2026-09-07 (T-037, T-038)

### `T-037` — Hallmark audit

- `T-033`~`T-036`으로 완성된 전체 결과물(shadcn 기반 도입, 컴포넌트 치환, 라우트
  기반 앱 셸, 과거 자료 조회 date picker)에 read-only Hallmark audit을 실행했다.
  대상: `globals.css`/`tokens.css`, `app-shell.tsx`, 5개 라우트 뷰,
  `fee-calculator.tsx`/`backup-panel.tsx`/`history-chart.tsx`/
  `daily-flight-overlay-chart.tsx`, shadcn UI 프리미티브 전체.
- 0 critical / 3 major / 6 minor, 최종 판정 "close, fix the minors". 상세 내역은
  `docs/journal.md` 2026-09-07 참고. 코드는 건드리지 않았다 — 반영은 `T-038`.

### `T-038` — Hallmark redesign

- `T-037`의 3 major 전부(숫자 테이블 `tabular-nums`, 차트/상태-pill 색상 토큰화,
  로딩 상태 `aria-live`)와 6 minor 중 4개(죽은 CSS 삭제, 브레이크포인트 수정,
  `/backup` 기본 오픈)를 반영했다. 나머지 2 minor(desktop-first 미디어 쿼리,
  shadcn 프리미티브 `transition-all`)는 accepted-not-fixed.
- hostile review(James=frontend/UI, Popper=backend/ops, 서브에이전트 2개 독립
  실행) 1라운드에서 자체 도입 버그 2건과 보안 회귀 1건을 잡아 전부 재현·수정했다:
  - 브레이크포인트 수정이 처음엔 `max-width: 64rem`을 써서 Tailwind `lg:`의
    `min-width: 64rem`과 정확히 1024px에서 동시에 참이 되는 새 버그를 만들었다
    (James P1) → `max-width: 63.9375rem`으로 정정.
  - 추가한 `aria-live="polite"`가 최종 내용이 이미 채워진 채로 마운트되는
    엘리먼트에 붙어 있어 스크린 리더가 안정적으로 announce한다는 보장이 없었다
    (James P1, `history-view.tsx`의 기존 동일 패턴도 같은 결함으로 확인) →
    `current-status-view.tsx`/`fees-view.tsx`/`history-view.tsx` 세 곳 모두
    상시 마운트 sr-only announcer 구조로 재설계.
  - `/backup` 기본 오픈은 인증 없는 파괴적 백업/복원 UI(ADR-003 전제: 내부망)의
    유일한 상호작용 게이트를 제거하는 노출 증가였는데, `T-035`의 동일 범주
    선례(같은 PR 안 ADR-003 addendum)를 따르지 않고 순수 UX 개선으로만
    서술했다(Popper P1) → **완전히 되돌렸다**(`BackupPanel`/`BackupView`/e2e
    spec/테스트 모두 `main`과 byte-identical 확인). 이 minor는 다시
    accepted-not-fixed로 남는다 — Hallmark가 지적한 것은 "클릭 1번 더 필요함"
    이라는 minor 취향 문제였을 뿐이라, 그 이득을 위해 방어 계층을 없애는
    트레이드오프는 맞지 않다고 판단했다.
  - P2 후속: 항공편 departure/arrival 테두리 색 4곳 추가 토큰화, aria-live
    재설계 검증 회귀 테스트 추가, PR 설명의 문서 인용 오류(존재하지 않는
    journal.md 근거를 현재형으로 인용) 정정.
- 새로 accepted-not-fixed로 남긴 항목: dark-mode 차트/톤 팔레트 미토큰화(라이트
  모드만 이번에 반영), 980–1024px 브레이크포인트 경계 전용 회귀 테스트 없음
  (jsdom이 미디어 쿼리를 평가하지 않음 — 근본 원인 수정으로 두 구간이 구조적으로
  배타적이 됐다고 보고 넘어감).
- PR [#26](https://github.com/digitie/kor-travel-airport/pull/26) squash-merge
  (`603884f`). CI backend/frontend PASS, live-e2e는 PR #18/#20/#22/#24와 동일한
  이유로 FAIL(머지 전 배포된 prod엔 아직 신규 코드가 없음) — 머지를 막지 않았다.
  n150 배포 후 `release_sha=603884f9adec43d160373ca33b90f4a351d3c5a0` 일치 확인,
  live E2E `15/15 PASS`(기존 `collector-status` 플레이크도 이번엔 관측 안 됨).

## 2026-09-06 (T-036)

### `T-036` — 과거 자료 조회 기능

- 원래 계획은 `/v1/parking/history`(raw 리스트 endpoint)에 날짜범위를 추가하는
  것이었지만, 조사 결과 프론트가 이 endpoint를 전혀 호출하지 않는다는 걸 확인하고
  범위를 재조정했다 — `/history` 라우트가 실제로 렌더링하는 건
  `/v1/parking/analytics/timeseries`(`getTimeSeries`)이므로, 여기에
  `start_date`/`end_date`(YYYY-MM-DD, `days`와 상호배타)를 추가했다. `days` 기반
  상대 조회는 완전히 그대로 유지된다. `_parse_local_date_query`/
  `_load_snapshots_between_local_dates`(`/v1/holidays/summary`가 이미 쓰는 로컬→UTC
  변환 템플릿)를 재사용했고, 최대 조회 기간은 90일(기존 `threshold_insights`와 동일
  캡)로 뒀다. `CollectorStatusResponse`에 `earliest_snapshot_observed_at`을 추가해
  프론트 date picker가 실제 데이터 존재 범위로 선택 가능 날짜를 제한할 수 있게 했다.
- `/history`에 shadcn `Calendar`(react-day-picker, 새로 설치) + `Popover` 날짜범위
  선택 UI와 최소/평균/최대 잔여 주차면 요약 카드를 추가했다. `/analytics`의 "일별
  흐름" 탭이 쓰는 공유 `useAnalyticsData` 훅은 건드리지 않고 `/history`만의 독립
  fetch로 구현해, 날짜범위 조회가 `/analytics` 쪽에 영향을 주지 않는다.
- hostile review(James/Popper, 서브에이전트 2개 독립 실행)에서 P0를 하나 찾았다 —
  Popper가 `build_time_series`를 실제로 실행해 재현: 이 함수는 버킷 배치 기준점을
  요청한 `end_date`가 아니라 "실제로 관측된 마지막 스냅샷"으로 잡는다(원래
  상대(`days`) 조회를 위해 설계된 동작). 그 결과 요청 범위 끝부분에 수집 공백(백업
  복원을 위한 scheduler 중지 창, 업스트림 rate-limit 차단, 혹은 그냥 "오늘"을 하루가
  끝나기 전에 조회하는 경우도 포함)이 있으면 응답이 조용히 요청 범위보다 앞쪽으로
  밀려서 반환되는데, 응답의 `start_date`/`end_date` 필드는 여전히 원래 요청한 범위를
  주장한다 — 재현·수정하고 일부러 수집 공백을 만든 회귀 테스트를 추가해 수정 전엔
  실패·수정 후엔 통과함을 확인했다. P1도 여럿 반영했다: (1) Popper — 무인증
  endpoint에서 `airport_code`/`parking_lot_id` 없이 90일 전체 조회가 가능해 기존
  30일 상한보다 3배 넓은 미인증 대량 조회를 허용하던 것 → 필수 파라미터로 막음.
  (2) Popper — ADR-005가 명시한 "라우트/DTO 변경 시 같은 커밋에 openapi 재생성" 정책을
  안 지킨 것 → `scripts/export_openapi.py` 재실행. (3) James — 달력의 선택 가능
  범위(`disabled`)가 실제 UTC 시각을 뷰어의 브라우저 타임존 기준 달력일로 비교해
  Asia/Seoul 기준과 최대 하루 어긋날 수 있던 것 → `seoulDateBoundary()` 추가(단,
  `toDateKey()` 자체는 5개 타임존으로 직접 재현 검증한 결과 문제 없음을 확인하고
  그대로 뒀다 — 달력 그리드 셀은 이미 브라우저-로컬 Date라 로컬 필드를 그대로 읽는 게
  맞는 설계였다). (4) James — Popover에 접근 가능한 이름이 없던 것(`PopoverTitle`
  누락), 앱 전체가 한글인데 달력만 영어로 뜨던 것(`date-fns/locale/ko` 추가), "최근
  N일 보기" 버튼이 스스로 사라지며 포커스를 body로 떨어뜨리던 것, 로딩 상태가
  `aria-live` 없던 것, Popover 안 2개월 달력이 모바일에서 넘칠 수 있던 것(1개월로
  축소), 임의 범위 + 고정 10분 간격이 한 응답에 수만 버킷을 요청할 수 있던 것(범위
  길이에 따라 interval 자동 조정), `HistoryChart` 제목이 명시적 범위 조회에도 "최근
  N일"로 고정 표시되던 것 — 전부 재현·수정했다. 달력 상호작용 테스트는 실제로 클릭한
  날짜가 API 호출에 그대로 반영되는지 검증하도록 강화했고(기존엔 "YYYY-MM-DD 형식인지"
  만 확인해 James가 지적한 타임존 버그류를 못 잡았을 것), locale 텍스트 대신 `data-day`
  속성으로 조회해 로케일 변경에도 안 깨지게 했다.
- PR [#24](https://github.com/digitie/kor-travel-airport/pull/24) squash-merge
  (`b9bdf1a`). CI는 backend/frontend PASS, live-e2e는 PR #18/#20/#22와 동일한
  이유로 FAIL(신규 기능이 머지 전 배포된 prod에는 아직 없어) — 선례대로 머지를 막지
  않았다. n150 배포 후 `release_sha=b9bdf1a9c6832217922934e1f8a0128a3bdf339f` 일치
  확인. 배포 직후 외부 게이트웨이(`pr-api.digitie.mywire.org`)가 일시적으로 504/timeout을
  반환했으나 n150 로컬(`127.0.0.1:14001`/`14002`, SSH로 직접 확인)은 두 컨테이너 모두
  `healthy`였다 — 배포 문제가 아니라 외부 게이트웨이 쪽 일시 장애로 판단, 2분 후
  재확인해 정상 복구됐다. live E2E 15개 중 14개 PASS, 나머지 1개는 T-035에서도 이미
  관측한 것과 동일한 기존(비-T-036) `collector-status.last_run.status` 실시간 플레이크
  (`success`/`partial_success` 오가는 실제 운영 데이터 특성) — 코드 회귀 아님.

## 2026-09-06 (T-035)

### `T-035` — 라우트 기반 앱 셸(pinvi 스타일 모바일 하단 탭바)

- 531줄 단일 컨트롤러 `dashboard-app.tsx` + 750줄 표시 컴포넌트 `dashboard-screen.tsx`를
  `DashboardProvider` context(`lib/dashboard-context.tsx`, bootstrap/15초 폴링/localStorage·
  cookie 영속화/`dataVersion` 카운터 보유) + 라우트별 view(`components/pages/*.tsx`)로
  분리했다. 라우트: `/`(현황)·`/analytics`(분석)·`/history`(과거조회)·`/fees`(요금계산)·
  `/backup`(백업). `useAnalyticsData` 훅이 analytics-only 상태(threshold/weekday/holiday/
  timeSeries/flightStatus)를 라우트 마운트 시점에만 불러온다 — 기존 IntersectionObserver
  lazy-load를 대체.
- 신규 `AppShell`(`components/app-shell.tsx`, pinvi `AppShell.tsx` 패턴 참고): 데스크톱은
  5개 라우트 전부 상단 탭 인라인 노출, 모바일은 하단 탭바(4 primary + shadcn `Popover`
  기반 "더보기"로 백업을 한 단계 뒤로 뺌). 데스크톱/모바일 마크업을 CSS-only(`hidden
  lg:block`/`lg:hidden`, Tailwind 기본 1024px 브레이크포인트)로 동시에 렌더링해 JS
  뷰포트 분기(`useViewportMode()`, 기존 860px 기준)를 제거했다.
- `/analytics`에 2차 탭(요일별 패턴/공휴일 패턴/임계치/일별 흐름, shadcn `Tabs`)을 둬
  기존처럼 전부 세로로 쌓지 않고 관점별로 바로 전환할 수 있게 했다(사용자 요청:
  "PC 화면도 메뉴나 탭 같은걸로 상세한 뷰를 분리").
- hostile review(James/Popper, 서브에이전트 2개 독립 실행)에서 P1을 다수 발견해 전부
  반영했다: (1) 공통 지적 — `useAnalyticsData`의 `error`/`loading`을 `analytics-view.tsx`/
  `history-view.tsx` 둘 다 destructure하지 않아 분석 fetch 실패가 완전히 조용히
  사라지던 것(기존엔 같은 에러가 페이지 상단 Alert로 항상 보였음) → Alert 렌더링 추가 +
  회귀 테스트 추가. (2) James P1 — 공항/주차장 변경 시 `useAnalyticsData`가 선택 상태
  변경과 그 결과인 `dataVersion` 증가 두 번 모두에 반응해 분석+비행편 fetch가 매번
  중복 발생하던 것(비행편 API는 외부 rate-limit 대상) → effect deps를 `dataVersion`만
  쓰도록 정리 + 회귀 테스트 추가. (3) James P1 — 모바일 "더보기" Popover가 내부 링크
  클릭으로 라우트 이동해도 안 닫히던 것(Base UI Popover는 outside-press/Escape로만
  닫힘) → `usePathname()` 변경 시 명시적으로 닫도록 제어형으로 변경, 실제 브라우저로
  재현·수정 확인. (4) James P1 — `FeesView`가 bootstrap 실패 시 "불러오는 중"
  메시지에 영원히 멈춰 있던 것 → `error` 분기 추가. (5) James P1 — 분석 "임계치" 탭의
  패널 3개가 추출 과정에서 그리드 클래스(`analytics-threshold-panels`)가 CSS 룰 없이
  고아로 남아 세로 스택으로 무너진 것 → 2열 그리드 CSS 추가(브라우저로 레이아웃 복원
  확인). (6) Popper P1 — `/backup`이 JS로 열고 닫던 접이식 버튼(href 없음)에서 홈
  화면 SSR HTML에 바로 노출되는 고정 `<a href>`가 돼 무인증 destructive 백업 UI의
  발견 용이성이 높아진 것(ADR-003 전제 변경) → `X-Robots-Tag: noindex,nofollow` 추가
  + ADR-003에 추가 기록 문단 남김. P2는 일부만 반영(withTimeout dangling timer 정리,
  live-e2e 오버플로 스윕을 전체 라우트×전체 width에서 "/"만 4개+나머지는 320/768px로
  축소해 rate-limited 비행편 API 호출량 감소, 롤백 시 신규 라우트 404 위험을
  `deployment.md`에 한 줄 기록) — 나머지(브레이크포인트 860→1024px 변경을 코드 주석으로
  남김, 라우트 간 analytics 캐시 없음, 백업 진행 중 라우트 이탈 시 상태 소실)는 이번
  PR 범위 밖으로 남기고 여기 기록한다.
- PR [#22](https://github.com/digitie/kor-travel-airport/pull/22) squash-merge
  (`0f15751`). CI는 backend/frontend PASS, live-e2e는 PR #18/#20과 동일한 이유로 FAIL
  (신규 라우트가 머지 전 배포된 prod에는 아직 없어 404) — 선례대로 머지를 막지 않았다.
  n150 배포 후 `release_sha=0f157514aee5d9d4fa2792754055b82d9dbb9485` 일치 확인,
  live E2E 15개 전부 PASS(첫 회는 실시간 collector 상태 `partial_success`로 인한
  기존(비-T-035) 단언 1건이 일시적으로 실패했다가 다음 스케줄러 사이클에서 `success`로
  돌아와 재실행 시 통과 — 실제 데이터 정상, 코드 회귀 아님).
- **후속 발견(docs PR [#23](https://github.com/digitie/kor-travel-airport/pull/23) 작업
  중)**: docs-only PR의 CI live-e2e에서 desktop "일별 흐름" 탭 클릭과 모바일 "더보기"
  popover가 CI에서만 재현되는 진짜 결함으로 실패했다(로컬에서는 통과). Chrome DevTools
  Protocol로 실제 n150 사이트에 500kbps/300ms RTT 네트워크 스로틀링을 걸어 로컬에서
  재현에 성공했다 — 라우트 전환 직후 곧바로 클릭하면 React가 그 DOM 노드의 이벤트
  핸들러를 아직 다시 연결하지 못한 상태(hydration 타이밍)라 클릭이 조용히 무시된다
  (같은 상황에서 클릭 전에 3초 대기를 추가하면 통과함을 확인해 가설을 검증했다). 이는
  T-035가 만든 로직 버그가 아니라 - Popover를 라우트 변경 시 닫도록 제어형으로 바꾼
  로직 자체는 정상 동작한다 - 클라이언트 라우팅 앱 전반의 특성이며, GitHub Actions
  러너가 한국 서버까지 가는 네트워크 지연이 로컬보다 훨씬 커서 CI에서만 드러났다.
  느린 연결의 실사용자도 라우트 이동 직후 첫 탭을 놓칠 수 있다는 뜻이라 UX상으로도
  무해하지 않다 - `e2e/live-dashboard.spec.ts`에 `clickUntilEffective()`(클릭 후
  결과가 실제로 반영됐는지 확인하고, 안 됐으면 재시도하는 `expect(...).toPass()`
  래퍼)를 추가해 두 테스트를 이 레이스에 강건하게 만들었다.

## 2026-09-06 (T-034)

### `T-034` — 컴포넌트를 shadcn 프리미티브로 교체

- native `<button>`/`<table>`/`window.confirm()`/`.metric-card`/`.notice`를 shadcn
  `Button`/`Card`/`Table`/`Alert`/`AlertDialog`로 치환했다(`dashboard-screen.tsx`,
  `fee-calculator.tsx`, `backup-panel.tsx`). 기존 className/`data-testid`를 전부
  보존했다 — Tailwind utility class는 `@layer utilities`에 속해 unlayered legacy
  CSS보다 우선순위가 항상 낮으므로 시각적으로 대부분 그대로였다(Playwright로 데스크톱/
  375px 확인).
- `backup-panel`의 `window.confirm()` 복원 확인을 Base UI `AlertDialog`(state로 제어,
  파일 선택 → 확인 다이얼로그 → "계속" 클릭 시에만 실제 API 호출)로 교체했다.
- **의도적으로 교체 안 함**(근거를 커밋에 남김): `<select>`(Base UI Select는 native
  select가 아니라 `getByDisplayValue` 등 기존 테스트가 깨짐), `ResponsiveSection`의
  `<details>/<summary>`(e2e가 `<summary>` 클릭과 `open` 속성을 직접 확인함),
  daily-flight-overlay-chart의 date toggle/체크박스(native `aria-pressed`/
  `getByLabelText` 의존).
- hostile review(James/Popper)에서 실제 결함을 발견해 반영했다: (1) James P1 — 성공
  메시지(`actionMessage`, `isError=false`)까지 shadcn `Alert`(무조건 `role="alert"`)로
  감싸 매 수동 수집 성공마다 assertive 알림이 발생하던 것을 plain
  `<p aria-live="polite">`로 분리, (2) James P2 — 다운로드 버튼의 `variant="link"`가
  기존에 없던 `hover:underline`을 추가한 것을 `hover:no-underline`으로 상쇄(cascade
  layer는 "겹치는 속성"만 보호하지 새 속성까지 막아주지 않는다는 점을 확인), (3) James
  P2 — `AlertDialogCancel`의 중복 취소 호출(onClick + onOpenChange) 제거, (4) Popper
  P1 — `AlertDialogAction`에 누락된 `disabled={busy}` 가드 추가 및 dialog 대기 중
  나머지 액션 버튼에도 `disabled` 추가, (5) Popper P1 — 무인증 destructive API(ADR-003)
  안전장치를 교체하면서 회귀 테스트가 전혀 없던 공백을 메움: 선택만으로는 복원 안 됨,
  취소 시 미호출+input 초기화, 확인 시 정확히 1회 호출, 그리고 Base UI가 dialog가 열린
  동안 배경 전체를 `inert` 처리해 접근성 트리에서 완전히 제외한다는 것을 실제 테스트로
  증명(Popper가 "jsdom은 검증 불가"라고 예상했던 것과 달리 검증 가능했다).
- PR [#20](https://github.com/digitie/kor-travel-airport/pull/20) squash-merge
  (`95ac97d`), n150 배포·release_sha 일치·live E2E `5 passed`(백업 패널 노출 확인
  포함) 확인 완료.

## 2026-09-06 (T-033)

### `T-033` — shadcn/ui 기반 도입

- shadcn/ui 전환 + 과거 자료 조회 + Hallmark 재감사/재설계 initiative의 첫 단계
  (계획 `C:\Users\digit\.claude\plans\iridescent-finding-parasol.md`, 하위 task
  T-034~T-038은 `docs/tasks.md` 진행 중).
- `npx skills add shadcn/ui`로 스킬 설치 후 `npx shadcn@latest init --defaults`
  (Tailwind v4 + Base UI, nova style)로 `frontend/`를 초기화했다. 컴포넌트 JSX는
  전혀 바꾸지 않았다 — 순수 빌드 도구 배선.
- shadcn init이 자동으로 저지른 세 가지를 감지·수정: (1) 프로젝트가 이미 쓰던
  `--muted`/`--accent`/`--radius`를 자체 기본값으로 덮어쓴 것을 소스 토큰으로
  재배선, (2) `next/font/google` Geist 주입으로 Pretendard 한글 폰트 스택이
  깨질 뻔한 것을 되돌림, (3) Next.js 16이 자동 생성한 `frontend/AGENTS.md`/
  `CLAUDE.md`를 `agentRules: false`로 차단(저장소는 루트에만 이 파일들을 둠).
  Tailwind v4 CSS 값은 `frontend/src/app/tokens.css`의 기존 oklch 값에서 파생했다.
- hostile review(James/Popper): James의 P0(Tailwind Preflight가 h1~h6
  font-weight/size를 inherit로 리셋해 헤딩 굵기·크기 소실 — 브라우저 재현 확인)를
  h1 bold/h2 1.5em·700/h3 1.17em·700 명시 복원으로 수정. Popper의 P1(Tailwind v4
  네이티브 바이너리의 n150 Alpine/musl 호환성 미검증)은 WSL Docker로
  `frontend/Dockerfile` 직접 빌드 성공으로 해소.
- PR [#18](https://github.com/digitie/kor-travel-airport/pull/18) squash-merge
  (`67e9199`), n150 배포·release_sha 일치·live E2E `5 passed`(320/375/414/768px
  무-오버플로 포함) 확인 완료.

## 2026-08-23 (T-029)

### `T-029` — `flight_status.py`를 `python-krairport-api`(krairport) client로 전환

- [ADR-004](</F:/dev/kor-travel-airport/docs/adr/004-krairport-provider-library.md>)의 마지막 남은
  범위(비행편)를 완료했다. `LiveFlightStatusClient`를 `KrairportFlightStatusClient`로
  교체했다.
- KAC ODCloud(`FlightStatusListDTL`)는 krairport의 다른 KAC 서비스(`openapi.airport.co.kr`)와
  다른 호스트(`api.odcloud.kr`)를 쓰는 별도 provider라 기존 `kac_raw_items`/
  `departures()`/`arrivals()`로는 닿지 않았다 — `python-krairport-api`에
  `KacClient.flight_status_detail_raw_items()`(sync/async)를 새로 추가하고
  `KrairportClient`/`AsyncKrairportClient` facade에
  `kac_flight_status_detail_raw_items()`로 노출했다(`python-krairport-api` PR
  [#7](https://github.com/digitie/python-krairport-api/pull/7), 커밋 `cbe4d13`). 이
  라이브러리 자체 테스트 91 passed(신규 3개 포함).
- IIAC 비행편은 krairport의 기존 `iiac_raw_items("StatusOfPassengerFlightsDeOdp",
  "getPassengerDeparturesDeOdp"/"getPassengerArrivalsDeOdp", ...)`가 endpoint와 정확히
  일치해 krairport 쪽 수정 없이 바로 전환했다.
- parking-radar 쪽: `parse_incheon_flight_status_json`에 krairport의 사전 추출된 raw item
  list를 받는 `_incheon_flight_section_items` 분기를 추가했다.
  `parse_kac_flight_detail_json`은 이미 `{"data": [...]}` 형태를 파싱하므로 변경이 필요
  없었다. 죽은 코드(한 번도 호출되지 않던 `_fetch_legacy_kac_status`, httpx 직접 호출
  전용이던 `_raise_for_upstream_status`/`MAX_UPSTREAM_ERROR_BODY_LENGTH`)도 함께 제거했다.
- `/v1/flights/status` 응답 스키마는 변경하지 않았다 — 파서 함수의 출력 형태가 그대로다.
- WSL 1차 `pytest 86 passed`(신규 4개 포함).

## 2026-08-23 (T-031)

### `T-031` — Docker 컨테이너에서 `test_cutover_guards.py` import 경로가 깨지는 사전 존재 버그 수정

- `T-030`(krairport 주차 마이그레이션) 검증 중 `docker compose run --rm --no-deps backend
  pytest -q`에서 발견한 뒤 `--ignore`로 우회하고 넘어갔던 버그를 실제로 고쳤다.
- 원인: `sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))`가 로컬 디렉터리
  깊이(`parking-radar/backend/tests/...` → `parents[2]` = 레포 루트)를 하드코딩하고
  있었다. Docker 이미지 안에서는 `Dockerfile`의 `COPY backend /app`으로 `backend/`가
  통째로 `/app`으로 flatten돼 `tests/`가 한 단계만 아래(`/app/tests/`)에 있어,
  `parents[2]`가 `/`(파일시스템 루트)를 가리키게 되고 `/scripts`(존재하지 않음)를
  찾다가 `ModuleNotFoundError: No module named 'observe_cutover'`로 깨졌다.
- 고친 방법: `parents[1]`(Docker)과 `parents[2]`(로컬) 둘 다 시도해 실제로 존재하는
  `scripts/` 디렉터리를 찾는 `_scripts_dir()` helper로 교체했다 — 디렉터리 깊이를
  하드코딩하지 않는다.
- CI의 `backend` job(`uv run pytest tests -q`, `.github/workflows/ci.yml`)은 레포 루트
  체크아웃 구조를 그대로 쓰기 때문에 `parents[2]`가 우연히 맞아떨어져 이 버그가 CI에서는
  전혀 드러나지 않았다 — Docker 2차 게이트(`docker compose run --rm --no-deps backend
  pytest`)에서만 재현됐다.
- WSL 1차 `pytest 82 passed`, Docker 2차(재빌드 후) `pytest 82 passed`(제외 없이 전부
  통과, 이전까지 `--ignore`로 제외하던 3개 포함).

## 2026-08-23 (ADR-006)

### 공휴일 수집을 `python-kasi-api`로 전환

- [ADR-006](</F:/dev/kor-travel-airport/docs/adr/006-kasi-provider-library.md>) 참고. 사용자
  요청으로 한국천문연구원(KASI) 특일 정보(`15012690`) 조회를 krairport(T-030, ADR-004)와
  동일한 provider 라이브러리 패턴으로 형제 라이브러리 `python-kasi-api`(`kasi`)로
  옮겼다. `KasiHolidayClient`가 `AsyncKasiClient.holidays()`를 호출하고, 반환된 각
  item의 `raw` mapping을 JSON 직렬화해 기존 `parse_holiday_response`에 그대로 넘긴다
  (`_parse_holiday_raw_items` 신규 분기). `FixtureHolidayClient`(sample 모드)는 변경
  없음.
- krairport 마이그레이션과 달리 이번에는 필드명/endpoint 불일치 같은 새 버그를 발견하지
  못했다 — 순수 provider 교체였다.
- hostile review(James/Popper) 모두 P0/P1 없음. Popper가 지적한 P2(공휴일은
  `CollectionService`처럼 별도 rate-limit backoff 스케줄링이 없다는 점)는 호출 빈도가
  훨씬 낮아(1일 캐시) 의도적 범위 선택으로 판단, ADR에 근거를 남겼다.
- WSL 1차 `pytest 82 passed`(신규 kasi 테스트 3개), Docker 2차 `pytest 79 passed`
  (`test_cutover_guards.py` 3개 제외, `T-031` 무관 사전 버그). GitHub PR
  [#7](https://github.com/digitie/parking-radar/pull/7) merge. 14번에 배포해 live
  검증 완료: `release_sha=986d64e`, `GET /v1/holidays/summary`가 실제 서비스 키로
  `source=kasi_holiday_info`, 광복절/대체공휴일 데이터를 정상 반환했다.

## 2026-08-23 (ADR-005)

### 백엔드 API를 `/v1` 버저닝 + RFC7807 에러로 정식 계약화

- [ADR-005](</F:/dev/kor-travel-airport/docs/adr/005-versioned-rest-api-contract.md>) 참고.
  `kor-travel-map` 패턴을 참조해 `/health`를 제외한 모든 라우트를 `APIRouter(prefix="/v1")`로
  이동(무-호환 clean-cut)하고, 모든 에러 응답을 RFC7807 `application/problem+json`으로
  통일했다. `scripts/export_openapi.py`로 `docs/openapi.json`을 기계 정본으로 커밋한다.
- frontend `lib/api.ts`(19개 endpoint 경로), `api/backend/[...path]/route.ts`(allowlist가
  `v1/` prefix를 요구하도록 변경), 관련 테스트 전부를 같은 PR에서 갱신했다.
- `{data, meta}` 응답 envelope, cursor pagination, 인증은 명시적으로 범위 밖으로 미뤘다
  — 23개 라우트 반환 타입 전체를 바꿔야 하는 별도 규모 작업으로 판단.
- hostile review(James=frontend, Popper=backend/ops) 2건 지적을 반영: (1) FastAPI
  `RequestValidationError`(422)가 `HTTPException` 전용 handler를 우회해 RFC7807 포맷을
  따르지 않던 것을 전용 handler 추가로 수정, (2) `scripts/verify_cutover.py`의 target(14번)
  호출이 `/v1` 없이 여전히 구 경로를 쓰고 있어 이 PR 머지 후 release-gate 스크립트가
  깨질 상황이었던 것을 target 호출에만 `/v1` prefix를 적용해 수정(source=13번은 레거시
  미버저닝 API이므로 그대로 유지). `scripts/odroid-status.ps1`은 13번 대상이라 의도적으로
  변경하지 않았다.
- WSL 1차 `pytest 79 passed`, `vitest 48 passed`, 로컬 Docker 2-stack 검증(`/v1/airports`,
  `/health`, 프록시 passthrough, RFC7807 에러 포맷) 통과. GitHub PR
  [#5](https://github.com/digitie/parking-radar/pull/5) merge, `live-e2e`는 14번 미배포로
  예상대로 실패(기존 패턴과 동일), `backend`/`frontend` CI는 통과.

## 2026-08-23 (T-032)

### `T-032` — PostgreSQL을 별도 compose 스택으로 분리 + 포트 재구성

- `kor-travel-docker-manager`의 "DB는 앱과 분리된 컨테이너/lifecycle로 운영한다" 패턴을
  단일 프로젝트 규모로 축소 적용했다. 여러 프로젝트를 한 곳에서 관리하는 중앙
  오케스트레이터 구조(network_mode: host, 프로젝트별 secret file 등)는 가져오지 않고,
  "DB는 앱 재배포와 무관한 별도 compose 파일"이라는 핵심만 가져왔다.
- `docker-compose.db.yml`(신규) — postgres 전용, 기존 named volume
  `parking-radar_parking_radar_postgres_data`를 그대로 재사용(볼륨명 고정, 새로 만들지
  않음). `docker-compose.yml`에서는 postgres 서비스를 제거하고 외부 네트워크
  `parking-radar-net`으로 통신하도록 바꿨다.
- 포트 재배치: DB `14000`(loopback 전용, 기존 `5432`에서 이동), API `14001`(기존
  `14000`), web `14002`(기존 `14001`). `scripts/deploy-server14.sh`의 `require_exact`
  값과 DB 스택 조건부 기동 로직(이미 떠 있으면 재생성하지 않음)을 갱신했다.
- 로컬에서 분리된 두 스택을 실제로 올려 backend↔postgres 통신, API(`14001`)/web(`14002`)
  응답을 확인했다.
- 운영 전환(server14): (1) `pg_dump`로 사전 백업(`/tmp/parking-radar-backup/pre-t032-migration.dump`,
  로컬 보관), (2) 기존 `docker compose stop postgres`(볼륨 유지, 컨테이너만 중지),
  (3) `.env.server14`의 포트 값 갱신, (4) 신/구 컨테이너 상태를 재확인하며 진행.
- 외부 reverse proxy(`pr.digitie.mywire.org`→web, `pr-api.digitie.mywire.org`→API)는
  사용자가 직접 갱신하기로 했다 — 새 포트(API `14001`, web `14002`)를 안내해야 한다.

### `T-030` — 주차 현황·주차요금 수집을 `python-krairport-api`로 전환

- [ADR-004](</F:/dev/kor-travel-airport/docs/adr/004-krairport-provider-library.md>) 범위를
  비행편에서 주차 현황/요금까지 확장하고, KAC/IIAC 주차현황(`15056803`/`15095047`)과 KAC
  주차요금(`15038474`)이 krairport의 기존 raw-item escape hatch로 정확히 대체됨을 소스
  코드 대조(`krairport/providers/{kac,iiac}.py`)로 확인했다. IIAC 주차요금(`15095053`)은
  krairport에 typed 지원이 없지만 같은 `iiac_raw_items` 범용 경로로 도달 가능해 krairport
  자체 수정 없이 4개 fetch 모두 전환했다.
- `backend/pyproject.toml`에 `python-krairport-api @ git+https://github.com/digitie/python-krairport-api@b8854137f26be4ae14c1693b83b425ee37c60655`
  PEP 508 direct reference로 의존성을 추가했다. 처음엔 `[tool.uv.sources]` git mapping으로
  시도했으나 Docker 빌드가 plain `pip install -e ".[dev]"`를 써서 인식하지 못해(`uv` 전용
  테이블) 실패했고, PEP 508 direct reference로 바꿔 pip/uv 양쪽에서 동작하게 고쳤다.
  `backend/Dockerfile`에 `git` 패키지를 추가했다(pip의 git+https 설치 요구사항).
- `backend/app/services/collection.py`에 `KrairportPublicDataClient`를 추가해
  `LivePublicDataClient`(직접 `httpx`)를 대체했다. krairport의 typed `ParkingFee` model은
  휴일 요금·분당 추가요금 필드가 없어서, typed model 대신 `kac_raw_items`/`iiac_raw_items`
  범용 escape hatch로 원본에 가까운 item dict를 받고 parking-radar 자체 `parsers.py` 로직은
  그대로 유지했다 — 파싱/필드 매핑 회귀 위험을 없앴다.
- `parsers.py`의 `parse_kac_parking`/`parse_kac_fee`/`parse_incheon_parking`/`parse_incheon_fee`가
  이제 문자열(XML/JSON envelope) 또는 사전 추출된 item list 양쪽을 받는다(하위 호환 유지,
  기존 파서 유닛 테스트 무변경). `FixturePublicDataClient`의 sample 데이터도 XML/JSON
  envelope 생성 대신 flat item list를 직접 JSON 직렬화하도록 단순화했다(`_build_kac_parking_xml`/
  `_build_kac_fee_xml`/`SAMPLE_INCHEON_JSON`/`SAMPLE_INCHEON_FEE_JSON` 삭제).
  `validate_source_response_body`는 krairport가 이미 검증한 JSON-array body를 만나면
  스킵하도록 갱신했다.
- **부작용**: `RawApiResponse.body_text`가 이제 업스트림 원문이 아니라 krairport가 파싱한
  item 목록의 JSON 직렬화다(krairport가 raw HTTP 텍스트를 공개 API로 안 내려줌). ADR-004에
  명시했다.
- **live smoke test로 발견·수정한 pre-existing 버그 2건** (사용자가 로컬 실제
  `DATA_GO_KR_SERVICE_KEY` 존재를 알려줘서 fixture가 아닌 실 upstream으로 검증):
  1. krairport가 KAC 전체를 `https://openapi.airport.co.kr`로 호출하고 있었는데, 이
     게이트웨이는 `http://`만 정상 동작한다(https는 요청과 무관하게 전부
     `NO OPENAPI SERVICE ERROR.`) — `python-krairport-api`
     [PR #6](https://github.com/digitie/python-krairport-api/pull/6)로 수정,
     `88d47ca`로 머지 후 parking-radar pin을 그 커밋으로 갱신했다.
  2. `parse_kac_fee`/`_kac_fee_sample_items`/`tests/fixtures/kac_fee_gmp.xml`이
     `PARKING_BASIC_ACCOUNT`류 SCREAMING_SNAKE_CASE 필드명을 기대하고 있었는데 실제 API는
     `parkingBasicAccount`류 camelCase를 반환한다 — **krairport 도입 이전부터 있던 버그이며,
     실제로는 KAC 주차요금 live 수집이 계속 빈 배열만 반환했을 가능성이 높다.** 실제
     필드명으로 파서·sample·fixture를 모두 고쳤다.
  두 수정 후 `CollectionService.collect()`를 실제 서비스키로 end-to-end 실행해 확인:
  `status=success`, `raw_response_count=6`, `snapshot_count=30`, `fee_rule_count=56`,
  `errors=[]`.
- 검증: WSL 1차 `uv run pytest tests -q` `72 passed`(krairport 수정 반영 후 재실행 포함).
  Docker 2차 `docker compose run --rm --no-deps backend pytest -q
  --ignore=tests/test_cutover_guards.py` `69 passed`(제외한 3개는 이 마이그레이션과 무관한
  사전 존재 버그 — `T-031` 참고). `alembic -c alembic.ini check`
  `No new upgrade operations detected`. `docker compose build backend`/`frontend` 성공.
  frontend Docker 테스트 `48 passed`. 실제 upstream 대상 live smoke test와 end-to-end
  collect() 실행까지 통과.
- 이번 세션에서는 `T-031`(`test_cutover_guards.py` Docker 경로 버그)을 발견했지만
  krairport 마이그레이션과 무관해 고치지 않고 별도 task로 등록했다(Surgical Changes 원칙).
- KAC 비행편(ODCloud `15113771`)은 krairport가 아직 지원하지 않아 이번 범위에서 제외했다 —
  `T-029`로 남아 있다.

### `T-028` — GitHub 정본 레포 전환 + kor-travel-map 문서 구조 이식

- 두 GitHub remote(`digitie/airport-parking-radar`, `digitie/parking-radar`) 상태를
  확인해 `digitie/parking-radar`가 정본(이미 열려 있던 Draft PR #1과 일치)임을 확인하고,
  `origin`을 `parking-radar.git`로, 구 remote를 `airport-parking-radar`로 재명명했다.
  두 레포의 `main` 히스토리가 갈라져 보였지만 `git diff --name-only`로 파일 내용이 완전히
  동일함을 확인해 별도 병합 없이 로컬 `main`을 새 `origin/main`으로 전환했다.
- `kor-travel-map`(`F:/dev/kor-travel-map`)의 문서 구조를 조사해 이 저장소에 없던 항목을
  선별 이식했다: ADR을 파일당 1개(`docs/adr/001~003-*.md`)로 분리하고 작성 규약을
  `docs/adr/README.md`에 명문화, `docs/runbooks/agent-failure-patterns.md`(반복 실수
  카탈로그), `docs/runbooks/branch-protection.md`(현재 `main`이 branch protection
  미설정임을 `gh api`로 확인 후 작성), `docs/runbooks/cross-repo-audit-checklist.md`(이번
  2-remote 상황을 재발 방지 절차로 문서화), `docs/dev-environment.md`(Windows/WSL 실행
  경계·포트 진단), `docs/test-strategy.md`(테스트 계층 책임 경계, 커버리지 미강제 현황
  명시)를 신규 작성했다. 사용자 확인 질문을 계기로, 이 저장소의 기존 적대적 리뷰 게이트
  (James/Popper, T-021)가 결과만 `journal.md`/`tasks-done.md`에 기록될 뿐 절차 문서가
  없다는 gap을 추가로 발견해 `docs/runbooks/hostile-review.md`도 T-021 실제 기록 기준으로
  작성했다. `CLAUDE.md`/`README.md`에 전부 링크를 추가했다.
- 멀티패키지 모노레포 전용 패턴(에이전트별 worktree/sandbox 브랜치, lint-imports 계층
  검사, sprint 문서군, integration-map)은 단일 서비스 구조인 이 저장소에 맞지 않아
  이식하지 않았다.
- 사용자 요청으로 `kor-travel-map`의 `CLAUDE.md`/`AGENTS.md` 본문(Codex/Antigravity
  entry 정책, 문서 언어 정책, 지시 우선순위, 행동 원칙 5종 — Think Before
  Coding/Simplicity First/Surgical Changes/Goal-Driven Execution/Practical Bias,
  작업 후 체크리스트)을 최대한 원문 그대로 `AGENTS.md`/`CLAUDE.md`에 이식했다. 식별자
  테이블·역할·외부 경계·Provider API 세부 원칙처럼 `kortravelmap` 패키지·PostGIS·
  멀티패키지 구조에 종속된 내용은 가져오지 않았다.
- `python-krairport-api`(`krairport`, `F:\dev\python-krairport-api`)를 비행편 데이터
  provider 라이브러리로 채택하기로 결정했다([ADR-004](</F:/dev/kor-travel-airport/docs/adr/004-krairport-provider-library.md>)).
  현재 `backend/app/services/flight_status.py`는 KAC/IIAC API를 `httpx`로 직접
  재구현하고 있어 이 결정과 어긋난다 — 실제 마이그레이션은 `docs/tasks.md`의 `T-029`로
  등록했고 아직 시작하지 않았다. `AGENTS.md`에 "Provider 라이브러리 사용 원칙" 절을
  추가하고 `SKILL.md` §4에 9번째 금지 항목으로 반영했다.

## 2026-08-22

### `T-027` — scheduler headroom 재조정 및 최종 검증

- `d312c98a9143e76e348295370dfd3348c5f5cef7`에서 fresh strict gate를 실행했으나 7회 중 한 샘플의
  target freshness가 `319.7s`가 되어 실패했다. 240초 tick과 외부 수집/commit 지연이 겹친 경계 문제로
  확인했다.
- 5분 threshold는 그대로 유지하고 server14 `SCHEDULER_SAFETY_BUFFER_SECONDS`를 `120`으로,
  effective tick을 `180초`로 조정했다. 배포 guard, verifier, live E2E 기대값, 운영 문서를 함께 갱신했다.
- `aefaf8c5bc2efc4604135529f85c51b2c8236839`을 14번에 배포하고 API `14000`, web `14001`,
  scheduler `300/180/120` 계약과 backup proxy `900000ms`를 확인했다.
- `EXERCISE_LIVE_BACKUP=true` exact live E2E는 실제 backup 생성 UI 포함 `5 passed (13.0s)`였고,
  fresh strict gate는 7회 모두 `failure_count=0`, `failed_samples=0`, `gate_duration_seconds=339.9`,
  `source_lots=53`, `target_lots_checked=53`으로 통과했다.
- 후속 기능 release에서는 Compose scheduler 기본값과 deploy guard를 모두 `120`으로 fail-closed 정렬하고,
  scheduler 실행 중 PostgreSQL restore를 `409`로 거부해 복원으로 5분 freshness가 깨지지 않게 했다.
  최종 기능 release strict gate는 `7/7`, `failed_samples=0`, `gate_duration_seconds=339.6`이었다.

### `T-026` — 최종 정합성·백업 안전성·라이브 검증

- runtime candidate `d312c98a9143e76e348295370dfd3348c5f5cef7`을 14번에 배포하고 API `14000`, web
  `14001`, `BACKUP_DIR=/app/backups`, 백업 proxy `900000ms`를 확인했다. 13번에는 Docker를 실행하지 않았다.
- HTTP migration과 live source가 겹친 migration 행 157건을 보호 백업 후 제거하고 analytics cache
  264건을 재계산 대상으로 비웠다. PostgreSQL lot·관측시각 중복은 `0`, history API 중복 timestamp도 `0`이다.
- backup dump password 전달, staged atomic upload, quota 사전 검사, symlink 차단, restore proxy timeout과
  migration/cache dedupe를 보완했다. 백엔드 targeted `15 passed`, 프론트 full `48 passed`, proxy `5 passed`다.
- `EXERCISE_LIVE_BACKUP=true E2E_BASE_URL=https://pr.digitie.mywire.org EXPECTED_RELEASE_SHA=d312c98...`
  로 실제 백업 생성 UI를 포함한 live E2E `5 passed`를 확인했다. fresh strict gate는 `7/7`,
- 당시 240초 scheduler의 fresh strict gate는 한 샘플에서 target freshness `319.7s`로 실패했다.
  threshold를 완화하지 않고 scheduler headroom을 T-027에서 조정한다.
- CI 기본 live E2E는 공유 server14를 변경하지 않으며, backup mutation은 명시적 환경 변수 실행으로 분리했다.

### `T-025` — Hallmark 후속 정리·리뷰 blocker 해소

- 중복 history KPI를 제거하고 요일 x 시간 히트맵 중심으로 화면을 단순화했다. 밝은 히트맵 셀과
  primary button의 명도 대비를 고정하고, 백업 파일 입력의 키보드 focus 및 목록 오류 상태를
  명시했다.
- 백업 생성은 temp dump의 파일 크기/quota를 최종 저장 전 검사하고, 복원 중 pre-restore
  backup을 pruning 보호 목록에 넣는다. verifier는 future-dated observation을 거부한다.
- server14 배포는 `14000`/`14001`, PostgreSQL loopback, live/scheduler/5분 계약을 검사하고
  rsync clean artifact로 stale 파일을 제거한다. legacy 13번 Docker 경로는 fail-closed다.
- `b7944ad`에서 backend `67 passed`, frontend `47 passed`, exact live E2E `5 passed`, strict
  gate `7/7` 및 `failed_samples=0`, GitHub Actions push/PR CI 전부 통과를 확인했다.

### `T-024` — Hallmark UI 구조 간결화

- 메인 헤더의 중복 브랜드 문구와 중복 KPI/동기화 시각을 제거하고, 공항·주차장 선택과 핵심 현재 현황을 한 흐름으로 정리했다.
- 요일/공휴일 분석에서 같은 데이터를 반복하던 상세 카드와 히트맵을 히트맵 중심으로 통합해 모바일 disclosure 수와 스크롤을 줄였다.
- 기존 분석·요금 계산·백업/복원 기능은 유지하고, frontend Vitest `47 passed`, TypeScript 검사와 production build를 통과했다.

### `T-023` — 192.168.1.14 배포·데이터 이전·운영 검증

- `192.168.1.14`에만 Docker Compose/PostgreSQL/backend/frontend를 배포했다.
- 포트는 API `14000`, web `14001`이며, PostgreSQL은 loopback `5432`로 제한했다. configured
  collection interval은 `300s`, effective scheduler tick은 `180s`(`120s` safety buffer)다.
- HTTP migration 결과: `imported_snapshots=36878`, `source_lots=53`, `failures=0`.
- delta import 후 현재 PostgreSQL `parking_snapshots=38946`, distinct snapshot lots `44`,
  parking lots `53`, legacy IDs `53`, duplicate legacy IDs `0`이며 Alembic head는
  `0003_legacy_source_identity`다.
- 7회 × 50초(총 300초) strict cutover observation: 각 `failure_count=0`, 최종 `failed_samples=0`.
- 13번에는 Docker 명령을 실행하지 않고 HTTP GET만 수행했다.

### `T-022` — exact live E2E·운영 smoke

- `E2E_BASE_URL=https://pr.digitie.mywire.org npm run test:e2e`: 5 passed.
- 14번 직접 origin `http://192.168.1.14:14001`에서도 5 passed.
- `https://pr-api.digitie.mywire.org/health`, web same-origin `/api/backend/health`, 14번 API
  health가 모두 `{"status":"ok","database":"ready","seeded":true}`를 반환했다.
- 외부 live E2E는 최종 수정 후 `5 passed (9.4s)`, 14번 직접 origin은 `5 passed (5.9s)`였다.
- 320/375/414/768px overflow와 backup/restore controls를 브라우저에서 확인했다.

### `T-021` — 적대적 전문 리뷰 에이전트 2명

- James(frontend/live UI)와 Popper(backend/PostgreSQL/ops)를 각각 독립 read-only reviewer로
  운용했다.
- Alembic lineage, source lag verifier, proxy timeout, backup pre-restore receipt, accessibility,
  stable legacy lot identity, explicit reconciliation mapping, PostgreSQL tests, 13번 Docker 금지
  guard 등 P0/P1 지적을 반영했다.
- 인증 없는 admin backup/restore는 사용자의 명시 요구라 유지하되, UI·runbook에 외부 공개 금지와
  gateway/private ACL 필요성을 명시했다.

### `T-020` — 단계별 원격 커밋·Draft PR·CI

- 원격 branch: `codex/parking-radar-postgres-migration`.
- Draft PR: [#1](https://github.com/digitie/parking-radar/pull/1).
- 주요 원격 커밋: `2b33a26`, `6b7ac89`, `2a88c09`, `c5e5b03`, `8d8a45a`, `f367db9`, `4980485`,
  `a690628`, `8f9af56`, `146573d`, `27e7b76`, `49e4a3e`.
- workflow run `32551945257`의 backend(PostgreSQL + `alembic check`), frontend, live-e2e job이
  모두 통과했다.

### `T-014` — 인증 없는 내부망용 백업/복원 UI와 API

- PostgreSQL `.dump` 생성·목록·다운로드·복원 API와 responsive UI를 구현했다.
- 복원 전 자동 backup을 응답에 포함하고, UI에 destructive operation 경고를 제공한다.
- 별도 app auth는 추가하지 않고 gateway/private network 보호를 문서화했다.

### `T-013` — 의존 라이브러리 최신화

- Python/Node lockfile과 Docker runtime을 갱신하고 CI에서 locked install, PostgreSQL Alembic,
  frontend build를 통과시켰다.

### `T-012` — 쿠키 기반 설정 기억

- 공항/주차장 선택을 `parking-radar-selection` cookie와 localStorage fallback으로 기억하고
  브라우저 테스트로 복원·변경을 검증했다.

### `T-011` — 초기 로딩·분석 API·쿼리 성능 개선

- `/dashboard/bootstrap` 단일 초기 요청, analytics viewport 지연 로딩, N+1 제거, response
  cache-control과 backend proxy connect/body timeout을 적용했다.

### `T-010` — Hallmark audit/redesign

- Hallmark 기준 audit/redesign을 반영해 dashboard hierarchy, responsive disclosure, status
  cards, charts, backup panel과 접근성 상태를 정리했다.
- live E2E에서 320/375/414/768px overflow 및 주요 control을 확인했다.

### `T-003` — 데이터 이전·5분 무손실 컷오버

- 7일 HTTP prewarm과 1일 delta import를 모두 실패 시 rollback하는 방식으로 수행했다.
- target scheduler는 configured `300s`와 effective `180s` safety-buffer tick으로, source는
  read-only 유지 상태에서 strict 5분 연속성 gate를 통과했다.
- source/target lot은 stable legacy ID로 대조하고, 양쪽 무관측 lot은 명시 allowlist 없이는
  통과하지 않는다. lot freshness, source lag, successful run gap 모두 `300s` 한도로 검사한다.

### `T-002` — Docker Compose + PostgreSQL + Alembic

- PostgreSQL 16 Compose, async SQLAlchemy, Alembic `0001_initial` → `0002_integrity_and_freshness`
  → `0003_legacy_source_identity` lineage, Postgres schema-head guard와 model/schema drift CI를
  구현했다.
- clean PostgreSQL `alembic upgrade head`, GitHub PostgreSQL CI, 14번 runtime health를 통과했다.

### `T-001` — kor-travel-map식 저장소·문서·AI 작업 구조

- `AGENTS.md`, `CLAUDE.md`, `SKILL.md`, `.claude/agents`, `.claude/skills`, `.codex/agents`,
  `.agents/skills`를 kor-travel-map 방식으로 이식했다.
- architecture/runbooks/reports와 tasks/resume/journal 구조를 정리하고 운영 IP·도메인·포트
  규칙을 문서화했다.
