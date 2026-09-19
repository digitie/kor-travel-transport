# CLAUDE.md — kor-travel-transport 진입 요약

이 파일은 Claude Code와 Claude Agent가 가장 먼저 읽는 요약이다. 정식 정책은
`AGENTS.md`, 상세 실행 규칙은 `SKILL.md`, 진행 상태는 `docs/resume.md`와
`docs/tasks.md`가 갖는다.

> **OpenAI Codex / Google Antigravity** 등 `AGENTS.md` 컨벤션을 따르는 AI agent는
> `AGENTS.md`를 entry로 사용한다. 이 저장소는 `CLAUDE.md` + `AGENTS.md` 두 파일만
> AI agent entry로 둔다 (Copilot/Cursor 등 IDE-side 룰 파일은 두지 않음 — drift 회피).

## 1. 이 저장소가 하는 일

이 저장소(`kor-travel-transport`)는 국내 여행 통합 교통정보 라이브러리/API와 이를
검증하는 `parking-radar` 반응형 웹앱을 담고 있다 — 저장소/패키지 식별자는
`kor-travel-transport`, 실제 배포되는 웹앱의 브랜드/화면 표시 이름은 계속
`parking-radar`다(Next.js 페이지
타이틀, 백엔드 `Settings.app_name`, 백업 파일명 접두어 등은 전부 `parking-radar`로
유지 — 사용자 눈에 보이는 것은 아무것도 바뀌지 않는다).

`kor-travel-transport`는 provider 데이터를 주기적으로 PostgreSQL에 저장하고 외부
OpenAPI와 내부 통계로 즉시 제공한다. 현재 `parking-radar`는 그중 국내 공항 주차장의
현재 잔여면과 최근 7일 흐름을 제공하는 FastAPI + Next.js 앱이다. 주차 관측
(`parking_snapshots`), 공항/주차장 기준정보,
요금 규칙, 분석 캐시는 역할을 분리한다. 공휴일·비행편은 주차 수집과 분리된 조회
데이터이며, 비행편은 하루 흐름 오버레이 차트에만 표시한다.

## 2. 운영 기준

- 백엔드: FastAPI, SQLAlchemy 2, PostgreSQL 16, Alembic
- 프론트엔드: Next.js App Router, React, TypeScript
- 실행: Docker Compose
- 타임존: 저장·API는 UTC aware timestamp, 화면 표시는 `Asia/Seoul`
- 수집: 운영 기본 5분. 외부 API rate limit과 실제 관측 시각을 함께 확인한다.
- 새 운영 호스트: `digitie@192.168.1.14` (별칭 `n150`)
- 기존 호스트: `digitie@192.168.1.13` — 데이터 확인 외 Docker 조작 금지
- GitHub 정본: `origin` → `github.com/digitie/kor-travel-transport` (이번 작업에서
  `kor-travel-airport`에서 개명, 저장소 식별자만 변경—
  배포되는 웹앱 자체의 이름은 계속 `parking-radar`다. §1 참고).
  `airport-parking-radar`는 구 개발 fork이며 새 작업의 대상이 아니다. remote가 여러 개
  보이면 `docs/runbooks/cross-repo-audit-checklist.md`를 먼저 확인한다.

## 3. 표준 작업 흐름

1. `docs/tasks.md`에서 task를 선택하고 `docs/resume.md`를 갱신한다.
2. `codex/` 브랜치에서 작고 검토 가능한 커밋을 만든다.
3. WSL 로컬 테스트 → Docker Compose 테스트 → Draft PR → CI 순서로 검증한다.
4. 적대적 리뷰 에이전트 2명의 지적을 재현하고 수정한다.
5. n150 운영 환경에서 live E2E UI와 수집/백업 smoke를 통과시킨다.
6. 모든 필수 검증 후 PR을 머지하고 `docs/journal.md`, `docs/tasks-done.md`를 갱신한다.

## 4. 먼저 읽을 문서

- 구조·의존 경계: `docs/architecture/architecture.md`
- PostgreSQL 모델·마이그레이션: `docs/architecture/data-model.md`, `docs/runbooks/migration.md`
- 성능: `docs/architecture/performance.md`
- 테스트·배포: `docs/runbooks/testing.md`, `docs/runbooks/deployment.md`, `docs/test-strategy.md`
- 개발 환경: `docs/dev-environment.md`
- 운영 안전성: `docs/runbooks/remote-command-safety.md`
- 결정 기록: `docs/adr/README.md`
- 반복 실수·GitHub 운영: `docs/runbooks/agent-failure-patterns.md`,
  `docs/runbooks/branch-protection.md`, `docs/runbooks/cross-repo-audit-checklist.md`
- 적대적 리뷰 게이트 절차: `docs/runbooks/hostile-review.md`
- 비행편 provider 라이브러리 방향: `docs/adr/004-krairport-provider-library.md`

## 5. 절대 금지 (가장 중요한 5개)

1. `main` 직접 push 금지 — feature branch + Draft PR + CI + 리뷰 후 머지한다.
2. 192.168.1.13에서 Docker stop/up/build 금지.
3. 백업 파일·SQLite·`.env`·API key를 git에 추가하지 않는다.
4. 인증 없는 백업 UI는 내부망 전제임을 문서·운영 설정에 남긴다(`docs/adr/003-*.md`).
5. `python-krairport-api` 같은 형제 provider 라이브러리 기능을 backend 안에 다시
   구현하지 않는다 — 부족하면 라이브러리 자체를 고친다(`docs/adr/004-*.md`).

전체 9개 규칙은 `SKILL.md` §4.

## 6. 작업 후 체크리스트 (1줄)

`pytest backend/tests -q` + `npm run test -- --run` + `npm run build` +
`docker compose run --rm --no-deps ...`(2차) + `docs/journal.md` + `docs/resume.md`
(+ ADR/task 이동 해당 시) + `main` 머지 전 `hostile-review.md` 게이트.
