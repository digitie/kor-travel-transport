# 배포 및 실행

> 현재 기준 배포 대상은 `192.168.1.14`이며 Docker/PostgreSQL은 n150에서만 실행한다. 13번은 source API와 rollback 기준으로 읽기만 한다. 새 배포는 [migration.md](migration.md)와 [`scripts/deploy-server14.sh`](../../scripts/deploy-server14.sh)를 우선 사용한다. 이 문서의 기존 ODROID 절차는 historical reference다.

## n150 현재 운영 절차

1. n150에 `/home/digitie/apps/kor-travel-transport/.env.server14`를 만들고
   [`.env.server14.example`](../../.env.server14.example)의 실제 DB 비밀번호와 운영
   API key를 입력한다.
2. WSL 로컬 테스트와 `docker compose config`를 통과시킨다.
3. [`scripts/deploy-server14.sh`](../../scripts/deploy-server14.sh)를 실행한다. 이
   스크립트는 대상 host가 `192.168.1.14`이고 Compose project가 `kor-travel-transport`인지 먼저
   확인한 뒤 현재 Git `HEAD`를 candidate artifact로 만들어 n150의 `docker compose`만
   호출하며 다른 Compose project를 중지하지 않는다. 배포 직후 `/health.release_sha`가
   candidate SHA와 일치하는지도 확인한다.
4. [migration.md](migration.md)의 prewarm → final delta → 180초 scheduler와 300초 이내 cutover 검증을
   완료한다.
5. release 이미지 보존: 배포마다 `kor-travel-transport-backend:rel-<sha12>` 태그가 남는다(ADR-010).
   n150에서 하나가 약 2.5 GB이고 Dockerfile의 `COPY backend`가 `pip install` 앞이라 pip·playwright 층도
   대부분 release마다 따로다. `docker image prune`은 태그가 붙은 이미지를 지우지 않는다. 배포가 health를
   통과한 뒤 지금 release와 바로 전 release(되돌릴 이미지)만 남기고 나머지 `rel-*`를 지운다. 운영 식별자
   개명 cutover의 관찰 기간에는 지우지 않는다. 배포 스크립트가 자동으로 지우지 않는 것은 다른 세션의
   되돌리기가 쓰는 태그를 지울 수 있어서다.

   ```bash
   docker inspect -f '{{.Config.Image}}' kor-travel-transport-backend-1        # 지금 release
   docker image ls kor-travel-transport-backend --format '{{.CreatedAt}}  {{.Tag}}' | sort -r
   docker image rm kor-travel-transport-backend:rel-<지울 sha12>   # 지금·바로 전 밖만. -f는 쓰지 않는다
   ```

공용 DB 최초 cutover는 일반 배포와 다르다. 먼저 WSL checkout에서
`DEPLOY_STAGE_ONLY=true ./scripts/deploy-server14.sh`로 reviewed artifact만 n150에 올린 뒤,
n150에서 `scripts/cutover-shared-db-server14.sh`를 실행한다. cutover는 staged artifact의
receipt-gated remote deploy를 호출하므로 n150에 `.git`이 없어도 된다. `.env.server14.legacy`는
동기화 삭제 대상이 아니며 live E2E 수용 전까지 보존한다.

> **롤백 시 주의(T-035 이후)**: frontend만 이전 이미지로 되돌리고 PostgreSQL 상태는
> 그대로 유지하는 롤백을 하면, T-035 이후 추가된 `/analytics`·`/history`·`/fees`·`/backup`
> 라우트는 롤백된(라우트 분리 이전) 빌드에서 404가 된다. 그 사이 공유되거나 북마크된 딥링크는
> 롤백 창에서 깨질 수 있다는 것을 감안하고, 필요하면 롤백 공지에 "/"로 이동하라고 안내한다.

```bash
REMOTE_HOST=192.168.1.14 \
REMOTE_APP_DIR=/home/digitie/apps/kor-travel-transport \
./scripts/deploy-server14.sh
```

### Dagster healthcheck·init만 바뀐 반영

> 2026-09 운영 식별자 개명 cutover([ADR-010](../adr/010-deploy-identity-rename-transport.md))가 #45의
> healthcheck·`init` 반영을 전체 release로 대신했다(여섯 서비스가 모두 R로 다시 만들어진다). 아래
> 절차는 그 뒤 healthcheck·`init`만 바뀐 반영에 쓴다. 2026-09-28 기준 이미지·태그 설명은 그 시점
> 기록이다.

`docker-compose.shared.yml`에서 Dagster 세 서비스의 healthcheck·`init`만 바뀌면 전체 배포를 쓰지
않는다. 전체 배포는 `up -d --build`로 backend·frontend·gateway 이미지를 n150에서 다시 빌드한다.
`rsync --delete`는 archive에 없는 `.transport-admin-release-sha`와 `.env.server14.before-*` 백업도
지운다. 대신 [`scripts/redeploy-dagster-services-server14.sh`](../../scripts/redeploy-dagster-services-server14.sh)로
Dagster 세 서비스만 재생성한다. 이 경로는 `deploy-server14-remote.sh`의 receipt·env gate를 거치지
않고 `.release-sha`도 갱신하지 않는다. 다음 전체 배포 전까지 배포 디렉터리는 `.release-sha`와
일치하지 않는다.

시작 전에 같은 디렉터리에 배포하는 다른 작업과 시간을 맞춘다. PR 배포 세션은 `.env.server14`를
고치고 트리 전체를 이 디렉터리에 rsync한다(2026-09-28 11:29 KST PR #44 세션은
`local/transport-pr44:paced`/`9067afc613eb` worker를 반영했다). 스크립트는 run 대기 뒤 교체 직전에 gate와 컨테이너
ID·daemon 정지를 다시 봐서 그 사이의 변경을 잡는다. 다만 그 직후 몇 초 사이의 변경은 막지 못한다.
SSH가 끊기면 스크립트도 끝나므로(daemon은 되살린다) tmux 안에서 실행한다.

```bash
# WSL: 작업 트리가 아니라 머지 커밋의 내용을 올린다.
m=<머지 커밋 SHA>
git show "$m:docker-compose.shared.yml" > /tmp/docker-compose.shared.yml.new
git show "$m:scripts/redeploy-dagster-services-server14.sh" > /tmp/redeploy-dagster-services-server14.sh
scp /tmp/docker-compose.shared.yml.new /tmp/redeploy-dagster-services-server14.sh \
  digitie@192.168.1.14:/tmp/

# n150
bash /tmp/redeploy-dagster-services-server14.sh /tmp/docker-compose.shared.yml.new
```

스크립트는 다음 순서로 진행하고, 하나라도 어긋나면 STOP을 출력하고 exit 1로 끝난다.

1. 이미지를 지금 code-server 이미지 ID로 고정한다(`BACKEND_RUNTIME_IMAGE` export). 셸 env가
   `--env-file`보다 우선한다. 고정하지 않으면 `.env.server14`의 값으로 재생성된다. 2026-09-27
   21:13Z에는 당시 미머지였던 PR #43 배포가 이 값을 `ab25bf7b`로 바꿔 두었다(#43은 2026-09-28
   `8a34f77`로 머지). 2026-09-28 11:29 KST 이후 env와 code-server는 `9067afc613eb`이나,
   실행 중 API는 `3b77ac7d588e`, webserver·daemon은 `c8b47811`로 분리돼 있다.
   `compose config -q`는 실행 중 이미지와 env의 차이를 잡지 못한다.
2. 지금 파일과 새 파일을 지금 env·고정 이미지로 렌더링해(`compose config --format json`) 비교한다.
   세 Dagster 서비스의 `healthcheck`·`init` 밖에서 다르면 STOP이다. 다른 PR이 main에서 이 파일을
   바꿨어도 여기서 멈춘다. 차이는 경로만 출력한다(값에는 비밀이 있다). 배포된 파일은 Windows
   `git archive`가 만든 CRLF라 줄 단위 `diff`로는 비교할 수 없다.
3. drift gate: 세 컨테이너 각각의 config-hash label을 지금 파일에서 다시 계산한 hash와 비교한다.
   계산에는 그 컨테이너가 만들어질 때의 이미지 문자열과 `DAGSTER_POSTGRES_URL`을 넣는다. DSN은
   `.env.server14`와 scheme만 달라도 된다. 이 두 가지 밖의 drift면 STOP이다.
4. Dagster GraphQL(`DAGSTER_GRAPHQL_URL`, 기본 `http://127.0.0.1:14004/graphql`)에서 in-flight run을
   한 번 읽는다. 읽지 못하면 daemon을 멈추기 전에 STOP이다. 그대로 멈추면 7의 대기가 상한까지
   daemon을 멈춘 채 헛돈다.
5. 고정 이미지에 `kor-travel-transport-backend:dagster-pin-<ID 앞 12자리>` 태그를 붙인다.
6. daemon을 `docker stop`으로 멈춘다(schedule·queue dequeue는 daemon이 한다). 이때부터 어디서
   끝나든(STOP·실패·Ctrl-C·SSH 끊김·출력 pipe 닫힘) EXIT trap이
   `docker start kor-travel-transport-dagster-daemon-1`로 옛 daemon 컨테이너를 그대로 되살린다. trap은
   errexit를 풀고 신호를 무시한 채 출력보다 `docker start`를 먼저 한다. 터미널이 사라졌거나 pipe가
   닫혔으면 출력이 실패하기 때문이다. 신호로 끝나면 exit code 128+번호(HUP 129, PIPE 141)를 남긴다.
   이렇게 바꾸지 않으면 bash가 EXIT trap을 돌려도 trap 안의 `$?`가 0이라 끊긴 실행이 exit 0으로
   끝난다. `docker stop` 도중에 끊겼으면 stop을 마저 끝낸 뒤 start한다. `compose start dagster-daemon`은 쓰지 않는다. 한 번만 도는
   `migrate`·`dagster-migrate` 컨테이너가 이 project에 없어 compose가 "missing dependency"로 거부한다.
   `compose up`은 고정 이미지로 daemon을 재생성한다.
7. `STARTED`·`STARTING`·`CANCELING` run이 0이 되기를 기다린다. code-server 재생성은 실행 중 run을
   끊는다. daemon이 멈춘 동안에는 `run_monitoring`도 돌지 않아, 끼인 run이나 멈춘 daemon이 남긴
   `STARTING`은 스스로 끝나지 않는다. 그래서 기다림에 상한을 둔다. 기본 1800초
   (`DRAIN_TIMEOUT_SECONDS`)가 지나면 남은 runId를 출력하고 STOP이다. 그런 run을 정리한 뒤 다시
   실행한다.
8. 2·3을 다시 돌리고, 세 컨테이너의 ID가 시작할 때와 같은지와 daemon이 아직 멈춰 있는지 본다.
   기다리는 동안 다른 배포가 env나 compose 파일을 바꿨거나, Dagster 서비스를 다시 만들었거나,
   daemon을 띄웠으면 여기서 멈춘다. 3의 gate는 각 컨테이너의 자기 이미지로 계산하므로 다른
   이미지로 다시 만든 컨테이너도 통과한다. 그래서 ID를 따로 본다. 떠 있는 daemon은 새 run을
   시작했을 수 있고, 재생성이 그 run을 끊는다.
9. 지금 파일을 `docker-compose.shared.yml.before-<UTC 시각>.<임의 6자>`로 남긴다. 시작할 때 떠 둔
   새 파일의 사본(2·8에서 검사한 그 내용)을 `install -m 664`로 넣고 `compose up -d --no-deps
   --no-build dagster-code-server dagster-webserver dagster-daemon`을 실행한다.
10. 효과 확인: 세 컨테이너가 고정 이미지로 떠 있고 3의 gate가 새 파일로 통과해야 한다. 그다음 셋 다
    healthy가 되기를 기다린다(기본 600초).

- 재생성되는 컨테이너는 `kor-travel-transport-dagster-{code-server,webserver,daemon}-1`뿐이다.
  backend·frontend·`dagster-gateway`·`migrate` 계열은 건드리지 않는다. 이미지는 빌드하지 않는다.
- code-server는 이미지가 그대로이고 healthcheck·`init`만 바뀐다. webserver·daemon은 의도적으로
  code-server와 같은 이미지로 바뀐다. 2026-09-28 11:29 KST 이후 code-server는
  `9067afc613eb`(태그 `local/transport-pr44:paced`)이고 webserver·daemon은 `c8b47811`이다.
  이 스크립트를 실행하면 세 서비스가 `9067afc613eb`로 통일되므로, **세 서비스 각각의 기존
  이미지를 보존하는 배포가 아니다.** PR #44에서는 이 healthcheck 전용 재배포를 실행하지 않았다.
  과거 09-27 조사 당시 code-server는 `148a471b`, `:latest`는 `3769528a`였고 `c8b47811`은
  image inspect에서 찾을 수 없었다. 그때의 태그/상태를 현재 값으로 가정하지 말고 실행 전에 읽는다.
- webserver·daemon은 `.env.server14`의 현재 `DAGSTER_POSTGRES_URL`로도 다시 뜬다. scheme이
  `postgresql://`에서 `postgresql+psycopg2://`로 바뀌고 사용자·host·DB·비밀번호는 같다.
  code-server와 그 run worker는 이미 이 scheme으로 같은 metadata DB에 붙어 있다. dagster_postgres
  0.29.24는 이 DSN을 SQLAlchemy로만 연다.
- STOP이면 반영을 미루거나 전체 배포로 반영한다. ADR-010부터 `deploy-server14-remote.sh`는
  `DAGSTER_POSTGRES_URL`의 `postgresql+psycopg2://`(`.env.server14`·`.env.server14.example`의 형식)도
  받는다. 그 전에는 `^postgresql://`만 받아 전체 배포가 거부됐다.
- `dagster-pin-*` 태그는 다음 전체 릴리스까지 둔다. 이 태그가 없으면 반영 뒤 고정 이미지를 붙잡는
  태그는 다른 작업이 관리하는 태그(현재 `local/transport-pr44:paced`)일 수 있다. 그 태그가 지워지면 되돌리기의
  재생성이 이미지를 찾지 못한다(compose가 `sha256:…`을 pull하려다 실패한다).
- 되돌릴 때는 새 셸에서 같은 스크립트에 옛 파일을 준다. 옛 파일은 스크립트가 남긴
  `/home/digitie/apps/kor-travel-transport/docker-compose.shared.yml.before-*`(완료 메시지에 경로가 나온다)나
  `git show "$m^1:docker-compose.shared.yml"`이다. 스크립트가 고정 이미지를 code-server에서 다시
  읽고(반영 뒤에도 고정 이미지다) daemon 정지·run 대기·gate를 똑같이 한다. healthcheck·`init`만
  돌아가고 webserver·daemon은 code-server 이미지에 남는다.
- 스크립트는 세 컨테이너가 모두 실행 중일 때만 시작한다. `up`이 중간에 실패해 하나라도 떠 있지
  않으면 되돌리기도 거부한다. 그때는 아래를 직접 실행한다. 고정 이미지는 스크립트가 처음에 출력한
  `이미지 고정: sha256:…` 값이다(`docker image inspect -f '{{.Id}}'
  kor-travel-transport-backend:dagster-pin-<12자리>`로도 읽는다). project 이름·`--env-file`·두 `-f`를
  빼면 다른 렌더링이 되거나(Dagster 서비스는 `docker-compose.shared.yml`에만 있다) 고정 없이
  재생성된다.

  ```bash
  cd /home/digitie/apps/kor-travel-transport
  export BACKEND_RUNTIME_IMAGE=<고정 이미지 sha256:…>
  install -m 664 <옛 파일> docker-compose.shared.yml
  docker compose --project-name kor-travel-transport --env-file .env.server14 \
    -f docker-compose.yml -f docker-compose.shared.yml \
    up -d --no-deps --no-build dagster-code-server dagster-webserver dagster-daemon
  ```

  `up`을 바로 할 수 없으면 `docker ps -a`로 daemon을 보고, 멈춰 있으면
  `docker start kor-travel-transport-dagster-daemon-1`로 먼저 띄운다.
- `kor-travel-transport-admin` project는 건드리지 않는다. webserver가 다시 healthy가 될 때까지
  관리 UI의 Dagster 화면(12302 → 14004)만 잠시 502를 줄 수 있다.
- `scripts/deploy-transport-admin-server14.sh`도 HEAD archive 전체를 같은 디렉터리에 `rsync`
  (삭제 없음)하므로 `docker-compose.shared.yml`을 그 배포 커밋의 내용으로 덮어쓴다. 이 변경이
  없는 브랜치에서 transport-admin을 배포하면 파일이 옛 probe로 돌아가고, 다음 전체 배포의
  `up`이 세 서비스를 옛 probe로 재생성한다. 그런 배포 뒤에는 세 컨테이너의 `init`과
  healthcheck를 `docker inspect`로 다시 확인한다.

n150의 기본 구성은 PostgreSQL 16, Alembic `0003_legacy_source_identity`,
`COLLECT_INTERVAL_SECONDS=300`, `SCHEDULER_SAFETY_BUFFER_SECONDS=120`,
`MANUAL_COLLECT_MIN_INTERVAL_SECONDS=300`, `ENABLE_MANUAL_COLLECT=false`이다. 백업 UI는 별도 인증이 없으므로
인터넷에 직접 노출하지 않고 내부망/게이트웨이 접근 제어를 전제로 한다. 백업 생성·복원 명령은
각각 최대 120초, restore 업로드는 최대 600초이며, web의 backup proxy timeout은
`900000ms`로 이 합계와 여유 시간을 수용한다.
운영 scheduler가 켜진 동안에는 restore endpoint가 `409`를 반환하므로, 복원은 scheduler를 중지한
유지보수 창에서만 수행한다.

보안 예외: 사용자가 별도 application auth를 요구한 backup/restore UI와 `/v1/admin/backups*`만
의도적으로 인증 없이 남겨 둔다. 수동 수집 endpoint는 public n150에서 비활성화하고
웹 proxy에도 노출하지 않는다. 백업 endpoint는 DB dump 다운로드와 복원을 포함하는
destructive 운영 API이므로, 외부 gateway가 private ACL/mTLS 등으로 차단되었음을 확인하기
전에는 릴리스 승인 대상이 아니다. UI의 경고 문구는 보안 경계가 아니다.

운영 포트 계약 (T-032, 2026-08-23 개편 — PostgreSQL을 별도 compose 스택으로 분리하며 포트를
한 자리씩 밀었다):

- DB: `14000` (loopback 전용, `127.0.0.1:14000` — 외부 노출 없음, `docker-compose.db.yml`)
- API: `14001` (`http://192.168.1.14:14001`)
- web: `14002` (`http://192.168.1.14:14002`)
- Docker 내부 backend: `http://backend:8000`
- 외부 API: `https://pr-api.digitie.mywire.org`
- 외부 live E2E: `https://pr.digitie.mywire.org`
- 배포 candidate: `GET /health`의 `release_sha`가 배포한 Git full SHA와 일치해야 한다.

외부 reverse proxy가 두 host를 각각 n150의 `14001`(API)/`14002`(web)로 전달해야 한다 —
이전 `14000`/`14001` 매핑에서 바뀌었으므로 reverse proxy 설정도 함께 갱신해야 한다. n150
host에는 443 listener가 없을 수 있으므로 Compose 배포만으로 기존
`pr.digitie.mywire.org`의 외부 라우팅이 바뀐다고 가정하지 않는다.

## 운영 식별자 개명 cutover (ADR-010)

n150의 배포 식별자를 `kor-travel-airport`에서 `kor-travel-transport`로 옮기는 한 번짜리 절차다.
결정과 이름 목록은 [ADR-010](../adr/010-deploy-identity-rename-transport.md)이 정본이다. 실행은
[`scripts/rename-deploy-identity-server14.sh`](../../scripts/rename-deploy-identity-server14.sh)가 맡고,
단계마다 조건이 어긋나면 `STOP:`을 출력하고 exit 1로 끝난다. 비밀값은 출력하지 않는다.

| 바뀌는 것 | 전 | 후 |
|---|---|---|
| 앱 디렉터리 | `/home/digitie/apps/kor-travel-airport` | `/home/digitie/apps/kor-travel-transport` |
| Compose project | `kor-travel-airport` | `kor-travel-transport` |
| 컨테이너 | `kor-travel-airport-<service>-1` | `kor-travel-transport-<service>-1` |
| 백엔드 이미지 | `.env.server14`의 `BACKEND_RUNTIME_IMAGE` | 배포 스크립트가 셸 env로 주는 `kor-travel-transport-backend:rel-<sha12>` |
| 빌드 이미지 | `kor-travel-airport-{frontend,dagster-gateway}` | `kor-travel-transport-{frontend,dagster-gateway}` |
| 백업 cron | digitie crontab의 `n150-backup-cron.sh` 줄 | 없음(Manager standalone backup으로 이관) |

바뀌지 않는 것: 포트(14001~14005, 12301·12302·12305), 공개 hostname, 공용 DB
`kor_travel_transport`·`kor_travel_transport_dagster`, RustFS bucket, Dagster location
`kor-travel-transport`, `kor-travel-transport-admin` project 이름, 공항 주차 도메인(`airports` 테이블,
`/v1/airports`, `airport_collection_job`, `AIRPORT_CODES_CSV`, trigger `dagster_airport`). 비밀값은
돌리지 않고 legacy volume `parking-radar_parking_radar_postgres_data`도 지우지 않는다(소유자 결정).

### 전제

- PR #44(`codex/query-collection-reliability`)가 main에 머지됐고, 이 개명 PR은 그 뒤 main에서
  rebase돼 머지됐다. 운영 스키마는 이미 #44의 `0015`다. #44가 없는 release는 `migrate`가 모르는
  revision에서 실패한다. 이 머지 커밋을 R(40자리)이라 한다.
- #44 세션은 머지 뒤 옛 디렉터리에 배포·재시작·`.env.server14` 편집을 하지 않는다. 그 세션의
  미추적 worker 스크립트는 옛 이름을 쓰므로 창 뒤에 돌리지 않는다.
- Manager의 `chore/retire-dedicated-postgres` release는 창 전에 따로 설치·검증한다. Manager 개명
  release(target `transport`)는 CI를 통과해 두고, 창이 끝난 뒤 설치한다.
- 창 전에 에이전트 공용 메모(n150 상시 서비스 목록)의 `kor-travel-airport`를 `kor-travel-transport`로
  고친다. 옛 메모를 읽은 에이전트가 옛 컨테이너를 되살리지 않게 한다. 같은 메모에 "정리 단계까지
  n150에서 `docker system prune`·`docker image prune`·`docker builder prune`을 하지 않는다"를 적는다.
  관찰 기간의 되돌리기 재료(멈춘 `*-retired-<날짜>` 컨테이너, 멈춘 컨테이너만 쓰는
  `kor-travel-airport-rollback:*`·`:pre-rename` 태그)는 Docker가 보기에 "안 쓰는" 것이라
  `prune --all`이 지운다. 설치된 Manager의 디스크 카드는 회수 가능 공간이 20 GiB를 넘으면
  `sudo -n docker system prune --all --volumes`를 다음 조치로 보여 주고, n150은 이미 그 선을 넘었다
  (2026-09-28: 이미지 17 GB, 빌드 캐시 32.6 GB 회수 가능). 그 안내를 따르면 `rollback`이
  "rollback 태그가 없다"로 멈추고 앞으로 고치는 것만 남는다. 창 전 재빌드도 캐시가 비어 길어진다.
- 다른 세션의 이미지 빌드(`docker compose … build`, `buildx bake`)가 돌지 않는다. n150 부하는 디스크
  대기라 겹치면 창이 길어진다. `prebuild`와 `window`는 빌드 프로세스가 보이면 STOP이다.

### 타이밍

n150 시계는 UTC이고 Dagster schedule은 `Asia/Seoul`이다(`backend/app/dagster/definitions.py`).

| 작업 | KST | UTC | 비고 |
|---|---|---|---|
| 공항 주차·고속도로 수집 | 5분마다 | 5분마다 | 고속도로 run이 17분까지 걸린 적이 있다 |
| KRIC 시간표 | 매시 정각 | 매시 정각 | 48시간 guard라 대부분 곧 끝난다 |
| 유가 | 00:00·08:00·16:00 | 15:00·23:00·07:00 | 보통 2시간까지, `max_runtime_seconds` 4시간 |
| 배편 시간표 | 00:45부터 4시간마다 | 15:45부터 4시간마다 | 04:45·08:45·12:45·16:45·20:45 KST |
| 철도·항구 기준정보 | 03:00(항구는 3일마다) | 18:00 | |
| 버스 기준정보 | 03:30 | 18:30 | |
| 옛 transport 백업 cron | 03:00, 3일마다 | 18:00 | `finish`가 지운다 |
| Manager standalone 백업 | 12:15~12:55 | 03:15~03:55 | 디스크 I/O가 크다 |

- `window`는 옛 daemon을 멈춘 뒤 `STARTED`·`STARTING`·`CANCELING` run이 0이 되기를 기다린다(기본
  상한 1800초). 유가 run 시작 뒤 2시간 안에서 창을 열면 상한에 닿는다. 권장 시작은 KST 10:05~11:30
  (UTC 01:05~02:30, 08:00 유가와 08:45 배편이 끝났는지 먼저 본다) 또는 KST 21:30~23:00(UTC
  12:30~14:00)이다.
- `QUEUED` run은 기다리지 않는다. 같은 metadata DB라 새 daemon이 이어서 꺼낸다. schedule마다 놓치는
  tick은 많아야 하나다.
- daemon이 멈춘 동안에는 run monitoring도 돌지 않아 `STARTING`에 남은 run은 스스로 끝나지 않는다.
  대기가 상한에 닿으면 스크립트가 옛 daemon을 다시 띄우고 멈춘다. 되살아난 daemon이
  `start_timeout_seconds`(300초)가 지난 `STARTING` run을 실패로 정리하므로 5분 이상 지난 뒤 다시
  연다. `STARTED`로 끼인 run은 Dagster UI에서 원인을 본 뒤 종료한다(종료 요청이 60초 안에 돌아오지
  않으면 code-server가 막힌 것이다. 2026-09-27 사례).
- `restore-point`는 공용 DB 약 1 GB를 dump한다(9분 이상). Manager 백업 시간과 겹치지 않게 창 전에
  돌린다.

### 단계

스크립트는 R 체크아웃에서 n150으로 옮겨 tmux 안에서 실행한다. SSH가 끊겨도 `window`는 옛 스택을
되살리지만, 창을 끝까지 보려면 tmux가 필요하다.

```bash
# WSL: 전용 worktree를 R에 둔다(공유 checkout은 다른 세션이 쓴다).
git -C /mnt/f/dev/kor-travel-transport worktree add --detach /mnt/f/dev/kor-travel-transport-R "$R"
cd /mnt/f/dev/kor-travel-transport-R
git show "$R:scripts/rename-deploy-identity-server14.sh" > /tmp/rename-deploy-identity-server14.sh
scp /tmp/rename-deploy-identity-server14.sh digitie@192.168.1.14:~/

# n150 (tmux)
bash ~/rename-deploy-identity-server14.sh prepare "$R"
bash ~/rename-deploy-identity-server14.sh restore-point

# WSL, R worktree: 새 디렉터리에 R을 올리기만 한다(컨테이너는 그대로).
DEPLOY_STAGE_ONLY=true ./scripts/deploy-server14.sh

# n150 (tmux)
bash ~/rename-deploy-identity-server14.sh prebuild "$R"
bash ~/rename-deploy-identity-server14.sh window "$R"   # 창
bash ~/rename-deploy-identity-server14.sh admin
bash ~/rename-deploy-identity-server14.sh finish
bash ~/rename-deploy-identity-server14.sh status
```

1. `prepare R`(라이브 변화 없음): 옛 project가 여섯 서비스로 돌고 새 project는 없는지 본다.
   `~/transport-rename/`(0700)에 스냅숏(컨테이너·이미지 ID·config-hash, Manager release, release
   파일, env 키 이름, `backups/` 목록, in-flight run), `crontab.before`, 옛 컨테이너 이미지 목록을
   남긴다. 새 디렉터리(0700)를 만들고 `.env.server14`를 `RELEASE_SHA`·`BACKEND_RUNTIME_IMAGE`만 빼고
   복사한다(0600). 되돌리기 이미지에 이 작업 전용 태그를 붙인다: `kor-travel-airport-rollback:backend`
   (옛 backend), `:code`(옛 code-server, webserver·daemon도 이것으로 되돌린다. 그들이 돌던 `c8b47811`은
   store에 없다), `:frontend`, `:gateway`(돌던 `f9f648a9`가 store에 없으면
   `kor-travel-airport-dagster-gateway:latest`로 대신하고 그렇게 출력한다). 다른 세션의
   `local/transport-pr4x:*` 태그가 지워져도 되돌리기가 이미지를 찾는다. 창 전이면 다시 실행해도 된다.
2. `restore-point`: 공용 PostgreSQL과 같은 major의 client(기본은 `kor-travel-shared-postgres`
   컨테이너의 이미지)로 두 DB를 `pg_dump -Fc`해 `~/transport-rename/restore-point/`에 둔다.
   비밀번호는 0600 passfile에만 쓰고 docker 명령줄에는 비밀번호 없는 URI만 넘긴다. 각 dump를
   `pg_restore --list`로 읽어 `TABLE DATA`가 있어야 `.dump`로 확정한다. API 백업
   (`POST /v1/admin/backups`)은 기본 120초 제한에 1 GB dump가 끝나지 않으므로 쓰지 않는다.
3. stage: 새 디렉터리에 R을 rsync하고 `.release-sha`를 쓴다. `backups/`와 `.env.server14`는 옮기지
   않는다.
4. `prebuild R`: R의 alembic migration 파일(CRLF 무시 내용 hash)이 옛 backend 이미지와 같고 운영 DB
   `alembic_version`이 R의 head인지 본다. revision ID만 보지 않는다(`0015`는 첫 커밋 뒤에도 고쳐졌다).
   렌더링한 새 project에 network가 없고(운영 overlay는 host network라 `kor-travel-transport-net`이
   필요 없다) 백엔드 계열 여섯 서비스가 release 태그를 쓰는지 본다. `backend`·`frontend`·
   `dagster-gateway`를 지금 env 사본으로 미리 빌드하고, 빌드한 이미지와 `:code`의 dagster 버전이 같은지 본다(같아야
   `dagster instance migrate`가 no-op이고 되돌린 옛 daemon이 metadata DB를 읽는다). 통과한 세 이미지의
   층 지문(`RootFS.Layers`의 sha256)을 `~/transport-rename/release-images`에 적는다. 이미지 ID가 아니라
   층을 적는 것은 containerd image store(n150)에서는 모든 단계가 cache hit인 재빌드도 config의 생성
   시각이 바뀌어 ID가 새로 나오기 때문이다(2026-09-28 WSL Docker 29.1.3·compose 5.1.4에서 확인: ID는
   재빌드마다 다르고 층은 같다, 내용이 바뀌면 층도 바뀐다. n150 Docker 29.6.1도 같은 containerd
   snapshotter다). backend 이미지는 `uv.lock`이 아니라
   `pip install -e ".[dev]"`(`dagster>=1.9,<2`)로 설치하므로 빌드할 때의 PyPI 최신 Dagster를 받는다
   (2026-09-28: `uv.lock`·CI 1.13.23, 운영 code-server 1.13.24). 그래서 gate는 소스가 아니라 빌드 결과에
   건다. 버전이 다르면 아래 "Dagster 버전이 다를 때"를 따른다.
5. `window R`(창): prepare 뒤 옛 컨테이너 이미지가 바뀌지 않았는지와 migration gate를 다시 본다.
   지난 시도나 rollback이 남긴 새 디렉터리 `backups/`가 옛 것과 다르면 옛 스택을 멈추기 전에 STOP이고,
   두 쪽을 hardlink로 합치는 명령(`sudo cp -a -l --update=none -T …`, 덮어쓰거나 지우지 않는다)을
   출력한다. `sudo rm -rf` 새 `backups/`는 하지 않는다. 새 backend가 쓴 dump는 거기에만 있다. 옛 스택이
   도는 동안 env를 다시 복사하고(frontend build arg `NEXT_PUBLIC_API_BASE_URL`·`NEXT_PUBLIC_API_PORT`가
   env에서 온다) 세 이미지를 다시 빌드하고 dagster 버전 gate를 다시 본다. 보통 cache hit이고, prebuild 뒤
   빌드 캐시가 비었거나 env가 바뀌었으면 긴 빌드와 새 Dagster 버전이 중단 밖에서 드러난다(층이 바뀌면
   그렇게 출력한다). 창 전 schedule 상태를 적는다. 옛 daemon을 먼저 멈추고 run을 기다린 뒤 나머지 옛 서비스를
   `docker stop`한다(rm·down 아님). 포트 14001~14005가 비었는지 본다. 옛 `.env.server14`를 새
   디렉터리에 다시 복사해(그 사이 다른 세션의 편집을 가져온다) 두 키 밖에서 같은지 비교하고, 옛
   파일을 `.env.server14.fenced-<날짜>`로 옮긴다. 이때부터 옛 배포 스크립트는 env가 없어 멈춘다.
   `sudo cp -al`로 `backups/`를 hardlink 사본으로 만든다(같은 파일시스템, 추가 공간 없음, root 소유
   유지, 옛 사본은 그대로). 새 디렉터리에서 `deploy-server14-remote.sh`로 올린다. 새 스택이 여섯
   서비스, 여섯 컨테이너의 이미지 층이 창 전 gate를 통과한 이미지(`release-images`)와 같음, Dagster 세 서비스
   healthy·`init`, 두 project를 통틀어 daemon 하나(`docker ps`가 실패하면 0으로 세지 않고 STOP),
   backend의 `backups` bind가 새 디렉터리, `/health.release_sha`가 R, frontend 응답, schedule 상태가
   창 전과 같음을 통과하면 옛 컨테이너를 은퇴시킨다. 배포 스크립트의 `up --build`는 창 전 재빌드의
   cache hit이어야 한다(ID는 새로 나오고 층은 같다). 그 사이 캐시가 비어 pip·apt 층이 다시
   만들어졌으면 층 확인에서 STOP이다. 이때
   `dagster-migrate`는 이미 그 이미지로 돌았으므로 새 이미지의 Dagster 버전을 보고, 다르면
   `restore-point`의 `kor_travel_transport_dagster` dump가 되돌릴 지점이다. 옛 daemon은 지우고(이미지가
   store에 없어 되돌리기 재료가 아니다) 나머지 다섯은 `restart=no`로 바꿔 `*-retired-<날짜>`로 이름을
   바꾼다. 이름으로 띄우는 `docker start`·Manager Start·재부팅이 옛 스택을 되살리지 못한다. 검증 전에
   어디서 멈추든(STOP·실패·Ctrl-C·SSH 끊김(exit 129)·출력 pipe 닫힘(exit 141)) 새 스택을 daemon부터
   멈추고, env를 되돌리고, 옛 컨테이너를 daemon 마지막으로 다시 띄운다. webserver·daemon·gateway는
   돌던 이미지(`c8b47811`, `f9f648a9`)가 store에 없어 `docker start`가 실패할 수 있다. 그렇게 뜨지 않은
   서비스는 rollback 태그로 재생성한다(`rollback`과 같은 `--no-deps --no-build --force-recreate`,
   daemon은 code-server가 healthy가 된 뒤 맨 나중). 그래도 뜨지 않으면 `실패:` 줄을 남기고, 그때는
   `rollback`을 실행한다.
6. `admin`: 관리 project는 이름이 그대로라 빌드하지 않는다. 떠 있는 `transport-admin-web`·
   `transport-dagster-gateway` 이미지에 `:pre-rename` 태그를 붙이고 새 디렉터리에서
   `up -d --no-build --force-recreate`로 세 서비스를 재생성한다(bind 경로만 바뀐다). 이미지가 그대로이고
   12301·12302·12305가 응답하는지 본다. 관리 UI release SHA 파일은 옛 값을 그대로 옮긴다. 재생성이
   중간에 실패해 컨테이너가 없어져도 `admin`을 다시 실행하면 된다. 없는 컨테이너는 첫 실행이 붙인
   `:pre-rename`(`:latest`와 같아야 한다)을 기준으로 삼는다. 스크립트 없이 손으로 할 때는 다음과 같다
   (`--no-build`를 빼면 관리 UI를 R로 다시 빌드한다).

   ```bash
   cd /home/digitie/apps/kor-travel-transport
   docker image inspect -f '{{.Id}}' kor-travel-transport-admin-transport-admin-web:{pre-rename,latest} \
     kor-travel-transport-admin-transport-dagster-gateway:{pre-rename,latest}   # 짝마다 같아야 한다
   docker compose --project-name kor-travel-transport-admin --env-file .env.server14 \
     -f docker-compose.transport-admin.yml up -d --no-build --force-recreate
   ```
7. Manager 개명 release 설치: `~/install-mgr.sh <sha>` → rebind → `ktdctl targets validate
   --check-coordinates`, `ktdctl status transport`(컨테이너 `kor-travel-transport-backend-1`·
   `-frontend-1`). 창과 이 설치 사이에는 Manager의 옛 airport 카드가 컨테이너를 찾지 못한다.
8. `finish`: 어떤 컨테이너도 옛 디렉터리를 bind하거나 working_dir로 쓰지 않는지 본다. digitie
   crontab에서 옛 `n150-backup-cron.sh` 줄만 지우고(지운 줄은 `crontab.removed`에 남긴다) 옛
   디렉터리를 `mv -T`로 `kor-travel-airport.retired-<날짜>`로 옮긴다(대상이 있으면 STOP).
9. 공개 확인: `https://pr-api.digitie.mywire.org/health`, `https://pr.digitie.mywire.org/api/backend/health`,
   `https://transport.digitie.mywire.org/login`, `https://transport-api.digitie.mywire.org/health`
   200, `https://transport-dagster.digitie.mywire.org/health` 204.

frontend는 R에서 다시 빌드된다. 이전 frontend 이미지 뒤에 머지된 frontend 변경도 이때 함께 나간다.
Dagster healthcheck·`init` 반영(#45)도 이 cutover가 한다. 여섯 서비스가 모두 R로 다시 만들어지므로
아래 `redeploy-dagster-services-server14.sh`를 따로 돌리지 않는다.

`.env.server14`에는 `RELEASE_SHA`와 `BACKEND_RUNTIME_IMAGE`를 두지 않는다. release SHA는 배포 스크립트가
runtime env에 붙이고, 이미지는 배포 스크립트가 `kor-travel-transport-backend:rel-<sha12>`로 export한다.
env 파일에 이미지를 적으면 다음 배포의 `up --build`가 같은 태그를 새 코드로 덮어써 이전 release
이미지가 dangling이 된다. 누가 env 파일에 두 줄을 다시 적어도 배포 스크립트가 `source` 뒤에 둘 다
candidate 값으로 export한다(`set -a; source`가 파일의 줄을 셸 env로 올리고, 셸 env는 `--env-file`보다
우선한다). `--env-file .env.server14`만 주는 즉석 compose 실행은 `:latest` fallback을 쓰므로 배포에는
스크립트만 쓴다.

### Dagster 버전이 다를 때

`prebuild`나 `window`가 `dagster 버전이 다르다(운영 X, 빌드 Y)`로 멈추면 PyPI에 운영 code-server보다
새 Dagster가 나온 것이다. backend Dockerfile은 `uv.lock`이 아니라 `pip install -e ".[dev]"`
(`dagster>=1.9,<2`)로 설치하므로 빌드 캐시가 없는 빌드는 그때의 최신을 받는다. gate를 끄거나 태그를
손으로 옮기지 않는다. 버전이 다르면 `dagster instance migrate`가 공유 metadata DB를 앞으로 올릴 수 있고,
그 뒤에는 되돌린 옛 daemon(X)이 그 DB를 읽지 못할 수 있다.

1. 창을 미룬다. 옛 스택은 그대로 돈다(`window`는 옛 스택을 멈추기 전에 멈춘다).
2. 작은 transport PR로 `backend/pyproject.toml`의 Dagster 계열을 운영 버전 X에 고정한다
   (`dagster==X`, `dagster-webserver==X`, 그와 짝인 `dagster-postgres`. 예: 1.13.24와 0.29.24).
   `uv lock`으로 `uv.lock`도 같은 버전으로 맞춘다. CI가 운영과 같은 버전을 돈다. X는
   `docker run --rm --network none --entrypoint python kor-travel-airport-rollback:code -c
   'import dagster; print(dagster.__version__)'`로 읽는다.
3. 그 PR을 머지하고 새 머지 커밋을 R로 `prepare`부터 다시 한다(stage도 새 R로).
4. Dagster를 올리는 일은 이 cutover가 끝난 뒤 따로 한다. 그때는 metadata DB dump를 먼저 뜬다.

Dockerfile이 `uv.lock`을 따르게 하는 것은 ADR-010 후속이다. 그 전까지는 이 gate가 유일한 장치다.

### 되돌리기

72시간 관찰이 끝나 정리하기 전까지는 `bash ~/rename-deploy-identity-server14.sh rollback`으로
되돌린다. 되돌릴 cutover가 없으면(옛 여섯 서비스가 돌고, 새 project는 떠 있지 않고, env fence·은퇴
디렉터리가 없음. 예: `prepare`만 한 상태) STOP이다. 옛 디렉터리 자리에 빈 디렉터리가 다시
생겼으면(옛 배포 스크립트의 `mkdir -p`, 옛 backend bind가 만든 빈 `backups/`) 지운 뒤 `mv -T`로
되돌리고, 그 밖의 내용이 있으면 아무것도 멈추기 전에 STOP이다.

먼저 새 daemon을 멈추고 창처럼 `STARTED`·`STARTING`·`CANCELING` run이 0이 되기를 기다린다(같은
`DRAIN_TIMEOUT_SECONDS` 상한). 새 code-server를 멈추면 실행 중인 유가(Playwright, 2시간까지)·배편 run이
끊겨 data.go.kr 오퍼레이션별 한도를 버린다. 상한에 닿거나 대기 중에 끊기면 새 daemon을 다시 띄우고
아무것도 옮기지 않은 채 멈춘다. run을 끊어도 되는 비상시에는 `rollback --no-drain`으로 기다리지 않는다
(끊긴 run은 되살린 옛 daemon의 run monitoring이 실패로 정리한다). 새 webserver가 떠 있지 않아 run을 셀
수 없을 때도 `--no-drain`이 필요하다.

그다음 나머지 새 project를 멈추고, 옛 env를 되돌리고, 옛 스택을 rollback 태그로 재생성한다
(code-server·webserver → backend·gateway·frontend → daemon 마지막, `--no-deps --no-build
--force-recreate`). 관리 스택은 `:pre-rename` 이미지로 옛 디렉터리에서 재생성하고, 지운 crontab 줄을
다시 넣고, 새 디렉터리의 env는 `.env.server14.rolled-back-<시각>`으로 옮긴다. Manager는 스냅숏의 이전
sha로 다시 설치하고 rebind한다. Manager만 따로 되돌리지 않는다(live 필드가 함께 바뀐다).
migration gate와 dagster 버전 gate를 통과한 이미지만 떴으므로(검증이 이미지 층을 본다) 스키마는 그대로다.

### 관찰과 정리

72시간 동안 Dagster schedule run이 정상인지, Manager 상태가 초록인지 본다. Manager transport 백업
역할이 설치되기 전까지는 주기 백업이 없으므로 `restore-point` dump를 지우지 않는다.

정리하기 전까지 n150에서 `docker system prune`·`docker image prune`·`docker builder prune`을 하지
않는다. Manager 디스크 카드가 `sudo -n docker system prune --all --volumes`를 권해도 따르지 않는다.
은퇴한 컨테이너는 멈춰 있고 rollback 태그는 그 멈춘 컨테이너만 쓰므로 `prune --all`이 모두 지운다.
그러면 `rollback`은 "rollback 태그가 없다"로 멈춘다. prune을 막을 수 없는 사정이면 창 뒤에 네 이미지를
파일로 남긴다(약 5 GB, 루트 디스크 여유를 먼저 본다). 지워졌으면 `docker load -i`로 태그가 돌아온다.

```bash
docker save -o ~/transport-rename/rollback-images.tar kor-travel-airport-rollback:{backend,code,frontend,gateway}
chmod 600 ~/transport-rename/rollback-images.tar
# 되돌리기 전에 태그가 없으면: docker load -i ~/transport-rename/rollback-images.tar
```

관찰이 끝나면 직접 실행한다(되돌릴 수 없다).

```bash
stamp=$(cat ~/transport-rename/stamp)
docker rm kor-travel-airport-{backend,frontend,dagster-code-server,dagster-webserver,dagster-gateway}-1-retired-$stamp
docker network rm kor-travel-airport_default kor-travel-airport-net
docker image rm kor-travel-airport-rollback:{backend,code,frontend,gateway} \
  kor-travel-transport-admin-transport-admin-web:pre-rename \
  kor-travel-transport-admin-transport-dagster-gateway:pre-rename \
  kor-travel-airport-backend:{latest,pr39-70a563e,pr39-f2d247f,pr40-0d7d292,pr41-3a6a1c3} \
  kor-travel-airport-frontend:latest kor-travel-airport-dagster-gateway:latest
sudo rm -rf /home/digitie/apps/kor-travel-airport.retired-$stamp   # .env.server14.* 백업 포함
```

legacy volume `parking-radar_parking_radar_postgres_data`는 남긴다. 정리 뒤 후속 PR에서
`deploy-server14-remote.sh`의 임시 개명 guard와 그 테스트를 지운다. 그 뒤로 쌓이는
`kor-travel-transport-backend:rel-*` 태그는 위 "n150 현재 운영 절차"의 보존 규칙(지금 release와 바로 전
release만 남긴다)을 따른다.

## PostgreSQL 별도 컨테이너 (T-032)

PostgreSQL은 `docker-compose.yml`(backend/frontend)이 아니라 `docker-compose.db.yml`에서
독립 lifecycle로 관리한다(`kor-travel-docker-manager`의 "DB는 앱과 분리된 컨테이너로
운영한다" 패턴을 단일 프로젝트 규모로 축소 적용). 두 스택은 외부 네트워크
`kor-travel-transport-net`으로 통신한다.

```bash
# DB 스택 (거의 재기동하지 않음 — 앱 배포와 무관한 lifecycle)
docker compose --project-name kor-travel-transport-db -f docker-compose.db.yml up -d

# 앱 스택 (배포마다 재빌드) — DB 스택이 먼저 떠 있어야 한다
docker compose --project-name kor-travel-transport -f docker-compose.yml up -d --build
```

`scripts/deploy-server14.sh`는 DB 스택이 이미 떠 있으면 건드리지 않고, 없을 때만 올린다 —
매 배포마다 postgres 컨테이너를 재생성하지 않는다.

기존 볼륨 `parking-radar_parking_radar_postgres_data`를 그대로 재사용하도록
`docker-compose.db.yml`의 volume `name`을 고정해뒀다. 이 값을 바꾸면 빈 새 볼륨이 생겨
기존 주차 스냅샷/요금 데이터와 연결이 끊긴다 — 절대 바꾸지 않는다.

**전환 절차(운영 서버, 최초 1회)**: (1) `pg_dump`로 백업 생성, (2) 기존 `docker-compose.yml`
(postgres 포함 구버전)로 `docker compose stop postgres`(볼륨은 유지, 컨테이너만 중지),
(3) `docker-compose.db.yml`로 새 DB 스택을 올려 같은 볼륨에 연결, (4) 행 수·최신 관측
시각이 전환 전과 같은지 확인, (5) `.env.server14`의 포트 값을 갱신하고 앱 스택을 새 포트로
배포, (6) reverse proxy를 새 API(`14001`)/web(`14002`) 포트로 갱신.

## 로컬 개발 실행

DB 스택을 먼저 올려야 앱 스택이 연결할 `kor-travel-transport-net` 외부 네트워크가 생긴다(T-032). 운영
overlay(`docker-compose.shared.yml`)는 모든 서비스를 host network로 돌려 이 network를 쓰지 않는다.

```bash
docker compose -f docker-compose.db.yml up -d
docker compose build
docker compose up -d
```

접속:

- 프론트엔드: [http://localhost:3000](http://localhost:3000)
- 백엔드 문서: [http://localhost:8000/docs](http://localhost:8000/docs)

## Historical: 기존 13번/ODROID 설정 (실행 금지)

아래 내용은 13번의 기존 SQLite/10분 운영을 보존하기 위한 참고 기록이다. 13번에서
Docker를 실행·중지·재생성하지 않는다. 현재 운영 배포에는 사용하지 말고, source API와
rollback 상태를 확인할 때만 읽는다.

이 절의 환경변수·포트·스크립트는 과거 기록이다. `scripts/deploy-odroid.ps1`와
`deploy/odroid/remote-deploy.sh`는 현재 fail-closed 차단 파일이며 Docker 명령을 실행하지 않는다.
운영 변경은 위의 n150 절차만 사용한다.

## 기존 실데이터 설정

`.env` 또는 셸 환경 변수에 다음 값을 넣는다.

```env
ENABLE_SCHEDULER=true
SEED_SAMPLE_DATA=false
USE_SAMPLE_CLIENT_WHEN_NO_KEY=false
COLLECT_INTERVAL_SECONDS=600
MANUAL_COLLECT_MIN_INTERVAL_SECONDS=600
UPSTREAM_RATE_LIMIT_BACKOFF_SECONDS=3600
ENABLE_INCHEON_COLLECTION=true
ENABLE_INCHEON_FEE_COLLECTION=true
AIRPORT_CODES_CSV=CJJ,CJU,GMP,HIN,ICN,KUV,KWJ,MWX,PUS,RSU,TAE,USN,WJU,YNY
DATA_GO_KR_SERVICE_KEY=...
```

설명:

- `ENABLE_SCHEDULER=true`
  - 10분 주기 자동 수집
- `SEED_SAMPLE_DATA=false`
  - live 운영에서는 샘플 시계열을 다시 넣지 않도록 유지
- `USE_SAMPLE_CLIENT_WHEN_NO_KEY=false`
  - 인증키가 없을 때 샘플로 조용히 떨어지지 않도록 강제
- `COLLECT_INTERVAL_SECONDS=600`
  - 10분
- `MANUAL_COLLECT_MIN_INTERVAL_SECONDS=600`
  - 수동 수집도 10분 제한
- `ENABLE_INCHEON_COLLECTION=true`
  - 인천공항 주차 현황을 별도 API로 수집
- `ENABLE_INCHEON_FEE_COLLECTION=true`
  - 인천공항 주차요금 규칙을 별도 API로 수집
- `AIRPORT_CODES_CSV`
  - 인천공항까지 운영하려면 `ICN`을 반드시 포함

- `client_mode=live` 상태에서는 `SEED_SAMPLE_DATA=false`를 기본값으로 사용한다.
- 샘플 시드가 필요하면 `client_mode=sample`에서만 켠다.
- `15056803` 카탈로그의 개발계정 트래픽 표기와 별개로, ODROID 실측에서는 100회 성공 후 101번째부터 제한 에러가 재현됐다.
- 중복 수집기를 제거한 현재 기준으로는 ODROID live와 local live 검증 스택의 기본값을 10분 주기로 둔다.
- 같은 인증키를 쓰는 live 수집기는 동시에 하나만 유지한다.
- live 수집기가 한도 초과를 감지하면 `UPSTREAM_RATE_LIMIT_BACKOFF_SECONDS` 동안 API 호출을 건너뛴다.
- `15056803` 공식 문서상 개발계정 트래픽은 `5,000/일`이지만, 실제 운영에서는 더 이르게 `LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR.`가 발생할 수 있다.
- 그래서 ODROID live는 하루 단위로 멈추지 않고, 짧은 backoff 뒤 다시 시도해 회복 시점을 놓치지 않도록 한다.
- ODROID live 저장 대상 공항은 `CJJ,CJU,GMP,HIN,ICN,KUV,KWJ,MWX,PUS,RSU,TAE,USN,WJU,YNY`다.
- 한국공항공사 `15056803`이 한도 초과 상태여도 인천공항 전용 `15095047`, `15095053`은 계속 시도한다.
- ODROID에는 `parking-radar` 외 별도 수집기(`airport-parking-monitor`)를 동시에 띄우지 않는다.
- 특히 `parking-collector.timer`가 살아 있으면 10분마다 `GMP,PUS,CJU,TAE`를 추가 호출해 같은 인증키를 소모한다.

임시 운영 예약:

- `2026-05-01` 기준 ODROID의 `UPSTREAM_RATE_LIMIT_BACKOFF_SECONDS`를 `409567`로 임시 변경해 다음 원 API 재시도를 `2026-05-06 00:00:00 KST` 이후로 미뤘다.
- `parking-radar-restore-backoff.timer`가 `2026-05-05 06:00:00 KST`에 실행되어 `.env.odroid`의 backoff 값을 `3600`으로 되돌리고 backend 컨테이너를 재생성한다.
- 예약 로그는 ODROID의 `/home/digitie/apps/parking-radar/logs/restore-backoff-20260505.log`에 남긴다.

## ODROID M1S 배포 파일

- 운영용 compose: [docker-compose.odroid.yml](../../docker-compose.odroid.yml)
- 운영용 환경 파일: [/.env.odroid](../../.env.odroid)
- 로컬 배포 스크립트: [scripts/deploy-odroid.ps1](../../scripts/deploy-odroid.ps1)
- 상태 확인 스크립트: [scripts/odroid-status.ps1](../../scripts/odroid-status.ps1)
- 원격 실행 스크립트: [deploy/odroid/remote-deploy.sh](../../deploy/odroid/remote-deploy.sh)

비밀값 관리:

- 공공데이터 인증키 `DATA_GO_KR_SERVICE_KEY`는 ODROID의 `/home/digitie/apps/parking-radar/.env.odroid`에 저장한다.
- 배포 패키지는 `.env`, `.env.*`를 제외하므로 로컬의 `.env.odroid`가 서버의 운영 키를 덮어쓰지 않는다.
- 로컬 `.env.odroid`는 접속 대상, 포트, 배포 경로 같은 배포 연결 정보 확인용으로만 사용하고, 운영 비밀값의 기준은 서버 파일이다.
- 관리자 토큰 기능은 사용하지 않는다. 브라우저에는 공공데이터 API 키를 요구하거나 노출하지 않는다.

기본 저장 정보:

- `ODROID_HOST=192.168.1.13`
- `ODROID_USER=digitie`
- `ODROID_APP_DIR=/home/digitie/apps/parking-radar`
- `PUBLIC_WEB_PORT=3000`
- `PUBLIC_API_PORT=18000`
- `BACKEND_INTERNAL_URL=http://backend:8000`
- `NEXT_PUBLIC_API_BASE_URL=` 비움
- `CORS_ORIGINS_CSV=http://192.168.1.13:3000,https://pr2.digitie.mywire.org,http://localhost:3000`
- `TRUSTED_HOSTS_CSV=192.168.1.13,pr2.digitie.mywire.org,localhost,127.0.0.1,testserver,backend`
- `ENABLE_API_DOCS=false`

포트 메모:

- 현재 ODROID에서는 `8000` 포트를 Portainer가 사용 중이다.
- 따라서 `parking-radar` 백엔드는 `18000` 포트를 기본값으로 사용한다.
- 프론트는 기본적으로 같은 origin의 `/api/backend`를 호출하고, Next.js 서버가 Docker 내부의 `BACKEND_INTERNAL_URL`로 프록시한다.
- 기존 13번 외부 서비스 주소는 `https://pr2.digitie.mywire.org/`를 기준으로 한다.

비밀번호는 저장하지 않으며, 배포 시에만 입력한다.

## ODROID 배포 절차 (비활성화됨)

ODROID 배포 절차는 폐기되었으며 실행하지 않는다.

1. `WSL2` 셸에서 1차 테스트를 실행한다.
2. `WSL2 + Docker`에서 2차 테스트를 실행한다.
3. 두 단계가 모두 통과하면 Windows PowerShell에서 배포 스크립트를 실행한다.
4. 배포 후 ODROID 웹/API 스모크 체크를 확인한다.

Windows 로컬 PowerShell 테스트만으로 ODROID에 배포하지 않는다. PowerShell은 배포 스크립트 실행과 원격 상태 확인 보조 도구로만 사용한다.

`.\scripts\deploy-odroid.ps1`는 실행 시 즉시 종료된다. Docker는 13번에서 절대 실행하지 않는다.

실제 운영 배포는 [n150 현재 운영 절차](#n150-현재-운영-절차)의
`scripts/deploy-server14.sh`만 사용한다.

호환성 메모:

- 원격 서버는 `docker compose` 플러그인만 있는 경우도 있고, `docker-compose` 바이너리만 있는 경우도 있다.
- 배포 스크립트는 두 방식을 모두 지원해야 한다.
- `.env.odroid`는 원격 셸에서 먼저 로드하므로 `--env-file` 지원 여부에 배포가 의존하지 않도록 유지한다.
- 배포 아카이브에는 `.env`, `.env.*`를 포함하지 않는다. 서버에 저장된 `.env.odroid`가 운영 환경의 단일 기준이다.
- `.env.odroid`는 원격 bash가 `source`로 읽으므로 UTF-8 without BOM, LF 줄바꿈을 유지한다. PowerShell `Set-Content -Encoding utf8`은 환경에 따라 BOM을 붙일 수 있어 원격에서 `$'\ufeffKEY=value\r': command not found` 오류를 만들 수 있다.
- Compose 구현에 따라 `sudo` 실행 시 셸 환경 변수가 사라질 수 있으므로, 원격 스크립트는 `.env.odroid`를 `.env`로도 연결해 Compose가 직접 읽게 한다.
- `docker-compose 1.29` 계열에서는 컨테이너 재생성 중 `ContainerConfig` 오류가 날 수 있다.
- 현재 n150 배포는 기존 Compose project를 내리지 않고 candidate artifact를 교체한다.
- 백엔드 healthcheck가 안정되기 전에는 프론트가 `depends_on`에서 실패할 수 있으므로, 원격 배포는 `backend -> health 확인 -> frontend` 순서로 올린다.

## 프론트 API 주소 결정 방식

- `NEXT_PUBLIC_API_BASE_URL`이 비어 있으면 브라우저는 같은 origin의 `/api/backend`를 호출한다.
- Next.js 서버의 `/api/backend/*` 라우트가 `BACKEND_INTERNAL_URL`로 요청을 프록시한다.
- Docker/ODROID 기본값은 `BACKEND_INTERNAL_URL=http://backend:8000`이다.
- WSL에서 Next.js를 직접 실행할 때는 `BACKEND_INTERNAL_URL=http://localhost:8000`을 사용한다.
- 명시적으로 내부/외부 API를 직접 호출해야 할 때만 `NEXT_PUBLIC_API_BASE_URL`을 채운다.

이 방식은 기존 13번 LAN IP(`http://192.168.1.13:3000`)와 외부 HTTPS 도메인(`https://pr2.digitie.mywire.org/`)을 같은 빌드로 처리하고, HTTPS 페이지가 별도 HTTP API 포트를 직접 호출하면서 생기는 mixed content/CORS 문제를 피하기 위한 것이다.

## 공개 서비스 보안 기준

- 운영에서는 `ENABLE_API_DOCS=false`로 `/docs`, `/redoc`, `/openapi.json`을 공개하지 않는다.
- `TRUSTED_HOSTS_CSV`에는 운영 도메인과 필요한 내부 호스트만 넣는다.
- `CORS_ORIGINS_CSV`에는 실제 웹 origin만 넣고 와일드카드를 쓰지 않는다.
- `ENABLE_MANUAL_COLLECT=false`인 운영 profile에서는 `POST /v1/admin/collect`가 404로
  비활성화되고 웹 proxy도 해당 경로를 전달하지 않는다.
- 브라우저에는 공공데이터 API 키를 요구하거나 노출하지 않는다.
- 백엔드는 `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, HTTPS 접근 시 `Strict-Transport-Security`를 응답 헤더로 내려준다.

## 빠른 라이브 검증용 스택

별도 포트에서 짧은 주기로 수집을 시험하고 싶다면 `docker-compose.live.yml`을 사용한다.

예:

```bash
BACKEND_LIVE_PORT=8010 \
ENABLE_SCHEDULER=true \
SEED_SAMPLE_DATA=false \
USE_SAMPLE_CLIENT_WHEN_NO_KEY=false \
COLLECT_INTERVAL_SECONDS=15 \
DATA_GO_KR_SERVICE_KEY=... \
docker compose -f docker-compose.live.yml --project-name kor-travel-transport-live up -d
```

이 스택은 빠른 검증이 끝나면 반드시 바로 내린다.

종료:

```bash
docker compose -f docker-compose.live.yml --project-name kor-travel-transport-live down
```

주의:

- `COLLECT_INTERVAL_SECONDS=15` 같은 짧은 주기는 검증용으로만 잠깐 사용한다.
- 검증용 스택을 켠 채 방치하면 ODROID와 같은 인증키 쿼터를 같이 소모한다.

## 수집 상태 확인

```bash
curl http://localhost:8000/v1/admin/collector-status
```

중요 필드:

- `scheduler_enabled`
- `collect_interval_seconds`
- `client_mode`
- `enabled_sources`
- `upstream_rate_limited`
- `upstream_rate_limited_until`
- `last_run`
- `recent_runs`

운영 판별에 특히 중요한 항목:

- `client_mode=live`인지
- `scheduler_enabled=true`인지
- `data_go_kr_service_key_configured=true`인지
- `upstream_rate_limited=false`인지

## 현재 데이터 즉시 갱신

```bash
curl -X POST http://localhost:8000/v1/admin/collect
```

다만 원본 관측 시각이 직전 수집과 같으면 `snapshot_count=0`이 나올 수 있다.  
이 경우는 실패가 아니라 중복 저장 방지다.

웹 UI에서도 같은 수동 수집을 실행할 수 있다.

주의:

- 마지막 적재 후 제한 시간이 지나지 않았으면 UI와 백엔드 모두 실행을 막는다.
- 외부 API 요청 한도에 걸렸으면 백엔드는 `429`와 함께 다음 재시도 가능 시각을 반환한다.
- 배포 후에는 버튼 노출 여부와 에러 메시지 표기를 한 번 확인하는 것이 좋다.

## 운영 권장 사항

- SQLite 런타임 파일은 Docker named volume에 둔다.
- 실데이터 환경 변수는 `.env`로 고정해 두고 재기동 시 일관되게 사용한다.
- 프론트 빌드 후에는 `docker compose up -d frontend`로 컨테이너를 재생성한다.

관련 문서:

- [current-state.md](../current-state.md)
- [../architecture/collection.md](../architecture/collection.md)

## WSL 테스트 기준

- 테스트 기준 환경은 `WSL2`이다.
- Windows 로컬 테스트는 지양한다.
- 1차 테스트는 `WSL2` 셸에서 실행한다.
- 2차 테스트는 `WSL2 + Docker`에서 실행한다.
- 테스트 합격 기준은 1차/2차가 모두 통과한 결과를 따른다.
- Windows PowerShell은 `deploy-odroid.ps1` 같은 배포 스크립트 실행과 상태 확인에 사용한다.
- 단, ODROID live 장애 조사와 운영 복구는 ODROID를 대상으로 한다.
- 사용자가 명시하지 않으면 WSL2에서 실행 중인 다른 프로젝트의 컨테이너, 타이머, 프로세스는 중지하거나 변경하지 않는다.
