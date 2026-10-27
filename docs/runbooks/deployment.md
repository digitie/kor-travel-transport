# 배포 및 실행


## Manager 호스트별 instance 정본 전달

공식 backend/code-server 배포에는 Manager559의 `dagster-instance-config show --json` 계약이
필요하다. 정상 Manager installer의 명시적 prepare·설치를 먼저 완료하고, 외부 Transport가
prepare를 자동 호출하지 않는다. 기존 registry·주소·NVMe·drain·rollback 검사는 계속 적용한다.

`deploy-prod-remote.sh`는 env를 읽은 뒤 다음 명령을 읽기 전용으로 호출한다.

```bash
sudo -n ktdctl dagster-instance-config show --json
```

정확 네 필드 `host`, `max_concurrent_runs`, `path`, `sha256`을 받아 transport target의 host와
맞추고 전체64자리 SHA를 검증한다. 숫자는 Manager가 소유하며 caller가 n150/Odroid 상한을
다시 선언하지 않는다. 설치/미준비/권한·JSON·필드 불일치면 Docker 변경 전에 exit2다.
Manager stdout/stderr·원 env를 오류에 재출력하지 않는다.

얻은 path만 `KOR_TRAVEL_DAGSTER_SHARED_INSTANCE_CONFIG`로 export하고 runtime·cutover·rollback
환경에도 보존한다. 미리 지정한 값이 정본과 다르면 거부한다. Compose의 tracked 기본값은 로컬
호환용이며 공식 배포의 대체 경로가 아니다. trusted 기본 설치 alias는 허용하지만 임의 경로·
부모 이동·개행·보간/volume 구문은 거부한다. Odroid의 content-addressed root 파일은 일반
사용자가 직접 읽거나 복사하지 않으며 Manager CLI가 소유·mode·호스트 bytes/SHA를 검증한다.

긴 build/drain 뒤 실제 up·cutover handoff와 실패 rollback 직전 같은 show 결과인지 재확인한다.
path/SHA/host/max가 달라지면 교체/rollback을 거부하고 운영자가 Manager 상태를 확인한다.
이 재검증이 외부 배포 전체와 Manager installer를 잠그는 보장은 아니다. 기존 lock 범위를
유지하며, 정본 전환은 승인된 순서로 수행한다. 현재 코드의 실제 두 호스트 effective mount·digest
수용은 후속 운영 readback으로 남긴다. 이 문서 갱신만으로 배포·서비스 변경 완료를 뜻하지 않는다.
[설계와 검증 상태](../reports/2026-10-26-manager-host-instance-caller.md).


## T-TRN-01 source 배포 계약(2026-10-17)

현재 source의 entry는 scripts/deploy-prod.sh --host <IPv4>, scripts/deploy-prod-remote.sh --host <IPv4>, scripts/deploy-transport-admin-prod.sh --host <IPv4>다. env 정본은 .env.prod와 .env.prod.example이며 app dir·project·실행 사용자는 유지한다. 구 env의 실제 개명·배포를 이 PR이 자동 수행하지 않는다. 구 .env.server14와 .env.server14.legacy/.env.server14.shared-dagster-cutover 세 파일은 정확한 exclude로 보존하며 root의 별도 확인 없이 정리하지 않는다.

주소는 필수 인자다. 원격 IPv4에 주소가 있고, sudo -n ktdctl targets validate --json의 targets.transport.host가 가리키는 hosts.<key>.addr와 같으며 호출자가 env를 읽을 수 있어야 한다. Manager PR530 설치 전 hosts 필드가 없거나 sudo/registry 조회가 실패하면 복사·Docker 변경 전에 exit2다. 코드에 허용 주소표나 호스트 기본값을 두지 않는다. 운영 UI도 transport 키를 사용한다.

공식 Manager installer는 backend venv의 ktdctl을 설치하며 전역 /usr/local/bin/ktdctl 진입점까지 만들지는 않는다. 이 계약의 sudo -n ktdctl 조회 전에 root가 정식 설치 경로의 실행 파일과 기존 전역 진입점을 확인한다. 아래 프로비저닝은 전역 경로가 없을 때만 수행하며, 기존 파일·symlink가 있으면 출처를 확인하고 임의로 덮어쓰지 않는다.

    if test -x /opt/kor-travel-docker-manager/backend/.venv/bin/ktdctl &&
       ! test -e /usr/local/bin/ktdctl && ! test -L /usr/local/bin/ktdctl; then
      sudo ln -s /opt/kor-travel-docker-manager/backend/.venv/bin/ktdctl /usr/local/bin/ktdctl
    fi
    sudo -n ktdctl targets validate --json

2026-10-17 root는 최초 CLI 부재 거절을 보존하고 이 root 소유 진입점 준비 뒤 실제 승인/비로컬/env 없음 효과 검사를 각각 exit0/2/2로 확인했다. tracked source와 env 정렬·기존 UI34 수용을 완료했지만 runtime build/recreate는 0이다. 전체 ARM build·새 bundle·첫 full cutover 및 아래 역사적 정책의 정산은 T-TRN-01/02 후속과 T-TRN-03a/04에서 구분한다. Manager530 제품의 실제 설치를 PR530 머지 완료로 해석하지 않는다.

DSN의 loopback11000/DB 이름, 공용 Dagster 버전, location absent 거절·PythonError 재로드 대기, 이 location의 run/worker drain·release lock은 바꾸지 않았다. 최신 사용자 지시에 따라 공용 daemon은 RUNNING을 유지한다. Transport 배포에서는 이 location의 schedule·sensor 원래 상태를 저장한 뒤 일시 중지하고, queued/run과 실제 worker의 자연 종료를 모두 확인한다. 검증된 전환 또는 복구 뒤 원래 instigator 상태를 복원한다. 공용 PG·daemon·다른 테넌트를 함께 재생성하지 않는다.

예전 n150/파일명으로 적힌 아래 절은 당시 이력이다. 현재 명령에는 위 prod entry·--host·.env.prod를 적용하고, 이전 정책 문구·실제 source 배포/ARM/live 수용은 T-TRN-03a/04에서 별도로 정산한다. 현재 source의 tracked-file/효과 검사 적용과 runtime image 재빌드·전체 cutover는 별개다.

## 현재 Odroid 정본(2026-10-19)

사용자 승인에 따라 현재 대상은 Manager가 지정한 Odroid다. project는
`kor-travel-transport` 하나이며 API12302/web12303/gateway12301/admin12305/CS12306을 사용한다.
앱·이미지·빌드·DB·환경 파일의 실제 장치는 NVMe여야 한다. staging과 공유 checkout 잠금은
`/mnt/media/kor-travel/build/transport` 아래에 두며 이 디렉터리는 digitie 소유0700이다.
상위 디렉터리의 권한을 확대하지 않는다. 부팅 조건을 추가하지 않는다.

앱 `/home/digitie/apps/kor-travel-transport`와 중앙 환경
`/opt/kor-travel-odroid/transport.env`·Manager override를 함께 확인한다.
Dagster code-server의 Odroid 포트는 공용 workspace/Manager registry와 같은 12306이다. 정본
[`transport.override.yml`](../../transport.override.yml)은 release archive에 포함되며, 배포 도구가
`/opt/kor-travel-odroid/transport/transport.override.yml`에 NVMe 저장 여부를 확인해 원자적으로 설치하고
Compose에 명시적으로 추가한다. 렌더된 command와 healthcheck가 모두 12306인지 검증하기 전에는 이미지 빌드나
컨테이너 교체를 시작하지 않는다. 기본 compose의 14005는 n150 호환 기본값으로만 유지한다.
관리자 배포는 같은 project의 gateway/admin 두 역할만 선택하며 다른 역할을 제거하지 않는다.
소비자 export는 GET과 기존 승인 IP/CIDR에 한정하고 빈 설정은 모두 거부한다.
기존 env 보호 exclude를 지우거나 HAProxy를 직접 수정하지 않는다. 공용 daemon RUNNING을 유지한다. DB 조회·worker 확인에 상한을 두고, 배포 시간 초과로 하위 작업의 종료가 불명확하면 pause를 유지한 채 별도 정산한다. 종료를 증명하기 전에 자동 rollback과 정방향 배포를 겹치지 않는다.

### 사전 빌드와 공식 staging의 metadata

사전 빌드는 가능하면 공식 `DEPLOY_STAGE_ONLY=true`로 준비한 같은 staging과 같은 사용자·파일 metadata를 사용한다. 별도 Python tar 추출의 `filter=data`는 group write를 제거하므로 GNU tar staging과 Git tree/내용이 같아도 COPY 캐시가 달라질 수 있다. 캐시 재사용은 실제 build 로그로 확인하며 동일 tree만으로 단정하지 않는다. BuildKit의 자원 상한과 Docker daemon 이미지 적재의 자원 사용도 구분한다.

실행 중인 배포의 source mode를 바꾸지 않는다. 불필요한 build를 취소해야 한다면 정확한 소유 PID뿐 아니라 공식 script/controller와 BuildKit solve의 종료, 기존 앱/schema 및 instigator 복원을 확인한다. 그 뒤 Manager global lock→Transport release lock 순으로 확보하고 tracked 일반 파일의 hash·실행 비트·경로와 보호 파일 보존을 확인한 경우에만 metadata를 정리한다. 종료가 불명확하면 재시도와 겹치지 않는다.

아래 n150 절과 이전 계획의 당시 미완 항목은 역사다. 최신 수용 증거는
[운영 계약 검증](../reviews/2026-10-19-track2-runtime-contract.md)와
[ARM 관리자 번들 수용](../audits/2026-10-19-admin-bundle-acceptance.md)을 따른다.
ADR accepted 여부는 별도 증거 정산 후 표시한다.

## 과거 n150 운영 절차

1. n150에 `/home/digitie/apps/kor-travel-transport/.env.server14`를 만들고
   [`.env.server14.example`](../../.env.server14.example)의 실제 DB 비밀번호와 운영
   API key를 입력한다.
2. WSL 로컬 테스트와 `docker compose config`를 통과시킨다.
3. [`scripts/deploy-server14.sh`](../../scripts/deploy-server14.sh)를 실행한다. 이
   스크립트는 대상 host가 `192.168.1.14`이고 Compose project가 `kor-travel-transport`인지 먼저
   확인한 뒤 현재 Git `HEAD`를 candidate artifact로 만들어 n150의 `docker compose`만
   호출하며 다른 Compose project를 중지하지 않는다. 배포 직후 `/health.release_sha`가
   candidate SHA와 일치하는지도 확인한다. Dagster는 공용 제어 평면(Manager ADR-54)에 합류했다 —
   공용 daemon은 다른 프로젝트도 돌리므로 멈추지 않는다. 이미지 빌드 뒤 공용 webserver
   (`127.0.0.1:11002`)에 이 location(`kor-travel-transport`)의 진행 중 run과 code-server worker가 0이
   되기를 최대 30분 기다린 직후 교체한다. 그 사이 schedule이 새 run을 띄우면 교체가 그 run을 끊고, 공용
   instance의 run monitoring이 실패로 닫는다(다음 tick이 다시 수집한다). 교체 뒤 code-server가 healthy이고
   공용 webserver가 location을 `RepositoryLocation`으로 다시 실어야 배포가 성공한다. 공용 plane이 아직
   location을 모르거나 옛 전용 daemon·webserver가 돌면 배포를 거부한다(합류는 아래 전환 절차로만 한다).
4. [migration.md](migration.md)의 prewarm → final delta → 180초 scheduler와 300초 이내 cutover 검증을
   완료한다.
   브라우저 live E2E 뒤 n150에서
   `python3 scripts/verify-dagster-workers-server14.py`를 실행해 GraphQL의
   `STARTED` run과 code-server의 실제 worker 프로세스, 앱의 `running`
   `collection_runs`와 Dagster 활성 job·시작 시각을 대조한다. 이 검사는
   읽기 전용이고 짧은 시작 경합을 재시도한 뒤에도 worker가 없거나 앱
   수집 실행에 대응하는 Dagster run이 없으면 실패한다. 앱 `collection_runs`의
   성공만으로 Dagster 실행 종료를 증명하지 않는다. 역방향으로 Dagster
   실행 기록 없이 남은 code-server worker도 실패로 보고한다.
5. release 이미지 보존: 배포마다 `kor-travel-transport-backend:rel-<sha12>` 태그가 남는다(ADR-010).
   n150에서 하나가 약 2.5 GB다. 지금 Dockerfile은 `pyproject.toml`·`uv.lock`만 먼저 복사해 의존성과
   playwright 층을 `COPY backend` 앞에서 만들므로 lock이 같으면 그 층은 release 사이에 재사용된다(#129 전에는
   `COPY backend`가 `pip install` 앞이라 release마다 따로였다). `docker image prune`은 태그가 붙은 이미지를 지우지 않는다. 배포가 health를
   통과한 뒤 지금 release와 바로 전 release(되돌릴 이미지)만 남기고 나머지 `rel-*`를 지운다. 운영 식별자
   개명 cutover의 관찰 기간에는 지우지 않는다. 배포 스크립트가 자동으로 지우지 않는 것은 다른 세션의
   되돌리기가 쓰는 태그를 지울 수 있어서다.

   ```bash
   docker inspect -f '{{.Config.Image}}' kor-travel-transport-backend-1        # 지금 release
   docker image ls kor-travel-transport-backend --format '{{.CreatedAt}}  {{.Tag}}' | sort -r
   docker image rm kor-travel-transport-backend:rel-<지울 sha12>   # 지금·바로 전 밖만. -f는 쓰지 않는다
   ```

2026-09-30 운영 메모: Manager의 `db-backup create transport --timeout 600`이 시간 초과로
실패했는데, 그 뒤 `pg_dump` 자식 프로세스가 삭제된 임시 dump에 계속 쓰며 n150 디스크를
포화시켰다. 백업 실패 뒤에는 성공으로 간주하지 말고 해당 실행의 자식 프로세스가
남았는지 확인한다. 이번에는 식별된 고아 프로세스만 종료하고 기존 앱 DB 백업의
SHA-256을 확인했다. Dagster DB는 별도 새 백업을 만들었다. 배포 동기화가 SSH 종료로
끊기더라도 현재 `.release-sha`와 `.transport-admin-release-sha`를 보존하도록 했다.
이 SHA-256 검사는 파일 무결성만 확인하며, 복원 성공이나 배포 직전 데이터 보존을
입증하지 않는다. 이번 릴리스에는 DB migration이 없었다.
공유 checkout의 backend 또는 관리자 소스 동기화는 시작 전에 `.staged-release-sha`를
무효화한다. backend 전체 동기화가
끝난 뒤에만 이를 새 SHA로 발행한다. 이 두 경로와 수동 원격 배포는 공통
`/home/digitie/apps/.kor-travel-transport-deploy.lock`을 복사·빌드가 끝날 때까지
유지하며, 경합하면 대기하지 않고 실패한다.
원격 배포
단계는 이 stage 완료 표식까지 검사한다. 관리자 동기화 뒤 수동 backend 원격 배포가
필요하면 `deploy-server14.sh`로 동일 후보를 다시 stage해야 한다.

공용 DB 최초 cutover는 일반 배포와 달랐다(완료). 먼저 WSL checkout에서
`DEPLOY_STAGE_ONLY=true ./scripts/deploy-server14.sh`로 reviewed artifact만 n150에 올린 뒤,
n150에서 `scripts/cutover-shared-db-server14.sh`를 실행했다. 이 한 번짜리 스크립트는 ADR-011로
지웠다(재현은 `git show 07d3848:scripts/cutover-shared-db-server14.sh`). cutover는 staged artifact의
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

### 최신 유가 테이블(0022) 배포 뒤 1회

0022는 `fuel_latest_prices` materialized view를 증분 테이블로 바꾸고 migration 안에서 한 번 채운다.
`deploy-server14.sh`는 daemon을 멈추고 활성 실행을 비운 뒤 교체하므로 보통은 빈틈이 없다. 그래도 드레인을
건너뛴 수동 반영이나 혼합 릴리스 창에서는 옛 Dagster 코드가 (1) 지워진 view를 refresh하려다 실패하고
(2) 그 전에 커밋한 유가 행이 새 테이블에 반영되지 않아 다음 오피넷 수집(최대 약 8시간)까지 빠질 수 있다.
배포가 health를 통과한 뒤 아래를 실행한다. 단조 upsert라 수집과 겹쳐도 안전하고 다시 실행해도 같다.

```bash
# n150. 먼저 읽기 전용으로 어긋난 (주유소, 유종) 수를 본다.
docker exec kor-travel-transport-backend-1 python scripts/backfill-fuel-latest-prices.py
# 0이 아니면 반영한다(남은 어긋남 0이어야 exit 0).
docker exec kor-travel-transport-backend-1 python scripts/backfill-fuel-latest-prices.py --apply
```

`--apply`는 전 이력 upsert를 한 트랜잭션으로 돌려(statement timeout 15분) `fuel_latest_prices` 행 잠금을
끝날 때까지 쥔다. **오피넷 수집 시각(KST 00·08·16시, 약 35분 소요)을 피해서** 돌린다 — 겹치면 수집기의
증분 upsert가 같은 행 잠금을 기다리다 앱 `statement_timeout`(60초)에 걸려 그 수집이 실패할 수 있다(다음 수집이
회복한다). 읽기 전용 점검은 잠금을 잡지 않는다.

### 공용 Dagster 제어 평면 합류(1회)와 그 뒤

2026-10 transport는 Manager의 공용 Dagster 제어 평면(ADR-54)에 합류했다. 옛 전용 webserver·daemon·
gateway와 `dagster-migrate`는 `profiles: [legacy-dagster]`로 내려갔고, 옛 Dagster 세 서비스만 다시 만들던
`scripts/redeploy-dagster-services-server14.sh`는 지웠다(되살리면 공용 daemon 옆에 옛 daemon을 띄운다).
합류 전환·되돌리기 절차와 계약은 [shared-db-dagster.md](../architecture/shared-db-dagster.md)의
"공용 Dagster 제어 평면" 절이 정본이다. 요약:

0. 사전: 운영 DB가 이 release의 Alembic head에 있어야 한다(전환은 migrate를 돌리지 않는다 — prepare가 확인하고
   거부한다). 합류 release에 새 migration이 있으면 합류 전 release로 먼저 일반 배포한다. `.env.server14`에
   `KOR_TRAVEL_DAGSTER_SHARED_APP_PASSWORD`를 더하고, `TRANSPORT_DAGSTER_INTERNAL_URL`이 있으면 지우거나
   `http://127.0.0.1:11002`로 바꾼다(운영 UI 배포 preflight가 그 밖의 값을 거부한다).
1. WSL(머지된 main): `DEPLOY_MODE=prepare-shared-dagster-cutover ./scripts/deploy-server14.sh` — stage·이미지
   빌드만 하고(이미지의 dagster가 공용 plane과 다르면, DB가 head가 아니면 거부) `.env.server14.shared-dagster-cutover`
   (0600, 전환이 쓸 env)를 남긴다. 컨테이너는 그대로다.
2. n150 root: Manager 전환 release를 설치한 직후
   `systemd-run --unit=dagster-cutover-transport --collect -E EXTERNAL_ENV_FILE=/home/digitie/apps/kor-travel-transport/.env.server14.shared-dagster-cutover /opt/kor-travel-docker-manager/scripts/dagster-shared-cutover.sh transport forward <manager-sha>`.
3. WSL: `./scripts/deploy-server14.sh`(일반 배포 — backend·frontend를 같은 release로 맞춘다), 이어서 **바로**
   `./scripts/deploy-transport-admin-server14.sh`(공용 webserver를 부르는 운영 UI, 옛 12302 gateway 제거 — 그
   전까지 옛 UI의 Dagster 화면은 지워진 14004를 불러 실패한다).
4. 운영 UI 배포 직후 `.env.server14.shared-dagster-cutover`(운영 비밀 전체의 사본)를 `shred -u`로 지운다. 되돌리기는
   지원하지 않는다(보장 없는 수동 best-effort).

이후 Dagster 정의·healthcheck가 바뀌는 반영도 일반 배포 하나로 한다(code-server만 Dagster 프로세스다).

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

## 백엔드 내부 식별자 개명 배포 (ADR-011)

[ADR-011](../adr/011-backend-internal-identity-transport.md) release는 DB schema를 바꾸지 않는다.
바뀌는 운영 효과는 백업 dump 파일 이름 접두어 하나다: 앱은 `kor-travel-transport-<UTC>Z*.dump`만
목록·다운로드·복원·보존 개수에 넣고, 옛 `parking-radar-*.dump`는 보지 않는다. 그래서 배포 직후
기존 파일 이름을 바꾼다. 비밀값은 출력하지 않는다.

1. 복원 지점: `/home/digitie/backups/transport.log`의 마지막 Manager standalone 백업이 90시간 안인지
   본다. 오래됐으면 crontab의 `run-standalone-backup.sh transport 3` 줄을 손으로 한 번 돌린다.
2. 평소처럼 `scripts/deploy-server14.sh`로 머지 SHA를 배포한다(마이그레이션 없음).
3. 배포 직후 앱 백업 디렉터리(`/home/digitie/apps/kor-travel-transport/backups`, root 소유)에서
   이름을 바꾼다. `mv -n`이라 같은 이름이 있으면 덮지 않는다.

   ```bash
   cd /home/digitie/apps/kor-travel-transport/backups
   sudo ls -la -- parking-radar-*.dump .parking-radar-* 2>/dev/null   # 바꿀 대상 확인
   for f in parking-radar-*.dump; do [ -e "$f" ] || continue
     sudo mv -n -- "$f" "kor-travel-transport-${f#parking-radar-}"; done
   sudo ls -- parking-radar-*.dump 2>/dev/null && echo "STOP: 남은 옛 이름이 있다"
   ```

   `.parking-radar-*`(점으로 시작)는 끝나지 않은 업로드·백업의 staging 파일이다. 새 코드는 이
   접두어를 청소하지 않으므로 1시간보다 오래된 것은 `sudo rm --`로 지운다.
4. 관리 UI 백업 목록(또는 관리 인증으로 `GET /v1/admin/backups`)에 옮긴 파일이 보이는지 본다.

되돌리기: 이전 `kor-travel-transport-backend:rel-<sha12>`로 다시 배포하고, 같은 디렉터리에서
`for f in kor-travel-transport-*.dump; do sudo mv -n -- "$f" "parking-radar-${f#kor-travel-transport-}"; done`.

## 운영 식별자 개명 cutover (ADR-010)

> 완료된 기록이다(2026-09-28 cutover). 실행 스크립트와 그 테스트는 ADR-011로 지웠다. 아래 명령을
> 다시 봐야 하면 `git show 07d3848:scripts/rename-deploy-identity-server14.sh`로 꺼낸다.

n150의 배포 식별자를 `kor-travel-airport`에서 `kor-travel-transport`로 옮기는 한 번짜리 절차다.
결정과 이름 목록은 [ADR-010](../adr/010-deploy-identity-rename-transport.md)이 정본이다. 실행은
`scripts/rename-deploy-identity-server14.sh`(ADR-011로 삭제, `07d3848`에서 꺼낼 수 있다)가 맡았고,
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
  revision에서 실패한다. 이 머지 커밋을 R(40자리)이라 한다. main이 움직여 다시 rebase했으면 새 머지
  커밋이 R이다. rebase 전 SHA나 브랜치 head를 R로 쓰지 않는다(모든 단계에 같은 R).
- **n150 freeze: R 머지부터 `finish`까지**(2026-09-28 계획: 약 10:30Z~13:30Z). 다른 세션에 미리 알린다.
  - transport·관리 UI 배포를 하지 않는다. 옛 디렉터리의 배포·재시작·`.env.server14` 편집도 하지 않는다.
    #44 세션의 미추적 worker 스크립트는 옛 이름을 쓰므로 창 뒤에 돌리지 않는다. (#47 뒤로 잡혀 있던
    parking-radar DB 이전은 #48에서 이미 공용 PostgreSQL을 쓰는 것으로 확인돼 할 일이 없다.)
  - Map·Manager 빌드·재구축·rebind를 하지 않는다(창 뒤 Manager 개명 release 설치만 예외).
  - 정리 단계까지 `docker system prune`·`docker image prune`·`docker builder prune`을 하지 않는다(아래).
  - 이유: 관리 UI는 #46의 `cda9a4d83c3d`가 아니라 #47 head `1db261e`를 손으로 올린 `4580a5ca3c61`
    (`local/transport-weather-ui:runtime`, 2026-09-28 07:24Z, 옛 디렉터리의 관리 project)로 돈다.
    `transport-api-gateway`·관리 `transport-dagster-gateway`는 다시 만들지 않았다. 지금은 두 빌드
    서비스 모두 `:latest`가 실행 중 이미지와 같아 `admin`이 통과한다. 그 사이 누가 관리 UI를 다시
    올리면 `:latest`가 달라져 `admin`이 STOP이고, 다른 빌드는 창을 디스크 대기로 늘리고, prune은
    rollback 태그를 지운다(2026-09-28 08:10Z 빌드 캐시 51.9 GB 중 35.9 GB 회수 가능).
  - `prebuild`·`window`는 빌드 프로세스(`docker compose … build`, `… up -d --build`, `docker build`,
    `docker image build`, `docker-buildx`)가 보이면 STOP이다. 두 단계 직전에 손으로도 본다.

    ```bash
    pgrep -fa '[d]ocker-buildx|docker( image)? build|compose .*[[:space:]](build|--build)([[:space:]]|$)' || echo "빌드 없음"
    ```
- Manager의 `chore/retire-dedicated-postgres` release는 창 전에 따로 설치·검증한다. Manager 개명
  release(target `transport`)는 CI를 통과해 두고, 창이 끝난 뒤 설치한다.
- 창 전에 에이전트 공용 메모(n150 상시 서비스 목록)의 `kor-travel-airport`를 `kor-travel-transport`로
  고친다. 옛 메모를 읽은 에이전트가 옛 컨테이너를 되살리지 않게 한다. 같은 메모에 "정리 단계까지
  n150에서 `docker system prune`·`docker image prune`·`docker builder prune`을 하지 않는다"를 적는다
  (2026-09-28 08:35Z 고쳤다: 메모 본문과 색인 줄, freeze, `docker compose -p kor-travel-airport up` 금지,
  ADR-010 포인터).
  관찰 기간의 되돌리기 재료(멈춘 `*-retired-<날짜>` 컨테이너, 멈춘 컨테이너만 쓰는
  `kor-travel-airport-rollback:*`·`:pre-rename` 태그)는 Docker가 보기에 "안 쓰는" 것이라
  `prune --all`이 지운다. 설치된 Manager의 디스크 카드는 회수 가능 공간이 20 GiB를 넘으면
  `sudo -n docker system prune --all --volumes`를 다음 조치로 보여 주고, n150은 이미 그 선을 넘었다
  (2026-09-28 08:10Z: 이미지 22.2 GB, 빌드 캐시 35.9 GB 회수 가능). 그 안내를 따르면 `rollback`이
  "rollback 태그가 없다"로 멈추고 앞으로 고치는 것만 남는다. 창 전 재빌드도 캐시가 비어 길어진다.
- 다른 세션의 이미지 빌드(`docker compose … build`, `… up -d --build`, `buildx bake`)가 돌지 않는다.
  n150 부하는 디스크 대기라 겹치면 창이 길어진다. `prebuild`와 `window`는 빌드 프로세스가 보이면 STOP이다.
- 공용 PostgreSQL prewarm(소유자 요구: 모든 DB에 prewarm이 필요하다)은 이 창 밖의 Manager 변경이다.
  2026-09-28 확인: `kor-travel-shared-postgres`(PostgreSQL 16.9, `postgres` 포함 DB 10개, 합계 약 71 GB,
  `kor_travel_transport` 14 GB·`kor_travel_transport_dagster` 117 MB)는 `shared_preload_libraries=
  pg_stat_statements`와 `shared_buffers=128MB`뿐이다. `pg_prewarm.*` 설정과 autoprewarm worker가 없고
  transport 두 DB에는 `plpgsql`만 있다(이미지에 `pg_prewarm` 1.2는 있다). autoprewarm은 instance
  전체의 shared buffer 목록을 저장해 재시작 때 다시 읽으므로 한 번 켜면 모든 DB에 걸린다. 다만
  되살리는 양은 `shared_buffers`가 한도라 128 MB로는 거의 없다(n150 RAM 15 GiB). 그래서
  `shared_preload_libraries`에 `pg_prewarm`, `pg_prewarm.autoprewarm=on`, `shared_buffers` 크기를 함께
  정한다. 10개 DB를 쓰는 instance를 재시작하므로 이 cutover 창에 넣지 않고 따로 창을 잡는다. cutover는
  PostgreSQL을 재시작하지 않으므로 prewarm이 없어서 나빠지는 것은 없다. 창 전에 해야 하면 `prepare`
  전에 하고, 그 뒤 `prepare`를 다시 실행해(창 전이면 다시 실행해도 된다) 조건을 다시 본다.

### 타이밍

n150 시계는 UTC이고 Dagster schedule은 `Asia/Seoul`이다(`backend/app/dagster/definitions.py`).

| 작업 | KST | UTC | 비고 |
|---|---|---|---|
| 공항 주차·고속도로 수집 | 5분마다 | 5분마다 | 고속도로 run이 17분까지 걸린 적이 있다 |
| KRIC 시간표 | 매시 정각 | 매시 정각 | 48시간 guard라 대부분 곧 끝난다 |
| 유가 | 00:00·08:00·16:00 | 15:00·23:00·07:00 | 09-21~28 성공 run 0~52분(00:00·08:00 KST 회차가 길다), 09-25 16:00 KST 회차는 `max_runtime_seconds` 4시간에서 실패 |
| 배편 시간표 | 00:45부터 4시간마다 | 15:45부터 4시간마다 | 04:45·08:45·12:45·16:45·20:45 KST. #44 배포(09-28) 뒤 약 10분, 그 전 140분 |
| 철도·항구 기준정보 | 03:00(항구는 3일마다) | 18:00 | |
| 버스 기준정보 | 03:30 | 18:30 | |
| 옛 transport 백업 cron | 03:00, 3일마다 | 18:00 | `finish`가 지운다 |
| Manager standalone 백업(geo_dagster·concierge·pinvi) | 12:15~12:55 | 03:15~03:55 | 디스크 I/O가 크다 |
| Manager transport_dagster 백업 | 01:50 | 16:50 | 매일, dump 4 MB |
| Manager transport 백업 | 02:15, 3일마다 | 17:15(UTC 1·4·…·28·31일) | 785 MB custom dump 약 8분(09-28 06:55Z 실측 467초). 09-28이 해당일 |

- `window`는 옛 daemon을 멈춘 뒤 `STARTED`·`STARTING`·`CANCELING` run이 0이 되기를 기다린다(기본
  상한 1800초). 유가 run은 52분까지 걸렸으므로 유가·배편 run이 돌고 있으면 창을 열지 않는다(Dagster
  UI에서 먼저 본다). 권장 시작은 KST 10:05~11:30 (UTC 01:05~02:30, 08:00 유가와 08:45 배편이 끝났는지
  먼저 본다) 또는 KST 21:30~23:00(UTC 12:30~14:00)이다. 뒤쪽 창은 16:50·17:15·18:00 UTC 백업보다
  앞서 `finish`까지 끝낸다.
- `QUEUED` run은 기다리지 않는다. 같은 metadata DB라 새 daemon이 이어서 꺼낸다. schedule마다 놓치는
  tick은 많아야 하나다.
- daemon이 멈춘 동안에는 run monitoring도 돌지 않아 `STARTING`에 남은 run은 스스로 끝나지 않는다.
  대기가 상한에 닿으면 스크립트가 옛 daemon을 다시 띄우고 멈춘다. 되살아난 daemon이
  `start_timeout_seconds`(300초)가 지난 `STARTING` run을 실패로 정리하므로 5분 이상 지난 뒤 다시
  연다. `STARTED`로 끼인 run은 Dagster UI에서 원인을 본 뒤 종료한다(종료 요청이 60초 안에 돌아오지
  않으면 code-server가 막힌 것이다. 2026-09-27 사례).
- `restore-point`는 `kor_travel_transport`(디스크 14 GB)를 custom format으로 dump한다. 2026-09-28
  06:55~07:03Z Manager 백업의 같은 dump가 785 MB, 467초(약 8분)였다. Dagster DB(117 MB)는 1분 안이다.
  dump는 14 GB를 읽으며 OS page cache를 흔든다(PostgreSQL은 재시작하지 않는다). Manager 백업
  시간(위 표)과 겹치지 않게 창 전에 돌린다.

### 단계

스크립트는 R 체크아웃에서 n150으로 옮겨 tmux 안에서 실행한다. SSH가 끊겨도 `window`는 옛 스택을
되살리지만, 창을 끝까지 보려면 tmux가 필요하다. 스크립트는 대상 경로·URL(`OLD_DIR`·`NEW_DIR`·작업
디렉터리·`API_URL` 등)을 셸 env에서 받지 않는다. tmux 셸에 남은 같은 이름의 export는 무시된다. env로
바꿀 수 있는 것은 대기 상한(`DRAIN_TIMEOUT_SECONDS` 등)과 `PG_CLIENT_IMAGE`·`SHARED_PG_CONTAINER`뿐이다.

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
   (`POST /v1/admin/backups`)은 기본 120초 제한에 약 8분 걸리는 dump가 끝나지 않으므로 쓰지 않는다.
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
   snapshotter다). backend 이미지는 `uv export --locked --extra dev`로 `uv.lock`을 requirements로 뽑아
   `pip install --no-deps`로 설치하고, 프로젝트 자체만 마지막에 `pip install -e ".[dev]" --no-deps`로 올린다.
   그래서 이미지의 Dagster는 `uv.lock`의 버전이다(#129 전에는 `pip install -e ".[dev]"`가 의존성까지 풀어
   빌드할 때의 PyPI 최신을 받았다 — 2026-09-28: `uv.lock`·CI 1.13.23, 운영 code-server 1.13.24). gate는
   여전히 소스가 아니라 빌드 결과에 건다. 버전이 다르면 아래 "Dagster 버전이 다를 때"를 따른다.
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

`prebuild`나 `window`가 `dagster 버전이 다르다(운영 X, 빌드 Y)`로 멈추면
`uv.lock`의 Dagster가 운영 code-server와 다른 것이다. backend Dockerfile은 `uv export --locked`로
`uv.lock`을 그대로 설치하므로(#129 이후) 이미지의 Dagster는 lock 버전이다. 대개 lock을 올린 PR이 원인이다. gate를 끄거나 태그를
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

Dockerfile은 #129부터 `uv.lock`을 따른다. 그래도 lock과 운영 `:code`가 어긋나는 것은 이 gate만 잡는다.

### 되돌리기

72시간 관찰이 끝나 정리하기 전까지는 `bash ~/rename-deploy-identity-server14.sh rollback`으로
되돌린다. 되돌릴 cutover가 없으면(옛 여섯 서비스가 돌고, 새 project는 떠 있지 않고, env fence·은퇴
디렉터리가 없음. 예: `prepare`만 한 상태) STOP이다. 옛 디렉터리 자리에 빈 디렉터리가 다시
생겼으면(옛 배포 스크립트의 `mkdir -p`, 옛 backend bind가 만든 빈 `backups/`) 지운 뒤 `mv -T`로
되돌리고, 그 밖의 내용이 있으면 아무것도 멈추기 전에 STOP이다.

먼저 새 daemon을 멈추고 창처럼 `STARTED`·`STARTING`·`CANCELING` run이 0이 되기를 기다린다(같은
`DRAIN_TIMEOUT_SECONDS` 상한). 새 code-server를 멈추면 실행 중인 유가(Playwright, 상한 4시간)·배편 run이
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
역할(#430)은 창 전에 설치됐다(digitie crontab: `transport_dagster` 매일 16:50Z, `transport` 3일마다
17:15Z, `~/backups/transport*/`). 창 뒤 첫 정기 dump가 생긴 것을 확인하기 전에는 `restore-point` dump를
지우지 않는다.

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

legacy volume `parking-radar_parking_radar_postgres_data`는 n150에 없다(2026-10-02 확인).
`deploy-server14-remote.sh`의 임시 개명 guard와 그 테스트는 ADR-011에서 지웠다. 그 뒤로 쌓이는
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

운영 데이터는 공용 PostgreSQL로 옮겨 이 스택은 쉬고 있다. volume 이름은 ADR-011에서
`kor-travel-transport_postgres_data`로 바꿨다(옛 `parking-radar_parking_radar_postgres_data`는 n150에
없다). 다른 호스트에 옛 볼륨이 있으면 이름으로 이어 붙이지 말고 dump/restore로 옮긴다.

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

## odroid 배포 계획(ADR-014 proposed, 미구현)

[ADR-014](../adr/014-odroid-host-and-deploy-host-flag.md)·Manager ADR-58(proposed)에 따라 transport 스택 전체
(backend·frontend·code-server·transport-admin·gateway, 그리고 odroid 로컬 PG `kor_travel_transport`·RustFS·공용 plane)를
odroid `192.168.1.13`에서 운영한다. 포트·compose project(`kor-travel-transport`, `kor-travel-transport-admin`)·앱 디렉터리
`/home/digitie/apps/kor-travel-transport`는 n150과 같고 호스트만 바뀐다. **아래 명령·파일명(`deploy-prod.sh`, `.env.prod`)은
T-TRN-01이 만들기 전까지 존재하지 않는다.** 단계 번호(4a/4b/5·해체 11)는 Track 2 설계 최종본 §11.2·§11.5의 것이고, 저장소 안
정본은 Manager 런북 `docs/prod-deployment.md` §9(§9.2 플립 PR 배포 절차·§9.5 검증 체크리스트·§9.6 n150 해체 — Manager Track 2 문서
PR에 수록, 머지 예정)다. Manager ADR-58 본문은 절차를 그 런북에 위임하므로 "ADR-58 §11.x"라는 절은 없다.

### 전제(odroid 쪽, Manager 런북이 정본)

- odroid 초기화 완료: 2026-10-13 03:4xZ 기준 **완료** = WSL 직접 ssh(키)·NOPASSWD sudo(`sudo -n` 동작)·docker 그룹·NTP 수동
  동기(시계 2026). **미완** = timesyncd 부팅 순서 사이클 drop-in(재부팅 뒤 재발 가능), `docker compose` v2·buildx 설치, 방화벽,
  NVMe 디렉터리 트리·fstab bind, swapfile. 미완 항목은 Manager `docs/prod-deployment.md` §9.1(T-OPS-01)이 맡고, 이 런북은 **재검사하지
  않고 Manager §9.5 체크리스트의 해당 행이 PASS로 기록돼 있는지만 본다** — 효과가 오늘의 수동 상태로도 초록이 되는 검사는 쓰지
  않는다: NTP는 "재부팅 2회마다 `systemctl show systemd-timesyncd -p ConditionTimestamp`가 비어 있지 않음 ∧ synchronized yes ∧
  `/var/lib/systemd/timesync/clock` mtime 갱신"(§9.5 NTP 행 — `timedatectl`의 `synchronized: yes` 하나는 2026-10-13 수동
  `set-ntp true` 상태로도 통과하므로 **그것만으로는 통과시키지 않는다**); compose는 "Manager compose `docker compose config` 렌더
  성공"(§9.1-5·§9.5 compose 행 — 버전 문자열이 아니다); 디스크는 `swapon --show`에 `/mnt/media/kor-travel/swapfile` 4 G ∧
  `findmnt -T /home/digitie/kor-travel-shared-data/pgdata -o SOURCE`가 NVMe 장치(§9.5 디스크 행); 주소는 `ip -4 addr show eth0`에
  `192.168.1.13/24` ∧ §9.5 "DHCP 임대 갱신 뒤에도 `.13` 유지" 행 PASS(OPNsense 예약 — 설계 §14-20 소유자 결정; 이 절의 `.13`
  리터럴 전부의 전제).
- odroid Manager 설치(현지 arm64 wheelhouse) → `ensure dagster`(**PG 11000 포함**, 빈 workspace plane healthy) → 롤 bootstrap
  (`kor_travel_transport` / `kor_travel_transport_app`; `kor_travel_transport_dagster`는 **만들지 않는다**) → `ensure storage`
  (RustFS 12101, 버킷 `kor-travel-transport-raw`) → `ensure cadv`.
- `.env.prod`(101 키 — head `eb40e3b` `.env.server14.example`의 `KEY=` 줄 수) 반입: **시작점은 n150 실파일 `.env.server14`**(예시
  파일 `.env.server14.example:19`의 `BACKEND_INTERNAL_URL=http://backend:8000`은 원격 검사 `scripts/deploy-server14-remote.sh:71`의
  `http://127.0.0.1:14001`과 어긋난다 — T-TRN-02가 고친다)를 복사해 아래 네 값을 바꾸고, **호스트별 비밀 두 쌍은 odroid Manager
  root `.env`에서 가져온다**(표 아래 두 행). **소유·권한은 n150과 같이 `digitie:digitie 0600`**(ADR-014 결정 1 — 원격 단계가 digitie로
  `source`·`awk`·`docker compose --env-file`을 돌린다: `scripts/deploy-server14-remote.sh:43-44`, `:91`, `:121`; 운영 UI
  `scripts/deploy-transport-admin-server14.sh:23-51`, `:114`; 토큰 `scripts/set-transport-admin-write-token.py:14`, `:41-48`).
  root 0600으로 두면 4b의 `source` 단계가 권한 오류로 멈춘다. 대가: Samba `[homes]` 공유 루트가 `/home/digitie`라 digitie SMB
  자격으로 읽힌다 — ADR-014 결과(부정)·열린 결정 A(소유자). 비밀번호 SSH 단계에서는 보내지 않는다.

| 키 | n150 값 | odroid 값 | 규칙 |
|---|---|---|---|
| `TRUSTED_HOSTS_CSV` | `192.168.1.14,pr…,pr-api…,localhost,127.0.0.1,testserver,backend` | `192.168.1.13,…`(나머지 동일) | LAN 항목 = 배포 host addr |
| `CORS_ORIGINS_CSV` | `http://192.168.1.14:14002,https://pr…,https://pr-api…` | `http://192.168.1.13:14002,…` | 같음 |
| `SERVICE_EXPORT_ALLOWED_CLIENTS_CSV` | `127.0.0.1/32,::1/128` | `127.0.0.1/32,::1/128,192.168.1.14/32` | Map code-server가 n150에서 LAN peer로 부른다 |
| `NEXT_PUBLIC_TRANSPORT_DAGSTER_URL`(T-TRN-02 신설 build arg) | (없음 — 코드 기본 `https://dagster.digitie.mywire.org`) | odroid plane 공개 host(Manager ADR-58 "열린 결정" 4 — 소유자) | 운영 UI 재build |
| `KOR_TRAVEL_DAGSTER_SHARED_APP_PASSWORD`(`.env.server14.example:12`) | n150 Manager `.env`의 값 | **odroid Manager root `.env`의 같은 키**(호스트별 발급; n150과 같게 할지는 소유자) | compose가 이 값으로 `KOR_TRAVEL_DAGSTER_SHARED_PG_URL`(`docker-compose.shared.yml:28`, loopback 리터럴)을 만든다 — 틀리면 code-server가 healthy가 되지 않아 배포가 exit |
| `RUSTFS_ACCESS_KEY_ID`·`RUSTFS_SECRET_ACCESS_KEY`(`:62-63`) | n150 RustFS 키 | **odroid Manager `.env`의 RustFS 키** | 틀리면 KRIC XLSX 업로드 403 |
| `DATABASE_URL`·`DAGSTER_POSTGRES_URL`·`RUSTFS_ENDPOINT_URL`·`BACKEND_INTERNAL_URL`·`TRANSPORT_*_INTERNAL_URL` | loopback | **불변**(URL; 비밀번호 부분은 odroid 롤 bootstrap 값) | PG·RustFS·plane이 odroid 로컬 |

### 순서(설계 §11.2 = Manager `prod-deployment.md` §9.2: 4a → 4b → 5)

1. **4a(플립 PR, Manager)**: registry `transport: {host: odroid}` + 파생물(workspace ×2·compose 기본값 `.13:14001`·Prometheus
   타깃) 머지 → n150 Manager 재설치 → **n150 transport code-server `stop`**(수집 중지 = 공백 시작 — `SCHEDULER_MODE=dagster`라 cs가
   유일한 수집 프로세스; backend·frontend는 아직 둔다) → n150 `ensure dagster`(plane 재생성, map/pinvi/conc tick 공백 ≈2 min) →
   odroid Manager 같은 sha 재설치 → odroid root `.env` workspace digest 갱신 → `ktdctl targets validate` → **odroid `ensure dagster`**
   (플립 PR workspace 반영 — webserver가 location `kor-travel-transport`를 **load error 상태로 싣는다**; code-server는 아직 없다.
   ADR-014 결정 10·B10: 원격 배포 단계는 webserver workspace에 이 location이 없으면(`absent`) `scripts/deploy-server14-remote.sh:222-226`에서
   exit 2이므로 이 단계가 4b보다 **앞**이어야 한다. Manager §9.2 ②는 아직 이 순서를 적지 않았다 — Manager 쪽 전달 사항, T-TRN-04 대조).
   효과: odroid `curl 127.0.0.1:11002/graphql`의 workspace에 `kor-travel-transport` 항목이 있고 typename이 `RepositoryLocation`이
   아닌 load error(`PythonError` 류)다 — T-TRN-01이 첫 배포에서 그 값을 기록한다.
2. **4b(이 저장소)**: 전제 — T-TRN-03a(금지 문구 교체)가 머지돼 있어야 한다(아니면 `AGENTS.md`·`SKILL.md`·`CLAUDE.md`가 이 단계를
   금지한다). n150 또는 WSL에서, tmux/nohup 아래
   ```bash
   ./scripts/deploy-prod.sh --host 192.168.1.13                  # T-TRN-01 뒤에만 존재
   ./scripts/deploy-transport-admin-prod.sh --host 192.168.1.13  # 같은 T, 운영 UI(12301/12305) — Dagster 링크 build arg 포함
   ```
   효과 검사(두 스크립트가 한다, 거부 = exit 2): 원격 IPv4 집합 ∋ `192.168.1.13` ∧ Manager 설치됨 ∧
   `sudo -n ktdctl targets validate --json`에서 `k = targets.transport.host`(hosts **키**, 예 `odroid` — `host:`를 생략한 default
   target에서도 resolve된 키가 실린다, 비어 있으면 거부)를 읽어 `hosts.<k>.addr == "192.168.1.13"`(두 스크립트 모두 같은 키;
   registry에 `transport-admin` target은 없다; `hosts` 필드 부재·키 없음도 거부 — Manager T-MGR-01a 출력 계약, ADR-014 "후속") ∧
   `.env.prod`를 호출 사용자(digitie)가 읽을 수 있음 ∧ 이미지 dagster 버전 == odroid plane 버전(기존 검사 그대로) ∧ odroid webserver
   workspace에 location 있음(4a 마지막 단계의 결과 — 기존 가드 `remote.sh:222-226` 그대로). 이어서 fresh `migrate`(Alembic head) →
   backend·frontend·code-server 기동 → webserver가 code-server를 다시 로드해 `RepositoryLocation`(`wait_location_loaded`, 최대 3분 —
   ADR-014 결정 10 전제 ②; 안 되면 odroid `ensure dagster` 1회로 webserver 재생성 뒤 재시도) → 운영 UI 배포. **첫 빌드 직후 Opinet
   Chromium headless smoke 1회(arm64)** — 실패면 `.env.prod`에 `OPINET_BROWSER_ENABLED=false`를 두고 진행한다(유가만 비활성;
   `TRANSPORT_COLLECTION_ENABLED=false`는 고속도로 수집까지 끄므로 쓰지 않는다 — ADR-014 결정 7·B9).
3. **참조 로드(쿼터 창)**: fresh DB이므로 KRIC 시간표(≤500회/48 h — `.env.server14.example:55-57`), 해상 기준정보(3일마다 03:00,
   run당 data.go.kr 요청 3건 — `backend/app/dagster/definitions.py:599`, `docs/architecture/shared-db-dagster.md` 수집 일정 표),
   휴게소 기준정보·유가(ADR-013), Opinet 유가(8시간 주기; 4b의 Chromium smoke가 통과한 경우만)가 각 schedule의 다음 tick에서
   채워진다. 1~2일 걸린다; 수동으로 앞당기지 않는다(한도).
4. **5(consumer 전환 — 공개 경로 먼저, 그 뒤 n150 stop → Map 게이트)**: n150 `ensure map`(transport URL `.13:14001` 기본값 반영,
   code-server 재생성 — Map은 HAProxy가 아니라 이 주소로 직접 부른다) → odroid `/health` 200·첫 5분 스냅샷 SUCCESS 확인 뒤
   **HAProxy(OPNsense) `pr`/`pr-api`/`transport`/`transport-api` backend → `.13:14002/14001/12305/12301`**(공개 경로 선전환; 공개
   `pr.`/`pr-api.` 4 host 200 확인) → **n150 transport backend·frontend stop** — n150 `/home/digitie/apps/kor-travel-transport`에서
   ```bash
   docker compose --project-name kor-travel-transport --env-file .env.server14 -f docker-compose.yml -f docker-compose.shared.yml stop backend frontend
   docker ps -a --filter name=kor-travel-transport-backend-1 --format '{{.Status}}'   # Exited …
   ```
   (원격 배포 스크립트의 `compose()` 모양 `scripts/deploy-server14-remote.sh:121`; 운영 UI project 12301/12305는 공개 host가 이미 `.13`이라
   그대로 둔다) → **Map export 1회 성공**을 n150 backend `Exited` 상태에서 확인(odroid access log peer `192.168.1.14`) → `pr2` host 제거
   (소유자 §14-2 미결 — ADR-014 가정) → n150 cron `run-standalone-backup.sh transport`를 odroid로 이동. 이 순서는 Manager §9.2 ④
   ("stop 상태에서 … 확인한 뒤 HAProxy")와 다르다 — `pr-api.`가 n150 backend로 가는 transport에서는 그 순서가 stop~전환 사이 공개 503을
   만들고, Map 게이트는 HAProxy와 무관하므로 선전환한다(ADR-014 결정 8, 설계 이탈 — Manager 쪽 전달). 대안을 택하면(§9.2 ④ 순서 유지)
   "n150 stop ~ HAProxy 전환" 사이 outage 창(Map export 다음 run까지, 분 단위)을 소유자가 수용한 것으로 적는다.
5. **해체(설계 §11.5 단계 11 = Manager `prod-deployment.md` §9.6)**: n150 transport 두 compose project `docker compose rm -sf <서비스 목록>`(bare `down` 금지 —
   map/pinvi/PG까지 내린다), 공용 PG `kor_travel_transport`·`kor_travel_transport_dagster` drop, 이미지 정리. 그 전까지는
   "n150 Manager 옛 sha 재설치 + code-server start(+ backend·frontend start, HAProxy `.14`로 복귀)"로 되돌릴 수 있는 상태를 유지한다.

### 게이트(효과 기반; 하나라도 빨강이면 다음 단계로 가지 않는다)

- [ ] 4a 끝: odroid webserver workspace에 `kor-travel-transport` 항목 존재(load error 상태; `absent`가 아님) — ADR-014 결정 10 전제 ①.
- [ ] odroid `/health`의 `release_sha` == 배포 SHA; code-server healthy(= `dagster_shared` 비밀번호가 맞다는 효과); odroid webserver가
      location `kor-travel-transport`를 `RepositoryLocation`으로 실음(결정 10 전제 ②); 12 schedule RUNNING; RustFS 버킷
      `kor-travel-transport-raw` 목록 조회가 odroid 키로 200(KRIC XLSX 업로드 경로).
- [ ] **같은 시각 run이 두 호스트에 0건**(n150 code-server stop 시각 ~ odroid 첫 tick 사이 n150 `collection_runs` 증가 0).
- [ ] 5분 스냅샷(공항·고속도로) 첫 run SUCCESS; 돌발 export `/v1/service/exports/highway-incidents/active`가 n150에서 200
      (토큰 + peer `.14`).
- [ ] HAProxy 4 host 전부 200(`.13` backend) — n150 stop **전**.
- [ ] n150 backend·frontend 컨테이너 `Exited` 상태에서 Map transport export 1 run 성공 + odroid access log peer `192.168.1.14`.
- [ ] NTP(odroid): Manager §9.5 NTP 행 PASS 기록(재부팅 2회 뒤 `ConditionTimestamp` 비어 있지 않음 ∧ synchronized yes) — 수동
      `set-ntp true` 상태의 `synchronized: yes`만으로는 통과시키지 않는다. Map의 돌발 ±30 min 시계 검사가 fail-closed라 재부팅 뒤
      시계가 틀리면 Map 적재가 거부된다.
- [ ] 주소: `ip -4 addr show eth0`에 `192.168.1.13/24` ∧ Manager §9.5 "임대 갱신 뒤 `.13` 유지" 행 PASS.
- [ ] Opinet Chromium headless smoke 1회(arm64) — 실패면 `OPINET_BROWSER_ENABLED=false`(유가만 비활성, 고속도로 수집은
      그대로)로 두고 다른 게이트는 진행; 그 사실을 T-TRN-04가 기록한다. `TRANSPORT_COLLECTION_ENABLED=false`로 두면 위의
      고속도로 스냅샷·돌발 export·Map export 게이트가 같이 비므로 그 fallback은 없다.
- [ ] 메모리(T-TRN-05 뒤): `docker inspect`의 `HostConfig.Memory`·`MemorySwap`이 다섯 서비스에서 같은 값(swap 0 효과); Opinet run
      ≥1회 포함 창에서 OOM-kill 0.
- [ ] `pr2` 404/제거(소유자 §14-2 미결 — ADR-014 가정).
- [ ] legacy 자산 삭제 조건(T-TRN-03b): 위 게이트 전부 초록 — 그 전까지 `docker-compose.odroid.yml`·`deploy/odroid/*`·
      `scripts/deploy-odroid.ps1`·`scripts/odroid-status.ps1`(ADR-014 결정 6의 집합 M; 그중 fail-closed 마커는
      `docker-compose.odroid.yml`·`deploy/odroid/remote-deploy.sh`·`scripts/deploy-odroid.ps1` 셋)는 그대로 둔다. (13번 금지 **문구**는
      이와 달리 4b **전**에 T-TRN-03a가 교체한다 — 소유자 §14-2 결정 직후.)

## Historical: 기존 13번/ODROID 설정 (실행 금지)

아래는 과거 SQLite/10분 운영의 참고 기록이며 현재 실행 절차가 아니다.
현재 Odroid 작업은 위 현재 정본 절·ADR-014를 따른다. legacy M6 삭제와 실제 서비스·볼륨의 은퇴는 구분한다.

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

- 현재 ODROID에서는 `8000` 포트를 Portainer가 사용 중이다. (과거 기록 — 2026-10-13 실측에서는 8000이 `parking-radar` uvicorn
  404이고 Portainer는 9443이다; ADR-014 B7.)
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

`.\scripts\deploy-odroid.ps1`는 실행 시 즉시 종료된다. 현재 운영에는 위 현재 정본 절·ADR-014 절차를 사용한다.

이 절은 당시 n150 배포의 역사적 기록이다. 현재 운영은 위 [현재 Odroid 정본](#현재-odroid-정본2026-10-19)과 scripts/deploy-prod.sh를 따른다.

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


## 공개 Dagster UI 링크 빌드 설정

`NEXT_PUBLIC_TRANSPORT_DAGSTER_URL`은 관리자 UI가 쓰는 공개 origin이다. 배포 env에서 이 값을 지정하면
`docker-compose.transport-admin.yml`이 Docker builder에 전달하고 Next 빌드에 포함한다. 미설정·빈 값은
기존 기본 공개 origin을 사용한다. 내부 GraphQL 주소와 admin token은 이 공개 변수에 넣지 않는다.
주소를 바꾸면 관리자 UI 이미지를 재빌드해야 하며 실행 중 컨테이너의 env만 바꿔서는 링크가 바뀌지 않는다.
최소 배포 인수 뒤 실제 로그인·Dagster 화면에서 링크 목적지를 확인하고 live gate를 남긴다.
