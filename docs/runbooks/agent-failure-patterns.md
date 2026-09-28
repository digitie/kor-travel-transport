# agent-failure-patterns — 반복되는 실수와 회피 규칙

이 문서는 에이전트가 이 저장소에서 반복하기 쉬운 실수를 "[증상] → 회피 규칙"으로 정리한다.
실제 이 저장소에서 발생한 사례는 근거(journal/tasks-done 항목)를 함께 남기고, 아직 이
저장소에서 발생하지 않았지만 같은 실행 환경(WSL2 + Windows, git + GitHub PR)에서 일반적으로
반복되는 패턴은 "일반 원칙"으로 따로 표시한다. 새 실수를 발견하면 여기에 추가한다.

## A. 검증·보고

- **A1 (일반 원칙)**: 실행하지 않았거나 취소된 검증을 "통과"로 보고하지 않는다. 검증 명령은
  한 번에 하나씩 실행하고, 실제 출력을 읽은 뒤에만 결과를 보고한다. `docs/tasks-rule.md` #6의
  "추정 수치를 만들지 않는다"와 같은 원칙이다.
- **A2 (실제 사례, T-027)**: 5분 수집 주기 그대로를 strict gate threshold로 썼더니 한 샘플이
  `319.7s`가 되어 실패했다. → 외부 스케줄/네트워크 변동을 포함하는 임계값은 이론값 그대로
  쓰지 말고 safety buffer를 두고(이 저장소는 120초), 그 여유를 ADR/런북에 근거와 함께 남긴다
  ([ADR-002](</F:/dev/kor-travel-airport/docs/adr/002-dual-check-5min-cutover.md>) 참고).
- **A3 (일반 원칙)**: 로컬(WSL2) green을 CI green과 동일시하지 않는다. 이 저장소의 CI는
  실제 PostgreSQL 16 컨테이너로 `alembic upgrade head` + `alembic check`까지 돌리므로,
  SQLite 기준 로컬 1차 테스트만 통과했다고 "완료"로 보고하지 않는다. 2차(WSL2+Docker)까지
  통과한 뒤에만 배포로 넘어간다(`AGENTS.md` WSL 테스트 기준).
- **A4 (실제 사례, PR #47)**: 과거 검증 이미지 태그를 재사용하면 최신 테스트/Compose 계약이
  빠진 채 검증될 수 있다. 이미지 이름만 보고 현재 후보라고 판단하지 않는다. 의존성 캐시를
  재사용하더라도 현재 후보의 backend·scripts·Compose·계약 파일을 다시 복사하고, 파일
  해시·의존성 검사·전체 테스트로 확인한다. 예전 이미지의 통과 수를 현재 후보 증적으로 쓰지 않는다.

## B. Git / 브랜치 / 원격

- **B1 (일반 원칙)**: `main`에 직접 커밋/push하지 않는다. 항상 `codex/<topic>` feature
  branch에서 시작해 Draft PR로 연다(`AGENTS.md`, `CLAUDE.md` §3).
- **B2 (일반 원칙)**: `git add -A`로 무관한 파일을 함께 stage하지 않는다. 커밋 전 항상
  `git status`로 diff 범위를 확인하고 관련 파일만 명시적으로 add한다.
- **B3 (일반 원칙, Windows Git)**: `rebase --continue`/`merge --continue` 계열 명령이 Vim
  편집기를 열어 비대화형 세션이 멈출 수 있다. 메시지 변경이 필요 없으면 `--no-edit`을
  붙이고, 편집기가 필요한 경우에도 `-c core.editor=true`로 우회한다.
- **B4 (실제 사례, 2026-08-23)**: 같은 코드베이스에 `origin`(`airport-parking-radar`)과
  `parking-radar`라는 서로 다른 GitHub remote 2개가 붙어 있어, 어느 쪽이 정본인지 착각할
  뻔했다. 실제로는 `digitie/parking-radar`가 Draft PR #1이 열려 있던 정본이었고,
  `airport-parking-radar`는 개발용 fork였다. → remote가 2개 이상이면 항상
  `git remote -v`와 각 remote의 최근 활동(열린 PR, 최신 커밋 날짜)을 먼저 확인하고,
  정본이 아닌 remote는 이름 자체를 구분되게 바꿔둔다
  ([cross-repo-audit-checklist.md](</F:/dev/kor-travel-airport/docs/runbooks/cross-repo-audit-checklist.md>) 참고).
- **B5 (일반 원칙)**: 두 브랜치의 히스토리가 갈라져 있을 때, 내용이 실제로 동일한지 확인하지
  않고 병합 전략(force-push, 무조건 merge)부터 정하지 않는다. `git diff <A> <B>`로 실제 파일
  내용이 같은지부터 확인한 뒤 결정한다. (오늘 `parking-radar/main`과 현재 브랜치 HEAD가
  파일 기준 완전히 동일하다는 것을 `git diff --name-only`로 먼저 확인하고 나서야 안전하게
  remote를 전환할 수 있었다.)

## C. Windows / WSL 실행 환경

- **C1 (일반 원칙)**: `command -v node`/`npm`이 `/mnt/c/...` 같은 Windows 경로를 가리키면
  WSL 셸에 Windows Node가 잘못 섞인 것이다. WSL 전용 Node(nvm 등)로 실행한다. 섞인 채로
  `npm ci`/`npm run build`를 돌리면 native optional dependency가 깨질 수 있다.
- **C2 (일반 원칙)**: 백그라운드로 띄운 서버(backend/frontend dev server)는 시작 로그만 보고
  "기동됨"으로 보고하지 않는다. 포트 리스너 존재와 실제 HTTP 200/health 응답까지 확인한다.
- **C3 (일반 원칙)**: 프로세스를 죽일 때 `pkill -f <pattern>`처럼 넓은 패턴 매칭을 쓰면 자기
  실행 중인 셸이나 무관한 프로세스까지 죽을 수 있다. 먼저 포트/PID를 특정한 뒤 그 PID만 종료한다.
- **C4 (일반 원칙, Windows↔WSL 포트 충돌)**: Windows에서 과거 떠 있던 `node.exe`가 포트를
  점유하면, WSL에서 새로 띄운 서버가 정상이어도 Windows 쪽 브라우저/curl은 이전 프로세스
  응답을 본다. `netstat -ano`(Windows)로 점유 PID를 확인해 `wslrelay`(정상)인지 실제
  `node.exe`(비정상, kill 필요)인지 구분한다.

## D. 이 저장소의 도메인 계약 (재확인 없이 바꾸면 안 되는 것)

`AGENTS.md`/`SKILL.md`의 금지 목록을 실패 시나리오 형태로 재정리한 것이다. 원본 규칙이
바뀌면 이 절도 함께 갱신한다.

- **D1**: `parking_snapshots`에 `(parking_lot_id, observed_at, source)` 중복 방지 제약을
  우회하는 방식으로 수집 로직을 바꾸면, 컷오버 gate가 요구하는 stable identity 대조가
  깨진다. 새 수집 경로를 추가할 때는 이 유니크 키를 먼저 확인한다.
- **D2**: DB 저장/도메인 로직에서 KST naive datetime을 그대로 쓰면 안 된다. 저장·API는
  UTC aware timestamp, 화면 표시만 `Asia/Seoul`로 변환한다(`CLAUDE.md` §2).
  `collected_at`처럼 운영 확인용 시각을 메인 UI에 그대로 노출하지 않는다
  (`docs/current-state.md` §5, §11).
- **D3**: 공휴일/비행편 데이터를 `parking_snapshots`에 섞어 저장하거나 최근 7일 주차
  시계열에 비행편을 함께 그리지 않는다. 비행편은 항상 별도 하루 흐름 오버레이 차트에만
  표시한다(`CLAUDE.md` §1, `AGENTS.md`).
- **D4**: 192.168.1.13에서는 Docker start/stop/build를 실행하지 않는다. 새 Docker 운영은
  192.168.1.14에서만 한다(`CLAUDE.md` §2, `AGENTS.md`).
- **D5**: 무인증 backup/restore API의 네트워크 경계(`TRUSTED_HOSTS_CSV`, CORS)를 건드릴 때는
  이 결정이 [ADR-003](</F:/dev/kor-travel-airport/docs/adr/003-unauthenticated-backup-network-restriction.md>)에
  근거한 의도된 설계임을 먼저 확인한다. "인증이 없으니 위험하다"고 판단해 임의로 인증을
  추가하기 전에 ADR을 먼저 갱신한다.
