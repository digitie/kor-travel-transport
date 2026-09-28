# test-strategy — 테스트 계층과 책임 경계

`docs/runbooks/testing.md`는 "무엇을 어떻게 실행하는가"를 다룬다. 이 문서는 "왜 이렇게
나누고, 각 계층이 무엇을 책임지는가"를 다룬다. 실행 명령이 필요하면 `testing.md`를 본다.

## 계층 구조

| 계층 | 도구 | DB | 대상 | 실행 위치 |
|---|---|---|---|---|
| Backend unit/API | `pytest` | 기본 SQLite(`tmp_path`), `TEST_DATABASE_URL`/`DATABASE_URL` 지정 시 PostgreSQL | 파서, 수집 서비스, 분석 로직, 요금 계산, FastAPI 라우트 | WSL2 (1차), CI (PostgreSQL 컨테이너) |
| Frontend component/API | `Vitest` | 없음(모킹) | API 클라이언트, 대시보드/차트 렌더링, 반응형 분기, 로컬 설정 저장 | WSL2 (1차), CI |
| Backend/frontend Docker | `docker compose run --rm --no-deps ...` | PostgreSQL(backend) | 1차와 같은 테스트를 실제 컨테이너 이미지 안에서 재실행 | WSL2 + Docker (2차) |
| Live E2E | `Playwright` | 실제 n150 PostgreSQL | 실제 배포된 n150를 대상으로 한 브라우저 시나리오 | WSL2 또는 Windows (원격 URL 호출이라 위치 무관), CI `live-e2e` job |

Alembic 스키마 검증(`alembic upgrade head`, `alembic check`)은 CI의 `backend` job 안에서
매 PR마다 실행되어 로컬 SQLite 기준 통과와 실제 PostgreSQL 스키마 상태를 분리해서 검증한다.

## 계층별 책임 경계

- **파싱/분석/요금 계산 로직**은 backend unit test가 책임진다. 외부 API 응답 형태 변화,
  분석 집계 공식, 요금 규칙 매칭은 여기서 검증한다.
- **API 계약**(요청/응답 스키마, 상태 코드, 캐시 헤더)은 backend API test(`TestClient` 기반)가
  책임진다.
- **UI 상호작용과 반응형**(모바일/데스크톱 분기, 토글, 툴팁, 접힘 섹션)은 frontend component
  test가 책임진다. `AGENTS.md`가 요구하는 "새 데이터 패널/상호작용 추가 시 모바일·데스크톱
  테스트 병행" 원칙이 여기 해당한다.
- **실제 배포 상태와의 drift**(배포된 SHA가 PR head와 일치하는지, 실제 캐시 헤더, 실제
  backup UI 경고 노출)는 live E2E만 검증할 수 있다. 로컬/Docker 테스트는 이 계층을 대체하지
  않는다.

## 외부 API 의존 테스트 정책

- 단위/API 테스트는 `sample` 클라이언트(고정 fixture 응답)를 기준으로 한다. 실제 외부
  data.go.kr 호출은 CI에서 발생하지 않는다.
- `live` 클라이언트 동작(`client_mode=live`, 실제 키로 호출)은 로컬에서만 임시로 검증하고
  검증 후 즉시 내린다 — 절차는 `testing.md`의 "실데이터 수집 검증"을 따른다.
- backup/restore의 실제 dump 생성은 기본 CI에서 실행하지 않는다. `EXERCISE_LIVE_BACKUP=true`를
  명시했을 때만 실제 mutation을 수행한다(공유 운영 DB 보호 목적).

## 테스트 격리

PostgreSQL을 대상으로 하는 backend 테스트는 각 실행 전 관련 테이블을
`TRUNCATE ... RESTART IDENTITY CASCADE`로 초기화한다(`backend/tests/conftest.py`). 새 테이블을
추가하면 이 TRUNCATE 목록에도 포함시킨다 — 빠뜨리면 이전 테스트가 남긴 행이 이후 테스트를
오염시킬 수 있다.

## 회귀 방지 규칙

- 새 분석/API 기능을 추가하면 최소 1개 이상의 단위 테스트와 API 테스트를 추가한다
  (`AGENTS.md`).
- 새 데이터 패널이나 UI 상호작용을 추가하면 컴포넌트 테스트를 함께 갱신한다(`AGENTS.md`).
- 스키마를 바꾸면 Alembic revision + 테스트 + `docs/architecture/data-model.md`를 함께
  갱신한다([ADR-001](adr/001-postgresql-as-primary-db.md)).
- CI green 전에는 머지하지 않는다(`backend`, `frontend`, `live-e2e` 3개 job 모두).

## 커버리지 현황

`pytest-cov`가 backend dev 의존성에 포함되어 있지만, CI는 현재 `--cov`/`--cov-fail-under`
없이 `pytest tests -q`만 실행한다 — 즉 **정량적 커버리지 임계값은 강제되지 않는다**.
`docs/tasks-rule.md` #6(추정 수치를 만들지 않는다) 원칙에 따라 이 문서에도 임의의 목표
수치는 적지 않는다. 커버리지 목표를 도입하려면 실제 측정값을 먼저 확인한 뒤 별도 task로
`docs/tasks.md`에 등록하고 이 문서를 갱신한다.

## Live E2E의 한계

`frontend/e2e/live-dashboard.spec.ts`는 실제 배포를 대상으로 하는 만큼 페이지 렌더링과 핵심
플로우 위주의 스모크 성격이 크다. 통과 수치(`N passed`)가 UI 전체 커버리지를 뜻하지는
않는다 — 세부 계산 로직의 정확성은 backend unit test가, 세부 상호작용 분기는 frontend
component test가 담당한다.
