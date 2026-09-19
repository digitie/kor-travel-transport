# tasks.md — parking-radar 백로그

진행 중/예정(`[ ]`) task만 두는 백로그다. 완료 항목은
[`docs/tasks-done.md`](tasks-done.md)에 이동하고, 현재 진척과 다음 작업은
[`docs/resume.md`](resume.md)에 기록한다. 작성 규칙은 [`docs/tasks-rule.md`](tasks-rule.md)를
따른다. 2026-09-06에 사용자 요청으로 shadcn/ui 전환 + 과거 자료 조회 + Hallmark
재감사/재설계 initiative(T-033~T-038)가 추가됐고, 2026-09-07 `T-038`(마지막 phase)
완료로 이 initiative 전체가 끝났다. 계획 전체는
`C:\Users\digit\.claude\plans\iridescent-finding-parasol.md`에 있다.

## 진행 중인 작업 인덱스

현재 진행 중 task는 `T-040`이다. `T-033`~`T-039`(shadcn/ui 전환 + 과거 자료 조회 +
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
