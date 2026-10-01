# 공용 DB와 Dagster 운영 경계

## 목적

`kor-travel-transport`는 국내 여행 교통정보를 주기 수집해 자체 PostgreSQL에 저장하고,
저장 데이터·통계·외부 OpenAPI를 즉시 제공한다. 운영 수집은 FastAPI web process의
background task가 아니라 Dagster가 맡는다. 이 경계는 고속도로·유가처럼 짧은 주기의
데이터와 열차·여객선처럼 변동이 적은 기준정보를 같은 운영 기준으로 다루기 위한 것이다.

## 프로세스 분리

운영은 `docker-compose.yml`과 `docker-compose.shared.yml`을 함께 사용한다. 후자는
`kor-travel-weather`와 같은 역할 분리를 따른다.

| 서비스 | 책임 | 사용자 코드 import |
| --- | --- | --- |
| `backend` | 읽기 API, 주차/교통 조회, 즉시 통계 | 하지 않음 (`SCHEDULER_MODE=dagster`) |
| `migrate` | 애플리케이션 Alembic migration 1회 실행 | Alembic만 |
| `dagster-code-server` | job 코드와 run worker 실행(`dagster code-server start`, 공용 plane의 location `kor-travel-transport`) | 함 |
| `dagster-migrate` *(legacy-dagster)* | 옛 전용 Dagster metadata schema 1회 초기화·업그레이드 | Dagster instance migration만 |
| `dagster-webserver` *(legacy-dagster)* | 옛 전용 Dagster UI/GraphQL | 하지 않음, gRPC workspace만 연결 |
| `dagster-daemon` *(legacy-dagster)* | 옛 전용 schedule, queue, run monitoring | 하지 않음, gRPC workspace만 연결 |
| `dagster-gateway` *(legacy-dagster)* | 옛 전용 UI의 loopback Basic Auth gateway | 하지 않음 |

2026-10부터 schedule·queue·run monitoring·UI는 Manager의 **공용 Dagster 제어 평면**이 맡는다(아래
"공용 Dagster 제어 평면" 절). *(legacy-dagster)* 서비스는 되돌리기용으로 compose에 남지만 평소 `up`은 띄우지
않는다.

`dagster dev`는 운영에서 사용하지 않는다. code-server는 독립 컨테이너라 실제 crash/OOM이면
`restart: unless-stopped`로 재기동하고, webserver/daemon은 child-process heartbeat를 관리하지
않는다. `dagster.yaml`의 `run_monitoring`은 사라진 worker가 STARTED 상태로 남아 queue를
막는 경우를 5분 시작 제한과 4시간 실행 상한으로 회수한다.

### healthcheck 계약

Manager #426·Map #1284와 같은 계약이며 `backend/tests/test_dagster_healthcheck_contract.py`가
command에서 Dagster 서비스를 찾아 검사한다.

- 모든 Dagster probe는 exec 형식(`CMD`)이고 Python probe는 `python -I`다. `CMD-SHELL`이나
  `CMD sh -c`는 timeout 때 셸만 죽이고 그 아래 Python을 고아로 남긴다. healthcheck를
  `disable`하지 않는다.
- code-server·webserver·daemon은 `init: true`다. PID 1인 dagster는 고아를 거두지 않는다.
- code-server probe는 `grpc_health`로 `DagsterApi`가 `SERVING`인지 8초 deadline과 함께 묻는다.
  CLI `dagster api grpc-health-check`와 같은 판정이지만 dagster를 import하지 않는다. CLI는
  deadline이 없어 끼인 서버 앞에서 끝나지 않는다. 테스트는 deadline이 숫자 상수이고 docker
  timeout(10s)보다 짧은지 확인하고, 실제 gRPC health 서버 앞에서 probe를 실행해 `SERVING`일
  때만 exit 0인지 확인한다.
- daemon `liveness-check`는 timeout 60s, interval 120s, retries 2다.
  `DAGSTER_DAEMON_HEARTBEAT_TOLERANCE`는 300s다. dagster는 마지막 heartbeat 뒤 heartbeat
  주기(30s) + tolerance가 지나야 낡았다고 본다. docker는 이전 probe가 끝난 뒤에야 interval을
  다시 세므로, 끼인 daemon이 unhealthy로 보이기까지 최악 30 + 300 + 60(진행 중이던 probe) +
  2 × (120 + 60) = 750s다. 이 시간을 기다리는 소비자는 없어 테스트는 상한으로 걸지 않는다.
- healthcheck는 상태를 보이게만 한다. docker는 unhealthy 컨테이너를 재시작하지 않는다.
  2026-09-27 code-server가 gRPC worker 8개를 모두 막힌 호출에 잃고 8시간 unhealthy로 남은
  사례는 `docs/journal.md`에 있다.

## 공용 PostgreSQL 계약

`kor-travel-docker-manager`가 host-network로 관리하는 `kor-travel-shared-postgres`와
RustFS를 소비한다. 이 저장소의 compose는 PostgreSQL superuser 권한을 받거나 DB/role을
생성하지 않는다. bridge 컨테이너에서는 Docker의 `host-gateway` 별칭인
Manager의 정식 Weather 운영 패턴과 같이 모든 runtime 컨테이너를 n150 host-network로
실행한다. 따라서 공용 PostgreSQL은 `127.0.0.1:11000`, RustFS는
`127.0.0.1:12101`로 접근한다. 일반 Compose bridge와 임시 TCP relay는 사용하지 않는다.
Manager 소유 bootstrap이 아래 두 DB와 각각 전용 role을 먼저 준비해야 한다.

| 용도 | DB | 환경변수 |
| --- | --- | --- |
| 애플리케이션 데이터·Alembic | `kor_travel_transport` | `DATABASE_URL` |
| Dagster run/event/schedule metadata | `kor_travel_transport_dagster` | `DAGSTER_POSTGRES_URL` |

두 DB를 합치면 양쪽 Alembic이 `alembic_version` 테이블을 서로 덮어쓰므로 절대 합치지 않는다.
운영 DSN은 `127.0.0.1:11000`을 사용하며, 비밀번호·service key·RustFS key는
n150의 비추적 환경 파일에만 둔다.

## 수집 일정과 저장 경계

| job | KST schedule | 저장 대상 | 호출량 경계 |
| --- | --- | --- | --- |
| `airport_collection_job` | 5분 | 공항 주차·요금 | 기존 rate-limit/backoff |
| `highway_collection_job` | 5분 | 소통·돌발 snapshot | KREX quota/backoff |
| `fuel_collection_job` | 8시간 | 주유소·유가 snapshot | Playwright provider throttle |
| `rail_reference_collection_job` | 매일 03:00 due 평가 | KRIC 공개 XLSX 역사 기준정보 | 마지막 성공 뒤 48시간이 지난 경우만 1회 |
| `maritime_reference_collection_job` | 매월 1·4·7…일 03:00 | 항구·터미널·선박종류 기준정보 | data.go.kr 요청 세 건을 순차 실행 |
| `ferry_timetable_collection_job` | 4시간마다 45분 | 항구별 운항일 시간표 snapshot | run당 최대 280건, 배치 전용 2초 간격, 다음 run 재개 |

KRIC는 인증 OpenAPI도 과도한 GET 대신 하루 한 번 이하의 batch 호출을 요청한다. 철도
기준정보 job은 매일 due만 평가하지만 마지막 성공 수집 뒤 **48시간**이 지나기 전에는
provider를 호출하지 않는다. 따라서 월 경계도 실제 수집 간격은 2일 이상이다. 한 run은 공개
XLSX를 한 번만 읽고, 인증 OpenAPI를 전국 역·열차 단위로 순회하지 않는다.
인증 OpenAPI의 역 상세·시간표는 이용자 요청에 필요한 단건 조회로 분리하고, 별도 cache
정책을 구현하기 전에는 Dagster batch에 포함하지 않는다. 여객선 기준정보는 저변동 기준으로
수집하고, 운항계획은 아래의 호출 예산을 가진 전용 job에서만 보충한다.

항구 운항시간표는 `ferry_timetable_snapshots`에 오늘 포함 10일만 저장한다.
`GET /v1/transport/ports/{port_id}/timetable?date=YYYY-MM-DD`는 DB를 먼저 반환하고, 누락된
항구·날짜 한 건만 provider에 비동기로 요청해 저장한다. Dagster는 한 run에 최대 280건만
보충하고, 배치 전용 2초 간격과 최대 15초 요청 timeout을 포함해 3시간 30분 예산 안에서 각 성공을
즉시 commit하므로 4시간 runtime 상한이나 일시 오류 뒤에도 다음 run이 남은 범위를 재개한다.
실시간 cache miss의 30초 보호는 유지하며 배치와 별도 설정이다. 배치의 기본 간격 대기는
최대 279회 × 2초 = 9분 18초이며 실제 실행에는 응답·DB 처리 시간이 추가된다.
provider가 호출 제한을 돌려주면 전 항구 요청을
`UPSTREAM_RATE_LIMIT_BACKOFF_SECONDS` 동안 429와 `Retry-After`로 차단한다.

## 운영 실행

Manager가 공용 DB/네트워크와 전용 role·RustFS bucket을 provision한 뒤에만 전환한다. 새 DB가
비어 있다고 바로 `DATABASE_URL`을 바꾸면 기존 주차·요금·수집 이력이 사라진다. 따라서
아래 순서를 모두 통과해야 한다.

1. Manager bootstrap receipt로 두 DB/전용 role/RustFS bucket이 준비됐음을 확인한다.
2. 현재 운영 `DATABASE_URL`을 `LEGACY_DATABASE_URL`로, 기존 환경 파일을
   `.env.server14.legacy`로 보존한다. n150 host-network에서 legacy DB에 연결할
   `LEGACY_HOST_DATABASE_URL`도 별도로 준비한다. 현재 legacy PostgreSQL은 loopback
   `127.0.0.1:14000`에만 노출되므로 이 DSN은 `postgresql://` scheme와 그 port를 사용한다.
   과거 Dagster metadata DB가 있으면 같은 방식의 `LEGACY_DAGSTER_HOST_DATABASE_URL`도 준비한다.
   runtime/host DSN은 같은 database 이름을 가리켜야 한다. 네 값은 Git에 절대 저장하지 않는다.
3. cutover 전 WSL checkout에서 `DEPLOY_STAGE_ONLY=true ./scripts/deploy-server14.sh`를 실행해
   reviewed candidate artifact와 full SHA manifest를 n150에 올린다. 이 단계는 컨테이너를
   변경하지 않으며, `.env.server14.legacy`도 보존한다. 이어 n150 maintenance window에서
   `CUTOVER_CONFIRM=MOVE_KOR_TRAVEL_TRANSPORT_HISTORY_TO_SHARED_DB`와 함께
   `scripts/cutover-shared-db-server14.sh`를 실행한다(완료. 스크립트는 ADR-011로 지웠고 재현은
   `git show 07d3848:scripts/cutover-shared-db-server14.sh`).
   one-shot은 staged artifact의 `deploy-server14-remote.sh`를 직접 호출하므로 n150의 Git checkout을
   요구하지 않는다. 또한 n150에 PostgreSQL client 패키지를 설치하지 않고, host network의
   일회성 `postgres:16-alpine` client container로 legacy loopback DB와 shared DB를 조회한다.
   DSN의 비밀번호는 URL percent-encoding을 유지한 채 Docker command/env가 아니라 cutover workdir의
   mode `0600` passfile로만 전달하고, client command에는 passwordless URI만 넘긴다.
   base dump → legacy writer quiesce → final dump/restore → public table
   row count와 최신 주차 observation watermark 비교를 fail-closed로 수행한다. 복원 전에는 두
   target DSN이 정확한 Manager host/port/DB를 가리키고 모든 비시스템 schema 객체와 Alembic
   행이 비어 있는지도 확인한다. 과거 Dagster metadata DB가 있으면
   `LEGACY_DAGSTER_DATABASE_URL`로 별도 dump/restore하고, 없을 때만
   `DAGSTER_METADATA_RESET_CONFIRM=START_FRESH_DAGSTER_METADATA_WITH_NO_LEGACY_STORE`를
   명시해 fresh metadata 시작을 승인한다. 검증 결과는 mode `0600`의 receipt로 남고, 같은
   script가 그 receipt를 staged target deploy에 전달한다. writer를 멈추기 직전 기존 backend의
   image와 환경·backup mount, frontend image·환경을 mode `0600` rollback artifact로 보존한다.
   artifact는 Compose label을 갖지 않는 standalone container로만 재기동하므로 candidate Compose의
   recreate 대상이 아니다. 기존 container가 host-network이면 그 mode를, legacy bridge이면
   `kor-travel-airport-net`(개명 전 이름, ADR-010)과 원래 `14001:8000`/`14002:3000` publish를 검증·복원한다. deploy
   또는 health 검증이 실패하면 candidate backend endpoint를 제거하고 rollback backend에 `backend`
   alias를 붙여 기존 frontend proxy 계약을 복원한다. API, web proxy health를 모두 확인한다.
   rollback 실패는 성공으로 숨기지 않고 fatal로 남긴다.
4. `scripts/deploy-server14.sh`는 target DB identity와 receipt를 함께 검증하므로, 빈 공용 DB를
   가리키는 환경 파일만으로는 기동하지 않는다. `migrate`와 `dagster-migrate`가 각각
   application/Dagster schema를 단독으로 처리하며, 장기 실행 컨테이너는 DDL을 실행하지 않는다.
5. health와 live E2E가 성공할 때까지 legacy DB volume, `.env.server14.legacy`, 두 dump를
   보존한다. 실패 시 shared compose를 내리고 legacy 환경으로 backend만 재기동해 rollback한다.

전환 검증을 건너뛰는 `docker compose up`은 금지한다. cutover가 아닌 이후의 검증된 배포만
receipt-gated deployment script를 사용한다.

```bash
docker compose -f docker-compose.yml -f docker-compose.shared.yml up -d --build
```

외부 Dagster UI는 Manager 공용 gateway(`https://dagster.digitie.mywire.org`, 11001)다. 운영 값은 최소한
`DATABASE_URL`, `KOR_TRAVEL_DAGSTER_SHARED_APP_PASSWORD`, 그리고 legacy-dagster 서비스의 보간을 위한
`DAGSTER_POSTGRES_URL`·`DAGSTER_UI_PASSWORD`를 요구한다.
KRIC 파일 수집은 `RAIL_REFERENCE_COLLECTION_ENABLED=true`와 RustFS endpoint·bucket·접근키가,
여객항구 기준정보는 `MARITIME_REFERENCE_COLLECTION_ENABLED=true`와,
TAGO 버스 터미널 기준정보는 `BUS_REFERENCE_COLLECTION_ENABLED=true`와
`DATA_GO_KR_SERVICE_KEY`가 모두 있을 때만 실행한다. Manager의 RustFS 초기화는
`kor-travel-transport-raw` bucket도 idempotent하게 준비한다. 비활성 상태는 실패가 아니라
명시적인 `skipped` run으로 남긴다.

provider는 HTTPS RustFS endpoint를 기본 요구한다. 현재 Manager RustFS는 host loopback의
사설 연결만 제공하므로 `RUSTFS_ALLOW_INSECURE_HTTP=true`는 그 host-gateway 경로에만
명시한다. 공용 인터넷 endpoint에는 이 값을 사용하지 않는다.

기존 `docker-compose.db.yml`은 기존 n150 데이터의 rollback과 local 개발 격리용이다.
공용 DB cutover가 완료되고 live E2E가 수용될 때까지 기존 DB volume을 삭제하거나 그 compose를
내리지 않는다.

## 공용 Dagster 제어 평면(2026-10, Manager ADR-54)

transport의 schedule·queue·run monitoring·UI는 Manager가 운영하는 **공용 Dagster 제어 평면**이 맡는다 —
공용 daemon(`kor-travel-dagster-daemon`), webserver(`127.0.0.1:11002`, 인증 없음, loopback), gateway(11001,
Basic Auth, 공개 host `https://dagster.digitie.mywire.org`)와 공용 instance(`dagster_shared`, 공용 PostgreSQL
`:11000`, role `kor_travel_dagster_shared_app`). 이 저장소에 남는 Dagster 프로세스는 code-server 하나다.

### 계약(`backend/tests/test_shared_dagster_plane_contract.py`)

- code-server는 `dagster code-server start -h 127.0.0.1 -p 14005 -m app.dagster.definitions --location-name
  kor-travel-transport`다. `api grpc`는 공용 webserver의 location reload를 무시한다. location 이름은 옛 workspace의
  이름 그대로다 — run의 `dagster/code_location` tag(공용 instance의 테넌트 상한 key)와 schedule selector id가
  이 이름에서 나온다. 포트는 literal이고 healthcheck가 같은 포트를 부른다.
- code-server는 공용 instance URL(`KOR_TRAVEL_DAGSTER_SHARED_PG_URL`, `postgresql+psycopg2://…/dagster_shared`)을
  받고 옛 metadata DSN은 받지 않는다. `$DAGSTER_HOME/dagster.yaml`은 Manager의 공용 instance 정의
  (`/opt/kor-travel-docker-manager/config/dagster-shared/dagster.yaml`, `KOR_TRAVEL_DAGSTER_SHARED_INSTANCE_CONFIG`로
  바꿀 수 있다)로 읽기 전용으로 덮는다. 공용 instance의 로컬 쓰기(`/opt/dagster/state`)는 이 컨테이너 안에서
  풀린다(root라 쓸 수 있다). compute log는 오늘처럼 code-server 컨테이너의 로컬 파일이다(D5).
- 옛 `dagster-webserver`·`dagster-daemon`·`dagster-gateway`와 옛 metadata DB의 `dagster-migrate`는
  `profiles: [legacy-dagster]`다. 활성 서비스는 그것에 기대지 않고 그 포트(14003·14004)를 부르지 않는다. 그
  profile로 직접 띄우지 않는다 — 공용 daemon이 같은 schedule을 이미 쏜다(이중 발화).
- 공용 instance의 상한은 Manager `config/dagster-shared/dagster.yaml`이 갖는다 — 이 location 3(옛
  `max_concurrent_runs`), `kortraveltransport/run_group` 넷 각 1(옛 값). 실행 상한은 job tag
  `dagster/max_runtime=14400`(옛 instance의 4시간, `backend/app/dagster/definitions.py`)이다. 이 저장소의
  `backend/dagster_home/dagster.yaml`은 legacy-dagster(되돌리기)만 쓴다.
- schedule의 상태는 코드에 선언한다 — 10개 모두 `default_status=RUNNING`(2026-10-02 옛 instance의 RUNNING 집합과
  같다). 이력은 새로 시작한다(D1). 옛 metadata DB `kor_travel_transport_dagster`는 30일 보존한다(지금 지우지 않는다).
- 운영 UI(`kor-travel-transport-admin`)는 공용 webserver에 이 location으로 좁힌 이름 붙은 query만 보낸다
  (`packages/kor-travel-transport-admin/frontend/lib/dagster-scope.ts`). 브라우저의 GraphQL 문서는 넘기지 않는다
  — 공용 webserver에는 다른 프로젝트의 run·schedule이 있다. 옛 `transport-dagster-gateway`(12302,
  `transport-dagster.digitie.mywire.org`)는 없어졌다(redirect 없음). Dagster UI 링크는 공용 host다.

### 전환(1회) — n150

Manager 쪽 전환 PR(`feat/transport-shared-dagster`의 flip)과 이 저장소의 전환 PR(`feat/shared-dagster-plane`)이
머지된 뒤 순서대로 한다. 비밀은 출력하지 않는다.

1. `.env.server14`에 `KOR_TRAVEL_DAGSTER_SHARED_APP_PASSWORD`를 더한다(값은 root만 읽는 Manager `.env`의 같은 이름 값).
2. WSL(머지된 main): `DEPLOY_MODE=prepare-shared-dagster-cutover ./scripts/deploy-server14.sh`. stage·이미지
   빌드(`kor-travel-transport-backend:rel-<sha12>`)만 하고 `.env.server14.shared-dagster-cutover`(0600)를 남긴다.
   컨테이너는 바꾸지 않는다.
3. n150 root: Manager 전환 release를 설치하고(`~/install-mgr.sh <sha>`) **이어서** 창 스크립트를 돈다:
   `systemd-run --unit=dagster-cutover-transport --collect -E EXTERNAL_ENV_FILE=/home/digitie/apps/kor-travel-transport/.env.server14.shared-dagster-cutover /opt/kor-travel-docker-manager/scripts/dagster-shared-cutover.sh transport forward <manager-sha>`.
   precheck(선언·렌더 대조, 이미지, plane이 아직 이 location을 안 싣는지) → 옛 daemon·webserver·gateway 정지(펜스)
   → 옛 DB의 진행 중 run 취소 → code-server를 공용 instance로 재생성 → 공용 daemon·webserver 재생성 → location
   `RepositoryLocation`·RUNNING instigator 동등(10 schedule) → 옛 컨테이너 제거 → 첫 tick(5분 주기라 몇 분).
4. WSL: `./scripts/deploy-server14.sh`(일반 배포 — backend·frontend를 같은 release로 맞춘다. 공용 plane이 location을
   싣는지·옛 daemon이 멈췄는지 확인한 뒤에만 교체한다).
5. WSL: `./scripts/deploy-transport-admin-server14.sh`(공용 webserver를 부르는 운영 UI. `--remove-orphans`가 옛
   12302 gateway 컨테이너를 지운다).

되돌리기: 먼저 전환 env 파일을 working_dir 밖에 복사한다(`sudo install -m 0600 .env.server14.shared-dagster-cutover
/root/transport-cutover.env` — 이전 release의 배포 동기화(`rsync --delete`)는 이 파일을 지운다). 이 저장소의 이전
release를 stage(`DEPLOY_STAGE_ONLY=true`)하고, Manager의 이전 release(prep — transport `own`)를 설치한 뒤
`EXTERNAL_ENV_FILE=/root/transport-cutover.env dagster-shared-cutover.sh transport rollback <prep-sha>`를 돈다. 공용
plane에서 location을 내리고 공용 instance의 진행 중 run을 취소한 뒤 옛 code-server·webserver·daemon·gateway를
다시 만든다(이미지는 그 env 파일의 tag — 정의는 tag만 다르다). 운영 UI도 이전 release로 다시 배포한다.
