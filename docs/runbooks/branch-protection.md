# branch-protection — GitHub 브랜치 보호 설정

`digitie/parking-radar`가 정본 레포로 확정된 뒤(2026-08-23, 2026-09-06 `digitie/kor-travel-airport`로
개명, 이후 `digitie/kor-travel-transport`로 개명) 확인한 결과, `main`은 아직 **branch protection이 전혀 설정되어 있지 않다**
(`gh api repos/digitie/kor-travel-airport/branches/main/protection`
→ `404 Branch not protected`). 이 문서는 실제로 설정해야 할 값과 확인 명령을 남긴다.

## 전제

- 레포 admin 권한 필요.
- 모든 변경은 `codex/*` feature branch → Draft PR → CI green → 리뷰 → merge로만 `main`에
  들어간다(`AGENTS.md`, `CLAUDE.md` §3). 긴급 수정도 예외를 두지 않는다.
- 단일 운영자(1인)라도 PR 화면에서 diff/check를 한 번 더 육안 확인한 뒤 머지한다. GitHub는
  작성자 본인의 approval을 required approval로 세지 않을 수 있으므로, 1인 운영으로
  self-merge가 필요하면 아래 "admin bypass" 항목을 켤지 여부를 명시적으로 정하고
  그 결정을 이 문서와 `docs/journal.md`에 남긴다.

## 설정 위치

GitHub → `digitie/kor-travel-transport` → Settings → Branches → Branch protection rules
(또는 신형 Rulesets) → branch name pattern = `main`

## 켜야 할 항목

| 항목 | 값 |
|---|---|
| Require a pull request before merging | enabled |
| Required approvals | 1 (1인 운영이면 admin bypass로 대체 검토) |
| Dismiss stale PR approvals on new commits | enabled |
| Require status checks to pass before merging | enabled |
| Require branches to be up to date before merging | enabled |
| Restrict deletions | enabled |
| Do not allow force pushes | enabled |
| Do not allow bypassing the above settings | 1인 운영 bypass가 필요 없을 때만 enabled |

## Required status checks

`.github/workflows/ci.yml` 기준 현재 job은 3개다. 이 이름 그대로 required로 등록한다.

```
backend
frontend
live-e2e
```

`live-e2e`는 실제 n150(`https://pr.digitie.mywire.org`)를 호출하는 job이라 대상
서버가 내려가 있으면 PR이 막힌다는 점에 주의한다. 이 job을 required로 유지할지, 또는
문서만 바꾸는 PR에도 항상 걸리는 게 맞는지는 운영 부담을 보고 재검토할 수 있다(재검토
결과는 이 문서와 필요하면 새 ADR에 남긴다).

## Merge 정책

- 기본 merge 방식: Squash and merge.
- 머지 후 feature branch 자동 삭제.
- `git push origin main`은 운영자도 사용하지 않는다. 긴급 수정도 단명 브랜치 + PR로 처리한다.

## 확인 명령

```bash
gh pr checks <PR_NUMBER> --repo digitie/kor-travel-transport
gh pr view <PR_NUMBER> --repo digitie/kor-travel-transport --json mergeStateStatus,statusCheckRollup,reviewDecision
gh api repos/digitie/kor-travel-transport/branches/main/protection
```

마지막 명령의 `required_status_checks.contexts`에 `backend`/`frontend`/`live-e2e`가 실제로
들어있는지 확인한다.

## 체크리스트

- [ ] branch protection rule 대상이 `main`인지
- [ ] PR 필수 + required approval 1 (또는 명시적 admin bypass 결정 기록)
- [ ] `backend`/`frontend`/`live-e2e` required status check 등록
- [ ] branch up-to-date 요구 설정
- [ ] force-push 차단, branch 삭제 제한
- [ ] `digitie/airport-parking-radar`(구 레포)는 더 이상 정본이 아님을 이 레포의 README나
      pinned 안내로 남길지 결정
