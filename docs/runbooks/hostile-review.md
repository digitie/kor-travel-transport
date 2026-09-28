# hostile-review — 적대적 리뷰 게이트

`CLAUDE.md` §3의 4단계("적대적 리뷰 에이전트 2명의 지적을 재현하고 수정한다")를 실제로
어떻게 수행하는지 정리한다. 지금까지는 CLAUDE.md/AGENTS.md에 한 줄로만 언급돼 있고
`docs/journal.md`/`docs/tasks-done.md`(T-021)에 결과만 기록돼 있었을 뿐, 과정 자체를 다루는
문서가 없었다.

## 목적

CI(lint/type/test)가 잡지 못하는 것 — 설계상 허점, 운영 안전성 누락, 접근성/UX 결함,
스키마·계약 불일치 —을 머지 전에 사람이 아닌 독립된 리뷰 관점으로 한 번 더 걸러낸다.

## 리뷰어 구성 (T-021 기준)

James/Popper는 실제 인물이 아니라, **전문 리뷰어 페르소나를 부여한 서브에이전트 2개**를
가리키는 이름이다. 원 작업자(코드를 만든 에이전트)가 스스로 검토하지 않고, 별도 서브에이전트를
독립적으로 띄워 서로 다른 관점에서 같은 diff를 보게 한다.

| 리뷰어 | 담당 범위 |
|---|---|
| James | Frontend / live UI — 반응형 레이아웃, 접근성, 상태(loading/empty/error/focus), UX 문구 |
| Popper | Backend / PostgreSQL / ops — 스키마·마이그레이션, 데이터 정합성, 운영 안전성(스케줄러, 백업/복원, rate limit), 배포 계약 |

두 서브에이전트는 **read-only**다. 코드를 직접 고치지 않고 지적만 남긴다. 수정은 원
작업자가 한다.

## 실행 방식 — 서브에이전트로 띄운다

James/Popper 각각을 별도 Agent 호출로 독립 실행한다(예: Claude Code의 Agent tool로 각각
새 서브에이전트를 띄운다). 핵심은 **서로 다른 관점을 프롬프트로 명시**하는 것이다 — 같은
프롬프트를 두 번 돌리는 것이 아니라, 각 서브에이전트에게 다른 전문 영역·다른 우선순위·다른
"무엇을 의심할지"를 지정한다.

- **독립성**: 두 서브에이전트는 서로의 지적 결과를 보지 않은 채로 각자 전체 diff를 검토한다
  (한쪽 결과를 다른 쪽에 미리 보여주면 관점이 섞여 적대성이 사라진다). 동시에 실행해도 되고
  순차로 실행해도 되지만, 순차라도 서로 참조시키지 않는다.
- **페르소나 프롬프트에 반드시 포함할 것**:
  - 담당 관점(위 표) — James는 프론트/live UI 렌즈, Popper는 백엔드/DB/운영 렌즈로 diff를
    보게 한다. 같은 코드도 관점이 다르면 다른 결함이 보인다.
  - 태도 지시: "통과시키는 것이 아니라 결함을 찾는 것이 목적이다. 애매하면 문제로 취급하고
    지적하라." — 우호적으로 훑어보고 승인하는 리뷰가 아니라, 깨뜨릴 방법을 찾는 리뷰여야
    한다.
  - 산출 형식: 지적마다 파일:라인, 실패 시나리오(어떤 입력/상태에서 무엇이 깨지는지),
    심각도(P0/P1/P2)를 요구한다.
  - Read-only 제약: 코드를 고치지 말고 지적만 하라고 명시한다.
- **일반 리뷰가 아닌 이유**: 원 작업자가 "이 정도면 됐다"고 판단한 지점을 그대로 다시 보면
  같은 사각지대를 반복한다. 별도 서브에이전트가 처음부터 다른 렌즈로 diff를 보는 것이
  이 게이트의 핵심이다 — 사람이 직접 리뷰하는 것으로 대체할 수도 있지만, 기본은 서브에이전트
  2개다.

## 심각도

- **P0**: 데이터 손실·운영 장애·보안 노출로 이어질 수 있는 결함. 머지 전 반드시 해소한다.
- **P1**: 계약 위반, 명백한 회귀, 접근성 실패 등 머지 전 해소해야 하는 결함.
- **P2**: 개선 여지가 있지만 머지를 막지 않는 지적. 후속 task로 남길 수 있다.

## 절차

1. Draft PR이 CI green을 통과한 뒤 James/Popper 서브에이전트를 각각 독립 실행한다 — 위
   "실행 방식" 절의 페르소나 프롬프트로 새 서브에이전트를 띄우고, 서로의 결과는 나중에만
   합친다.
2. 각 서브에이전트의 지적을 P0/P1/P2로 분류해 모은다.
3. **재현**: 지적마다 실제로 그 문제가 재현되는지 먼저 확인한다(오탐 여부 판단 없이 "재현된
   실패"만 있으면 넘어가는 방식은 쓰지 않는다 — `docs/runbooks/agent-failure-patterns.md`
   A2 "실행하지 않은 검증을 통과로 보고하지 않는다"와 같은 원칙).
4. P0/P1은 전부 수정한다. P2는 수정하거나, 수정하지 않기로 했으면 그 판단 근거를
   `docs/journal.md`에 남긴다(예: ADR-003의 무인증 백업 API처럼 "위험이지만 의도된 설계"인
   경우).
5. 수정 후 CI를 다시 통과시키고, 필요하면 두 리뷰어를 재실행해 새 회귀가 없는지 확인한다
   (T-025 "Hallmark 후속 정리·리뷰 blocker 해소"가 이 패턴의 실제 사례다).
6. `docs/journal.md`/`docs/tasks-done.md`에 리뷰어 이름, 반영한 지적 요약, runtime
   candidate SHA를 남긴다.

## 이 게이트를 건너뛰면 안 되는 경우

- `main`으로의 모든 머지(`AGENTS.md`, `CLAUDE.md` §3).
- 무인증 backup/restore, 스케줄러 안전장치처럼 되돌리기 어려운 운영 결정이 걸린 변경.

## 실제 사례

- T-021: Alembic lineage, source lag verifier, proxy timeout, backup pre-restore receipt,
  접근성, stable legacy lot identity, PostgreSQL 테스트, 13번 Docker 금지 guard 등 P0/P1
  지적을 반영했다.
- T-025: Hallmark 후속 정리에서 재리뷰 blocker를 해소했다.
- ADR-003: 무인증 backup/restore API 노출이 P0/P1 지적 대상이었지만, gateway/private
  network 보호를 조건으로 유지하기로 한 판단이 남아 있다.

## 관련 문서

- [runbooks/agent-failure-patterns.md](agent-failure-patterns.md)
- [runbooks/branch-protection.md](branch-protection.md)
- [adr/003-unauthenticated-backup-network-restriction.md](../adr/003-unauthenticated-backup-network-restriction.md)
