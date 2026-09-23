# 배포 및 실행

> 현재 기준 배포 대상은 `192.168.1.14`이며 Docker/PostgreSQL은 n150에서만 실행한다. 13번은 source API와 rollback 기준으로 읽기만 한다. 새 배포는 [migration.md](migration.md)와 [`scripts/deploy-server14.sh`](../../scripts/deploy-server14.sh)를 우선 사용한다. 이 문서의 기존 ODROID 절차는 historical reference다.

## n150 현재 운영 절차

1. n150에 `/home/digitie/apps/kor-travel-airport/.env.server14`를 만들고
   [`.env.server14.example`](../../.env.server14.example)의 실제 DB 비밀번호와 운영
   API key를 입력한다.
2. WSL 로컬 테스트와 `docker compose config`를 통과시킨다.
3. [`scripts/deploy-server14.sh`](../../scripts/deploy-server14.sh)를 실행한다. 이
   스크립트는 대상 host가 `192.168.1.14`이고 Compose project가 `kor-travel-airport`인지 먼저
   확인한 뒤 현재 Git `HEAD`를 candidate artifact로 만들어 n150의 `docker compose`만
   호출하며 다른 Compose project를 중지하지 않는다. 배포 직후 `/health.release_sha`가
   candidate SHA와 일치하는지도 확인한다.
4. [migration.md](migration.md)의 prewarm → final delta → 180초 scheduler와 300초 이내 cutover 검증을
   완료한다.

공용 DB 최초 cutover는 일반 배포와 다르다. 먼저 WSL checkout에서
`DEPLOY_STAGE_ONLY=true ./scripts/deploy-server14.sh`로 reviewed artifact만 n150에 올린 뒤,
n150에서 `scripts/cutover-shared-db-server14.sh`를 실행한다. cutover는 staged artifact의
receipt-gated remote deploy를 호출하므로 n150에 `.git`이 없어도 된다. `.env.server14.legacy`는
동기화 삭제 대상이 아니며 live E2E 수용 전까지 보존한다.

유가 수집처럼 transport backend와 Dagster 실행부만 갱신할 때는
[`scripts/deploy-transport-runtime-server14.sh`](../../scripts/deploy-transport-runtime-server14.sh)를
사용한다. 이 스크립트는 candidate image로 Alembic migration과 `head` revision을 먼저
확인한 뒤 `backend`, `dagster-code-server`, `dagster-webserver`, `dagster-daemon`만
`--no-deps`로 재생성한다. 기존 parking-radar frontend와 gateway는 대상에 포함하지 않는다.
완료 조건은 backend의 candidate `release_sha`와 세 Dagster 서비스의 `healthy` 상태이며,
어느 하나라도 `unhealthy` 또는 제한 시간 초과이면 성공으로 처리하지 않는다.

> **롤백 시 주의(T-035 이후)**: frontend만 이전 이미지로 되돌리고 PostgreSQL 상태는
> 그대로 유지하는 롤백을 하면, T-035 이후 추가된 `/analytics`·`/history`·`/fees`·`/backup`
> 라우트는 롤백된(라우트 분리 이전) 빌드에서 404가 된다. 그 사이 공유되거나 북마크된 딥링크는
> 롤백 창에서 깨질 수 있다는 것을 감안하고, 필요하면 롤백 공지에 "/"로 이동하라고 안내한다.

```bash
REMOTE_HOST=192.168.1.14 \
REMOTE_APP_DIR=/home/digitie/apps/kor-travel-airport \
./scripts/deploy-server14.sh
```

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

## PostgreSQL 별도 컨테이너 (T-032)

PostgreSQL은 `docker-compose.yml`(backend/frontend)이 아니라 `docker-compose.db.yml`에서
독립 lifecycle로 관리한다(`kor-travel-docker-manager`의 "DB는 앱과 분리된 컨테이너로
운영한다" 패턴을 단일 프로젝트 규모로 축소 적용). 두 스택은 외부 네트워크
`kor-travel-airport-net`으로 통신한다.

```bash
# DB 스택 (거의 재기동하지 않음 — 앱 배포와 무관한 lifecycle)
docker compose --project-name kor-travel-airport-db -f docker-compose.db.yml up -d

# 앱 스택 (배포마다 재빌드) — DB 스택이 먼저 떠 있어야 한다
docker compose --project-name kor-travel-airport -f docker-compose.yml up -d --build
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

DB 스택을 먼저 올려야 앱 스택이 연결할 `kor-travel-airport-net` 외부 네트워크가 생긴다(T-032).

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

- 운영용 compose: [docker-compose.odroid.yml](</F:/dev/kor-travel-airport/docker-compose.odroid.yml>)
- 운영용 환경 파일: [/.env.odroid](</F:/dev/kor-travel-airport/.env.odroid>)
- 로컬 배포 스크립트: [scripts/deploy-odroid.ps1](</F:/dev/kor-travel-airport/scripts/deploy-odroid.ps1>)
- 상태 확인 스크립트: [scripts/odroid-status.ps1](</F:/dev/kor-travel-airport/scripts/odroid-status.ps1>)
- 원격 실행 스크립트: [deploy/odroid/remote-deploy.sh](</F:/dev/kor-travel-airport/deploy/odroid/remote-deploy.sh>)

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
docker compose -f docker-compose.live.yml --project-name kor-travel-airport-live up -d
```

이 스택은 빠른 검증이 끝나면 반드시 바로 내린다.

종료:

```bash
docker compose -f docker-compose.live.yml --project-name kor-travel-airport-live down
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

- [current-state.md](</F:/dev/kor-travel-airport/docs/current-state.md>)
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
