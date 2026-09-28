# dev-environment — Windows/WSL 실행 경계

`README.md`의 "빠른 시작"과 `docs/runbooks/testing.md`가 각 명령을 다루지만, "이 명령을 어느
셸에서 실행해야 하는가"는 여러 문서에 흩어져 있었다. 이 문서는 그 경계를 한 곳에 모은다.
새 내용을 추가하는 문서가 아니라, 이미 `AGENTS.md`/`testing.md`에 흩어진 WSL2 기준 원칙을
실행 위치 표와 구체적 진단 명령으로 보강한 것이다.

## 1. 실행 위치 원칙

작업 디렉터리는 Windows NTFS(`F:\dev\kor-travel-transport`)에 있고, WSL2는 같은 경로를
`/mnt/f/dev/kor-travel-transport`로 접근한다. 기준은 `AGENTS.md`/`README.md` "WSL 테스트 기준"과
동일하다 — **테스트 합격 기준은 항상 WSL2 결과**다.

| 작업 | 기준 실행 위치 |
|---|---|
| 파일 읽기/편집 | Windows NTFS 원본 (에디터/Claude Code 등) |
| `git status`/`add`/`commit`/`push`/`fetch` | Windows Git 또는 WSL git 어느 쪽이든 가능 (원본이 NTFS라 둘 다 같은 상태를 본다) |
| `python -m pytest backend/tests -q` (1차) | WSL2 셸 |
| `npm run test -- --run`, `npm run build` (1차) | WSL2 셸 |
| `docker compose run --rm --no-deps ...` (2차) | WSL2 셸 (Docker Desktop WSL2 backend) |
| `npm run e2e:install`, `E2E_BASE_URL=https://pr.digitie.mywire.org npm run test:e2e` | WSL2 셸 기준. Chromium이 WSL2에 필요한 system lib 없이 실행되지 않으면 Windows PowerShell에서 같은 명령을 대신 실행해도 된다. **`E2E_BASE_URL`을 반드시 지정한다** — `frontend/playwright.config.ts`는 이 값이 없으면 `http://127.0.0.1:3000`으로 폴백하므로, 지정하지 않은 `npm run test:e2e`는 로컬 dev server를 요구하게 되고 §3의 포트 충돌 시나리오에 그대로 노출된다. |
| `docker compose`/배포 스크립트 실행, 원격 상태 확인 | Windows PowerShell 보조 가능 (`AGENTS.md` 기준), 다만 테스트 통과 기준으로 삼지 않는다 |
| `scripts/deploy-server14.sh` | WSL2 또는 Git Bash에서 실행 (bash 스크립트) |

## 2. WSL Node 오염 진단

`testing.md`의 "WSL Node 런타임 주의"에 이미 기록된 것처럼, WSL의 `PATH`가 Windows
`node`/`npm`을 먼저 잡으면 `WSL 1 is not supported. Could not determine Node.js install
directory` 같은 오류가 난다. 프론트엔드 1차 테스트 전에 확인한다.

```bash
command -v node
command -v npm
```

결과가 `/mnt/c/...`로 시작하면 Windows Node가 섞인 것이다 — WSL 내부에 설치된 Node(nvm 등)를
활성화한 뒤 다시 확인한다. `/usr/...` 또는 `/home/.../nvm/...`이면 정상이다.

## 3. 포트 점유 프로세스 진단 (Windows ↔ WSL2)

WSL2는 `localhostForwarding`으로 Windows에서 `localhost:3000`/`localhost:8000` 접근을
허용한다. 과거 Windows에서 직접 띄운 Node 프로세스가 같은 포트를 점유한 채 남아 있으면,
WSL2에서 새로 띄운 서버가 정상이어도 Windows 쪽 브라우저/curl은 예전 프로세스 응답을 볼 수
있다. 화면이 갱신되지 않거나 예상과 다른 응답이 보이면 먼저 포트 점유자를 구분한다.

PowerShell:

```powershell
netstat -ano | Select-String ":3000|:8000"
Get-Process -Id <PID>
```

- `ProcessName`이 `wslrelay`면 WSL2 내부 서버를 정상적으로 포워딩하는 것이다.
- `ProcessName`이 `node`/`node.exe`면 Windows에서 직접 뜬 별개 프로세스다 — 의도한 것이
  아니면 종료하고 WSL2 쪽 서버만 남긴다.

프로세스를 종료할 때는 이름 기반 패턴(`taskkill /IM node.exe /F` 같은 전체 종료)을 쓰지
않는다. 다른 프로젝트의 Node 프로세스까지 함께 죽을 수 있으므로, 위에서 확인한 PID만
지정해서 종료한다.

## 4. NTFS I/O 참고

`docs/runbooks/troubleshooting.md`의 "SQLite 관련 문제"에 기록된 대로, OneDrive/Windows
경로 bind mount에 런타임 SQLite 파일을 직접 두면 `unable to open database file` 같은 간헐
오류가 날 수 있다. 이는 WSL2의 NTFS 접근(9p 프로토콜)이 random I/O에 상대적으로 느리기
때문이다. PostgreSQL은 Docker named volume을 쓰므로 이 문제에서 자유롭지만, 새로운 파일
기반 상태(캐시, 임시 dump 등)를 추가할 때는 named volume이나 컨테이너 내부 경로를 우선
검토한다.
