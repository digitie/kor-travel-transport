# ADR-010: n150 운영 식별자를 `kor-travel-airport`에서 `kor-travel-transport`로 옮기고 공항 주차 도메인은 그대로 둔다

- **상태**: accepted (저장소 쪽 준비. n150 cutover는 PR #44 머지 뒤 실행)
- **날짜**: 2026-09-28
- **결정자**: agent + human
- **대체**: [ADR-008](008-repo-rename-kor-travel-transport.md)의 "운영 리소스 이름은 호환 유지" 보류를
  이 결정이 대체한다. ADR-008의 저장소·패키지 개명 결정은 그대로다.

### 컨텍스트

ADR-008로 저장소·패키지·DB·RustFS bucket·Dagster location은 `kor-travel-transport`가 됐지만 n150의
Compose project, 컨테이너, 앱 디렉터리, 빌드 이미지, 백업 cron은 `kor-travel-airport`로 남았다.
배포 스크립트는 그 옛 이름만 허용했고, Manager target도 옛 이름에 묶였다. 운영자가 컨테이너 이름으로
교통 스택을 찾을 때 공항 주차만 하는 스택처럼 보였고, 옛 이름을 상시 서비스로 기억한 에이전트가
옛 컨테이너를 되살릴 수 있었다.

조사(2026-09-28, 읽기 전용)에서 확인한 제약:

- 모든 서비스가 host network에 고정 포트(14001~14005, 12301·12302·12305)라 두 project를 나란히 띄울 수
  없다. 같은 metadata DB에 dagster-daemon 둘이 붙으면 schedule을 두 번 평가한다.
- 옛 project에는 named volume이 없다. 데이터는 공용 PostgreSQL(`127.0.0.1:11000`)과 RustFS에 있고 이미
  transport 이름이다. bind는 `backups/`(root 소유, 1.4 GB)와 관리 gateway 설정 템플릿뿐이다.
- webserver·daemon·gateway가 돌던 이미지(`c8b47811`, `f9f648a9`)는 store에서 지워졌다. backend·
  code-server는 다른 PR 세션의 태그(`local/transport-pr4x:*`)에만 붙어 있었다.
- 운영 스키마는 PR #44 배포로 이미 `0015`였다. #44가 없는 release는 배포할 수 없다.
- 3일 백업 cron은 `backups/` 권한 때문에 2026-09-05 뒤로 dump를 만들지 못했다. 공용 DB dump는 1 GB가
  넘어 API 백업의 기본 120초 제한 안에 끝나지 않는다.
- Dagster 버전은 한 곳에서 정해지지 않는다. `backend/uv.lock`(CI가 도는 것)은 1.13.23이지만
  `backend/Dockerfile`은 `pip install -e ".[dev]"`(`dagster>=1.9,<2`)라 이미지를 빌드할 때의 PyPI 최신을
  받는다. 운영 code-server는 1.13.24다. 소스나 lock 파일로는 배포될 이미지의 버전을 알 수 없다.
- n150의 빌드 캐시는 48.6 GB(32.6 GB 회수 가능)이고 다른 세션도 빌드한다. 미리 빌드한 이미지가 창의
  `up --build`에서 그대로 cache hit이 된다는 보장은 없다.

### 결정

1. 배포 식별자만 옮긴다.

   | 항목 | 새 이름 |
   |---|---|
   | 앱 디렉터리 | `/home/digitie/apps/kor-travel-transport` |
   | Compose project | `kor-travel-transport`(`docker-compose.yml`의 `name:`) |
   | dormant stack | `kor-travel-transport-db`, `kor-travel-transport-live` |
   | 로컬 개발 network | `kor-travel-transport-net`(운영 overlay는 host network라 쓰지 않는다) |
   | 백엔드 이미지 | release마다 `kor-travel-transport-backend:rel-<sha12>`, fallback `kor-travel-transport-backend:latest` |
   | 빌드 이미지 | `kor-travel-transport-frontend`, `kor-travel-transport-dagster-gateway` |
   | 스크립트 allowlist | 위 디렉터리·project만 허용 |

2. 공항 주차 도메인은 바꾸지 않는다: `airports` 테이블과 열·인덱스·FK, `/v1/airports`·
   `/v1/parking/airports`·`AirportSummary`, `AIRPORT_CODES_CSV`, `airport_collection_job`과 schedule·op,
   저장된 trigger `dagster_airport`, advisory lock key, `python-krairport-api`, UI `airportCode`
   (쿠키), `kind=airport`, `--color-airport`, PinVi category `airport`.
3. 과거 기록과 다른 저장소 이름도 그대로 둔다: ADR-007·008 본문, journal·tasks-done·PR URL,
   `migration.md`의 당시 기록, 이미 실행한 `cutover-shared-db-server14.sh`의 `LEGACY_*`·`TARGET_*`
   이름(머리 주석만 단다), `airport-parking-radar`·`airport-parking-monitor`, volume
   `parking-radar_parking_radar_postgres_data`.
4. 바뀌지 않는 것: 포트, 공개 hostname(edge는 LAN 포트로 라우팅한다), DB·role, RustFS bucket,
   Dagster location `kor-travel-transport`, 관리 project `kor-travel-transport-admin`.
5. `.env.server14`에는 `RELEASE_SHA`·`BACKEND_RUNTIME_IMAGE`를 두지 않는다. `deploy-server14-remote.sh`가
   `source` 뒤에 release 태그를 export한다. `DAGSTER_POSTGRES_URL`은 운영 형식
   `postgresql+psycopg2://`도 받는다.
6. `deploy-server14-remote.sh`에 임시 guard를 둔다. compose label `com.docker.compose.project=
   kor-travel-airport`인 컨테이너가 하나라도 떠 있으면 새 project를 올리지 않는다. cutover 정리 뒤 후속
   PR에서 지운다.
7. 저장소 자체 백업 cron(`scripts/n150-backup-cron.sh`)을 없앤다. 주기 백업은 Manager standalone
   backup으로 옮긴다(소유자 결정). 그 전까지의 복원 지점은 cutover의 직접 `pg_dump -Fc`다.
8. Dagster healthcheck·`init` 반영(#45)은 따로 돌리지 않고 이 cutover의 전체 release에 접는다.
9. 비밀값은 돌리지 않고 legacy volume은 지우지 않는다(소유자 결정).
10. n150 cutover는 [`scripts/rename-deploy-identity-server14.sh`](../../scripts/rename-deploy-identity-server14.sh)
    (`prepare` → `restore-point` → stage → `prebuild` → `window` → `admin` → Manager 설치 → `finish`,
    되돌리기는 `rollback`)로 한다. 절차·타이밍은 [deployment.md](../runbooks/deployment.md)
    "운영 식별자 개명 cutover"가 정본이다. Manager target 개명은 별도 Manager PR이 한다.
11. Dagster 버전 gate는 빌드한 이미지에 건다. `window`는 옛 스택을 멈추기 전에 다시 빌드하고 gate를 다시
    보며 통과한 이미지의 층 지문(`RootFS.Layers`)을 적는다. 새 스택 검증은 여섯 컨테이너의 이미지 층이
    그것과 같은지 본다. 이미지 ID는 쓰지 않는다. containerd image store에서는 모두 cache hit인 재빌드도
    ID가 새로 나온다(2026-09-28 WSL Docker 29.1.3에서 확인, n150 29.6.1도 같은 containerd snapshotter).
    버전이 다르면 gate를 끄지 않고 Dagster를 운영
    버전에 고정한 새 R로 다시 한다(runbook "Dagster 버전이 다를 때").
12. 정리 단계까지 n150에서 `docker system/image/builder prune`을 하지 않는다. 되돌리기 재료(멈춘
    은퇴 컨테이너와 그것만 쓰는 rollback·`:pre-rename` 태그)를 `prune --all`이 지운다.

### 근거

- host network와 단일 metadata DB 때문에 blue/green은 새 포트와 edge 변경이 필요하다. 몇 분의
  중단보다 위험이 크다. 느린 일(스테이징, 이미지 빌드, dump)은 모두 창 전에 하고 창 안의 `up --build`는
  cache hit이 되게 해 사용자 중단을 API·web 약 3~5분으로 줄인다.
- daemon 하나만 돌게 하는 장치를 셋 둔다: 옛 daemon을 먼저 멈추고 run을 기다린다, 새 스택 검증에서
  두 project를 통틀어 daemon이 하나인지 본다, 새 배포 guard가 옛 project의 실행 중 컨테이너를
  거부한다. 옛 컨테이너는 검증 뒤 daemon을 지우고 나머지를 `restart=no`로 이름을 바꿔 이름으로
  되살아나지 않게 한다(재부팅·Manager Start·다른 세션의 `docker start`).
- 되돌리기 재료를 다른 세션 태그에 맡기지 않는다. 이 작업 전용 `kor-travel-airport-rollback:*` 태그로
  재생성한다. 이미지가 store에 없는 옛 컨테이너를 `docker start`에만 기대지 않는다. `rollback`은 처음부터
  재생성하고, 창의 자동 되살리기는 `docker start`를 먼저 하되 뜨지 않은 서비스를 같은 rollback 태그로
  재생성한다(daemon 마지막). 그런 컨테이너를 `docker start`할 수 있는지는 n150에서 확인하지 못했다.
- 미리 빌드는 중단을 줄이는 수단일 뿐 무엇이 배포되는지를 정하지 않는다. 배포되는 이미지가 gate를 본
  이미지와 같은 내용인지는 층 지문으로 확인한다. 이 확인은 `dagster-migrate` 뒤라서 사후 탐지다. 사전
  장치는 창 직전 재빌드(가장 최근에 쓴 캐시라 곧바로 이어지는 빌드가 cache hit이 된다)와 빌드 중
  거부다. 검토가 제안한 "ID가 그대로인지"는 containerd store에서 매번 어긋나 창마다 되살리기로 끝났을
  것이다.
- `rollback`도 창처럼 새 daemon을 먼저 멈추고 run을 기다린다. 기다리지 않으면 유가(2시간까지)·배편 run이
  끊겨 data.go.kr 오퍼레이션별 한도를 버린다. 되돌릴 cutover가 없으면(`prepare`만 한 상태) 거부한다.
- migration gate는 revision ID가 아니라 파일 내용(CRLF 무시)과 운영 DB `alembic_version`을 본다.
  `0015`는 첫 커밋 뒤에도 고쳐졌다.
- 백업 API는 1 GB dump를 끝내지 못하므로 복원 지점을 API에 맡기지 않는다. 두 DB를 직접 dump하고
  `pg_restore --list`로 읽힌 것만 남긴다.
- `backups/`는 같은 파일시스템의 hardlink 사본(`sudo cp -al`)으로 옮긴다. 즉시 끝나고 추가 공간이
  없으며 root 소유를 유지하고, 옛 사본이 남아 되돌리기가 원래 bind로 돈다.

### 결과 (긍정)

- 컨테이너·디렉터리·이미지 이름이 저장소·DB·Dagster location과 같아진다.
- 옛 이름으로 두 번째 스택이나 두 번째 daemon이 뜨는 경로가 막힌다.
- release마다 백엔드 이미지 태그가 남아 이전 release로 되돌릴 이미지가 dangling이 되지 않는다.
- 운영 env 형식의 Dagster DSN으로 전체 배포가 다시 가능하다.

### 결과 (부정)

- API·web이 약 3~5분, 관리 UI가 약 1분 끊긴다. Dagster schedule은 schedule마다 tick을 하나까지 놓친다.
- Manager 개명 release를 설치하기 전까지 Manager의 옛 airport 카드는 컨테이너를 찾지 못한다.
- Manager 백업 역할이 설치될 때까지 주기 백업이 없다.
- frontend는 R에서 다시 빌드되므로 이전 frontend 이미지 뒤에 머지된 변경도 함께 나간다.
- 정리 단계(72시간 관찰 뒤) 이후에는 앞으로 고치는 것만 가능하다. 그때까지 n150에서 prune을 할 수 없다.
- PyPI에 운영보다 새 Dagster가 나오면 gate가 cutover를 멈춘다. 그때는 Dagster를 고정한 새 R이 필요하다.
- release 태그는 하나에 약 2.5 GB이고 `docker image prune`이 지우지 않는다. 지금·바로 전 release만 남기는
  보존 단계를 배포 runbook에 둔다(자동 삭제는 다른 세션의 되돌리기 태그를 지울 수 있어 하지 않는다).

### 후속

- cutover 정리 뒤 `deploy-server14-remote.sh`의 임시 guard와 그 테스트를 지운다.
- Manager: transport 백업 역할, `config_files`에 `docker-compose.shared.yml`, 선언되지 않은 Dagster·관리
  컨테이너는 각각 별도 설계로 다룬다.
- API 백업의 `BACKUP_COMMAND_TIMEOUT_SECONDS`(기본 120초)와 `BACKUP_STORAGE_LIMIT_BYTES`를 1 GB 넘는 DB에
  맞춰 따로 검토한다. 복원 전 사전 백업도 같은 제한을 받는다.
- 에이전트 공용 메모의 상시 서비스 목록을 새 이름으로 고친다(창 전). 같은 메모에 정리 단계까지 prune
  금지를 적는다.
- backend 이미지가 `uv.lock`을 따르게 한다(지금은 빌드 시점의 PyPI 최신). 그러면 CI·운영·되돌리기
  이미지의 Dagster 버전이 한 곳에서 정해진다.
