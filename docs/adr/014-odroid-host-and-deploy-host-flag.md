# ADR-014: transport 스택을 odroid(192.168.1.13)에서 운영하고 배포 스크립트는 `--host <addr>`를 효과로 검사한다

- **상태**: accepted (2026-10-19 현재 운영 계약 수용; 최초 전환 이력 미회수 범위와 T-TRN-05는 별도)
- **날짜**: 2026-10-13
- **결정자**: agent + human (교차 저장소 Track 2 설계 "geo·weather·transport를 odroid로 옮긴다" 2026-10-13 최종본;
  소유자 지시 "설계와 각 프로젝트 문서 수정해서 코딩을 할 수 있게 준비")
- **관계**: Manager **ADR-58**(proposed — `hosts:` registry·호스트 프로필 Manager·호스트당 Dagster plane/PG·target별
  host 플립 PR)이 상위 결정이고 이 ADR은 그 transport 몫이다. geo **ADR-070**·weather(`docs/decisions.md` 인덱스)·Map
  **ADR-110**·concierge **ADR-50**이 같은 설계의 다른 몫이다. Track 1(geo 주소 데이터셋 릴리스 대응 — geo ADR-069·Map
  ADR-109·transport T-045)과의 상호작용: transport는 geo를 호출하지 않으므로(T-045, `docs/architecture/data-model.md`
  "주소·행정구역 값의 출처") 호스트 이전은 Track 1에 **무영향**이다; Track 1의 Map/concierge 센서 폴링·전량 재지오코딩은
  geo 몫(geo ADR-070 §관계)이고 transport 쪽에 할 일이 없다. 모든 file:line은 이 저장소 `eb40e3b`(origin/main, 2026-10-13) 기준 —
  단 이 PR이 함께 고치는 `docs/runbooks/deployment.md`는 줄 번호 대신 절 제목으로 인용한다. Manager 쪽 인용(ADR-58·`docs/prod-deployment.md`
  §9·`test_transport_shared_bootstrap_contract.py`)은 Manager origin/main `094d397` + Track 2 문서 PR(머지 예정) 기준이며, 그 PR 머지 뒤
  절 번호를 한 번 대조한다(T-TRN-04).

### 2026-10-19 현재 운영 정합

아래 컨텍스트·파일 줄 번호·명령은 2026-10-13 설계 시점의 기록이다. 현재 배포는
[현재 런북](../runbooks/deployment.md)과 [Manager 대조](../audits/2026-10-19-manager-contract-alignment.md)를 따른다.
Manager main `397a91ca`의 §9.2②는 workspace digest·동일 SHA 설치·targets validate 후
`dagster-plane converge --dry-run/--confirm`으로 plane을 먼저 반영한다. 아래 결정10의
옛 `ensure dagster` 명령을 현재 운영에서 실행하지 않는다. plane/workspace 선행이라는
효과 조건은 유지하며, 운영의 공용 PG를 포함한 ensure는 사용하지 않는다.

PR90에서 현재 Odroid gateway 정본·Map 실제 소비자 GET 15개·UI34를 수용했다.
admin ARM 번들 증거는 [실제 빌드 기록](../audits/2026-10-19-admin-bundle-acceptance.md)에 연결했다.
현재 양 호스트 active run0·daemon OFF·상태 불변, Odroid5역할 healthy와 정상 Transport
location, n150 Transport 컨테이너 및 location 부재를 읽기 전용으로 확인했다.
현재 배포의 host 효과 검사와 실제 n150 소비자 GET/UI 수용을 근거로 운영 결정을 accepted로
정산한다. 최초 workspace load-error→정상 순간의 원문은 미회수이며, 과거 n150 backend
exited를 현재 상태라고 주장하지 않는다. 현재 부재는 중복 실행이 없다는 조건을 충족한다.
HAProxy는 사용자 설정을 유지한 채 외부 UI/API를 검증했으며 직접 접속·변경하지 않았다.
아래 최초 전환 체크리스트는 역사적 절차로 보존한다. accepted는 모든 후속 task 완료를
뜻하지 않는다. 메모리 한도·실제 Opinet 수용은 T-TRN-05에서 별도 처리한다.

### 컨텍스트

**소유자 목표.** geo·weather·transport 세 서비스와 그들의 PostgreSQL을 odroid(`192.168.1.13`, ODROID M1S: 실측 aarch64
Cortex-A55 ×4 1.8 GHz, RAM 7,676 MiB, swap 0, eMMC 58 GB + NVMe 938 GB `/mnt/media`, Docker 29.1.3, cgroup v1)에서 돌리고,
n150(`192.168.1.14`)의 Map/PinVi/concierge와 OPNsense HAProxy는 **REST로만** 호출한다. 포트·URL·컨테이너명·compose 프로젝트명·디렉터리
규칙은 n150과 **동일**, 호스트만 `.14 → .13`. 데이터 보존·롤백은 비범위(소스에서 재적재).

**이 저장소가 지금 단일 호스트(n150)에 결박된 자리.**

| # | 결박 | 근거(head `eb40e3b`) |
|---|---|---|
| B1 | 배포 스크립트가 `REMOTE_HOST`를 `192.168.1.14`로 **하드코딩해 거부**하고(기본값도 `.14`), app dir·env 파일명(`.env.server14`)·project명도 리터럴 대조; 전송은 `git archive` + `scp` + `ssh … bash -s`. **운영 UI 배포 스크립트도 같은 결박**(기본 `.14`, `.14` 아니면 exit 2, `.env.server14`만 허용) | `scripts/deploy-server14.sh:4`, `:18-33`, `:51-56`; `scripts/deploy-transport-admin-server14.sh:6`, `:9`, `:13`, `:15` |
| B1′ | `.env.server14`·`deploy-server14` 이름이 스크립트 밖에도 박혀 있다: 원격 runtime env mktemp 접두, `.gitignore`/`.dockerignore` 예외, compose 주석, 이미지 COPY, 토큰 스크립트의 절대 경로, 계약 테스트 5개 | `scripts/deploy-server14-remote.sh:86`; `.gitignore:18`; `.dockerignore:13`; `docker-compose.shared.yml:24`; `backend/Dockerfile:25`; `scripts/set-transport-admin-write-token.py:14`, `:41`; `scripts/verify-release-stage.sh:4`; `.env.example:38`; `packages/kor-travel-transport-admin/frontend/.env.example:11`; `backend/tests/test_deploy_server14_remote_guard.py`, `test_shared_db_deploy_contract.py`, `test_shared_dagster_cutover_guards.py`, `test_dagster_runtime_dependencies.py`, `test_admin_write_token_script.py` |
| B2 | 원격 스크립트가 DSN을 `@127.0.0.1:11000/kor_travel_transport`로 `require`하고, `DAGSTER_POSTGRES_URL`도 `…/kor_travel_transport_dagster` 모양을 요구; `BACKEND_INTERNAL_URL`은 `http://127.0.0.1:14001` | `scripts/deploy-server14-remote.sh:71`, `:77-79`, `:81-84` |
| B3 | 이미지의 dagster 버전이 공용 plane(`127.0.0.1:11002`)과 같아야 배포 | `scripts/deploy-server14-remote.sh:145-150` |
| B4 | compose가 `DAGSTER_POSTGRES_URL`을 `:?` 필수 보간(legacy-dagster 전용 anchor)하고, code-server는 Manager **설치 경로**의 `dagster.yaml`을 bind | `docker-compose.shared.yml:18`, `:305`; legacy profile `:256-258`, `:333-335`, `:358-360`, `:389-393` |
| B5 | `TRUSTED_HOSTS_CSV`·`CORS_ORIGINS_CSV`에 `192.168.1.14` 리터럴(TrustedHostMiddleware·CORSMiddleware); export allow-list는 loopback뿐 | `.env.server14.example:39-40`, `:51`; `backend/app/main.py:630-632`; `backend/app/core/config.py:49`, `:109-110` |
| B6 | 운영 UI의 Dagster 링크는 코드 기본값 `https://dagster.digitie.mywire.org`(= n150 plane 공개 host); `NEXT_PUBLIC_TRANSPORT_DAGSTER_URL`을 읽지만 compose build arg로 **넘기지 않는다**(계약 테스트는 "env 우선 + 그 리터럴 폴백" 모양을 이미 단언 — 고정된 것은 폴백 상수뿐) | `packages/kor-travel-transport-admin/frontend/lib/dagster-scope.ts:118`; `docker-compose.transport-admin.yml:26-31`; `backend/tests/test_transport_admin_contract.py:124`; `.env.server14.example:104-106` |
| B7 | odroid에는 transport 전신인 SQLite `parking-radar` 스택이 3000/8000/18000에서 `pr2.digitie.mywire.org`를 받으며 살아 있고(Portainer는 9443; 런북 "포트 메모"의 "8000 = Portainer"는 과거 기록 — 실측은 8000이 uvicorn 404, 설계 fact base §A), 저장소는 "13번에서 Docker 금지"를 **fail-closed 마커 3개**(빈 compose·throw·exit 2)로 박아 두었다. 같은 legacy 자산이지만 성격이 다른 것: `deploy/odroid/bootstrap-docker.sh`는 `.14`가 아니면 거부하는 n150 전용 Docker 설치 스크립트, `scripts/odroid-status.ps1`은 비추적 `.env.odroid`의 `ODROID_HOST`로 legacy 스택을 GET하는 읽기 전용 상태 프로브(거부 분기 없음) | 마커: `docker-compose.odroid.yml:1-5`(`services: {}`), `scripts/deploy-odroid.ps1:6`(`throw`), `deploy/odroid/remote-deploy.sh:4-9`(`exit 2`) + `deploy/odroid/README.md:4` 문구; 그 밖의 legacy 자산: `deploy/odroid/bootstrap-docker.sh:4-7`, `scripts/odroid-status.ps1:25-31`; 문서: `docs/runbooks/deployment.md` "Historical: 기존 13번/ODROID 설정 (실행 금지)" 절과 그 "포트 메모"(이 PR이 앞에 절을 끼워 넣어 줄 번호 대신 절 제목으로 인용); `AGENTS.md:32`, `SKILL.md:41`, `CLAUDE.md:68` |
| B8 | 주기 백업은 저장소 cron이 아니라 Manager standalone backup(n150 digitie crontab, transport 3일마다 02:15 KST) | 저장소 cron 폐지 `docs/architecture/backup-restore.md:25-28`; 주기·시각은 Manager `scripts/run-standalone-backup.sh:12-13`(origin/main `094d397`)과 Manager `docs/prod-deployment.md` §9.6 cron 행 |
| B9 | Opinet 유가 수집은 이미지에 설치한 Playwright 1.63.0 Chromium으로 돈다. 토글은 **두 층**: `TRANSPORT_COLLECTION_ENABLED=false`는 provider 전체를 `DisabledTransportProvider`로 바꿔 **KREX 고속도로 소통·돌발까지** 끄고, `OPINET_BROWSER_ENABLED=false`는 `LiveTransportProvider`의 `opinet`만 `None`으로 둬 **유가만** 끈다(고속도로는 그대로) | `backend/Dockerfile:1`(`python:3.12-slim`), `:23`; `backend/uv.lock:1285-1286`; `backend/app/core/config.py:57`, `:62`; `backend/app/services/transport_collection.py:182-190`, `:230-243`, `:292-294`; `.env.server14.example:123`, `:128` |
| B10 | 원격 단계는 **공용 webserver(`127.0.0.1:11002`)의 workspace가 location `kor-travel-transport`를 싣고 있을 때만** 교체한다 — `location_state`가 `absent`면 "the shared Dagster plane does not list … yet"으로 **exit 2**, 옛 전용 daemon·webserver가 돌아도 exit 2. 교체 뒤에는 code-server healthy와 webserver가 location을 `RepositoryLocation`으로 **다시 싣는 것**(최대 3분)을 기다린다 — 즉 현행 배포도 "컨테이너 교체 → grpc 서버 재기동 → webserver가 그 location을 재로드"에 이미 기대고 있다 | `scripts/deploy-server14-remote.sh:187-189`(`absent`), `:222-226`(거부), `:227-232`(legacy daemon), `:191-216`(`wait_code_server_health`·`wait_location_loaded`) |
| B11 | transport compose 세 파일에는 메모리 한도가 **없다**(`mem_limit`/`memswap_limit`/`oom_score_adj`/`pids_limit` 0건) — n150(15 GiB)에서는 문제되지 않았다 | `docker-compose.yml`·`docker-compose.shared.yml`·`docker-compose.transport-admin.yml` grep 0건 |

**odroid 상태(2026-10-13 03:4xZ 실측, 설계 fact base §A2·§A3).** 완료: WSL에서 `ssh digitie@192.168.1.13` 직접 접속(키),
`/etc/sudoers.d/digitie` NOPASSWD → `sudo -n` 동작, docker 그룹 추가, `timedatectl set-ntp true`로 시계 2026 동기화(RTC 갱신).
**미완**: timesyncd 부팅 순서 사이클 영속화(보존 unit `webvnc-router-timesyncd-config.service` drop-in — 재부팅 뒤 재발 가능;
**오늘의 `synchronized: yes`는 수동 동기 결과라 영속화 완료의 증거가 아니다**), `docker compose` v2 플러그인·buildx 설치(python
`docker-compose 1.29.2`만 있음), 호스트 방화벽(전부 inactive), NVMe 디렉터리 트리·fstab bind, swapfile. **주소**: `192.168.1.13`은
DHCP 임대(`ip -4 addr` `dynamic`; NM 프로필은 보존 서비스 `webvnc-router-network.service` 소유)이고 OPNsense 예약 유무는 미확인 —
이 ADR의 `.13` 리터럴(`--host`, `.env.prod`의 TrustedHost/CORS, allow-list, HAProxy backend, Map compose 기본값 `.13:14001`)은
전부 **설계 §14-20(OPNsense DHCP 예약) 결정을 전제**한다("후속" 열린 결정 20). odroid는 Plex(32400/32469)·Samba(139/445)·webvnc-router(2121/6080)·8080·1994를 상주시키는 가정용
미디어 호스트이기도 하다 — 이들은 **공존 대상**이고 폐기 범위는 `parking-radar`·Portainer뿐이라고 **가정한다**(설계 기본값;
소유자 §14-2 미결 — "후속" 참조). 우리 포트 집합(11000~14106 TCP)과
odroid 점유 포트의 충돌은 **0**(설계 §4.6).

### 결정

1. **배포 스크립트: `deploy-server14.sh` → `deploy-prod.sh --host <addr>`(필수 인자, 기본값 없음).** host 목록 파일을
   두지 않는다(주소의 정본은 Manager registry `hosts:` 한 곳). 리터럴 대조(B1 `.14`) 대신 **효과 검사**: ① 원격의 IPv4 집합
   (`hostname -I`)이 `<addr>`을 포함 ② Manager가 설치돼 있음 ③ 원격에서 `sudo -n ktdctl targets validate --json`을 읽어
   **`targets.transport.host`가 가리키는 hosts 키 `k`**를 얻고 **`hosts.<k>.addr == <addr>`**를 대조한다(`sudo -n` 불가·`hosts`
   필드 부재·`k`가 `hosts`에 없음 → exit 2). Manager Track 2 초안(`docs/docker-management.md` "`targets validate --json` 출력")의
   `targets.<id>.host` 값은 **주소가 아니라 hosts 키**(`odroid`/`n150`/`all`; 규칙 `host = hosts[<target.host>].addr`,
   `docs/platform-topology.md` §10.1)이므로 주소와 직접 비교하지 않는다 — 그 출력에 `hosts.<키>.addr`가 함께 실려야 하며 이것을
   T-MGR-01a에 대한 **교차 저장소 계약**으로 "후속"에 올렸다(스크립트는 여전히 주소 목록을 갖지 않는다). app dir·env 파일명·
   project명 **대조는 유지하되 env 파일의 승인 값은 `.env.server14` → `.env.prod`로 바꾼다**(예시 파일 `.env.server14.example` →
   `.env.prod.example`; B1′의 mktemp 접두·ignore 예외·compose 주석·이미지 COPY·토큰 스크립트 경로·계약 테스트 5개가 같이
   따라간다 — T-TRN-01). **운영 UI 스크립트도 같은 규칙**: `deploy-transport-admin-server14.sh` → `deploy-transport-admin-prod.sh
   --host <addr>`, 같은 효과 검사 ③을 **같은 키 `targets.transport.host`로** 한다(registry에 `transport-admin` target은 없다 — 운영 UI는
   transport target의 두 번째 compose project일 뿐이고, 새 target을 만들지 않는다). **계약의 전제**: `targets.<id>.host`는 registry에
   `host:`를 생략한 target(설계 §7.2의 default)에서도 **resolve된 hosts 키**를 싣는다(빈 값·부재는 Manager 쪽 결함으로 보고 exit 2 —
   T-TRN-04 대조 항목). **실행 위치**: n150 또는 WSL(2026-10-13부터 `.13` 직접 ssh 가능). 스크립트는 오늘처럼 `ssh`/`scp`를 옵션
   변수 없이 부르므로(`deploy-server14.sh:53-55`, `deploy-transport-admin-server14.sh:20`) 접속 설정은 `~/.ssh/config`에 두고 점프
   호스트를 하드코딩하지 않는다. 긴 배포는 ssh timeout 밖(tmux/nohup)에서 돌린다.
   **원격 단계의 실행 사용자와 `.env.prod` 소유는 n150과 같다**: `ssh digitie@<addr> … bash -s`(`deploy-server14.sh:5`, `:51-56`)로
   digitie가 `source "${REMOTE_ENV_FILE}"`(`deploy-server14-remote.sh:43-44`)·`awk`(`:91`)·`docker compose --env-file`(`:121`)을
   돌리고, 운영 UI 스크립트는 digitie로 `grep`·`docker compose --env-file`(`deploy-transport-admin-server14.sh:23-51`, `:114`)을,
   토큰 스크립트는 그 파일을 교체 기록(`set-transport-admin-write-token.py:14`, `:41-48`)한다. 따라서 odroid의 `.env.prod`는
   **`digitie:digitie 0600`**이다(설계 §7.5·§11.3의 "transport `.env.prod`를 root 0600"은 이 배포 기제와 양립하지 않아 **채택하지
   않는다** — 설계 이탈, "후속" 열린 결정 A; 대안 (나) 원격 단계 전체를 `sudo -n bash -s`로 올리고 root 0600은 remote·admin·토큰
   스크립트 세 곳의 변경을 더 요구한다). 스크립트는 env 파일을 **호출 사용자가 읽을 수 없으면 exit 2**로 멈춘다(기존 `-f` 존재
   검사 `remote.sh:25`에 `-r`를 더한다 — 권한 오류가 `source`에서 터지지 않게).
2. **loopback URL은 불변, 그 URL에 붙는 자격증명은 호스트별.** `DATABASE_URL`(`@127.0.0.1:11000/kor_travel_transport`),
   `RUSTFS_ENDPOINT_URL`(`127.0.0.1:12101`), `BACKEND_INTERNAL_URL`(`http://127.0.0.1:14001` — `remote.sh:71` `require_exact`;
   예시 파일 `.env.server14.example:19`의 `http://backend:8000`은 그 검사와 어긋나는 낡은 값이라 T-TRN-02가 고친다),
   `TRANSPORT_API_INTERNAL_URL`, `TRANSPORT_DAGSTER_INTERNAL_URL`(`127.0.0.1:11002`), 그리고 compose가 만드는
   `KOR_TRAVEL_DAGSTER_SHARED_PG_URL`(`docker-compose.shared.yml:28` — `.env` 키가 아니라 compose 안 리터럴, `@127.0.0.1:11000/dagster_shared`)은
   odroid에서도 같은 문자열이다 — PG·RustFS·plane이 **odroid 로컬**에 있기 때문이다(Manager ADR-58 "호스트당 PG 하나·loopback·11000",
   "호스트당 plane"). `require_exact`/regex(B2)는 유지한다. 단 그 loopback에 붙는 **비밀 두 쌍은 odroid 것**이다:
   `KOR_TRAVEL_DAGSTER_SHARED_APP_PASSWORD`(`.env.server14.example:12` — compose 주석대로 Manager root `.env`의 같은 키와 같은 값이어야
   하고, odroid에는 별도 Manager `.env`가 새로 생긴다, Manager `prod-deployment.md` §9.1-9)와 `RUSTFS_ACCESS_KEY_ID`/
   `RUSTFS_SECRET_ACCESS_KEY`(`:62-63` — odroid RustFS 인스턴스의 키). n150 값을 그대로 복사하면 code-server가 `dagster_shared`에
   붙지 못해 healthy가 되지 않거나(B10의 `wait_code_server_health`에서 exit) KRIC XLSX 업로드가 403이다.
3. **`DAGSTER_POSTGRES_URL`: env는 남기고 DB는 만들지 않는다.** odroid PG에 `kor_travel_transport_dagster`를 만들지 않는다 —
   Manager `db-init-transport`는 그 DB를 만들지 않고(Manager origin/main `094d397` `backend/tests/test_transport_shared_bootstrap_contract.py:37-38,47`,
   `"DAGSTER" not in script` — 로컬 stale 체크아웃 `F:\dev\kor-travel-docker-manager`는 반대를 단언하므로 보지 않는다, 설계 §14-9),
   backend 코드는 그 변수를 읽지 않는다(`backend/app` grep 0건). n150의 `kor_travel_transport_dagster`는 공용 plane 합류 전 옛
   bootstrap의 산물이다(`docs/architecture/shared-db-dagster.md`). 값은 compose `:?` 보간(B4)과
   원격 스크립트 regex(B2)를 만족하는 **모양만 갖춘 문자열**이다(존재하지 않는 DB를 가리켜도 활성 서비스는 쓰지 않는다).
   legacy-dagster profile은 odroid에서도 띄우지 않는다.
4. **host-bound env 세 개는 규칙으로 파생한다.** `TRUSTED_HOSTS_CSV`·`CORS_ORIGINS_CSV`의 LAN 항목 = 배포 host addr
   (`.13`; 포트는 TrustedHostMiddleware가 떼므로 `Host: 192.168.1.13:14001`도 통과), 공개 도메인 항목은 불변.
   `SERVICE_EXPORT_ALLOWED_CLIENTS_CSV` = loopback **+ n150 `192.168.1.14/32`**(Map code-server가 LAN peer로 부른다;
   ADR-013의 peer-IP 판정은 host network라 그대로 성립하고, uvicorn 기본 `forwarded-allow-ips=127.0.0.1`이라 `.14`에서 온
   XFF는 무시돼 `request.client.host`=`.14`로 판정된다). 공개 gateway는 `/v1/transport/*` GET만 통과시키고 그 외는 404이므로
   (`deploy/transport-admin/api-gateway.conf.template:19-31`) export는 LAN peer 경로뿐이다.
5. **운영 UI Dagster 링크 = odroid plane 공개 host.** 기존 변수 `NEXT_PUBLIC_TRANSPORT_DAGSTER_URL`(B6, 이미 코드가 읽는다)을
   `docker-compose.transport-admin.yml` build arg로 넘기고 `.env`에서 준다(Next.js `NEXT_PUBLIC_`은 build 시점 값 — 바꾸면
   재build). 기존 계약 테스트(`test_transport_admin_contract.py:124`)는 이미 "env 우선 + 상수 폴백" 모양을 단언하므로 **그대로
   두고**, 새 검사는 compose 렌더의 build arg 존재와 번들 값뿐이다(T-TRN-02). 공개 host 이름(`weather-dagster.` 재사용 vs 새 이름)은
   Manager ADR-58 "열린 결정" 4(설계 §14-4) 소유자 결정. **설계가 적은 `TRANSPORT_DAGSTER_PUBLIC_ORIGIN` 부활은 쓰지 않는다**
   (아래 "근거"; 설계 이탈이므로 "후속"의 열린 결정에 올렸다).
6. **legacy 폐기·금지 문구·마커는 두 단계로 푼다.** odroid의 `parking-radar` 스택·Portainer 컨테이너·HAProxy `pr2` host를 폐기
   대상으로 **가정하고**(설계 기본값; 소유자 §14-2 미결 — Plex·Samba·webvnc-router·8080/1994·Portainer **볼륨**은 보존). 저장소
   쪽은 **(a) 문구 먼저**(T-TRN-03a, 문서만): 소유자 §14-2 결정 직후·odroid 배포(4b) **전**에 `AGENTS.md`·`SKILL.md`·`CLAUDE.md`·
   `docs/architecture/architecture.md`·`README.md`·`docs/tasks.md` "운영 제약"·런북 5개(`deployment.md`·`migration.md`·
   `troubleshooting.md`·`agent-failure-patterns.md`·`hostile-review.md`)의 "13번에서 Docker 금지" 계열 문장을 **"odroid 작업은
   `docs/runbooks/deployment.md` 계획 절·ADR-014 절차만 따른다"**로 교체한다(교체 문구에 "Docker"와 "금지"를 같은 줄에 두지 않는다 —
   수용 검사가 교체 결과에 다시 걸리지 않게; 원문 문장 목록은 T-TRN-03a) — 그렇지 않으면 4b를 수행하는 에이전트가 저장소 규칙이
   금지하는 행위를 해야 한다. **(b) 자산 뒤**(T-TRN-03b): legacy odroid 자산 집합 **M** = {`docker-compose.odroid.yml`,
   `deploy/odroid/README.md`, `deploy/odroid/remote-deploy.sh`, `deploy/odroid/bootstrap-docker.sh`, `scripts/deploy-odroid.ps1`,
   `scripts/odroid-status.ps1`}를 odroid 배포 게이트가 전부 초록인 뒤 삭제한다. M 가운데 **fail-closed 마커**는 셋(`docker-compose.odroid.yml`
   빈 services·`scripts/deploy-odroid.ps1` throw·`deploy/odroid/remote-deploy.sh` exit 2, + `deploy/odroid/README.md` 문구)이고 legacy
   스택이 살아 있는 동안 실수로 그 compose를 올리지 못하게 하는 마지막 잠금이다; `bootstrap-docker.sh`(n150 전용 설치)·
   `odroid-status.ps1`(legacy 스택 상태 조회)은 마커가 아니라 쓸모가 끝나는 자산이다(B7). T-TRN-01은 M을 **건드리지 않으므로**
   (`scripts/deploy-odroid.ps1:6`에 `deploy-server14.sh` 문자열이 남는다) 그 수용 grep은 M을 제외하고, T-TRN-03b가 M 부재와 제외 없는
   grep을 함께 단언한다.
7. **이미지: arm64, odroid 현지 빌드.** 레지스트리 없음(Manager ADR-58). base `python:3.12-slim`·`node:22-alpine`·
   `nginx:1.27-alpine`(`docker-compose.transport-admin.yml:12`)은 arm64 manifest가 있다. **미검증**: Playwright 1.63.0
   (`backend/uv.lock:1285-1286`) arm64 Chromium × `python:3.12-slim`의 Debian 릴리스 조합(`playwright install --with-deps chromium`,
   `backend/Dockerfile:23`) — 첫 빌드 뒤 headless 렌더 smoke로 확인한다. **실패 시 fallback은 `OPINET_BROWSER_ENABLED=false`**
   (B9: 유가만 꺼지고 KREX 고속도로 소통·돌발은 계속 수집). `TRANSPORT_COLLECTION_ENABLED=false`는 **쓰지 않는다** — 그 플래그는
   provider 전체를 끄므로 고속도로 수집·돌발 export·Map export 게이트가 같이 비어 전환 게이트와 양립하지 않는다(설계 §8.3의
   "`TRANSPORT_COLLECTION_ENABLED=false`로 Opinet만 비활성"은 **사실 오류**이며 이 ADR이 정정한다; 새 토글은 필요 없다 —
   `OPINET_BROWSER_ENABLED`는 head에 이미 있다).
8. **전환 순서: n150 수집 먼저 멈춤(이중 수집 금지), 공개 경로는 선전환.** 같은 KRIC/Opinet/data.go.kr 키로 두 호스트가 동시에
   수집하면 오퍼레이션별 일일 한도를 2배 소모한다. 순서는 Manager 런북 `docs/prod-deployment.md` §9.2(호스트 플립 PR 배포 절차;
   설계 최종본 §11.2의 4a/4b/5 — Manager ADR-58은 절차를 그 런북에 위임한다)를 따르되, 명령과 세부 순서는 `docs/runbooks/deployment.md`
   "odroid 배포 계획" 절이 transport 몫으로 적는다: transport 플립 PR → n150 재설치 → n150 transport code-server **stop**(수집 중지;
   `SCHEDULER_MODE=dagster` `.env.server14.example:23`이라 cs stop = 수집 0) → odroid `ensure dagster`(결정 10) → odroid
   `deploy-prod.sh --host 192.168.1.13` → fresh `migrate` → 참조 로드(KRIC 시간표 ≤500회/48 h `.env.server14.example:55-57`;
   해상 기준정보는 3일마다 03:00, run당 data.go.kr 요청 3건 — `backend/app/dagster/definitions.py:599`, `docs/architecture/shared-db-dagster.md`
   수집 일정 표; 휴게소, Opinet) → 5분 스냅샷 재개 → n150 `ensure map`(transport URL `.13:14001` 기본값) → **HAProxy
   `pr`/`pr-api`/`transport`/`transport-api` → `.13`(공개 경로 선전환 — odroid `/health` 200·첫 스냅샷 뒤)** → n150 transport
   backend·frontend **stop**(n150 체크아웃에서 `docker compose --project-name kor-travel-transport --env-file .env.server14
   -f docker-compose.yml -f docker-compose.shared.yml stop backend frontend` — 원격 스크립트의 `compose()` 모양 `remote.sh:121`;
   운영 UI project는 두지 않아도 된다 — 공개 host는 이미 `.13`) → Map export 1회 성공(n150 backend `exited` 상태) → `pr2` 제거.
   HAProxy를 Map export 게이트 **앞**에 두는 것은 Manager §9.2 ④("stop 상태에서 … 확인한 뒤")와 순서가 다르다 — transport는 `pr-api.`가
   n150 backend 14001로 가므로 stop → 게이트 → 전환이면 그 사이 공개 `pr.`/`pr-api.`가 503이고, Map은 HAProxy가 아니라 compose
   기본값 `.13:14001`로 직접 부르므로 두 게이트는 독립이다(설계 이탈로 "후속"에 올렸다; 수용 대안은 "stop → 게이트 → 전환 + 공개 outage
   창 ≤ Map export 다음 run까지"). 게이트: "같은 시각 run이 두 호스트에 0건", n150 backend **exited** 상태에서 Map export 1회 성공.
   **데이터는 fresh 재적재** — n150 `kor_travel_transport`(32 GB, highway 스냅샷 28 GB)는 전환 확인 뒤 drop하고 이력을 보존하지
   않는다(소유자 비범위).
9. **백업: odroid Manager standalone backup으로 transport 3일만(설계 기본값; 소유자 §14-7 미결).** n150 cron의
   `run-standalone-backup.sh transport`를 odroid로 옮긴다(B8). 이전 자체에 백업·복원은 없다.
10. **공용 plane 합류는 배포보다 먼저(B10 불변, 4a의 마지막 단계).** 원격 단계의 "workspace에 location이 없으면 exit 2" 가드는
    바꾸지 않는다(첫 합류를 허용하도록 "설치된 workspace 파일이 location을 선언한다"로 바꾸는 대안 (b)는 효과 검사를 파일 검사로
    낮춘다 — 메모리 `detector-bind-to-effect-not-name`). 대신 odroid에서 **플립 PR workspace로 `ensure dagster`를 4b 배포 전에**
    돌려 webserver workspace에 `kor-travel-transport`가 실리게 한다 — 그 시점 code-server는 없으므로 location은 **load error 상태**
    (`location_state`가 `absent`가 아닌 값)이고 webserver·daemon은 healthy다. 4b의 `compose up`이 code-server를 띄우면 webserver가
    그 grpc location을 다시 로드해 `wait_location_loaded`가 `RepositoryLocation`을 본다 — 현행 배포가 컨테이너 교체 뒤 같은 재로드에
    기대는 것(B10 `:191-216`)과 같은 기제다. **전제 두 가지를 T-TRN-01 첫 odroid 배포에서 실측·기록한다**: ① 4a 뒤 `location_state`
    ≠ `absent`, ② code-server healthy 뒤 3분 안에 `RepositoryLocation`(안 되면 webserver 재생성 `ensure dagster` 1회가 수동 탈출로 —
    그래도 안 되면 대안 (b)로 돌아간다). 거부 메시지가 안내하는 `DEPLOY_MODE=prepare-shared-dagster-cutover` 경로는 n150 합류
    (2026-10-02) 전용이고 fresh DB에서는 `database_at_release_head`(`remote.sh:152-159`)로 역시 exit 2라 odroid에는 쓰지 않는다.
11. **메모리 한도·swap 한도는 이 저장소 compose의 리터럴(두 호스트 동일).** 설계 §3.2 예산(transport backend 0.8g, code-server
    1.0g, frontend + admin web + gateway 합 0.3g)과 실측 반영 기록 #20(odroid cgroup v1 swap accounting on — 기본 swap 한도 2×mem_limit가
    실제로 적용된다)에 따라 `docker-compose.shared.yml`의 `backend`·`dagster-code-server`·`frontend`와 `docker-compose.transport-admin.yml`의
    `transport-admin-web`·`transport-api-gateway`에 `mem_limit`를 두고 **각 서비스 `memswap_limit == mem_limit`**(swap 0 → 한도 도달 =
    OOM = run FAILURE, 호스트 swapfile은 한도 없는 프로세스 몫)으로 둔다(B11, T-TRN-05). 0.3g의 세 서비스 분배는 설계에 없으므로 T-TRN-05가
    n150 `docker stats` 실측으로 정한다. `oom_score_adj`는 두지 않는다(설계는 PG `-800`·plane `-600`만 리터럴 — Manager compose 몫;
    cs는 기본 0이라 호스트 OOM이 run worker를 먼저 고른다는 설계 의도와 같다). n150(cgroup v2)에서는 `memory.swap.max=0`이 되어
    같은 뜻이므로 호스트별 값을 두지 않는다. Manager T-MGR-04의 transport cs registry 등록은 **측정**(cAdvisor)이지 한도가 아니다 —
    한도는 compose를 가진 이 저장소만 걸 수 있다.

### 근거

- **리터럴 결박 대신 효과 검사(결정 1).** `.14` 거부(B1)는 "n150이 아닌 곳에서 Docker를 돌리지 않는다"는 2026-05의 보호였다. 호스트가
  둘이 되면 그 리터럴은 Manager registry와 두 번째 정본이 된다(소유자 원칙: 단일 정본·Manager 범용성 — 리터럴 대신 rendered
  모델 파생·런타임 검증). `targets validate --json`은 Manager가 registry에서 계산한 host **키**와 그 키의 `addr`를 돌려주므로
  스크립트는 주소 목록을 가질 필요가 없고(키→주소 매핑도 Manager 출력에서 읽는다), "원격 IPv4 ∋ addr"은 잘못된 호스트에 올리는
  것을 효과로 막는다. host 목록 파일(`deploy/hosts.yml` 류)과 스크립트 안의 키→주소 표는 정본을 둘로 만들어 기각. 대안 (b)
  "`--host`를 키(`odroid`)로 받고 addr는 출력에서 유도"도 같은 출력을 요구하므로 인자 모양만 다르다 — 설계 §9.1·§11.2 4b가
  `--host 192.168.1.13`(주소)을 쓰므로 (a)를 택했다.
- **`.env.prod`는 digitie 소유(결정 1)**: 배포 기제(원격 `source`·`awk`·`--env-file`·토큰 스크립트의 교체 기록)가 전부 digitie로
  돌고 이 ADR의 핵심은 "B2~B4·배포 경로 불변"이다. root 0600을 택하면 세 스크립트를 `sudo -n`으로 올리는 코드 변경이 붙고 docker
  그룹 대신 root가 compose를 돌리게 돼 n150과 운영 모양이 갈린다(단순성·과결박 금지). 대가는 결과(부정)의 SMB 가시성이다.
- **loopback 불변(결정 2)**이 이 ADR의 핵심 단순화다. PG·RustFS·plane이 호스트마다 하나씩 있으면(Manager ADR-58) 이 저장소의
  compose·DSN·require 검사는 **한 글자도 안 바뀐다**. 대안 "n150 PG를 LAN으로 열어 odroid가 쓴다"는 C6c 잠금 해제·pg_hba 개방·
  gRPC 무인증 LAN 노출을 요구해 기각(설계 §6.1 (b)).
- **DB 없는 env(결정 3)**: `:?` 보간을 풀거나 regex를 지우는 코드 변경은 legacy-dagster profile(되돌리기 수단)을 함께 걷어내는
  별개 결정이다. 지금은 값만 남겨 변경 0으로 둔다 — 비용은 "존재하지 않는 DB를 가리키는 변수"라는 설명 한 줄이고,
  `docs/architecture/shared-db-dagster.md`에 적었다.
- **export allow-list에 n150만 추가(결정 4)**: ADR-013의 토큰 + peer-IP 이중 잠금은 호출자가 LAN peer가 돼도 그대로 작동한다.
  odroid 호스트 방화벽은 **계획**(미완 — 전부 inactive; T-OPS-01·Manager ADR-58 "열린 결정" 28의 (가) 우리 포트만 제한/(나)
  default-deny 중 어느 쪽이든 14001은 n150·HAProxy로 제한)이고, 적용되기 전까지는 ADR-013의 토큰 + peer-IP 이중 잠금만이 경계다.
  두 정책 모두 결론이 같으므로 인증을 더하지 않는다.
- **기존 변수 재사용(결정 5)**: 설계 §9.1은 "`TRANSPORT_DAGSTER_PUBLIC_ORIGIN` 부활"을 적었으나 head에서 코드는 이미
  `NEXT_PUBLIC_TRANSPORT_DAGSTER_URL`을 읽고(`dagster-scope.ts:118`) 옛 `TRANSPORT_DAGSTER_PUBLIC_ORIGIN`은 "더 쓰지 않는다"로
  문서화돼 있다(`.env.server14.example:104-106`). 새 이름을 되살리는 것보다 compose에 build arg 한 줄을 더하는 쪽이 작다(단순성).
  런타임 env로 바꾸는 대안은 Next.js 서버 컴포넌트 경로를 거쳐야 해 변경이 더 크다.
- **fresh 재적재(결정 8)**: 소유자 비범위(보존·롤백 없음). highway 스냅샷은 ≈0.5 GB/day로 다시 쌓이고, 참조 데이터는 쿼터 창
  안에서 1~2일에 복구된다. pg_dump 이관(32 GB)은 설계하지 않는다.
- **Opinet만 비활성(결정 7)**: Chromium은 유가 수집 한 경로에만 쓰이므로 arm64 실패가 스택 전체를 막을 이유가 없다 — 단 그
  경로를 끄는 토글은 `OPINET_BROWSER_ENABLED`다. `build_transport_provider`(`transport_collection.py:292-294`)는
  `TRANSPORT_COLLECTION_ENABLED=false`면 `DisabledTransportProvider`를 돌려 `collect_highway`도 빈 payload를 내므로(`:186-187`),
  `collect_highway_transport`·`collect_fuel_transport` op(`backend/app/dagster/definitions.py:277-288`)가 같이 빈다.
- **가드를 바꾸지 않고 순서를 바꾼다(결정 10)**: B10 가드는 "code-server만 공용 instance로 가고 옛 daemon이 schedule을 쏘는" 이중
  발화를 막는 효과 검사다. 첫 합류를 위해 그것을 파일 검사로 바꾸면 n150에서 지켜 온 보호가 약해진다(메모리
  `deduplicating-a-rule-can-weaken-it`). odroid `ensure dagster`를 한 단계 앞으로 옮기는 쪽은 코드 변경 0이고, 어차피 4a의 workspace
  digest 갱신을 plane에 반영하려면 `ensure dagster`가 필요하다(digest는 env이고 plane 재생성이 적용 수단).
- **메모리 한도는 compose 소유자가(결정 11)**: transport의 code-server·backend는 이 저장소 compose에 있고 Manager compose에 없다(외부
  project). 설계 §3.2의 7.85 GiB 최악 창 산식은 transport 행의 `mem_limit`를 전제하므로 한도가 없으면 산식 자체가 성립하지 않고,
  Chromium 피크가 호스트 OOM에서 PG 대신 아무 프로세스나 고를 수 있다. 값은 설계 리터럴을 그대로 쓰고 호스트별 분기를 두지 않는다
  (단순성; n150에서도 같은 값이 무해하다 — 실측 backend 0.55·cs 0.57 GiB).

### 결과 (긍정)

- 이 저장소의 compose·DSN·probe·plane 버전 검사·plane 합류 가드(B2~B4·B10)가 호스트 이전에서 **불변** — 바뀌는 것은 배포 스크립트의
  host 검사, `.env` 값(LAN addr·allow-list·Dagster 링크·호스트별 비밀 두 쌍), compose의 메모리 한도 줄(결정 11)뿐이다.
- odroid의 legacy SQLite 스택·`pr2`·fail-closed 마커가 사라져 "같은 서비스가 두 호스트에" 상태가 끝난다.
- n150에서 transport의 PG 32 GB·CPU 피크(backend 129 %, code-server 60 %)·메모리 ≈1.4 GiB가 빠진다(설계 §3.6).

### 결과 (부정)

- **전환 중 수집 공백**: n150 stop부터 odroid 첫 run까지 5분 스냅샷·돌발이 비고, 참조 데이터는 KRIC 쿼터(≤500/48 h) 때문에
  1~2일 걸린다. 이중 수집 금지를 택한 대가다.
- highway 28 GB 이력 포기 — 30일 통계 화면이 전환 직후 빈다.
- Map의 transport 호출이 loopback RST 대신 **LAN timeout**을 본다 — odroid 다운 시 Map 쪽 connect timeout 분리는 Map ADR-110(T-MAP-02)
  몫이고 transport는 할 일이 없다. Map의 돌발 ±30 min 시계 검사(fail-closed)는 odroid NTP 영속화(미완)가 깨지면 transport 응답을
  거부한다 — 좋은 신호이지만 전환 게이트에 시계 검사가 들어간다.
- A55 ×4에서 Opinet Chromium·KRIC XLSX 적재가 n150보다 느리다(가정 2~3배; 실측 전).
- 운영 UI Dagster 링크는 build 시점 값이라 plane host가 바뀌면 재build가 필요하다.
- `DAGSTER_POSTGRES_URL`이 "존재하지 않는 DB"를 가리키는 변수로 남는다 — 설명 없이는 오해하기 쉽다.
- odroid `.env.prod`(digitie 0600)는 Samba `[homes]`(`valid users = %S`, 쓰기 가능 — 설계 fact base §A2)로 **digitie SMB 자격을
  가진 LAN 클라이언트에게 읽힌다**(n150과 같은 노출면이지만 odroid는 Samba가 켜져 있다). 설계 §11.3의 SMB 게이트 행 "transport
  `.env.prod`가 읽히지 않음"은 이 ADR과 맞지 않으므로 Manager 쪽에서 root `.env`·bind 대상으로 축소해야 한다(열린 결정 A).
- **DHCP 임대가 바뀌면 consumer만 끊긴다**: 배포 시점의 "원격 IPv4 ∋ addr" 검사는 그때만 잡는다. 임대 변경 뒤 odroid 스택은
  멀쩡히 돌고 Map export·HAProxy·TrustedHost(`Host: 192.168.1.13`)만 조용히 실패한다 — §14-20 OPNsense 예약이 전제인 이유이고,
  Prometheus `up{host="odroid"}` 전부 0은 다운뿐 아니라 주소 이동 신호로 읽는다(Manager 런북).
- **메모리 한도가 생긴다**: n150에서 한도 없이 돌던 Opinet Chromium 피크가 cs 1.0g 한도에 닿으면 run FAILURE다(swap 없음). 설계
  예산의 "+0.3 Opinet 중"은 가정이라 첫 몇 run에서 OOM이 보이면 한도를 올리는 것이 아니라 Opinet 배치 크기를 먼저 본다(T-TRN-05 수용).

### 후속

- **선행**: Manager ADR-58 T-MGR-01a(`hosts:`·`targets validate --json`) 머지가 T-TRN-01의 전제 — **교차 저장소 계약**: 그 `--json`
  출력은 `targets.<id>.host`(hosts 키) 외에 **`hosts.<키>.addr`**(IPv4 문자열)를 실어야 한다(Manager 초안 `docs/docker-management.md`
  "`targets validate --json` 출력"에는 `host` 키만 있고 addr가 없다; 그 문장 "`targets.transport.host == <addr의 키>`"와 이 ADR
  결정 1 ③은 같은 뜻이어야 하며, **`targets.<id>.host`는 `host:`를 생략한 target에서도 resolve된 hosts 키**여야 한다 — 둘 다 T-TRN-04의
  대조 항목이다). odroid 초기화 미완 항목(NTP drop-in·compose v2/buildx·방화벽·fstab bind·swapfile)은 Manager 런북
  (`docs/prod-deployment.md` §9.1)과 T-OPS-01이 맡고, 이 저장소 런북은 그 결과를 Manager §9.5 체크리스트 행의 PASS로만 확인한다.
  **Manager 런북 §9.2 ②에 전할 것**: transport에 한해 odroid `ensure <target>` **앞에** odroid `ensure dagster`(플립 PR workspace 반영,
  location은 load error로 실림)가 와야 한다(결정 10·B10) — 지금 ②는 재설치·digest·validate 뒤 바로 `ensure <target>`이다.
- **소유자 결정이 열려 있는 것**(Manager ADR-58 "열린 결정" 절 — 번호는 설계 §14를 그대로 쓴다): 2 legacy 폐기 범위(이 ADR은
  `parking-radar`·Portainer·`pr2`만 가정), 3 Dagster (a) 호스트당 plane, 4 odroid plane 공개 host 이름(결정 5의 값), 7 백업 대상
  (transport 3일만), 12 이전 순서 transport 먼저, 13 수집 공백 수용, **20 odroid IP 고정(OPNsense DHCP 예약 추천 — 이 ADR의 `.13`
  리터럴 전부의 전제, 컨텍스트 "주소")**, 26 compose major(Ubuntu `docker-compose-v2` 2.40 vs docker.com 5.x — 배포 스크립트의
  `docker compose` 호출 모양은 같다), 28 방화벽 정책. **이 ADR이 설계에서 이탈한 것(소유자 확인)**:
  설계 §9.1·T-TRN-02의 `TRANSPORT_DAGSTER_PUBLIC_ORIGIN` 부활 대신 `NEXT_PUBLIC_TRANSPORT_DAGSTER_URL` build arg 채택(변경 최소;
  plane host 변경 = 운영 UI 재build 비용 수용) — 확인되면 Manager ADR-58/설계 §9.1의 transport admin 행을 이 변수명으로 갱신한다;
  **열린 결정 A(이 ADR 추가)** `.env.prod` 소유 = `digitie:digitie 0600`(결정 1; 설계 §7.5·§11.3의 root 0600 대신) — 승인되면
  Manager 런북 §9.5의 SMB 게이트 행에서 transport `.env.prod`를 빼고 root `.env`·bind 대상만 남긴다, 기각이면 대안 (나)로 T-TRN-01
  범위가 remote·admin·토큰 스크립트 `sudo -n` 승격까지 넓어진다; 수용 검사 기반은 설계 §13의 bats 대신 **pytest 계약 테스트**
  (저장소에 bats가 없고 CI `ci.yml:49-70`은 pytest·vitest·tsc만 돈다 — 기존 `test_deploy_server14_remote_guard.py`가 `docker`를
  PATH 스텁으로 바꿔 진짜 스크립트를 돌리는 패턴을 `ssh`/`sudo`에도 쓴다); **설계 §11.2 4b의 "배포 → migrate → odroid `ensure dagster`"
  순서를 "4a 끝에 odroid `ensure dagster` → 4b 배포"로**(결정 10 — B10 가드와 양립하는 유일한 코드 무변경 순서); **5단계에서 HAProxy
  선전환**(결정 8 — 공개 outage 0; 대안은 outage 창 수용); **메모리·swap 한도를 이 저장소 compose 리터럴로**(결정 11, T-TRN-05 — 설계
  T-MGR-03은 Manager compose만 다루고 transport compose는 이 저장소에 있어 설계 T 목록에 자리가 없었다).
- **구현 T**(`docs/tasks.md` T-046): T-TRN-01 `deploy-prod.sh`·`deploy-transport-admin-prod.sh --host` + pytest 계약 테스트(거부 분기
  다섯 각각 exit 2 — sudo 불가·env 읽기 불가 포함; 빈 workspace plane + fresh DB 호스트에서 location `absent`면 거부·load error면 통과)
  + `.env.server14.example` → `.env.prod.example` + B1′ 추종 변경 + 결정 10 전제 ①② 실측 기록; T-TRN-02 env 규칙·
  `NEXT_PUBLIC_TRANSPORT_DAGSTER_URL` build arg·compose 렌더/번들 검사·`BACKEND_INTERNAL_URL` 예시 정정; T-TRN-03a 금지 문구 교체
  (4b 전, 문서만); T-TRN-03b 자산 집합 M 삭제(게이트 뒤); T-TRN-04 arm64 Playwright smoke 기록 + Manager 문서 머지 뒤 인용 절 번호·
  `--json` 계약·§9.2 ② 순서 1회 대조 + 이 ADR accepted; **T-TRN-05** compose 메모리·swap 한도 + 계약 테스트(결정 11).
- **accepted 조건**: odroid 배포 1회 성공(`/health.release_sha` 일치, plane healthy, 같은 시각 run 두 호스트 0건), n150 backend
  `exited` 상태에서 Map export 1회 성공, HAProxy 4 host 전환, 결정 10 전제 ①② 실측 기록. 그때 상태를 accepted로 바꾸고
  `docs/runbooks/deployment.md`의 "계획" 절을 현재 절차로 승격한다.
- 이 ADR이 뒤집히면(odroid 보류) 바뀌는 것은 없다 — 코드는 아직 n150 전용이고 fail-closed 마커도 그대로다.
