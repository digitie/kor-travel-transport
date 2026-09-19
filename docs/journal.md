# journal.md — 작업 일지

## 2026-09-19

- 사용자 요청으로 저장소의 목적을 국내 여행용 통합 교통정보 라이브러리/API로 명시했다.
  provider 데이터를 주기적으로 PostgreSQL에 저장하고, 저장 자료를 외부 OpenAPI와 내부
  통계로 즉시 제공하는 방향을 공통 문서와 현재 구현에 반영했다.
- T-040 구현에서 `python-krex-api`의 고속도로 소통·돌발, 최신 `python-opinet-api`
  Playwright 지역별 collector의 주유소·유가·편의정보를 연결했다. Alembic `0004`/`0005`와
  소스별 수집 상태, 중복 방지, 조회/통계 API, 테스트 fixture를 추가했다.
- 오피넷 collector는 공식 Open API 대체가 아닌 공개 화면 기반 실험 기능이므로 pin된
  provider의 기본 8시간 throttle(허용 범위 8~12시간)을 존중하고, 원본/오류와 화면 변경
  위험을 문서화했다.
- 유가 OpenAPI는 보관 기간의 모든 가격 이력을 메모리에 올리지 않고 DB window query로
  주유소·유종별 최신 1건만 반환하도록 보강했으며, 과거 가격이 최신값으로 덮이지 않는
  회귀 테스트를 추가했다. WSL2 백엔드 전체 `105 passed`, 프론트 단일 worker에서
  기존 52개와 누락 worker 재실행 9개를 합쳐 `61 passed`,
  TypeScript 검사와 production build도 통과했다.

## 2026-09-07

- `T-039`: 사용자가 "전체적으로 UI를 컴팩트하게 — 공항/주차장 선택 + 새로고침을
  모바일에서도 한 줄로, 분석 페이지의 좌측 칼럼 사이즈 효율화" 요청. 코드 조사만으로는
  "분석 페이지 좌측 칼럼"이 정확히 어떤 문제인지 모호했다 — 브라우저 확장이
  연결되지 않아(`mcp__claude-in-chrome__*`) Playwright를 라이브 사이트
  (`https://pr.digitie.mywire.org`)에 직접 붙여 스크린샷을 찍어 확인하는 방식으로
  대체했다: 임계치 탭의 2열 그리드에서 왼쪽 패널(요일별, 데이터 2행)이 오른쪽 패널
  (날짜별, 스크롤 가능한 긴 목록)과 같은 높이로 늘어나 아래쪽에 큰 빈 공간이
  남는 게 실제 문제였다(`align-items: stretch` 기본값) — `align-items: start`로
  해결.
  - 헤더 컨트롤(공항/주차장 select + 새로고침)을 모바일에서도 한 줄로 압축했다.
  - 이 과정에서 실제 운영 버그를 하나 발견했다: `.lot-card-grid lg:hidden`이
    모든 폭(데스크톱 포함)에서 전혀 작동하지 않고 있었다 — `.lot-card-grid`가
    `@import "tailwindcss"` 뒤에 이어붙인 순수 커스텀 클래스라서(unlayered CSS)
    Tailwind `@layer utilities` 안의 `lg:hidden`을 CSS Cascade Layers 스펙에
    따라 무조건 이긴다. 1280px에서도 모바일 카드 목록이 데스크톱 테이블
    아래 그대로 렌더링되고 있었다는 걸 라이브 사이트의 컴퓨티드 스타일로
    확인한 뒤 `.lot-card-grid` 자체에 미디어 쿼리를 추가해 고쳤다.
  - hostile review(James/Popper)가 실제 데이터로 재현한 P1 2건을 반영했다:
    (1) 세부 주차장명이 최대 13자(`T1 장기 P1/P2/P3/P4 주차타워` 등)이고
    구분자가 뒤쪽에 있어, 두 select를 반씩 나눈 최초 구현은 320px에서
    서로 다른 주차장("국내선 제1주차장"/"국내선 제2주차장")이 똑같이
    잘려 보이는 실제 혼동 가능성을 만들었다 — grid 비율을 0.8fr/1.2fr로
    재배분해 고쳤다. (2) 헤더 새로고침 버튼이 `current-status-view.tsx`의
    다른 용도로 만들어진 `.action-stack` 클래스를 재사용하는 바람에
    381-1023px 구간에서 의도치 않은 2열 그리드 규칙을 상속받아 select 폭을
    추가로 빼앗고 있었다 — 래퍼를 없애고 버튼을 그리드 자식으로 직접 둬서
    분리했다.
  - **배운 것**: (1) "레이아웃이 비효율적"이라는 모호한 사용자 피드백은 코드만
    읽어서는 특정하기 어려울 수 있다 — 이번처럼 실제 화면(또는 라이브 사이트에
    직접 붙인 헤드리스 브라우저)을 보는 것이 코드 추측보다 훨씬 빠르고
    정확하다. (2) 모바일 컴팩트화처럼 "실제 데이터로 검증"이 필수인 UI
    변경에서, 테스트/시연에 쓴 표본 데이터(청주공항의 짧은 이름들)가 우연히
    가장 쉬운 경우였을 뿐, 실제 운영 데이터(인천공항의 13자 주차장명)는 훨씬
    가혹한 케이스였다 — hostile review가 아니었으면 놓쳤을 것이다. 좁은 화면에
    여러 텍스트 필드를 압축할 때는 항상 실제 데이터의 최댓값(길이·구분자
    위치)을 확인할 것. (3) 새 UI 요소가 기존의 공유 CSS 클래스(`.action-stack`)를
    재사용할 때는 그 클래스가 이미 다른 컨텍스트에서 갖고 있는 반응형 규칙까지
    같이 상속된다는 걸 놓치기 쉽다 — 공유 클래스에 새 용도를 얹기 전에 그
    클래스의 기존 모든 사용처와 각 사용처의 breakpoint 규칙을 확인할 것.
  - PR [#28](https://github.com/digitie/kor-travel-airport/pull/28) squash-merge
    (`e39f05b`). CI backend/frontend PASS, live-e2e는 두 번의 push 모두 다른
    이유로 FAIL했지만 둘 다 예상된 것이었다(1차: release-SHA 불일치 선례,
    2차: 이 PR이 새로 추가한 회귀 테스트가 아직 배포 전인 구버전 사이트에서
    스스로 고치려는 버그를 정확히 잡아낸 것) — 머지를 막지 않았다. n150 배포 후
    `release_sha=e39f05b52e56d363eccf4a146c6271a4ad800cad` 일치 확인, live E2E
    `15/15 PASS`(새 회귀 테스트 포함).

- `T-037`: `T-033`~`T-036`으로 완성된 전체 결과물(shadcn 기반 도입, 컴포넌트 치환,
  라우트 기반 앱 셸, 과거 자료 조회 date picker)에 read-only Hallmark audit을
  실행했다. 0 critical / 3 major / 6 minor, 최종 판정 "close, fix the minors".
  3 major: 숫자 데이터 테이블에 `tabular-nums` 미적용, 차트 레이어·상태 pill 색상이
  토큰이 아닌 raw hex/rgba로 인라인된 것(gate 48 위반), 로딩 상태에 `aria-live`가
  전혀 없는 것. 6 minor: 퇴역한 `.mobile-disclosure`/`.responsive-desktop` 패턴의
  죽은 CSS, `.control-band`의 단일 컬럼 붕괴 구간이 Tailwind `lg:` 전환점(1024px)과
  980px에서 어긋나는 것, `/backup` 전용 라우트에서도 패널이 기본 접힘 상태라 클릭이
  하나 더 필요한 것, dark-mode 차트/톤 팔레트가 토큰화 안 된 것, stock shadcn
  프리미티브 3곳의 `transition-all`, `globals.css` 전반의 desktop-first 미디어
  쿼리 구조.
- `T-038`: 위 3 major 전부와 6 minor 중 4개(죽은 CSS 삭제, 브레이크포인트 수정,
  aria-live 추가, `/backup` 기본 오픈)를 반영했다. 나머지 2 minor(desktop-first
  미디어 쿼리, shadcn 프리미티브 `transition-all`)는 각각 "기존 아키텍처 전체를
  건드리는 별도 과제" / "업스트림 동기화와 어긋남"이라는 근거로 accepted-not-fixed로
  남겼다.
  - hostile review(James=frontend/UI, Popper=backend/ops/docs, 서브에이전트 2개
    독립 실행) 1라운드에서 자체 도입 버그와 진짜 보안 회귀를 모두 잡았다:
    - **James P1(자체 도입 버그)**: `.control-band` 브레이크포인트 수정에
      `@media (max-width: 64rem)`을 썼는데, 이는 Tailwind `lg:`의
      `min-width: 64rem`과 숫자가 완전히 같다 — `max-width`/`min-width`는 둘 다
      경계값 포함이라 정확히 1024px(아이패드 가로 모드 등 실제로 흔한 폭)에서 두
      미디어 쿼리가 동시에 참이 돼, 고치려던 바로 그 "헤더는 1컬럼인데 nav/table은
      아직 데스크톱" 버그를 폭만 좁혀 재현했다. `max-width: 63.9375rem`(1023px)로
      정정.
    - **James P1(카고컬트 anti-pattern)**: 추가한 `aria-live="polite"`가(그리고
      이 패턴을 그대로 베낀 `history-view.tsx`의 기존 인스턴스도) 이미 최종
      내용이 채워진 채로 마운트되는 엘리먼트에 붙어 있었다 — 스크린 리더가 이런
      live region을 안정적으로 announce한다는 보장이 없다(내용이 바뀌는 상시
      마운트 엘리먼트여야 한다). `current-status-view.tsx`/`fees-view.tsx`/
      `history-view.tsx` 세 곳 모두 상시 마운트 sr-only announcer + 보이는
      알림에는 `aria-hidden`을 붙이는 구조로 재설계했다.
    - **Popper P1(보안 회귀, 실제 반영)**: `/backup` 전용 라우트에서 패널을 기본
      오픈으로 바꾼 것은, 인증 없는 파괴적 백업/복원 관리 UI(ADR-003 전제:
      내부망)에서 "클릭 1번"이라는 유일한 상호작용 게이트를 제거하는 조치였다.
      `T-035`가 `/backup`을 nav 링크로 노출했을 때 동일한 노출 증가 범주에 대해
      같은 PR 안에서 ADR-003 addendum을 추가한 전례가 있는데, 이번 PR은 그 근거
      추가 없이 순수 UX 개선으로만 서술했다. Hallmark가 지적한 것은 "클릭 1번
      더 필요함"이라는 minor 취향 문제였을 뿐이라, 그 정도 이득을 위해 방어
      계층을 하나 없애는 트레이드오프는 맞지 않다고 판단해 **완전히 되돌렸다**
      (`BackupPanel`/`BackupView`/e2e spec/테스트 전부 `main`과 byte-identical
      확인). 이 minor는 다시 accepted-not-fixed로 남는다.
    - James P2 후속: 같은 rgba 계열인데 누락됐던 항공편 departure/arrival
      테두리 색 4곳을 마저 토큰화(`--color-chart-flight-departure-border`/
      `-arrival-border`), aria-live 재설계를 검증하는 회귀 테스트 추가.
    - Popper P2(문서 인용 오류): PR 본문이 "docs/journal.md에 근거 기록됨"이라고
      현재형으로 썼지만 실제로는 이 커밋에 journal.md 변경이 없었다(이 저장소
      관례상 journal 항목은 이 완료 문서 PR에서 별도로 남긴다) — PR 설명을
      "후속 문서 PR에서 기록 예정"으로 정정.
  - 새로 accepted-not-fixed로 남긴 항목(다음 Hallmark 라운드 후보): dark-mode
    차트/톤 팔레트 미토큰화(라이트모드만 이번에 반영), 980–1024px 브레이크포인트
    경계에 대한 전용 회귀 테스트 없음(jsdom이 미디어 쿼리를 평가하지 않아
    Playwright/실브라우저 뷰포트 테스트가 필요한데, 근본 원인(폭 중복) 수정으로
    두 구간이 구조적으로 배타적이 됐다고 보고 이번엔 전용 테스트 없이 넘어갔다).
  - PR [#26](https://github.com/digitie/kor-travel-airport/pull/26) squash-merge
    (`603884f`). CI backend/frontend PASS, live-e2e는 기존 선례(PR
    #18/#20/#22/#24)와 동일한 이유로 FAIL(머지 전 배포된 prod엔 아직 신규 코드가
    없음) — 머지를 막지 않았다. n150 배포 후 `release_sha=603884f9…` 일치 확인,
    live E2E `15/15 PASS`(이번엔 기존 `collector-status` 플레이크도 관측 안 됨).

## 2026-08-23

- GitHub remote가 `origin`(`airport-parking-radar`)과 `parking-radar` 2개로 갈라져 있던
  것을 발견했다. `git diff --name-only`로 두 `main` tip의 파일 내용이 완전히 동일함을
  확인한 뒤(한쪽이 다른 쪽을 squash merge한 결과), `origin`을 `parking-radar.git`로,
  구 remote를 `airport-parking-radar`로 재명명했다. 재발 방지 절차는
  `docs/runbooks/cross-repo-audit-checklist.md`에 남겼다.
- `parking-radar` main(`gh api .../branches/main/protection`)에 branch protection이
  전혀 설정되어 있지 않음을 확인했다(`404 Branch not protected`). 실제 설정값은
  `docs/runbooks/branch-protection.md`에 남겼고, 아직 GitHub 설정 자체는 적용하지 않았다 —
  다음에 레포 admin 권한으로 직접 적용해야 한다.
- `kor-travel-map`(`F:/dev/kor-travel-map`)의 문서 구조를 조사해 이 저장소에 없던
  구조/내용을 선별 이식했다(`T-028`, 상세는 `docs/tasks-done.md` 참고). 멀티패키지 모노레포
  전용 패턴(에이전트별 worktree/sandbox 브랜치, codegraph 게이트, sprint 문서군)은 단일
  서비스 구조에 맞지 않아 가져오지 않았다.
- PR [#2](https://github.com/digitie/parking-radar/pull/2)(문서 전용)를 hostile
  review(James/Popper 서브에이전트, P1 3건·P2 2건 수정) 후 squash merge했다.
- `T-030`: 주차 현황·주차요금 수집을 `python-krairport-api`로 전환했다. 실제 소스를 대조한
  결과 KAC/IIAC 주차현황과 KAC 주차요금은 krairport의 raw-item escape hatch로 그대로
  대체됐고(엔드포인트 완전 일치 확인), IIAC 주차요금도 같은 범용 경로로 커버돼 krairport
  자체 수정은 필요 없었다. Docker 빌드가 `[tool.uv.sources]`를 인식하지 못해(plain pip
  사용) PEP 508 direct git reference로 바꾸고 `Dockerfile`에 `git`을 추가했다. WSL
  1차 `72 passed`, Docker 2차 `69 passed`(`test_cutover_guards.py` 제외, 무관한
  사전 존재 버그 — `T-031`로 등록). KAC 비행편(ODCloud)은 krairport 미지원이라
  `T-029`로 남겨뒀다.

## 2026-08-22

- 최종 runtime은 배포한 Git full SHA와 14번 `/health.release_sha`가 일치하는 상태다. 기능 코드
  candidate `aefaf8c5bc2efc4604135529f85c51b2c8236839`와 docs-only release에서도
  `https://pr-api.digitie.mywire.org`, `https://pr.digitie.mywire.org/api/backend/health`가
  `database=ready`를 반환했고, API/web 포트는 각각 `14000`/`14001`이다.
- 14번 PostgreSQL에서 보호 백업을 만든 뒤 `migration_http`와 live source가 같은 lot·관측시각을
  가진 157행을 제거하고 analytics cache 264행을 무효화했다. 이후 DB 중복과 history API 중복
  timestamp는 모두 `0`이었다.
- 백업 UI는 `EXERCISE_LIVE_BACKUP=true`를 지정한 exact live E2E에서 실제 dump 생성까지 수행해
  `5 passed`했다. 기본 CI는 공유 운영 DB를 변경하지 않도록 backup mutation을 실행하지 않는다.
- d312c98의 preflight strict gate에서 한 샘플이 `319.7s`가 된 원인을 확인한 뒤 5분 threshold는
  유지하고 server14 safety buffer를 120초로 늘려 effective tick을 180초로 조정했다.
- aefaf8c runtime의 exact live E2E는 실제 backup 생성 UI를 포함해 `5 passed (13.0s)`였고,
  fresh strict gate는 50초 간격 7회 모두 `failure_count=0`, `failed_samples=0`,
  `gate_duration_seconds=339.9`, `source_lots=53`, `target_lots_checked=53`으로 통과했다.
- frontend full `48 passed`, backend full `71 passed`, proxy `5 passed`와 production build를
  확인했다.
- 이후 scheduler safety 기본값/배포 guard를 fail-closed로 맞추고, scheduler 실행 중 restore를 `409`
  유지보수 창으로 제한했다. 해당 최종 기능 release의 fresh strict gate도 7회 모두 통과해
  `failed_samples=0`, `gate_duration_seconds=339.6`, `source_lots=53`, `target_lots_checked=53`이었다.

- 사용자 요청으로 SQLite 기반 운영 앱을 PostgreSQL/Docker 기반으로 전환하는 작업을 시작했다.
- `kor-travel-map`의 `docs/tasks.md`, `resume.md`, `tasks-done.md`, `tasks-rule.md` 방식과
  `AGENTS.md`/`CLAUDE.md`/`SKILL.md`/AI agent·skill 구조를 기준으로 삼았다.
- 192.168.1.13은 Docker 소켓이 `root:docker`이고 `digitie`가 해당 그룹에 없어 Docker
  조작을 하지 않기로 했다. 192.168.1.14는 Docker Compose와 Docker 접근이 가능하다.
- `kor-travel-map` 방식의 AI 작업 문서와 docs backlog 구조를 이식했다. `AGENTS.md`,
  `CLAUDE.md`, `SKILL.md`, `.claude`, `.codex`, `.agents` 경로를 포함한다.
- PostgreSQL 16/Alembic clean upgrade와 14번 runtime을 확인했다. remote status는
  Alembic `0003_legacy_source_identity (head)`, API `14000`, web `14001`, configured scheduler
  `300s`, effective scheduler `180s`, safety buffer `120s`다.
- HTTP migration은 7일 prewarm `imported_snapshots=36878`, 1일 delta
  `imported_snapshots=5192`, `source_lots=53`, `failures=0`으로 완료했고, reconciliation 후
  duplicate lot `0`을 확인했다. 2026-08-22 현재 DB query는 `parking_snapshots=38946`,
  distinct lots `44`, reference lots `53`, legacy IDs `53`이다.
- 14번 target collector run은 최종 검증 시 id `36`, observed `2026-08-22T04:13:03Z`,
  success, snapshot_count `44`였다. strict 7회 × 50초(총 300초) HTTP-only cutover
  observation은 각 `failure_count=0`, final `failed_samples=0`이었다. verifier는 stable
  legacy lot identity, reviewed empty-lot allowlist, freshness/source lag/run gap `300s`를
  epsilon 없이 검사한다.
- 로컬 WSL 검증은 backend `59 passed`, frontend `9 files / 43 tests passed`, TypeScript와
  production build 통과였다. GitHub Actions run `32547913806`에서도 backend, frontend,
  live-e2e가 모두 통과했다.
- exact live UI 검증은 `E2E_BASE_URL=https://pr.digitie.mywire.org npm run test:e2e`로
  5 passed였고, 14번 직접 origin에서도 5 passed였다. API `https://pr-api.digitie.mywire.org`
  health와 web same-origin backend health도 정상이다.
- 두 적대적 reviewer James(Frontend)와 Popper(Backend/Ops)의 P0/P1 지적을 반영했다.
  무인증 backup/restore는 사용자의 명시 요구라 유지하되 gateway/private network 보호를
  runbook에 남겼다.
- `digitie/parking-radar`의 Draft PR [#1](https://github.com/digitie/parking-radar/pull/1)은
  runtime candidate `b7944ad`와 일치한다. 새 레포 CI와 두 reviewer의 재검토가 끝나면
  merge한다. 이전 `airport-parking-radar` PR은 대상 레포가 아니며, 13번에는 Docker 명령을
  실행하지 않았다.
- Hallmark 최종 정리로 메인 화면에서 중복 KPI, 보조 브랜드 문구, 수집기 내부 동기화 시각을
  제거하고, 요일/공휴일의 중복 상세 카드를 히트맵 중심으로 통합했다. 핵심 분석·요금·백업/복원
  기능은 유지했으며 frontend 테스트 `47 passed`, TypeScript와 production build가 통과했다.
- 적대적 재리뷰에서 발견된 P1/P2를 반영한 runtime candidate는 `b7944ad`다. 히트맵/버튼
  대비, 백업 롤백 파일 보존과 quota 선검사, server14 clean artifact·정확한 포트/수집 계약,
  legacy ODROID fail-closed, future timestamp 차단, live collector readiness 검증을 추가했다.
- candidate `b7944ad`의 WSL 백엔드는 `67 passed`, 프론트는 `47 passed`와 TypeScript/build를
  통과했다. `E2E_BASE_URL=https://pr.digitie.mywire.org EXPECTED_RELEASE_SHA=<candidate>`로
  live E2E `5 passed (13.3s)`를 확인했고, strict cutover gate는 `samples=7`,
  `failed_samples=0`, `gate_duration_seconds=300`, `source_lots=53`, `target_lots_checked=53`이었다.
- GitHub Actions push run `32559078722`와 PR run `32559082014`는 live job 재실행을 포함해
  backend/frontend/live-e2e 모두 통과했다. 첫 live job은 배포 경합으로 구 SHA를 읽었고,
  재실행은 `b7944ad`를 읽어 통과했다.
- `T-030`(주차 현황·주차요금 → `python-krairport-api`)을 구현하고 PR
  [#3](https://github.com/digitie/parking-radar/pull/3)으로 머지했다. 실 서비스 키로 live
  검증하는 과정에서 krairport 자체의 KAC HTTPS 스킴 버그(모든 KAC 호출이 `https://`로 고정돼
  있었으나 실제로는 `http://`에서만 응답)와, parking-radar `parse_kac_fee`의 사전 존재하던
  필드명 버그(SCREAMING_SNAKE_CASE로 기대했으나 실제 응답은 camelCase — KAC 주차요금 수집이
  이전부터 항상 0건이었을 가능성)를 함께 발견했다. krairport 버그는 원칙대로
  `python-krairport-api` 자체(별도 PR [#6](https://github.com/digitie/python-krairport-api/pull/6))에서
  고쳤고, parsers.py 버그는 이 PR 안에서 고쳤다.
- `T-032`(PostgreSQL을 `docker-compose.db.yml` 별도 컨테이너로 분리, 포트 재배치: DB
  `14000`/API `14001`/web `14002`)를 구현하고 PR
  [#4](https://github.com/digitie/parking-radar/pull/4)로 머지했다. 14번 운영 데이터는
  `pg_dump` 사전 백업 후 기존 named volume을 재사용하는 방식으로 무손실 전환했고,
  `parking_snapshots` 56,039건을 전환 후 재확인했다. 외부 reverse proxy는 사용자가 직접
  새 포트로 갱신했다.
- ADR-005(백엔드 API `/v1` 버저닝 + RFC7807 에러 통일 + `docs/openapi.json` 기계 정본)를
  구현하고 PR [#5](https://github.com/digitie/parking-radar/pull/5)로 머지했다. hostile
  review(Popper)가 지적한 `RequestValidationError`의 RFC7807 미적용과
  `scripts/verify_cutover.py` target 호출의 버저닝 누락을 같은 PR에서 고쳤다. `{data, meta}`
  envelope는 범위 밖으로 명시적으로 미뤘다(ADR-005 "후속" 참고). `live-e2e`는 14번이 이
  candidate로 아직 배포되지 않아 예상대로 실패했다.
- PR #5(`/v1` API 버저닝)를 14번에 배포하고 live 검증까지 완료했다. `scripts/deploy-server14.sh`를
  WSL에서 SSH로 실행했다(Windows Git Bash에는 SSH 키 접근이 없어 실패, WSL은 성공 —
  스크립트 자체는 CRLF 문제로 WSL bash에서 shebang 파싱에 실패해 `sed`로 LF 정규화한
  임시 사본을 실행했다. 원본 스크립트 파일 자체는 git상 LF로 저장돼 있고, 로컬 체크아웃의
  Windows `core.autocrlf` 변환이 원인이었다). 배포는 서버14가 여러 다른 프로젝트
  (`kor-travel-map`, `pinvi` 등)의 동시 빌드로 혼잡해 예상보다 오래 걸렸을 뿐 실제로는
  정상 진행 중이었다 — 폴링 출력이 오래 멈춰 보일 때 별도 SSH 연결로 실제 프로세스 상태를
  재확인해 멈춘 게 아님을 확인했다. 배포 후 `release_sha=03bd6f3`로 `/health`,
  `/v1/airports`, `/v1/parking/current`, `/v1/admin/collector-status`가 모두 정상
  응답했고, hostile review에서 Popper가 지적한 `RequestValidationError`의 RFC7807
  누락 수정도 실제로 `422` + `application/problem+json`으로 확인했다. 외부 도메인
  (`pr-api.digitie.mywire.org`, `pr.digitie.mywire.org`)도 같은 SHA로 응답해 reverse
  proxy 추가 변경 없이 그대로 동작했다.
- 사용자 요청으로 공휴일(KASI 특일 정보) 조회도 krairport와 같은 패턴으로
  `python-kasi-api`(`kasi`)로 이관했다(`T-030`/ADR-004와 동일한 provider 라이브러리
  원칙). ADR-006 신규 작성, `codex/kasi-holiday-migration` 브랜치 PR
  [#7](https://github.com/digitie/parking-radar/pull/7)로 구현 완료. krairport 때와 달리
  이번에는 필드명/endpoint 불일치 같은 새 버그를 발견하지 못했다 — 순수 provider 교체였다.
- hostile review(James/Popper) 모두 P0/P1 없음을 확인했다. Popper가 지적한 P2(공휴일은
  `CollectionService`처럼 별도 rate-limit backoff 스케줄링이 없다는 점)는 의도적 범위
  선택으로 판단해 ADR-006에 근거를 남겼다. PR #7을 머지(`986d64e`)하고 14번에 배포해
  live 검증까지 완료했다: `release_sha=986d64e`, `GET /v1/holidays/summary`가 실제
  서비스 키로 `source=kasi_holiday_info`, 광복절/대체공휴일 데이터를 정상 반환했다.
- `T-031`(Docker 컨테이너에서 `test_cutover_guards.py`가 `ModuleNotFoundError`로 깨지던
  사전 버그)을 고쳤다. `sys.path` 계산이 로컬 repo-root 깊이(`parents[2]`)를 하드코딩해
  Docker 이미지(`backend/`가 `/app`으로 flatten됨)에서만 깨졌던 것을, `parents[1]`/
  `parents[2]` 둘 다 시도해 `observe_cutover.py`가 실제로 존재하는 디렉터리를 찾는
  `_scripts_dir()`로 교체했다. hostile review에서 `is_dir()`만으로는 우연히 존재하는
  다른 `scripts/`를 잘못 고를 수 있다는 지적을 받아 파일 존재까지 확인하도록
  강화했다. PR [#9](https://github.com/digitie/parking-radar/pull/9) 머지, WSL/Docker
  양쪽 `82 passed`(제외 없이 전부 통과).
- `T-029`(`flight_status.py` → `python-krairport-api`)를 완료해 ADR-004 전체 범위를
  마무리했다. KAC ODCloud(`FlightStatusListDTL`)는 krairport의 다른 KAC 서비스와 다른
  호스트(`api.odcloud.kr`)를 쓰는 별도 provider라, `python-krairport-api`에
  `KacClient.flight_status_detail_raw_items()`를 새로 추가하고(별도 저장소 PR
  [#7](https://github.com/digitie/python-krairport-api/pull/7), 커밋 `cbe4d13`) parking-radar의
  pin을 갱신했다. IIAC는 krairport의 기존 `iiac_raw_items`가 endpoint와 정확히 일치해
  라이브러리 수정 없이 전환했다. hostile review(James/Popper)에서 두 가지를 지적받아
  고쳤다: (1) IIAC 출발/도착 테스트가 공유 mock return value 때문에 두 호출을 구분하지
  못하던 것을 `side_effect`로 강화, (2) `KrairportRateLimitError`가 다른 upstream 오류와
  동일하게 처리돼 캐시되지 않던 것 — 비행편은 페이지 조회마다 즉시 호출되므로 rate limit
  창 동안 방문자마다 upstream을 재호출해 창을 계속 갱신하는 문제가 있어, `status:
  "rate_limited"`로 구분하고 `upstream_rate_limit_backoff_seconds` 동안 캐시하도록
  고쳤다. PR [#10](https://github.com/digitie/parking-radar/pull/10) 머지(`9961579`), 14번에
  배포해 live 검증 완료: `release_sha=9961579`, KAC(`GMP`)와 IIAC(`ICN`) 양쪽
  `/v1/flights/status`가 실제 서비스 키로 `status=success`와 실제 항공편 데이터를
  반환했다.

## 2026-08-24

- 사용자 요청으로 운영 호스트 `192.168.1.14`의 별칭을 "server14"/"14번"에서 "n150"으로
  통일했다(과거 기록 문서는 그대로 보존). `docs/journal.md`/`docs/tasks-done.md`/
  `docs/runbooks/migration.md`처럼 히스토리를 다루는 문서는 고치지 않았다.
- n150이 느리다는 신고를 받아 조사했다: CPU 4코어에 load average `30.57`(1분), swap
  `4.0Gi/4.0Gi`(거의 꽉 참), 컨테이너 42개가 동시에 떠 있었다(kor-travel-map,
  kor-travel-geo, pinvi, tvnm05 등 parking-radar 외 다른 프로젝트가 대부분). 원인은
  parking-radar 자체가 아니라 여러 프로젝트가 4코어 호스트를 공유하며 용량을 초과한
  것으로 판단했다. `tvnm05-current-*`/`tvnm05-live-*`가 동시에 떠 있어 중복처럼 보였지만
  생성 시각을 확인해 보니 candidate/live 두 환경이 의도적으로 공존하는 blue/green
  패턴이라 정리 대상이 아니라고 판단하고 손대지 않았다. `vm.swappiness`가 아무 파일에도
  설정돼 있지 않아(커널 기본값 60) `/etc/sysctl.d/99-parking-radar-swappiness.conf`에
  `vm.swappiness=10`을 등록해 적용했다(load average `30.57`→`25.01`로 소폭 개선). 이미
  swap에 올라간 4GiB를 강제로 비우는 `swapoff -a && swapon -a`는 당시 free 메모리가
  2.1GiB뿐이라 OOM 위험이 있어 실행하지 않았다.
- 사용자 요청으로 PostgreSQL dump를 3일마다 자동 생성하도록
  `scripts/n150-backup-cron.sh`를 추가했다(PR
  [#13](https://github.com/digitie/parking-radar/pull/13)). 앱 코드 변경 없이
  `POST /v1/admin/backups`를 `localhost:14001`로 호출만 하는 독립 스크립트이며, 오래된
  dump 정리는 기존 `BACKUP_RETENTION_COUNT`가 그대로 담당한다. n150의 crontab(다른
  프로젝트 백업 job과 공존, `CRON_TZ=UTC`)에 `0 18 */3 * *`(3일마다 03:00 KST)로
  등록하고 dry-run으로 실제 dump 생성을 확인했다. Windows 로컬 체크아웃의
  `core.autocrlf`가 `scp`로 옮긴 스크립트를 CRLF로 깨뜨려(`deploy-server14.sh`와 동일한
  문제) 원격에서 `sed -i 's/\r$//'`로 정규화해야 했다.

## 2026-09-06

- 사용자 요청으로 ADR-007(저장소/패키지/n150 운영 식별자를 `kor-travel-airport`로 개명,
  배포되는 웹앱 브랜드는 `parking-radar`로 분리 유지)을 PR
  [#15](https://github.com/digitie/kor-travel-airport/pull/15)로 구현·머지했다(`395717b`).
  이 세션에서 n150 live 상태를 직접 재확인했다: 외부 게이트웨이(`pr-api.digitie.mywire.org`,
  `pr.digitie.mywire.org`)와 n150 로컬 모두 `release_sha=395717b`로 응답했고, DB
  ready/seeded, scheduler 정상 수집(180초 effective tick, 연속 5회 success, rate-limit
  없음)까지 확인해 rename 자체가 이미 무중단으로 n150에 정착해 있음을 검증했다.
- rename 작업 중 발견한 사전 버그(두 배포 스크립트 `scripts/deploy-server14.sh`,
  `scripts/n150-backup-cron.sh`가 git에 100644로 추적돼 `git archive` 재배포 때마다 n150에서
  실행 권한이 초기화되는 문제, PR #13 활성화 당시 크론이 exit 126으로 실패해 수동
  chmod로 우회했던 것)를 PR
  [#16](https://github.com/digitie/kor-travel-airport/pull/16)로 100755로 고쳤다.
- 이 세션(Windows 로컬)에는 n150 SSH 공개키가 등록돼 있지 않아 처음엔 배포가 막혔다 —
  사용자가 WSL에는 이미 `digitie@192.168.1.14` SSH 접근이 되어 있음을 알려줘 이후
  모든 `scripts/deploy-server14.sh` 실행은 `wsl.exe -e bash -lc '... bash
  scripts/deploy-server14.sh'`로 진행했다(Windows Git Bash에는 여전히 키가 없다는 사실을
  `docs/dev-environment.md` 또는 이 파일에 남겨 다음 세션이 반복 조사하지 않도록 한다).
- hostile review(James/Popper)를 PR #16에 대해 실행했다. James는 P0/P1/P2 없음. Popper는
  P1(파일모드 fix가 git에만 있고 n150에 실제로 재배포·검증됐는지 diff/문서 어디에도 없다는
  점)과 P2 2건(향후 mode 회귀를 잡는 CI 가드 부재, `backend/Dockerfile`의 `COPY scripts`가
  mode-only 변경에도 이미지 캐시를 무효화하는 점)을 지적했다. P1은 실제로 HEAD(`605fa80`)를
  n150에 배포한 뒤 `stat -c '%a'`로 두 스크립트가 `775`인지 확인하고
  `n150-backup-cron.sh`를 직접 실행해 exit `0`과 실제 `parking-radar-*.dump` 생성까지
  재현·검증하는 것으로 해소했다(수정 코드는 필요 없었다 — 지적대로 "검증이 없었다"는
  공백 자체를 이 세션에서 메웠다). P2 두 건은 이번 PR 범위 밖으로 판단해 코드는 고치지
  않았다 — CI mode 가드는 별도 task로 남길 만하지만 지금 백로그에 넣지 않았고, Dockerfile
  캐시 무효화는 기능에 영향이 없는 빌드 시간 이슈라 그대로 뒀다.
- PR #16을 squash-merge(`b893d0b`)했다. squash 특성상 main의 최종 SHA가 배포에 썼던 브랜치
  팁(`605fa80`)과 달라져, `release_sha`를 main과 정확히 맞추기 위해 `b893d0b`를 다시
  n150에 배포했다(내용은 동일해 Docker 레이어 대부분 캐시 히트). 최종적으로 외부
  게이트웨이가 `release_sha=b893d0be8c534d5392ed08453b292ce3493db7e3`로 응답하고 web도
  200을 반환하는 것까지 확인했다.
- 사용자 요청으로 shadcn/ui 전환 + 과거 자료 조회 기능 + Hallmark 재감사/재설계
  initiative를 시작했다(`docs/tasks.md` T-033~T-038, 계획 파일
  `C:\Users\digit\.claude\plans\iridescent-finding-parasol.md`). 조사 결과 프론트엔드는
  Tailwind/컴포넌트 라이브러리 없이 순수 CSS(1844줄 `globals.css` + oklch `tokens.css`)로
  된 단일 페이지 앱이었고, 백엔드 history/analytics API는 전부 상대 `days` 조회만
  지원해 임의 과거 날짜 조회가 불가능했다. `F:\dev\pinvi`의 `AppShell.tsx`(데스크톱
  상단 탭 / 모바일 하단 탭바 4+더보기)를 IA 참고 패턴으로 확인했다.
- T-033(shadcn/ui 기반 도입, PR [#18](https://github.com/digitie/kor-travel-airport/pull/18))을
  구현했다. `npx skills add shadcn/ui`로 스킬을 저장소 루트 `.agents/skills`(관례에 맞춰
  `.claude/skills`는 심볼릭 링크가 아닌 실제 복사본으로 — 이 환경은 `core.symlinks=false`라
  심볼릭 링크를 커밋하면 세션 로컬 절대경로가 박힌 깨진 텍스트 파일이 된다)에 설치한 뒤
  `npx shadcn@latest init --defaults`(Tailwind v4 + Base UI, nova style)로 초기화했다.
  init이 자동으로 저지른 세 가지 사고를 감지·수정했다: (1) 이 프로젝트가 이미 쓰던
  `--muted`/`--accent`/`--radius`를 shadcn 자체 기본값으로 덮어써 기존 ~30곳의 규칙이
  깨질 뻔한 것을 소스 토큰(`--muted-foreground`/`--color-accent`/`--radius-card`)으로
  재배선, (2) `next/font/google`의 Geist를 주입해 한글 최적화 Pretendard 스택을 덮어쓴
  것을 되돌림, (3) Next.js 16이 `frontend/AGENTS.md`/`CLAUDE.md`를 자동 생성한 것을
  `agentRules: false`로 차단(저장소는 루트에만 CLAUDE.md/AGENTS.md를 둠, CLAUDE.md §1).
  hostile review(James/Popper)에서 James가 P0(Tailwind Preflight가 h1~h6의
  font-weight/font-size를 inherit로 리셋해 헤딩이 굵기·크기를 잃는 것, 브라우저에서
  `getComputedStyle`로 재현 확인 — h1 400/h2·h3 16px)를 지적해 원래 UA 기본값(h1 bold,
  h2 1.5em/700, h3 1.17em/700)을 명시적으로 복원했다. Popper가 지적한 P1(Tailwind v4
  네이티브 바이너리가 n150의 Alpine(musl) 이미지에서 실제로 빌드되는지 CI만으로는
  증명 못 한다는 점)은 WSL Docker로 `frontend/Dockerfile`을 직접 빌드해 성공을
  확인하는 것으로 해소했다. PR #18을 squash-merge(`67e9199`)하고 n150에 배포,
  release_sha 일치와 live E2E `5 passed`(320/375/414/768px 무-오버플로 포함)까지
  확인했다. 컴포넌트 JSX는 아직 바꾸지 않았다 — T-034(shadcn 프리미티브 치환)가 다음
  단계다.
- T-034(컴포넌트를 shadcn 프리미티브로 교체, PR
  [#20](https://github.com/digitie/kor-travel-airport/pull/20))를 구현했다.
  native button/table/`window.confirm()`/`.metric-card`/`.notice`를 shadcn
  Button/Card/Table/Alert/AlertDialog로 바꾸되 기존 className·`data-testid`를 전부
  보존해 Tailwind utility layer가 항상 unlayered legacy CSS에 밀린다는 걸 활용했다.
  `<select>`/`ResponsiveSection`의 `<details>`/daily-flight-overlay-chart의 토글·
  체크박스는 기존 테스트가 native DOM 구조(`getByDisplayValue`, `open` 속성,
  `aria-pressed`)에 의존해 이번엔 일부러 안 건드렸다 — 근거를 커밋 메시지와
  tasks-done.md에 남겼다. hostile review(James/Popper)가 이번엔 진짜 결함을 여럿
  찾았다: James가 성공 메시지까지 shadcn Alert(항상 `role="alert"`)로 감싸 매 수동
  수집 성공마다 assertive 알림이 뜨던 것(P1), 다운로드 버튼 `variant="link"`가 없던
  hover 밑줄을 추가한 것(P2, cascade layer는 "겹치는 속성"만 보호한다는 걸 이번에
  확인), AlertDialogCancel의 onClick+onOpenChange 중복 취소(P2)를 지적했다. Popper는
  더 무겁게 봤다 — 무인증 destructive 백업/복원 API(ADR-003)의 유일한 안전장치를
  바꾸면서 `AlertDialogAction`에 `disabled={busy}`가 빠진 것(P1)과 회귀 테스트가
  하나도 없는 것(P1)을 지적했다. 전부 수정하고 `backup-panel.test.tsx`에 4개 테스트를
  추가했는데, 그 중 하나(dialog 열린 동안 배경 버튼이 `inert` 처리되어 접근성 트리에서
  완전히 사라지는지)가 Popper 본인이 "jsdom은 검증 불가"라고 적었던 것과 달리 실제로
  jsdom에서 검증 가능함을 확인했다 — `disabled` 속성이 아니라 Base UI의 `inert`
  처리 자체를 `queryByRole`로 직접 증명했다. PR을 머지하고 CI에서 `tsconfig.test.json`
  기준 타입에러(`pre_restore_backup: null` vs 실제 타입 `| undefined`, 기본
  tsconfig는 tests/를 제외해서 로컬에서 못 잡았었다)를 한 번 더 고쳤다. n150 배포,
  release_sha `95ac97d` 일치, live E2E `5 passed`(백업 패널 노출 확인 포함) 확인했다.
- T-035(라우트 기반 앱 셸, PR [#22](https://github.com/digitie/kor-travel-airport/pull/22))를
  구현했다. 531줄 단일 컨트롤러 `dashboard-app.tsx`를 `DashboardProvider` context +
  라우트별 view 5개(`/`·`/analytics`·`/history`·`/fees`·`/backup`)로 쪼개고, pinvi
  `AppShell.tsx` 패턴을 참고한 새 `AppShell`(데스크톱 상단 탭 전부 인라인, 모바일 하단
  탭바 4 primary + shadcn `Popover` 기반 "더보기"로 백업을 뒤로 뺌)을 얹었다. 데스크톱/
  모바일 마크업을 CSS-only(`hidden lg:block`/`lg:hidden`)로 동시에 렌더링해 기존 JS
  뷰포트 분기(`useViewportMode()`)를 제거했고, `/analytics`엔 2차 탭(요일별/공휴일/
  임계치/일별 흐름)을 둬 사용자가 요청한 "PC 화면도 메뉴나 탭으로 상세 뷰 분리"를
  달성했다. hostile review(James/Popper, 서로 다른 렌즈의 독립 서브에이전트 2개)에서
  P1을 다섯 건 이상 발견했다 — 분석/과거조회 fetch 에러가 라우트 분리 과정에서 완전히
  조용히 사라지던 것(두 리뷰어가 공통으로 지적), 공항/주차장 변경 시 분석 데이터가
  이중으로 fetch되던 것, 모바일 "더보기" popover가 라우트 이동 후에도 안 닫히던 것,
  요금계산 화면이 bootstrap 실패 시 "불러오는 중"에 영원히 멈추던 것, 임계치 탭
  패널이 그리드 CSS 없이 고아 클래스로 남아 레이아웃이 무너진 것, `/backup`이 무인증
  destructive 관리 UI인데 크롤러가 바로 찾을 수 있는 고정 링크가 된 것(ADR-003 전제
  변경, 관련 addendum을 ADR-003에 남김). 전부 재현·수정하고 회귀 테스트를 추가했다.
  PR #22를 squash-merge(`0f15751`)하고 n150에 배포, release_sha 일치와 live E2E
  `15 passed`(첫 회는 실시간 collector 상태가 마침 `partial_success`였던 기존
  단언 1건만 일시 실패, 다음 스케줄러 사이클에서 재확인해 `success`로 통과 — 코드
  회귀 아님)까지 확인했다. 상세는 `docs/tasks-done.md` T-035 참고.
- T-035 docs 갱신 PR(#23) 작업 중 CI live-e2e에서 데스크톱 "일별 흐름" 탭 클릭과
  모바일 "더보기" popover 클릭이 CI에서만(로컬 재실행은 계속 통과) 실패하는 걸
  발견했다. 무시하지 않고 Chrome DevTools Protocol로 실제 n150 사이트에 직접
  500kbps/300ms RTT 스로틀링을 걸어 로컬에서 재현했다 — 라우트 전환 직후 바로
  클릭하면 React가 그 요소의 이벤트 핸들러를 아직 재연결하지 못한 상태(hydration
  타이밍)라 클릭이 조용히 무시되고(같은 조건에서 클릭 전 3초 대기를 추가하면
  통과함을 확인해 가설 검증), CI 러너가 한국 서버까지의 네트워크 지연이 로컬보다
  훨씬 커서 이 레이스가 CI에서만 결정적으로 드러났다. T-035의 Popover 제어 로직
  자체는 정상이었다 — 느린 연결의 실사용자도 겪을 수 있는 클라이언트 라우팅 앱
  공통의 특성. `e2e/live-dashboard.spec.ts`에 `clickUntilEffective()`
  (`expect(...).toPass()`로 클릭→결과 확인을 통째로 재시도)를 추가해 해소했고,
  throttling으로 3회 연속 재현·수정 확인 후 스크래치 테스트는 삭제했다. 상세는
  `docs/tasks-done.md` T-035 "후속 발견" 참고.
- T-036(과거 자료 조회 기능, PR [#24](https://github.com/digitie/kor-travel-airport/pull/24))을
  구현했다. 원래 계획한 `/v1/parking/history`가 프론트에서 전혀 안 쓰인다는 걸 조사로
  발견해, 실제로 `/history`가 렌더링하는 `/v1/parking/analytics/timeseries`에
  `start_date`/`end_date`를 추가하는 쪽으로 범위를 재조정했다. hostile
  review(James/Popper)에서 Popper가 P0를 하나 발견했다 — `build_time_series`를 직접
  실행해 재현: 이 함수가 버킷 배치 기준점을 요청한 end_date가 아니라 "실제 마지막
  관측 스냅샷"으로 잡아서, 요청 범위 끝에 수집 공백(백업 복원 중 scheduler 중지,
  업스트림 rate-limit 등)이 있으면 응답이 조용히 요청 범위보다 앞으로 밀리는데
  응답의 start_date/end_date 필드는 원래 요청을 그대로 주장한다. 실제로 트레일링
  갭이 있는 데이터로 회귀 테스트를 만들어 수정 전 실패·수정 후 통과를 확인했다.
  James가 지적한 달력 타임존 버그(disabled 범위가 브라우저 로컬 타임존으로 비교돼
  Asia/Seoul과 최대 하루 어긋남)도 반영했는데, 이번엔 반대로 James가 같이 지적한
  `toDateKey()` 자체의 타임존 버그 주장은 5개 타임존으로 직접 재현 시도해본 결과
  실제로는 버그가 아님을 확인하고 그 부분은 고치지 않았다 — hostile review 지적도
  "재현해서 확인 후 반영"이 원칙이지 무조건 수용이 아님을 보여준 사례. 그 외 Popover
  접근성 이름 누락, 한글 앱에 영어 달력, 포커스 유실, 임의 범위의 무제한 버킷 수 등도
  전부 재현·수정했다. PR #24를 squash-merge(`b9bdf1a`)하고 n150에 배포,
  release_sha 일치 확인. 배포 직후 외부 게이트웨이가 잠깐 504를 반환했지만 n150
  로컬 컨테이너는 SSH로 직접 확인한 결과 둘 다 healthy였다 — 외부 게이트웨이 쪽
  일시 장애로 판단했고 2분 뒤 재확인해 정상화됐다. live E2E 15개 중 14개 PASS,
  나머지 1개는 T-035에서 이미 기록한 것과 같은 기존 `collector-status` 플레이크.
  상세는 `docs/tasks-done.md` T-036 참고.
