# cross-repo-audit-checklist — 복수 GitHub remote 정합성 점검

이 저장소는 한때 서로 다른 GitHub remote 2개(`digitie/airport-parking-radar`,
`digitie/parking-radar`)가 같은 코드베이스를 가리키고 있었다(2026-08-23 확인).
`digitie/parking-radar`를 정본으로 확정했지만, 두 레포가 완전히 사라지지 않는 한 이 문제는
재발할 수 있다. 이 문서는 그때 다시 확인할 절차를 남긴다.

## 0. 정본 선언 (가장 먼저 확인)

- **정본**: `origin` → `https://github.com/digitie/kor-travel-transport.git`
  (2026-08-23 `digitie/parking-radar`로 정본 확정 → 2026-09-06 `digitie/kor-travel-airport`로
  개명 → 이후 `digitie/kor-travel-transport`로 개명(ADR-008). GitHub는 구 이름에 대한 접근을 새
  이름으로 자동 redirect하지만, 새 스크립트/문서는 새 이름을 직접 참조한다). 저장소 개명과 무관하게 배포되는 웹앱
  브랜드는 계속 `parking-radar`다 — README.md/CLAUDE.md §1 참고.
- **구 레포**: `airport-parking-radar` remote → `https://github.com/digitie/airport-parking-radar.git`.
  개발 중 사용했던 fork이며, 2026-08-23 이후 새 작업의 대상이 아니다.
- 로컬 remote 이름과 실제 정본이 일치하는지는 항상 `git remote -v`로 재확인한다. 이름만
  보고 판단하지 않는다(과거 `origin`이 구 레포를 가리켰던 적이 있다).

## 1. Stale 함정 회피 (필수)

- 각 remote는 `git fetch <remote> --prune` 후 **`<remote>/main` 기준으로만** 비교한다.
  로컬 체크아웃이나 오래된 로컬 브랜치만 보고 "이쪽이 최신"이라고 판단하지 않는다.
- 두 remote의 히스토리가 갈라져 보이면, 먼저 `git merge-base <A> <B>`로 공통 조상을 찾고
  `git diff --name-status <base> <A>` / `<base> <B>`로 각자 실제로 얼마나 나갔는지 확인한다.
  파일 개수 차이만 보고 "더 많이 바뀐 쪽이 최신"이라고 단정하지 않는다 — 실제로는
  `git diff --name-only <A> <B>`로 두 tip의 **파일 내용 자체가 동일한지**부터 확인해야 한다
  (2026-08-23 사례: `parking-radar/main`과 당시 작업 브랜치 HEAD는 파일 기준으로 완전히
  동일했다 — 한쪽이 다른 쪽을 squash merge한 결과였을 뿐, 독립적으로 갈라진 게 아니었다).
- 산출물(보고서·커밋 메시지)에는 비교에 사용한 각 remote의 기준 commit hash를 남긴다.

## 2. 코드/설정 대조

- `.github/workflows/*.yml`이 두 레포에서 서로 다른 배포 대상(호스트, URL, secret 이름)을
  가리키고 있지 않은지 대조한다.
- `docker-compose*.yml`, `.env.*.example`의 포트·호스트 값이 정본과 일치하는지 확인한다.
- 배포 스크립트(`scripts/deploy-*.sh`, `scripts/deploy-*.ps1`)가 정본이 아닌 레포/호스트를
  가리키고 있지 않은지 확인한다.

## 3. 문서 — 전제 신선도 점검

- `CLAUDE.md`/`AGENTS.md`/`README.md`에 적힌 GitHub 레포 URL이 정본과 일치하는지 grep한다.
- `docs/journal.md`, `docs/tasks-done.md`에 "이전 레포는 대상이 아니다" 같은 문장이 있으면
  그 판단이 여전히 유효한지 재확인한다(전제가 바뀌었는데 문장만 남아있는 것이 가장 흔한
  drift 패턴).
- 두 레포 중 하나에만 열린 PR/이슈가 있는지 `gh pr list --repo <owner>/<repo>`,
  `gh issue list --repo <owner>/<repo>`로 각각 확인한다.

## 4. 산출물 규칙

- 불일치를 발견하면 `docs/reports/<topic>-YYYY-MM-DD.md` 형식 보고서로 정리하고, 각 항목에
  file:line 근거와 "어느 쪽이 정본이라 그쪽 값으로 맞춰야 하는지"를 명시한다.
- 수정은 정본 레포 기준 PR로만 반영한다. 구 레포는 필요 시 README나 pinned 안내로 "archived,
  정본은 `digitie/parking-radar`"를 남기는 것으로 그친다(구 레포에 새 커밋을 만들지 않는다).

## 재발 방지

- 이 상황이 왜 생겼는지는 `docs/journal.md`와 이 세션의 remote 전환 기록을 참고한다.
  근본 원인이 남아있다면(예: CI/배포 스크립트가 아직 구 레포를 참조) 별도 task로
  `docs/tasks.md`에 등록한다.
