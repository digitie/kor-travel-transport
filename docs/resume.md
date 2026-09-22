# resume.md — 현재 인수인계

## 현재 상태

- 2026-09-22 `codex/transport-map-view`에서 주유소·역·항구 지도와 저장 장소 API를 구현 중이다.
  항구 좌표는 키 없는 해양수산부 항만가이드라인 CSV에서 RustFS 보관 후 연결하고, 시간표는
  실시간 요청만 허용한다. 다음 단계는 Docker/HTTPS UI 검증, 적대적 리뷰, provider와 transport
  PR의 CI·머지다.

- 2026-09-22 `codex/transport-dashboard-performance`은 n150에서 7일 통계가 약 3.9초,
  수집 상태가 30ms인 것을 측정했다. 대시보드는 빠른 저장 상태·돌발을 먼저 표시하고,
  통계는 독립 패널로 늦게 반영하며 60초 session cache를 사용하도록 보완했다. 느린 통계가
  수집 상태 화면을 가로막지 않는 Playwright 계약을 추가했다. Docker build와 n150 live
  E2E, CI·적대 리뷰 뒤 별도 PR로 머지한다.

- 2026-09-22 `codex/transport-admin-e2e-expansion`은 병합 뒤 n150 HTTPS UI E2E를
  260개 운영 행렬로 확장 중이다. 재현된 관리 proxy 10초 abort/`502`를 공개 gateway와
  같은 30초 timeout으로 보완했다. route-filter 통계의 public `504`에는 covering index
  migration `0008`을 추가했다. 두 적대 리뷰는 P0/P1 없음으로 결론냈고, P2로 받은
  공격 Origin CSRF 검증과 invalid concurrent index 복구 문서를 반영했다. n150 backend
  migration 배포와 260개 HTTPS live E2E(260/260, 2분 18초), backend/frontend/admin CI를
  모두 통과했다. 별도 PR #34는 Draft 해제·squash merge만 남았다.

- 2026-09-22 `codex/transport-admin` PR #33 후보 `92cb128`은 n150에 전용 API
  `12301`, Dagster `12302`, UI `12305`로 배포됐다. backend health SHA 일치와
  7일 통계 `2.50초`를 확인했다. HTTPS browser E2E가 발견한 로그아웃의 internal HTTP
  redirect와 Dagster CSRF 기대값을 보완 중이므로, 이 후속 패치를 CI·두 적대적 리뷰·live
  E2E에 다시 통과시킨 뒤에만 머지한다.

- 2026-09-22 `codex/transport-admin`에서 weather admin과 같은 인증된 server-side proxy
  구조의 transport 전용 운영 UI를 구현 중이다. 기존 `parking-radar` frontend/Compose는
  변경하지 않는다. 새 독립 Compose project는 public API `12301`, Dagster `12302`, UI
  `12305`를 사용한다. Manager ADR-48의 사전 정의된 monitoring 포트는 Prometheus
  `12102`, cAdvisor `12103`, Grafana `12104`이며, 이 전환과 n150 live E2E가 다음
  배포 게이트다.

- 2026-09-22 현재 `codex/shared-db-dagster`의 PR #32는 최신 후보를 n150에 배포한 상태다.
  외부 live E2E가 KREX 동일 관측 시각의 행에서 과거 `collected_at`을 읽는 정합성 문제를
  발견했다. 수집 성공 때 동일 행의 수집 run·원본 값·수집 시각을 갱신하도록 보완하고,
  WSL 회귀 검증을 통과했다. 이 후속 커밋의 CI, James/Popper 재리뷰, live E2E를 모두
  통과한 뒤에만 PR을 머지한다.

- 현재 후보는 `e8ad95f` 이후 적대적 리뷰 P0/P1을 보완하는 후속 커밋이다. Manager bootstrap PR #381이 병합·n150 재설치됐고,
  transport application/Dagster 전용 shared DB와 RustFS raw bucket이 준비됐다. legacy
  history의 final dump/restore·count/watermark 검증도 끝났으며 receipt가 배포 전제조건으로
  남아 있다. runtime은 Manager Weather 정본과 동일한 host-network로
  `127.0.0.1:11000` PostgreSQL과 `127.0.0.1:12101` RustFS에 접근한다.
- n150에 `e8ad95f`을 배포해 application/Dagster metadata migration, backend, code-server,
  webserver, daemon, gateway, frontend가 모두 정상 기동한 것을 확인했다. `/health`의
  release SHA가 후보와 일치하고, code-server/webserver는 loopback 전용, gateway는
  무인증 요청에 401을 반환한다. 이번 보완은 cutover candidate staging/n150 direct deploy,
  legacy rollback env 보존, gateway loopback bind, 공항 수집 advisory lock의 전용 connection
  소유권을 추가한다. 다음 한 작업은 이 후보를 배포한 뒤 CI·두 적대적 리뷰·live E2E를
  통과시켜 PR #32를 머지하는 것이다.
- 현재 브랜치는 `codex/shared-db-dagster`다. 운영 scheduler 분리, 3일 주기 철도·여객항구
  기준정보 Dagster job, RustFS 원본 참조, shared PostgreSQL compose overlay를 구현했다.
  `python-kric-api#3`은 CI와 두 적대적 리뷰를 통과해 `6ed5ace`로 병합됐고, pagination 보강 PR #4의
  `cd01fbc`를 transport가 고정한다. 그
  commit을 고정한다. 항구 시간표는 DB·raw response에 저장하지 않는 실시간 조회 계약이다.
  `python-kric-api#4`의 bounded pagination 병합 SHA `cd01fbc`를 고정했다. 여객항구 기준정보 job은
  Manager RustFS/DB bootstrap이 준비된 뒤에만 활성화할 수 있다.
- 최신 검증은 새 `python-kric-api@cd01fbc` 환경의 WSL backend 138개 통과/1개 live skip, 새 image와
  `0006` migration을 적용한 Docker backend 139개 통과다. shared overlay `docker compose config`와
  shell syntax 검사는 통과했다. 공용 DB 전환은 검증 없는 기동을
  금지하며, legacy history final dump/restore·count/watermark 검증과 Dagster metadata migration
  one-shot을 요구한다. 다음 작업은 provider PR #4 병합·pin 갱신, Manager의 transport app/Dagster
  전용 role·DB와 RustFS bucket bootstrap PR, 이어서 feature REST와 항구 실시간 시간표 endpoint 구현이다.

- 이 작업의 목표는 `kor-travel-transport`를 국내 여행용 통합 교통정보 라이브러리/API로
  운영하는 것이다. provider에서 데이터를 주기적으로 수집해 PostgreSQL에 저장하고,
  저장 자료를 외부 OpenAPI와 내부 통계로 즉시 제공한다.
- 현재 T-040 브랜치에서 `python-krex-api` 고속도로 소통·돌발과 최신
  `python-opinet-api` Playwright 주유소·유가 수집/저장/API/통계를 구현했다. WSL2
  백엔드 전체 테스트는 통과했다. 최신 보강에서는 DB 실패 실행의 durable 상태,
  RFC7807 OpenAPI 계약, 활성 live 소스의 실제 저장·최신성 E2E 검증을 추가했다.

- 기준일: 2026-09-20
- 최신 검증: 런타임 `f7987b2d8858e83b2a602ac70cdcd5b5a4902d6b`의 WSL/Docker
  PostgreSQL 백엔드 각각 130개, 프론트 각각 85개와 타입/build가 통과했다. n150 배포와
  공개 health SHA 일치, 설치 OPINET `39e7acc`의 초기 탐색/종료(지역 조회 0회)를 확인했다.
  유가 59,035건과 다음 07:05:20 KST 예약은 보존됐다. 배포 직후 WSL E2E 첫 주차 표시의
  timeout 실패(15개 통과/1개 실패)를 보존했으며, 이후 동일 SHA GitHub push/PR CI의
  backend/frontend/live-e2e는 모두 통과했다. 아래는 이 최종 검증에 이른 진행 이력이다.
- 작업 브랜치: `codex/transport-collection-openapi`, Draft PR #30.
  기존 검증 런타임은 `50c9cd42d2f7a071f216d815e9bbce94546383ca`이며 현재 후보는
  후속 OPINET `39e7acc` pin과 검색 문맥 API 설명·통합 회귀를 추가한 상태다.
  n150 최종 배포는 `15d46a9a223827c7732d984f73822fbe7e15712e`이며 공개 `/health`의
  SHA 일치와 DB 정상 상태를 확인했다. 이 배포의 런타임은 위 `50c9cd4`와 동일하다.
  형제 provider 수정 PR은 KREX #16(`adda287`), OPINET #18(`39e7acc`)이다. 앞선
  `1601ef3`의 실제 수집 후 최종 리뷰에서 지역 간 동일 UID 가격 소실 경로를 재현해
  provider의 전역 병합으로 보완했고 통합 의존성을 새 SHA로 고정했다. 통합 최종 리뷰의
  추가 P1을 `af26362`/`02545fe`에서 보완했으며, 소스별 DB transaction 격리를 추가해
  검증을 완료했다. 기존 candidate의 WSL 백엔드 전체 125개가 통과했고 격리 보완 후에는
  실제 PostgreSQL NOT NULL 오류를 이용한 집중 테스트 4개 및 최종 전체 128개가 통과했다.
  고속도로 소통/돌발의 독립 성공·backoff, skip 기록의 실패 은폐 방지, 유효 가격 없는
  OPINET 실패 처리, RFC7807 500 및 JSON 프록시 body timeout을 보강한다.
  수정 프론트 WSL 전체 80개/타입 검사/build와 Docker 80개 통과. 두 reviewer가
  `50c9cd4` 코드의 P0/P1 없음으로 판정했다. James는 코드 승인, Popper는 전국 유가
  운영 게이트 미완료로 최종 승인을 보류했다. Docker 백엔드 128개도 통과했으며
  해당 런타임의 최종 n150 배포도 완료했다. 배포 SHA를 고정한 WSL 공개 live E2E는
  15개 통과/1개 실패했다. 실패는 `opinet_browser.last_error=collection_failed`로,
  소스 준비 상태 검증에서 멈춰 후속 교통/유가 조회·통계 검증에는 도달하지 않았다.
  이후 승인된 복구 실행과 강화 E2E는 아래와 같이 성공했다. 최종 후보 배포/CI 검증 전으로
  PR은 아직 미머지다.
  n150 실제 첫 KREX 성공은 소통 8,370건·돌발 80건이고, 다음 주기 수집과 공개 통계까지
  확인했다. 이는 전국 OPINET 성공 증적과 별개다.
  사용자 승인으로 22:23:21 KST에 예외 OPINET 전국 수집 run 13556을 1회 시작했다.
  기존 상태는 보호 receipt로 백업했고 기존 오류를 삭제하지 않았다. run 13556은
  23:12:02 KST에 success 완료, DB 기준정보 11,807곳/가격 59,035건/양수 29,426건을
  새 세션에서 확인했다. 다음 예정은 9월 20일 07:05:20 KST로 확정됐다.
  강화 E2E `308b278`을 배포 SHA `15d46a9`에 고정한 실행도 16개 모두 통과했다.
  별도 최신성 점검에서 20:31 KST 공개 소통 API의 최신 관측은 19:52 KST로 남아 있었다.
  새 공급자 연결에서도 같은 응답 시각을 확인했다. 수집 성공만으로 실시간 자료가
  갱신됐다고 간주하지 않는다. 22:25 KST에는 관측이 22:20 KST로 갱신됨을 확인했다.
  추가 E2E 보강은 관측/저장 시각 모두 15분 이내·미래 60초 이내를 요구한다. 회귀를
  포함한 프론트 WSL/Docker 85개, 타입/build와 두 코드 재리뷰를 통과했다.
- 다음 한 작업: 두 리뷰어의 최종 운영 확인을 마치고 증적 문서 후보의 배포 SHA와 CI를
  정렬한 뒤 provider PR #16/#18 및 PR #30을 `kor-travel-transport`에 머지한다. 그 다음에만 KRIC
  provider 구현과 교통정보 확장 조사 문서를 시작한다.
- `digitie/kor-travel-airport`(구 `digitie/parking-radar`) PR #2~#28 모두 **MERGED**
  상태다. 이 세션에서 다룬 마지막 코드/운영 PR은
  [#28](https://github.com/digitie/kor-travel-airport/pull/28)(UI 밀도 개선,
  T-039)이다.
- **완료된 initiative**: shadcn/ui 전환 + 과거 자료 조회 기능 + Hallmark
  재감사/재설계(계획 `C:\Users\digit\.claude\plans\iridescent-finding-parasol.md`)
  + UI 밀도 개선(T-039, 별도 계획 문서 없이 직접 요청).
  T-033(shadcn 기반 도입)·T-034(button/card/table/alert/confirm-dialog 치환)·
  T-035(라우트 기반 앱 셸)·T-036(과거 자료 조회 기능)·T-037(Hallmark audit)·
  T-038(Hallmark redesign)·T-039(UI 밀도 개선) 전부 완료·배포·live E2E 검증까지
  끝났다. 현재 진행 중인 작업은 `docs/tasks.md`의 T-040이다.
  - **T-039에서 새로 배운 것**: (1) "레이아웃이 비효율적"처럼 모호한 사용자
    피드백은 코드만 읽어서는 특정하기 어렵다 — 브라우저 확장이 연결 안 될 때는
    Playwright를 라이브 사이트에 직접 붙여 스크린샷으로 확인하는 게 코드
    추측보다 훨씬 빠르고 정확했다(이번 세션 내내 `mcp__claude-in-chrome__*`가
    연결되지 않은 상태였다). (2) 좁은 화면에 여러 텍스트 필드를 압축할 때는
    테스트에 쓴 표본 데이터가 아니라 실제 운영 데이터의 최댓값(길이·구분자
    위치)을 반드시 확인할 것 — 청주공항의 짧은 이름으로 검증하고 끝냈다면
    인천공항의 13자 주차장명(`T1 장기 P1/P2/P3/P4 주차타워`)에서 서로 다른
    주차장이 구분 안 되는 실사용 버그를 놓쳤을 것이다(hostile review가 잡음).
    (3) 새 UI가 기존 공유 CSS 클래스(`.action-stack`)를 재사용하면 그 클래스가
    다른 컨텍스트에서 이미 갖고 있는 반응형 규칙까지 같이 상속된다 — 공유
    클래스에 새 용도를 얹기 전에 기존 모든 사용처와 각자의 breakpoint 규칙을
    확인할 것.
  - **T-038에서 새로 배운 것**: (1) Hallmark 감사 지적을 그대로 코드로 옮길 때도
    새 버그를 만들 수 있다 — `.control-band` 브레이크포인트를
    `max-width: 64rem`으로 고쳤다가 Tailwind `lg:`의 `min-width: 64rem`과
    정확히 1024px에서 겹치는 새 overlap 버그를 만들었다(둘 다 경계값 포함이라
    같은 값을 쓰면 항상 겹친다) — `63.9375rem`처럼 한 스텝 아래 값을 써야
    진짜 배타적 구간이 된다. (2) `aria-live`는 "속성을 붙이는 것"이 아니라
    "상시 마운트된 엘리먼트의 내용을 바꾸는 것"이 핵심이다 — 이미 최종 내용을
    가진 채로 마운트되는 엘리먼트에 `aria-live="polite"`를 붙이는 건 스크린
    리더 announce를 보장하지 않는다(브라우저/AT마다 다름). 이 실수는
    `history-view.tsx`의 기존(이미 hostile-review를 거친) 패턴을 그대로 베낀
    데서 나왔다 — "이미 리뷰를 거친 기존 코드"도 검증 없이 복제하면 안 된다.
    (3) 디자인 감사가 지적한 minor(예: "클릭이 하나 더 필요함")를 고치기 전에
    그 UI가 무엇을 보호하는지 확인할 것 — `/backup`의 기본-접힘은 UX 결함이
    아니라 인증 없는 파괴적 관리 UI의 유일한 상호작용 게이트였다. 이 세션은
    hostile review가 지적하기 전까지 이걸 놓쳤다.
  - **T-036에서 새로 배운 것**: (1) 계획서에 적힌 API 대상(`/v1/parking/history`)이
    실제로 프론트에서 전혀 안 쓰이는 걸 조사로 발견했다 — task를 시작하기 전에 항상
    "이 endpoint를 실제로 누가 호출하는지" 먼저 확인할 것, 계획 문서가 최신이라고
    가정하지 말 것. (2) hostile review 지적을 무조건 수용하지 말고 재현해서 검증할
    것 — Popper의 P0(`build_time_series` 앵커 버그)는 직접 재현해 실제 버그로
    확인했지만, James가 같이 지적한 `toDateKey()` 자체의 타임존 버그 주장은 5개
    타임존으로 직접 재현 시도한 결과 사실이 아님을 확인하고 그 부분은 고치지
    않았다(반대로 James가 지적한 `disabled` 범위 비교 쪽 타임존 버그는 진짜였다 —
    같은 리뷰 안에서도 finding별로 따로 검증해야 한다). (3) 상대(`days`) 조회용으로
    설계된 시계열 버킷 함수(`build_time_series`)를 명시적 날짜범위 조회에 재사용할
    때는 "버킷 배치 기준점"이 암묵적으로 "최신 관측 시각"에 고정돼 있는지부터
    확인할 것 — 수집 공백이 있으면 조용히 잘못된 기간의 데이터를 반환할 수 있다.
    (4) react-day-picker(mode="range")는 클릭 1번으로 `{from, to}`를 모두 채운다
    (같은 날짜로) — "선택 완료 시 자동 닫기" 같은 로직을 짤 때 `from !== to`까지
    확인하지 않으면 첫 클릭만으로 팝오버가 닫혀버린다(실제로 이 버그를 만들었다가
    되돌렸다). 또한 react-day-picker는 선택이 바뀔 때마다 day-grid DOM 노드를
    리마운트하므로, 첫 클릭 전에 캡처해둔 두 번째 버튼 참조는 첫 클릭 후 detached된다
    — 테스트에서 두 번째 요소는 항상 재조회해야 한다.
  - **T-034에서 `<select>`/`ResponsiveSection`의 `<details>`/daily-flight-overlay의
    토글·체크박스는 의도적으로 안 건드렸다** — 기존 테스트가 native DOM 구조
    (`getByDisplayValue`, `<summary>` 클릭+`open` 속성, `aria-pressed`)에 의존해서다.
    T-035에서 라우팅이 실제로 바뀌었고 `ResponsiveSection`/`mobile-disclosure`
    패턴 자체가 없어졌지만(각 라우트가 자기 콘텐츠만 보여주므로 접이식 섹션이 불필요),
    `<select>`는 여전히 native로 남아 있다(AppShell의 공항/주차장 선택) — 그대로 유효한
    판단이다.
  - **로컬 검증 시 반드시 `npx tsc -p tsconfig.test.json --noEmit`도 같이 돌릴 것**
    (기본 `tsc --noEmit`은 `tests/`를 제외해서 안 잡힘) — T-034에서 이걸 놓쳐 CI에서
    한 번 걸렸다(`frontend` job이 정확히 이 명령을 실행함).
  - shadcn CLI(`init`/`add`)가 `globals.css`/`layout.tsx`를 자동 편집할 수 있으니
    (T-033에서 겪음: 기존 `--muted`/`--accent`/`--radius` 덮어쓰기, Geist 폰트 주입,
    Tailwind Preflight의 헤딩 bold 제거) 새 컴포넌트 추가 때마다 diff를 재확인할 것.
  - **T-035에서 새로 배운 것**: (1) 데스크톱/모바일을 CSS-only 동시 렌더링(`hidden
    lg:block`/`lg:hidden`)으로 바꾸면 RTL 테스트의 singular 쿼리(`getByRole`/
    `findByText`)가 "여러 개 찾음"으로 깨진다 — `getAllBy*`/`findAllBy*`로 바꾸거나
    `within()`으로 특정 nav를 스코프해야 한다. (2) 이 저장소의 `live-e2e` CI job은
    PR별 preview가 아니라 **실제 n150 운영 배포**(`pr.digitie.mywire.org`)를 대상으로
    돈다 — 새 라우트를 추가하는 PR은 머지 전 CI에서 항상 404로 실패한다(PR #18/#20/#22
    전부 동일 패턴, backend/frontend만 통과하면 머지 진행). (3) live E2E의
    `collector-status.last_run.status`를 `"success"`로 단언하는 기존 테스트는 실제
    운영 스케줄러가 `success`/`partial_success`를 주기적으로 오가서 실패할 수 있다 —
    코드 문제가 아니라 실시간 외부 API(KAC/인천) 특성이다. 보통 다음 스케줄러 사이클
    (3분 이내)에 `success`로 돌아오지만, 2026-09-06 재검증 때는 13분·5사이클 연속
    `partial_success`가 관측된 적도 있다(`raw_response_count`는 3으로 정상 — 소스
    자체는 다 응답하지만 그 중 일부 lot이 간헐적으로 실패). 여러 번 재시도해도 계속
    실패하면 코드 회귀가 아니라 실시간 데이터 상태이니 이 단언을 느슨하게(예:
    `["success","partial_success"]`에 포함되는지) 바꾸는 걸 별도 task로 고려할 만하다
    — 지금은 손대지 않았다. (4) **hydration 타이밍 레이스**: 클라이언트 라우트 전환
    직후 곧바로 다른 요소를 클릭하면(예: 탭 전환 직후 "더보기" 클릭) 로컬의 빠른
    연결에서는 안 드러나다가 CI 러너처럼 지연이 큰 환경에서만 클릭이 조용히
    무시되는 경우가 있다 — Chrome DevTools Protocol
    (`context.newCDPSession(page)` + `Network.emulateNetworkConditions`)로 실제
    네트워크를 로컬에서 스로틀링해 재현할 수 있다. 이런 클릭은
    `expect(async () => { await el.click(); await expect(result).toBe(...); }).toPass()`
    로 감싸 "효과가 실제로 나타날 때까지 클릭 자체를 재시도"하게 만들어야 한다(단순
    `.click()` 뒤 단언만 재시도하는 것으로는 해결 안 됨 — 클릭 자체가 무효였으므로).
- 저장소 식별자가 `parking-radar` → `kor-travel-airport`로 개명됐다(PR
  [#15](https://github.com/digitie/kor-travel-airport/pull/15), ADR-007). 배포되는
  웹앱 브랜드/백업 파일명/쿠키 키는 계속 `parking-radar`다 — `CLAUDE.md` §1 참고.
  n150 앱 디렉터리도 `/home/digitie/apps/kor-travel-airport`로 이미 이동 완료됐고,
  이 세션에서 n150 컨테이너 실사(`docker compose ps`)로 재확인했다.
- n150 SSH 접근: 이 저장소를 여는 Windows 로컬 세션(Git Bash)에는 n150용 SSH 키가
  등록돼 있지 않다. **WSL(`wsl.exe -e bash -lc '...'`)에는 `digitie@192.168.1.14`
  접근이 이미 되어 있으므로, `scripts/deploy-server14.sh`를 포함한 모든 n150 SSH
  작업은 WSL을 경유해서 실행한다.**
- `docs/tasks.md`의 진행 중 백로그: `T-037`~`T-038`(Hallmark audit → redesign, 위
  initiative 참고). `T-029`/`T-031` 등 이전 세션 항목은 모두 완료·머지·live 검증까지
  끝나 있다.
- 운영 호스트 `192.168.1.14`의 별칭을 "server14"/"14번"에서 "n150"으로 통일했다(PR
  [#12](https://github.com/digitie/parking-radar/pull/12)). IP·실제 파일명은 그대로다.
- n150에 `vm.swappiness=10`을 영구 적용했다(`/etc/sysctl.d/99-parking-radar-swappiness.conf`).
  4코어에 load average 30대, swap 거의 꽉 참, 컨테이너 42개(대부분 다른 프로젝트) 상태였고,
  parking-radar 자체 문제가 아니라 호스트 공유 용량 초과로 판단했다. 근본 해결(코어
  증설/다른 프로젝트와 용량 조정)은 여전히 미해결.
- `scripts/n150-backup-cron.sh`를 n150의 crontab에 등록해(3일마다 03:00 KST) PostgreSQL
  dump 자동 생성을 활성화했다. dry-run으로 실제 백업 생성 확인 완료.
- PR #3(`T-030`) 검증 중 발견한 두 버그(krairport의 KAC HTTPS 스킴 버그,
  `parse_kac_fee`의 SCREAMING_SNAKE_CASE 필드명 버그)는 모두 수정·머지 완료.
  `docs/adr/004-*.md` "후속" 참고.
- PR #4(`T-032`)로 PostgreSQL이 `docker-compose.db.yml` 별도 스택으로 분리됐고, n150
  운영 데이터도 기존 named volume을 재사용해 실제로 마이그레이션 완료했다(백업 확보 후
  무손실 전환, `parking_snapshots` 56,039건 확인).
- PR #5(ADR-005)로 `/health`를 제외한 모든 백엔드 라우트가 `/v1` prefix로 이동했다
  (무-호환 clean-cut). RFC7807 에러 포맷 통일, `scripts/export_openapi.py` →
  `docs/openapi.json` 기계 정본 추가. hostile review(Popper)에서 발견한
  `RequestValidationError` RFC7807 미적용, `scripts/verify_cutover.py`의 target(n150)
  호출 버저닝 누락도 같은 PR에서 수정했다. `{data, meta}` envelope는 명시적으로 범위
  밖(ADR-005 "후속"). n150 배포·live 검증 완료(`release_sha=03bd6f3`).
- PR #7(ADR-006)로 공휴일 수집을 `python-kasi-api`(`kasi`)로 옮겼다. hostile review
  P0/P1 없음. n150 배포·live 검증 완료(`release_sha=986d64e`,
  `GET /v1/holidays/summary` 실 KASI 데이터 확인).
- PR #9(`T-031`)로 `test_cutover_guards.py`가 Docker 컨테이너 안에서
  `ModuleNotFoundError`로 깨지던 사전 버그를 고쳤다(`sys.path` 계산이 로컬 repo-root
  깊이를 하드코딩한 것이 원인). WSL/Docker 양쪽 `82 passed`.
- PR #10(`T-029`)으로 ADR-004의 마지막 범위(비행편)를 완료했다. KAC ODCloud
  (`FlightStatusListDTL`)는 krairport에 없던 endpoint라, 형제 저장소
  `python-krairport-api`에 `KacClient.flight_status_detail_raw_items()`를 새로
  추가했다(별도 PR [python-krairport-api#7](https://github.com/digitie/python-krairport-api/pull/7),
  커밋 `cbe4d13`). IIAC는 krairport의 기존 `iiac_raw_items`가 endpoint와 정확히
  일치해 라이브러리 수정 없이 전환했다. hostile review(Popper)가 지적한 rate-limit
  backoff 비대칭(비행편은 페이지 조회마다 즉시 호출되므로 5분 주기 수집보다 위험도가
  높음)을 반영해 `KrairportRateLimitError`를 `status: "rate_limited"`로 구분하고
  `upstream_rate_limit_backoff_seconds` 동안 캐시하도록 고쳤다. n150 배포·live 검증
  완료(`release_sha=9961579`, KAC(`GMP`)/IIAC(`ICN`) 양쪽 `/v1/flights/status`가 실
  서비스 키로 `status=success` 반환).
- 운영 원본(레거시, 재배포 금지): `digitie@192.168.1.13:/home/digitie/apps/parking-radar`
  — 여전히 구 unversioned API를 서비스한다. `scripts/odroid-status.ps1`은 의도적으로
  버저닝하지 않았다.
- 운영 대상: `digitie@192.168.1.14`
- n150 공개 포트 (T-032 이후): API `14001`, web `14002`, DB `14000`(loopback 전용, 별도
  컨테이너). live E2E 기준 URL: `https://pr.digitie.mywire.org`
- n150 외부 API URL: `https://pr-api.digitie.mywire.org`
- (해결됨, PR #15/#16) 예전에는 Windows 로컬 체크아웃의 `core.autocrlf`가 배포 스크립트를
  CRLF로 깨뜨려 매 배포마다 `sed 's/\r$//'`로 우회해야 했고, git이 두 스크립트를
  100644(non-executable)로 추적해 재배포 때마다 실행 권한이 초기화되는 문제도 있었다.
  PR #15가 `.gitattributes`(`*.sh eol=lf`)를, PR #16이 파일모드(100755)를 고쳐 지금은
  `scripts/deploy-server14.sh`/`scripts/n150-backup-cron.sh` 모두 추가 우회 없이
  그대로 실행된다 — 2026-09-06 세션에서 n150 재배포 후 `stat -c '%a'`로 `775` 확인,
  `n150-backup-cron.sh` 직접 실행으로 exit `0` + 실제 dump 생성까지 재검증했다.

## 다음 한 작업

T-040의 provider 오류 수정 → 독립 리뷰 2명 → WSL/Docker 테스트 → n150 실제
수집·DB·공개 API·E2E 검증 → PR #30 머지 순서로 진행한다. 비활성/샘플 데이터는
최종 운영 승인으로 인정하지 않는다. 머지 후 KRIC provider와 교통정보 확장 조사를 진행한다.

## 확인된 사실

- 13번의 현재 서비스는 프론트 `:3000`, 백엔드 `:8000`에서 응답한다.
- 13번은 Docker를 조작하지 않고 `http://192.168.1.13:3000/api/backend` HTTP GET만 사용했다.
- 13번 수집기는 10분 주기, n150 scheduler는 configured 300초/effective 180초로 운영 중이며
  최신 strict 검증에서는 run `86`, `2026-08-22T07:21:03Z` 관측까지 성공했다.
- n150 PostgreSQL은 Alembic `0005_transport_query_indexes (head)`이고 n150은 Docker Compose로
  API `14001`, web `14002`를 제공한다. 주차 configured scheduler는 300초, effective tick은
  180초 tick과 120초 safety buffer다.
- HTTP fallback migration은 snapshots 38,946건/lot 44개 관측, reference lot 53개/legacy ID
  53개 상태로 운영되고, duplicate legacy ID는 0개다.
- 이전 T-039 검증 당시 n150 runtime은 배포 Git full SHA와 `/health`의 release SHA가 일치하며 API/web 포트 계약
  (`14001`/`14002`)을 지킨다. 2026-09-07 기준 `release_sha=e39f05b52e56d363eccf4a146c6271a4ad800cad`
  (=`main` HEAD, PR #28 squash-merge 커밋, T-039)이고, 외부 게이트웨이(`pr-api`/`pr.digitie.mywire.org`)
  양쪽에서 이 값과 정상 응답을 재확인했다(live E2E `15/15 PASS`, 새로 추가한
  `.lot-card-grid` 데스크톱-숨김 회귀 테스트 포함). 외부 게이트웨이가 응답하지 않을 때는 항상 먼저
  n150에 SSH로 직접 접속해 로컬 포트(`14001`/`14002`)를 확인해 "배포가 실패했는지" vs
  "게이트웨이만 문제인지"를 구분할 것(T-036 배포 때 실제로 겪은 패턴).

## 남은 운영 확인

- exact SQLite dump는 사용하지 않았으므로 raw response와 기존 collection run ID 보존이 필요하면
  별도 운영 export를 제공한다.
- 백업/복원은 별도 app auth가 없으므로 `pr.digitie.mywire.org` gateway/private ACL의 외부
  노출 제한을 유지한다.
- scheduler 실행 중 restore는 `409` 유지보수 창 응답으로 제한하고, n150 scheduler는
  `300/180/120` 계약으로 운영한다. 마지막 기능 release의 strict gate는 `7/7` 통과했다.
