# AGENTS.md

> **OpenAI Codex / Google Antigravity** 등 `AGENTS.md` 컨벤션을 따르는 AI agent는 본
> 파일을 entry로 사용한다. Claude Code는 별도 `CLAUDE.md`(1쪽 요약)가 있으나 정식
> 정책·결정은 본 파일·`SKILL.md`가 갖는다. 이 저장소는 `CLAUDE.md` + `AGENTS.md` 두 파일만
> AI agent entry로 둔다 (Copilot/Cursor 등 IDE-side 룰 파일은 두지 않음 — drift 회피).

이 문서는 `kor-travel-transport` 저장소(배포되는 웹앱 브랜드는 여전히 `parking-radar`)에서
작업하는 사람과 에이전트가 공통으로 따라야 할 기준을 정리한다. 이 저장소의 목적은 국내
여행 교통정보를 주기적으로 수집해 PostgreSQL에 저장하고, 외부 OpenAPI와 내부 통계로
제공하는 통합 라이브러리/API를 운영하는 것이다.

## 프로젝트 목표

- 국내 공항 주차장 혼잡도와 잔여 주차면을 빠르게 확인할 수 있어야 한다.
- 현재 상태뿐 아니라 최근 7일 30분 간격의 과거 흐름도 함께 볼 수 있어야 한다.
- 시간대별, 날짜별, 요일별, 공휴일별, 임계치 이벤트 관점의 분석이 가능해야 한다.
- 공휴일과 비행편 정보는 주차 수집과 분리해 조회한다. 최근 7일 주차 시계열에는 비행편을 섞지 않고, 별도의 하루 흐름 오버레이 차트에서 0~24시 시간축 위에 표시한다.
- 한국공항공사 요금 데이터 기준으로 주차요금 계산이 가능해야 한다.
- 모바일과 PC 모두에서 동일한 핵심 기능이 동작해야 한다.

## AI 작업 문서와 진입 순서

- 이 저장소의 AI 작업 문서는 `CLAUDE.md`(1쪽 진입 요약), `SKILL.md`(상세 작업
  매뉴얼), `.claude/agents/`, `.codex/agents/`, `.agents/skills/`에 둔다.
- 작업 시작 시 `CLAUDE.md` → `AGENTS.md` → `SKILL.md` → `docs/architecture/`의
  관련 문서 → `docs/resume.md` → 대상 코드 순서로 읽는다.
- 외부에서 가져온 `.claude/`, `.codex/`, `.agents/skills/` 원문은 upstream 동기화를
  위해 영어를 유지할 수 있다. 프로젝트 설명과 운영 문서는 한국어로 작성한다.
- main에 직접 push하지 않고 `codex/` feature branch와 Draft PR을 사용한다. CI,
  두 명의 적대적 리뷰, live E2E UI 검증이 끝난 뒤에만 머지한다.
- 192.168.1.13에서는 Docker를 조작하지 않는다. 새 Docker 운영은 192.168.1.14에서만
  수행한다.

## 문서 언어 정책

이 저장소의 모든 Markdown 문서는 한국어로 작성한다. 공식 API 필드명, 코드 식별자, 명령어,
URL, 라이브러리·제공자 원문, 환경변수처럼 그대로 보존해야 하는 값만 영어를 유지한다.
신규 문서와 기존 문서 모두 동일 규칙을 우선한다.

**예외**: `.claude/`, `.codex/`, `.agents/skills/` 아래의 벤더링된 상위(upstream) agent/skill
원문은 이 규칙의 예외다 — upstream 동기화 충실성을 위해 영어 원문을 유지한다. 아래 "행동
원칙"의 소제목(Think Before Coding 등)도 예외다 — 참고한 원 프로젝트와 동일한 짧은 원칙명을
유지해 검색·인용이 쉽도록 두되, 본문 설명은 한국어로 쓴다.

## 지시 우선순위

읽는 순서(위 "AI 작업 문서와 진입 순서")는 `CLAUDE.md` → `AGENTS.md` → `SKILL.md`지만,
내용이 상충할 때 실제로 무엇을 더 우선할지는 아래 순서를 따른다. `CLAUDE.md`는 1쪽 요약이라
본 파일·`SKILL.md`의 정식 정책을 압축 인용한 것이므로 별도 항목을 두지 않는다 — 셋이
상충하면 정식 정책인 `AGENTS.md`/`SKILL.md`를 정본으로 보고 `CLAUDE.md` 쪽을 고친다.

1. 사용자 요청
2. 이 `AGENTS.md`
3. `SKILL.md`
4. `docs/architecture/architecture.md`, `docs/adr/README.md`, `docs/architecture/data-model.md`,
   `docs/test-strategy.md`, `docs/runbooks/testing.md`
5. `README.md` 및 나머지 `docs/`
6. 기존 코드와 테스트
7. 최소한의, 되돌릴 수 있는 가정

## 행동 원칙

### Think Before Coding (모호함을 먼저 드러내기)

- 요청이 모호할 때는 해석을 조용히 정하지 말 것
- 중요한 가정은 숨기지 말고 드러낼 것
- 해석에 따라 구현 방향이 크게 달라지면 그 차이를 먼저 표면화할 것
- 안전하게 진행하기 어려울 정도로 혼란스러우면 추측하지 말고 확인할 것

### Simplicity First (최소 구현 우선)

- 요청을 완전히 해결하는 최소한의 코드만 작성할 것
- 요청되지 않은 기능을 추가하지 말 것
- 일회성 용도를 위해 추상화를 만들지 말 것
- 구체적인 필요 없이 설정 가능성이나 유연성을 늘리지 말 것
- 구현이 문제에 비해 커졌다고 느껴지면 줄일 것

### Surgical Changes (범위를 벗어나지 않기)

- 요청을 처리하는 데 필요한 코드만 변경할 것
- 작업이 요구하지 않으면 주변 로직까지 다시 쓰지 말 것
- 관련 없는 코드의 포맷, 이름, 스타일을 건드리지 말 것
- 사용자가 더 넓은 변경을 원한 것이 아니라면 기존 패턴을 맞출 것
- 관련 없는 문제를 발견하면 패치에 섞지 말고 따로 언급할 것

### Goal-Driven Execution (검증 가능한 결과로 바꾸기)

- 모호한 요청을 구체적이고 검증 가능한 결과로 바꿀 것
- 버그 수정은 재현 없이 바로 신뢰하지 말 것
- 리팩터링은 동작 보존을 전제로 전후 기대를 확인할 것
- 넓고 막연한 점검보다 목적이 분명한 검증을 선호할 것
- 완전한 검증이 불가능하면 무엇이 아직 미검증인지 밝힐 것

### Practical Bias (실무 균형)

- 비단순 작업에서는 성급함보다 신중함을 우선할 것
- 변경 내역은 리뷰 가능한 범위와 요청 범위에 가깝게 유지할 것
- 아주 단순하고 명백한 한 줄 작업은 과하게 무겁게 다루지 말 것

## 에이전트 공용 runbook (필독)

`docs/runbooks/` — Claude/Codex 등이 공유하는 운영 runbook. 작업 전 아래 두 개는 훑는다.

- `docs/runbooks/agent-failure-patterns.md` — 이 저장소 반복 실패 패턴(CI/로컬 괴리,
  git/브랜치, Windows/WSL 실행 환경, 도메인 계약)과 회피·복구. 게이트가 깨지면 여기부터.
- `docs/runbooks/hostile-review.md` — 머지 전 적대적 리뷰 서브에이전트 2개(James/Popper)를
  독립 실행하는 절차.

인덱스는 `docs/runbooks/README.md`. 환경 1차 문서는 `docs/dev-environment.md`.
GitHub 운영은 `docs/runbooks/branch-protection.md`, `docs/runbooks/cross-repo-audit-checklist.md`.

## Provider 라이브러리 사용 원칙

- 이 저장소와 형제 관계인 `python-krairport-api`(`krairport`, `F:\dev\python-krairport-api`)처럼
  이미 검증된 provider 라이브러리가 있으면, 같은 기능을 backend 안에 다시 구현하지 않는다.
  이 저장소(`kor-travel-transport`) 안에 provider adapter/wrapper를 새로 만들지 않는다.
  ([ADR-004](</F:/dev/kor-travel-airport/docs/adr/004-krairport-provider-library.md>))
- 형제 라이브러리는 `F:\dev\<repo>` 로컬 체크아웃을 먼저 조회한다. GitHub fetch는 로컬에
  없을 때만 fallback으로 쓴다.
- provider 응답 필드 의미·파싱 규칙 같은 데이터 정합성의 1차 책임은 해당 provider
  라이브러리에 있다. 불일치나 부족한 기능을 발견하면 이 저장소 안에 우회 코드를 추가하지
  말고, 해당 라이브러리(`F:\dev\python-krairport-api` 등)를 직접 수정해 개선한 뒤 그 결과를
  `parking-radar`(이 저장소가 배포하는 웹앱)가 소비한다.

## 기본 원칙

- FastAPI, SQLAlchemy 2, PostgreSQL, Next.js, React 기반 구조를 유지한다. SQLite는
  legacy import와 빠른 단위 테스트 호환성에만 사용한다.
- 운영 환경은 Docker Compose를 기준으로 설계한다.
- 기능 변경 시 문서와 테스트를 함께 갱신한다.
- 운영 중 발견한 예외사항, 외부 API 접근 상태, 타임존 기준, 수집 제한 규칙은 문서로 남긴다.
- 공항/주차장/스냅샷/요금 규칙의 역할을 섞지 않는다.
- 수집 원본 데이터와 분석 결과를 분리해 생각한다. 분석은 가능하면 `parking_snapshots`를 기반으로 계산한다.

## 백엔드 작업 원칙

- API 스키마는 `backend/app/schemas.py`에 명시적으로 정의한다.
- 분석 로직은 `backend/app/services/analytics.py`에 모은다.
- 수집/파싱/요금 계산 책임을 한 파일에 섞지 않는다.
- 공휴일 API 조회/파싱 책임은 `backend/app/services/holidays.py`에 둔다.
- 공휴일 정보는 `parking_snapshots`에 저장하지 않고 조회/분석 보조 데이터로 다룬다.
- 새로운 분석 기능을 추가할 때는 최소 1개 이상의 단위 테스트와 API 테스트를 추가한다.

## 프론트엔드 작업 원칙

- 대시보드는 모바일/데스크톱 모두 지원해야 한다.
- 데이터 시각화는 반응형 레이아웃에서 줄바꿈, 오버플로, 가독성을 먼저 고려한다.
- 새로운 데이터 패널을 추가하면 모바일 뷰와 데스크톱 뷰를 모두 테스트한다.
- API 호출은 `frontend/src/lib/api.ts`를 통해 일관되게 처리한다.
- 최근 7일 주차 시계열은 실제 주차 관측 구간만 보여주고, 기본 미래 축을 추가하지 않는다.
- 비행편 마커는 `하루 흐름과 비행편` 오버레이 차트에서만 표시한다.
- 공휴일 배경, 날짜별 선 토글, 비행편 마커 hover/click 같은 상호작용을 추가하면 컴포넌트 테스트를 함께 갱신한다.

## 테스트 원칙

- 백엔드 변경 시 `pytest` 테스트를 추가 또는 갱신한다.
- 프론트엔드 변경 시 `Vitest` 컴포넌트 또는 API 테스트를 추가 또는 갱신한다.
- Windows 로컬 PowerShell에서 테스트를 끝낸 것으로 판단하지 않는다.
- 1차 테스트는 `WSL2` 셸에서 백엔드/프론트엔드 로컬 테스트로 실행한다.
- 2차 테스트는 `WSL2 + Docker`에서 `docker compose run --rm --no-deps ...` 형태로 실행한다.
- 1차와 2차 테스트가 통과한 뒤 192.168.1.14에 배포한다.
- 반응형 UI 변경 시 모바일/데스크톱 렌더링 확인을 포함한다.

## 문서 반영 범위

다음 항목이 바뀌면 문서도 함께 업데이트한다.

- 사용자 기능
- API 계약
- 분석 기준
- 데이터 모델
- 테스트 방식
- 배포/실행 절차
- 운영 예외사항과 재발 방지 메모

## WSL 테스트 기준

- 이 저장소의 기본 작업/검증 기준은 `WSL2`이다.
- Windows 로컬 테스트는 지양하며, 필요할 때도 참고 결과로만 취급한다.
- 1차 테스트는 `WSL2` 셸에서 직접 실행한다.
  - 백엔드: `python -m pytest backend/tests -q`
  - 프론트엔드: `npm run test -- --run`, `npm run build`
- 2차 테스트는 `WSL2 + Docker`에서 실행한다.
  - 백엔드: `docker compose run --rm --no-deps backend pytest -q`
  - 프론트엔드: `docker compose run --rm --no-deps frontend npm run test -- --run`
- 192.168.1.14 배포는 1차/2차 테스트 이후 진행한다. 192.168.1.13에서는 Docker를
  실행하거나 중지하지 않는다.
- Windows PowerShell은 배포 스크립트 실행과 원격 상태 확인 보조 용도로 사용하고, 테스트 기준 환경으로 간주하지 않는다.
- 운영 장애 조사 중 사용자가 명시하지 않은 다른 WSL 프로젝트의 컨테이너/프로세스는 임의로 중지하거나 변경하지 않는다.

## 작업 후 체크리스트

- [ ] `python -m pytest backend/tests -q` (WSL2 1차)
- [ ] `npm run test -- --run`, `npm run build` (frontend, WSL2 1차)
- [ ] `docker compose run --rm --no-deps backend pytest -q`,
      `docker compose run --rm --no-deps frontend npm run test -- --run` (WSL2 2차)
- [ ] `docs/journal.md`에 작업 항목 추가(역시간순)
- [ ] `docs/resume.md`의 "현재 상태"/"다음 한 작업" 갱신
- [ ] 완료 task는 `docs/tasks.md` → `docs/tasks-done.md`로 이동
- [ ] 되돌림 비용이 큰 결정이면 `docs/adr/README.md`에 ADR 추가
- [ ] `main` 머지 전 [hostile-review.md](</F:/dev/kor-travel-transport/docs/runbooks/hostile-review.md>)
      게이트(James/Popper 서브에이전트) 통과
