# tasks.md — parking-radar 백로그

진행 중/예정(`[ ]`) task만 두는 백로그다. 완료 항목은
[`docs/tasks-done.md`](tasks-done.md)에 이동하고, 현재 진척과 다음 작업은
[`docs/resume.md`](resume.md)에 기록한다. 작성 규칙은 [`docs/tasks-rule.md`](tasks-rule.md)를
따른다. 2026-09-06에 사용자 요청으로 shadcn/ui 전환 + 과거 자료 조회 + Hallmark
재감사/재설계 initiative(T-033~T-038)가 추가됐고, 2026-09-07 `T-038`(마지막 phase)
완료로 이 initiative 전체가 끝났다. 계획 전체는
`C:\Users\digit\.claude\plans\iridescent-finding-parasol.md`에 있다.

## 진행 중인 작업 인덱스

- [ ] PR #51 최종 게이트: 추가 parking-radar live 검사에서 발견한 오피넷 데이터 노후
      (마지막 성공 2026-09-26T15:36:34Z)의 복구 범위를 사용자가 승인했다.
      Dagster 실패 전파·provider 오류 감지/진단을 검증·배포하고 9/29 07:48 KST 단일
      유가 수집 성공과 가격 갱신을 확인했다. 남은 parking-radar live 2개 실패
      (주차 조회 지연·고속도로 running 상태 유지)를 확인하고 전체 16개와 최종 CI를
      통과한 뒤 머지한다. 관리자 UI 421개 통과와 별개이며 기준을 낮추거나 검사를 제외하지 않는다.
- [ ] provider 브라우저 진단 후속(P2): 비숫자 지역은 안전한 순번으로 구분하고,
      응답 이후 DOM/파싱 및 초기 navigation 오류의 안전 진단도 별도로 보강한다.
      현재 응답 대기 구간 진단을 전체 오류 정제나 timeout 근본 해결로 해석하지 않는다.

### 후속: 유가 지역 분산 수집 (현재 모든 작업 머지 후 별도 PR)

- [ ] 시군구별 수집 간격을 30분~2시간 범위의 무작위 간격으로 변경한다.
- [ ] 시군구 순서와 하위 주소체계의 수집 순서를 각각 무작위화한다.
- [ ] 최하위 주소체계 수집 간격을 2~90초 범위에서 무작위화한다.
- [ ] `Asia/Seoul` 06:00 이상~20:00 미만에는 위 주간 간격을 적용하고, 20:00~다음 날
      06:00에는 시군구 60~180분, 최하위 주소 10~120초의 무작위 간격을 적용한다.
      사용자의 최종 수정에 따라 기존 야간 3배 규칙은 폐기한다. 순서 무작위화는
      양쪽 시간대에 유지한다. 시간대 경계·자정·재시작 회귀를 포함한다.
- [ ] 주소 단계별 실제 provider 지원 범위를 먼저 확인하고, 진행 위치·다음 허용 시각을
      영속화해 Dagster 재시작/중복 실행에 안전하도록 설계한다. 제공기관 호출 제한과
      차단·한도 오류의 유예를 우회하지 않는다. 현재 단일 검증 run에는 적용하지 않는다.

### 후속: 지도 정보·검색 컨트롤 개선 (현재 기항지/버튼 PR 완료 후)

- [ ] 유가 마커를 주유소 브랜드별 아이콘으로 표시
- [ ] 공항 마커에 주차 현황과 현재 기준 ±10분~±1시간 출도착/비행편 정보 표시
- [ ] 고속도로 노선별 돌발 현황을 지도 마커로 표시
- [ ] 교통/유가 페이지에 각각 돌발 현황/유가 지도 뷰 추가
- [ ] 지도 데이터 출처·표시 유종을 shadcn multiselect combobox로 전환하고 우측 장소 목록의 중복 선택 기능 제거
- [ ] 열차/도시철도 역·노선 검색/선택을 shadcn multiselect combobox로 전환하고 칼럼 폭 축소
- [ ] 배편 검색도 같은 combobox·좁은 칼럼 구성 적용
- [ ] 고속/시외버스 출발·도착을 shadcn combobox로 전환하고 출발지 선택 시 실제 연결된 도착지만 제공
- [ ] 나머지 select도 단일/다중 shadcn combobox로 전환

- [ ] Map 지도 페이지의 색상 외 레이아웃·상호작용을 최대한 동일하게 반영
- [ ] Weather Dagster 정보 페이지의 색상 외 구조·상호작용·페이지별 링크를 최대한 동일하게 반영

현재 진행 중 task는 `T-042`, `T-043`(운영 식별자 개명)이다. `T-033`~`T-039`(shadcn/ui 전환 + 과거 자료 조회 +
Hallmark 재감사/재설계 + UI 밀도 개선) 전체가 완료돼 `docs/tasks-done.md`로
이동했다.

### T-040 통합 교통정보 수집·OpenAPI

- [x] `python-krex-api` 고속도로 소통·돌발과 `python-opinet-api` Playwright 유가
      collector를 PostgreSQL 주기 수집에 연결
- [x] 저장 스냅샷 조회·내부 통계 OpenAPI와 Alembic migration 추가
- [ ] WSL/Docker 테스트, James/Popper 적대적 리뷰, n150 live E2E 후 PR 머지
- [ ] 현재 PR 머지 후 KRIC provider와 교통정보 확장 조사 문서 작업을 이어간다.
- [ ] 후속 P2: KREX 공통 코드 조회의 `FlowDirection` 노출, 대량 저장 데이터의 보관 기간과
      외부 목록 API 커서 페이지 정책을 정의한다. 현재 목록 조회는 최대 1,000건으로 제한한다.
      2026-09-19 운영 측정은 소통 16,740행/16,228,352바이트(인덱스 포함)다. 매 5분
      8,370개 신규 관측을 저장한다고 가정하면 소통 테이블만 약 2.18 GiB/일이다.
      실제 중복 관측은 저장하지 않으며 원본·백업 용량은 별도다. 보관 기간 결정 전
      데이터를 임의 삭제하지 않는다.
- [ ] 별도 보안 후속: `npm audit --omit=dev`가 보고한 Next.js/AVIF·sharp 취약점의 영향
      검토와 의존성 패치, WSL/Docker/live E2E 검증을 수행한다.
- [ ] 후속 P2: provider 인증/영구 파싱 오류의 장기 backoff·fail-stop 정책을 정의한다.
      현재 quota는 별도 backoff, 그 밖의 고속도로 오류는 기본 5분 주기로 재시도한다.
- [ ] 후속 P2: 통계 API의 운영 지연과 proxy timeout 여유를 측정하고 보완한다.
      9월 19일 공개 proxy에서 간헐 504 후 재조회 성공을 확인했다. 전국 데이터 증가 시
      쿼리 계획/응답량/호스트 I/O를 분리해 확인하며 단순 timeout 완화로 숨기지 않는다.
      9월 28일 이미지 적재·배포 후 첫 E2E에서 45초 timeout과 내부 집계 슬롯 포화 429가
      발생했다. 후속 2/7/10일 조회는 각각 1.85/5.10/16.65초에 성공했지만 최초 원인은
      미확정이다. 장기 집계의 유가 heap fetch·원본 경계 읽기, DB 조회 제한 시간과
      클라이언트 이탈 후 취소/슬롯 해제를 재현해 검증한다. 단순 재시도로 해결 처리하지 않는다.

### T-041 공용 DB·Dagster와 철도·여객항구 기준정보

- [ ] `kor-travel-docker-manager` 공용 PostgreSQL의 app/Dagster metadata 전용 DB·role provision
- [ ] FastAPI의 in-process scheduler를 운영에서 끄고 code-server/webserver/daemon/gateway 분리
- [ ] KRIC XLSX 철도 역사 및 여객항구 기준정보를 매 3일 Dagster job으로 저장
- [ ] 공개 파일을 공용 RustFS에 저장하는 async provider 계약을 `python-*-api`에 추가
- [ ] Map/PinVi `place`·`notice`·`price` contract REST와 항구 실시간 시간표 API 구현
- [ ] WSL/Docker, 적대적 리뷰 2명, n150 live E2E와 shared DB cutover 검증 후 PR 머지

### T-042 Transport 전용 운영 관리 UI

- [ ] PR #46 Popper P2: 내장 지도에서 검색 조건/전달 장소 목록이 바뀌면 이전 겹침 선택
      목록을 제거하거나 현재 결과로 제한한다. 전용 지도는 조회 변경 시 제거되지만 내장 지도는
      이전 실제 장소를 선택할 수 있다. 닫기/재선택이 가능해 후속으로 분리하며 회귀 테스트를 추가한다.

- [ ] PR #44 머지 후 오피넷 실제 수집 성공을 확인한다. 사용자 요청으로 배편 선실행 검증까지를
      이번 머지 범위로 정했으며, 오피넷 8시간 보호와 16:00 KST 정기 실행은 변경하지 않는다.
- [ ] 공용 PostgreSQL의 09-28 12:28~12:33 KST 내부 프로세스 종료·복구 모드 원인을 조사한다.
      자동 복구 후 API 200·항구 데이터 영속성은 확인했지만 초기 원인은 확정하지 않았다.
      다른 프로젝트/공용 DB 변경은 영향 범위와 권한을 별도로 확인한다.
- [ ] Popper 통합 리뷰 P2: 기존 `.env.example`의 `FERRY_TIMETABLE_MAX_DAYS_AHEAD=7`을
      코드/운영 예제의 9와 정렬하고 10일 조회 계약을 검증한다. origin/main에도 있던 불일치이며
      운영 설정에는 영향이 없다. PR #44의 배치 간격 변경과 분리한다.

- [ ] KRIC 48시간 보호 종료 이후 첫 실제 시간표 적재·공휴일 달력·정확 연결 범위를 확인한다.
      보호 종료는 9월 29일 15:04:58 KST이며 매시간 due 평가가 실행을 결정한다.
      API·역 비교 UI 구현과 실제 운영 데이터 적재 완료를 구분한다.
- [ ] 일반철도 운행 데이터 및 버스터미널 좌표 제공자를 연결한 뒤 동일 지도 검색 UI를 확장한다.
- [ ] 운영 호스트의 UI 빌드·이미지 적재 I/O를 분리한다. 9월 27일 n150에서 빌드 중
      CPU I/O wait 48~64%와 일시적인 Dagster 시작 timeout을 확인했다. 사전 빌드 이미지
      승격·레이어 전송 방식과 배포 시간대를 검토하며 health timeout만 늘려 숨기지 않는다.
      PR #43은 사전 빌드로 바꿨지만 9월 28일 UI 교체·첫 페이지 준비에도 수분이 걸렸다.
      직후 첫 공개 장소 목록은 29.7초, 주유소 목록은 17.4초였다. warm 반복 측정의
      p95 개선과 cold 응답·무중단 배포는 별개이며 완료 처리하지 않는다.
- [ ] 9월 27일 16시 오피넷 `Page.goto`/DOMContentLoaded 시간 초과 뒤 다음 정기 수집을
      확인한다. 마지막 성공 00:36 KST와 Dagster 작업 종료/실제 provider 실패를 구분한다.
      인증·호출 제한을 우회하거나 근거 없이 timeout만 늘리지 않는다.
- [ ] 오피넷 최신 병합 PR #19(`8708f10`, 기본 대기 60초)와 transport 고정 버전
      `39e7acc`의 차이를 반영한다. transport가 `opinet_browser_timeout_ms=30000`을
      명시 전달하므로 의존성 버전만 올려도 대기 정책은 바뀌지 않는다. 9월 28일 배치의
      화면 데이터 대기 실패와 호스트 I/O를 함께 재현·검증하고 수집 성공을 별도로 확인한다.

- [x] weather admin의 인증·server-side proxy·Dagster GraphQL 경계를 transport 전용
      Next.js 패키지로 복제
- [x] 기존 `parking-radar`와 독립된 API/Dagster/UI gateway Compose project 추가
- [x] 고속도로·유가 저장 스냅샷, 수집 상태, Dagster 상태, 허용 경로/세션/CSRF 단위·계약 테스트 추가
- [x] 교통·유가 통합 저장 통계 화면, Apache ECharts 비교 그래프, 열차·도시철도·배편 분리 화면 추가
- [x] `digitie/maplibre-vworld-react` 고정 revision을 사용하는 VWorld React 지도와 항구 시간표 명시 호출 계약 추가
- [x] bbox 기반 저장 장소 지도 요청·절단 안내, 실제 VWorld 타일·모바일 viewport live E2E 계약, vendor tarball provenance 기록
- [x] VWorld 제공 영역 밖 `200/XML FileNotFound`를 공통 provider fallback으로 분리하고,
      submodule·vendor tarball·SRI를 병합된 provider revision으로 동기화
- [ ] 후속 P2: 수집량 증가 전 fuel/rail numeric 좌표 bbox 복합 index를 `EXPLAIN (ANALYZE,
      BUFFERS)` 측정으로 설계한다. 현재 지도는 zoom별 전체 최대 900개를 요청하므로 즉시
      PostGIS migration을 강제하지 않는다.
- [ ] 후속 P2: `kind` 없는 legacy 장소 목록의 작은 `limit`에서 세 종류가 공정하게
      반환되도록 API 계약을 별도 버전으로 정리한다. 지도는 종류별 bbox 요청만 사용한다.
- [ ] 후속 P2: 지도 map event test seam으로 zoom 8·10의 종류당 200/300개 예산과, 타일
      오류 뒤 회복 시 안내 해제를 E2E로 고정한다. 현재 initial zoom 7의 종류당 100개,
      선택 중 오류 가시성, 성공 타일은 live E2E가 확인한다.
- [ ] 후속 P2: VWorld `vworld-tile-error`의 `mapId`를 transport 지도 identity와 대조하고,
      fallback 오류·정상 회복 event를 자동 검증한다. 현재 단일 map instance의 listener
      cleanup과 오류 배너 가시성은 확인됐다.
- [ ] P2: 예정 열차 마커의 301역 viewport 절단·늦은 응답 취소·숨김 탭·클러스터 왕복
      조합을 자동 검증한다. PR #43은 목록 왕복에서 지난 열차 숨김과 DB 300역 조회를
      검증하지만 모든 지도 이벤트 조합을 포괄하지 않는다.
- [ ] 후속 P2: transport deploy script의 stale middleware 보존/제거 조건을 mock으로
      검증하고, versioned release directory의 atomic switch와 remote checkout canonical path
      검증을 설계한다. 현재 build 실패는 `up --force-recreate` 전에 끝나 기존 서비스는 유지된다.
- [ ] cAdvisor `12103`, Prometheus `12102`, Grafana `12104` 전환 후 n150에서 transport
      12301/12302/12305를 배포
- [ ] 두 적대적 리뷰, CI, n150 live E2E 뒤 Draft PR을 머지

### T-043 n150 운영 식별자 개명(airport → transport, ADR-010)

- [x] 저장소 준비(`chore/rename-deploy-identity-transport`): compose `name:`·network·이미지 fallback,
      배포 스크립트 allowlist, Dagster DSN `postgresql+psycopg2://` 허용, release 태그 export,
      임시 개명 guard, 저장소 백업 cron 제거, cutover 스크립트와 가짜 docker 테스트, runbook·ADR-010
- [ ] PR #44 머지 뒤 origin/main으로 rebase, CI, 두 적대적 리뷰, 머지(창 직전)
- [ ] Manager `chore/retire-dedicated-postgres` release를 따로 설치·검증하고 Manager 개명 PR을 준비
- [ ] n150 cutover: `prepare` → `restore-point` → stage → `prebuild` → `window` → `admin` → Manager 설치
      → `finish`(runbook `deployment.md` "운영 식별자 개명 cutover")
- [ ] 72시간 관찰 뒤 정리(은퇴 컨테이너·옛 network·옛 이미지·rollback 태그·은퇴 디렉터리), 후속 PR로
      임시 guard 제거
- [ ] 후속: API 백업 `BACKUP_COMMAND_TIMEOUT_SECONDS`·`BACKUP_STORAGE_LIMIT_BYTES`를 785 MB dump(약 8분)
      DB에 맞춰 검토. Manager transport 백업 역할은 #430으로 설치됐다(16:50·17:15 UTC).
- [ ] 후속(소유자 요구, Manager 변경): 공용 PostgreSQL의 모든 DB에 prewarm — `pg_prewarm`
      preload·`pg_prewarm.autoprewarm=on`·`shared_buffers`(지금 128 MB) 크기. instance 재시작이라
      개명 창과 따로 한다(ADR-010 후속, runbook 전제).

`T-034`에서는 `<select>`/`ResponsiveSection`의 `<details>`/
daily-flight-overlay-chart의 토글·체크박스는 테스트 호환성 위험 때문에 의도적으로
native 구현을 유지했다 — `T-035`에서 라우트 구조가 바뀌었지만 이 판단은 그대로
유효하다(재검토 결과 변경 없음). `T-035`가 남긴 후속 미해결 항목(`docs/tasks-done.md`
T-035 참고): 분석 뷰의 브레이크포인트가 860px→1024px(Tailwind 기본값)로 바뀐 것은
의도적이나 별도 공지·테스트는 없음, 라우트 전환 시 analytics 데이터가 캐시되지 않아
`/analytics`↔`/history` 왕복마다 재요청됨, 백업 생성/복원 진행 중 다른 라우트로
이동하면 진행 상태가 사라짐(백엔드 `operation_lock`이 데이터 손상은 막지만 사용자
피드백은 소실). `T-036`이 남긴 후속 미해결 항목(`docs/tasks-done.md` T-036 참고):
라우트 간 analytics 데이터가 캐시되지 않는 문제가 `/history`에도 동일하게 있음(같은
근본 원인, T-035와 동일), 날짜범위 선택 팝오버가 선택 완료 후 자동으로 안 닫힘(수동
닫기만 가능). `T-038`이 남긴 후속 미해결 항목(`docs/tasks-done.md` T-038 참고):
dark-mode 차트/톤 팔레트 미토큰화, `globals.css` 전반의 desktop-first 미디어 쿼리
구조, stock shadcn 프리미티브 3곳의 `transition-all`, 980–1024px 브레이크포인트
경계 전용 회귀 테스트 없음, `/backup`이 여전히 클릭 1번으로 열림(의도적 유지 —
아래 참고). `T-039`가 남긴 후속 미해결 항목(`docs/tasks-done.md` T-039 참고):
새로고침 버튼 tap target이 320px에서 44×42px(WCAG AA 24×24는 통과, AAA
44×44에는 2px 못 미침 — 사소함), `.lot-card-grid`가 숨는 이유(64rem 미디어
쿼리)가 JSX에는 클래스명이 아니라 주석으로만 남아 있어 향후 편집 시 실수로
`lg:hidden`을 다시 붙이면 같은 버그가 재현될 수 있음.

## 완료 조건

이 백로그는 코드·문서·테스트·운영 검증이 모두 끝난 뒤 각 항목을 완료 처리한다.

- [x] PostgreSQL 컨테이너가 healthcheck를 통과하고 애플리케이션이 기동된다.
- [x] 기존 SQLite 테스트와 PostgreSQL Docker 테스트가 모두 통과한다.
- [x] 최근 주차 관측 구간과 마지막 수집 시각이 이전 시스템보다 늦지 않다.
- [x] n150에서 연속 수집이 시작되고 5분 간격의 관측 공백이 발생하지 않는다.
- [x] n150 공개 포트는 API `14000`, web `14001`이며 live E2E는
  `https://pr.digitie.mywire.org`에서 실행한다.
- [x] API 외부 주소는 `https://pr-api.digitie.mywire.org`로 smoke 검증한다.
- [x] 백업 생성·다운로드·복원 UI를 실제 브라우저에서 확인한다. 실제 운영 DB를 덮어쓰는 복원 실행은
  pre-restore backup 보호를 확인한 뒤 별도 운영 승인으로 남긴다.
- [x] 모바일 320/375/414px와 데스크톱 768px 이상에서 가로 스크롤·접근성 회귀가 없다.
- [x] 두 리뷰 에이전트의 critical/major 지적이 해소되거나 근거와 함께 기록된다.
- [x] Draft PR이 CI와 live E2E를 통과한 뒤에만 머지한다.

## 운영 제약 및 미해결 위험

- 192.168.1.13에서는 Docker를 조작하지 않는다. 원본은 `http://192.168.1.13:3000/api/backend`
  HTTP GET으로만 읽었고, 외부 원본 주소 `https://pr2.digitie.mywire.org`는 cutover 당시
  parking-radar가 아닌 Home Assistant 응답을 보여 원본 검증에 사용하지 않았다.
- HTTP fallback은 공항·주차장·관측 시계열을 보존했지만 raw response와 기존 collection run ID를
  복원하지 않는다. exact SQLite dump가 필요하면 운영자 권한으로 별도 파일을 제공해야 한다.
- 13번의 현재 수집기는 10분 주기로 동작 중이다. n150은 configured 5분 계약과 120초 safety
  buffer(실제 tick 180초)로 운영하며, 공공데이터 API rate limit과 실제 응답 시각은
  `docs/architecture/collection.md`에 기록한다.
- 백업/복원 API에는 별도 인증이 없다. 인터넷에 직접 노출하지 않고 내부망 또는 외부
  게이트웨이에서 접근을 제한해야 한다.
