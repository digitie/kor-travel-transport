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
  ([ADR-002](../adr/002-dual-check-5min-cutover.md) 참고).
- **A3 (일반 원칙)**: 로컬(WSL2) green을 CI green과 동일시하지 않는다. 이 저장소의 CI는
  실제 PostgreSQL 18 컨테이너로 `alembic upgrade head` + `alembic check`까지 돌리므로,
  SQLite 기준 로컬 1차 테스트만 통과했다고 "완료"로 보고하지 않는다. 2차(WSL2+Docker)까지
  통과한 뒤에만 배포로 넘어간다(`AGENTS.md` WSL 테스트 기준).
- **A4 (실제 사례, PR #47)**: 과거 검증 이미지 태그를 재사용하면 최신 테스트/Compose 계약이
  빠진 채 검증될 수 있다. 이미지 이름만 보고 현재 후보라고 판단하지 않는다. 의존성 캐시를
  재사용하더라도 현재 후보의 backend·scripts·Compose·계약 파일을 다시 복사하고, 파일
  해시·의존성 검사·전체 테스트로 확인한다. 예전 이미지의 통과 수를 현재 후보 증적으로 쓰지 않는다.
- **A5 (실제 사례, PR134/136)**: 장시간 PG 실행의 CLI 출력 부착이 끊기면 마지막 진행 표시만 남고 최종 summary나
  wrapper 종료 파일을 잃을 수 있다. → 시작 시 정확 source/컨테이너 ID·명령·소유 label을 기록하고 stdout/최종 summary,
  wrapper exit와 독립 `docker wait`의 컨테이너 종료값을 각각 회수한다. `docker wait` 명령 자체의 exit0과 출력된
  컨테이너 exit1은 구분한다. 부착 출력이 끊겼다고 실행을 성공/실패로 단정하거나 다른 실행의 건수를 가져오지 않는다.
  PR134는 독립 컨테이너 exit0이나 최종 건수 미회수이며 출력 미회수의 원인은 확정하지 않았다. PR136은 전체 exit1과 summary를 모두 회수했다.
  원문·부분 로그·환경 분리 재검증을 보존하며 [통합 검증 원장](../reports/2026-10-26-parking-admin-integration-acceptance.md)을 따른다.

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
  ([cross-repo-audit-checklist.md](cross-repo-audit-checklist.md) 참고).
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
- **C5 (실제 사례, PR136)**: 같은 source를 WSL 절대 경로와 Docker `/repo`에서 공유하면 pytest assertion rewrite의
  기존 `.pyc`에 WSL `co_filename`이 남아 오류 위치 formatter가 basename으로 표시될 수 있다. → 두 환경의
  `PYTHONPYCACHEPREFIX`를 소유한 별도 경로로 격리한다. `PYTHONDONTWRITEBYTECODE`만으로 기존 cache 읽기가
  차단된다고 가정하지 않는다. 실패 시 소스/bytecode 해시와 실행하지 않고 파싱한 `co_filename`, 원래 traceback을 보존한다.
  assertion/rewrite·제품 formatter를 바꾸지 말고 같은 소스/의존성에서 최소 환경 차이로 집중 재검증한다.
  PR136의 원래 PG 전체1182통과/2실패/6건 건너뜀·exit1은 그대로 두고, 경로 격리 뒤 같은2개 통과를 별도로 기록했다.

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
- **D4**: Odroid 작업은 현재 배포 런북·ADR-014의 Manager 대상 승인과 NVMe 검사를 통과한다.
  사용자 승인 밖의 서비스 변경이나 daemon 재개를 수행하지 않는다(`CLAUDE.md` §2, `AGENTS.md`).
- **D5**: 무인증 backup/restore API의 네트워크 경계(`TRUSTED_HOSTS_CSV`, CORS)를 건드릴 때는
  이 결정이 [ADR-003](../adr/003-unauthenticated-backup-network-restriction.md)에
  근거한 의도된 설계임을 먼저 확인한다. "인증이 없으니 위험하다"고 판단해 임의로 인증을
  추가하기 전에 ADR을 먼저 갱신한다.


## E. 배포 사전 계약과 복원

- **E1 (실제 사례, 2026-10-26)**: Git 변경이 없는 배포 계약도 운영 파일의 CRLF와 Git archive의 LF 때문에
  바이트 비교가 실패할 수 있다. → 먼저 변경 경로와 양쪽 hash를 읽기 전용으로 확인한다. 이번 사례는
  `.py/.json/.yaml/.yml` 63개를 CRLF→LF만 변환해 대조했을 때 내용 차이 0이었다. shell·binary는 exact를
  유지하고 공백·인코딩·내용을 임의 보정하지 않는다. 운영 env 두 개는 기존 byte/권한/소유권을 그대로
  보존한다. 설치 overlay의 줄바꿈 교체는 정확히 승인된 기존/후보 hash와 동일 metadata/path로 제한한다.
  중단한 audit/input/unit을 덮어쓰지 않고 새 실행 기록을 쓴다([실행 원장](../reports/2026-10-26-parking-production-rollout.md)).
- **E2 (비운영 적대적 재현, 2026-10-26)**: 일정 원상복원이 일부만 성공한 동안 새 run이 CS 실행 artifact를
  만들 수 있다. 이후 첫 snapshot만 복원하면 이 artifact가 사라진다. → 일정 복원 시도 이후의 실패에서는
  현재 runtime/state를 보존하고 재pause를 검증한 UNKNOWN으로 남긴다. 초기 pause·재pause 자체가 미확인이면
  `paused:null`로 구분하며 전체 중지 성공으로 보고하지 않는다. 이 경계는 운영 유실 사고가 아닌 로컬
  재현·회귀로 확인했다. 원래 pause가 유지된 앞 단계의 검증된 이미지 복구와 구분한다.
- **E3 (실제 사전 관측과 비운영 회귀, 2026-10-26)**: `/health.seeded`는 `ParkingSnapshot` 존재 여부다.
  `SEED_SAMPLE_DATA=false`와 같은 뜻으로 해석해 `seeded:false`를 강제하지 않는다. 이번 운영의
  `seeded:true`는 기존 수집 자료가 있다는 뜻이며 검증을 맞추기 위해 env나 DB를 바꾸지 않는다.
- **E4 (실제 사례, 2026-10-26)**: Docker `inspect`의 `Mounts` 배열 순서는 같은 컨테이너에서도 바뀔 수
  있다. 배열을 그대로 비교한 guard가 세 이미지 빌드 뒤 교체 전 확인과 복구 확인을 모두 거부했다.
  → `Type/Source/Destination/RW` 등 계약 필드는 유지하고 결정적 키로 순서만 정규화한다. 항목을
  집합으로 바꿔 중복을 지우거나 실제 mount 차이를 무시하지 않는다. 중단 원장·실제 child 종료·builder
  원래 상태·완성 이미지 계보를 보존하고, 이미 staging된 소스를 과거 runtime의 rollback 원본으로
  잘못 기록하지 않는다. 후속 절차는 새 기록에서 검증한다.
- **E5 (실제 실패와 격리 재현, 2026-10-27)**: 새 코드 서버에는 이전 writable layer의
  `/opt/dagster/state`와 부모가 없을 수 있다. `docker cp`는 없는 부모를 생성하지 않아 정방향과
  이미지 복구가 같은 단계에서 실패했다. → G→R·해당 위치의 실행/worker 자연 종료·원본 manifest를
  확인하고, 부모를 lstat로 검사해 symlink/비정상 소유권·권한을 거절한다. 누락 디렉터리만 만들고
  새로 만든 경로에만 명시적0755를 적용한다. `mkdir(mode=0755)`만으로는 umask077에서0700이 된다
  (격리 재현이며 당시 운영 exec의 umask를 관측한 것은 아니다). 기존 target은 원본과 정확히 일치하는
  부분 상태만 허용하고 복사 뒤 전체 내용·uid/gid/mode를 확인한다. 일정 복원은 그 뒤에 한다.
- **E6 (실제 사전 중단, 2026-10-27)**: 같은 후보 SHA로 새 시도를 해도 이전 rollback 태그는 남는다.
  부재 검사를 없애거나 옛 태그를 덮지 않는다. → 실행별 고유 namespace를 보존·복구 참조 양쪽에
  일관되게 적용하고 기존 다섯 이미지 ID 보존과 새 다섯 참조 부재를 확인한다. 재사용한 제품
  release 태그·공식 셸·다른 프로젝트 이미지는 바꾸지 않는다.

## 임시 Docker 검증망과 LAN 겹침 (2026-10-23 실제 사례)

별도 project/name만 설정하고 IPAM을 생략한 Compose test망이192.168.0.0/20을 배정받아
WSL에서 Odroid192.168.1.13으로 가는 경로를 가로챘다. 실제 호스트 장애가 아니었다.
실행 중 검증은 유지하고 해당 IP의 임시 /32 route로 복구했다. 이후 새 test망은 기존
Docker/호스트 route와 겹치지 않는 명시IPAM을 검증해 사용하고, 종료 후 owned Compose
project만 down해 정리한다. 이번 임시 route는 해당 test망 종료 후 원 작업자가 제거한다.
