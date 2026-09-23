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
| `dagster-migrate` | Dagster run/event/schedule metadata schema 1회 초기화·업그레이드 | Dagster instance migration만 |
| `dagster-code-server` | job 코드와 run worker 실행 | 함 |
| `dagster-webserver` | Dagster UI/GraphQL | 하지 않음, gRPC workspace만 연결 |
| `dagster-daemon` | schedule, queue, run monitoring | 하지 않음, gRPC workspace만 연결 |
| `dagster-gateway` | loopback Basic Auth와 same-origin POST 검증 뒤 Manager TLS proxy에만 UI 제공 | 하지 않음 |

`dagster dev`는 운영에서 사용하지 않는다. code-server는 독립 컨테이너라 실제 crash/OOM이면
`restart: unless-stopped`로 재기동하고, webserver/daemon은 child-process heartbeat를 관리하지
않는다. `dagster.yaml`의 `run_monitoring`은 사라진 worker가 STARTED 상태로 남아 queue를
막는 경우를 5분 시작 제한과 4시간 실행 상한으로 회수한다.

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

KRIC는 인증 OpenAPI도 과도한 GET 대신 하루 한 번 이하의 batch 호출을 요청한다. 철도
기준정보 job은 매일 due만 평가하지만 마지막 성공 수집 뒤 **48시간**이 지나기 전에는
provider를 호출하지 않는다. 따라서 월 경계도 실제 수집 간격은 2일 이상이다. 한 run은 공개
XLSX를 한 번만 읽고, 인증 OpenAPI를 전국 역·열차 단위로 순회하지 않는다.
인증 OpenAPI의 역 상세·시간표는 이용자 요청에 필요한 단건 조회로 분리하고, 별도 cache
정책을 구현하기 전에는 Dagster batch에 포함하지 않는다. 여객선 기준정보도 매일 또는 전국
항구별 운항계획을 무차별 호출하지 않는다.

항구 운항시간표는 저장하지 않는다. `GET /v1/transport/ports/{port_id}/timetable?date=YYYY-MM-DD`가
요청한 항구와 날짜만 provider에 비동기로 전달해 실시간 응답으로 반환한다. 오늘부터 설정된
미래 일수 안에서만 조회하고, 같은 `(항구, 날짜)`는 process cache와 async lock으로 묶어 cache
TTL 동안 외부 API를 한 번만 호출한다. provider가 호출 제한을 돌려주면 전 항구 요청을
`UPSTREAM_RATE_LIMIT_BACKOFF_SECONDS` 동안 429와 `Retry-After`로 차단한다. 따라서 시간표는
오래된 DB snapshot으로 오인되지 않으며, 반복 클릭이나 오류 재시도도 provider quota를 소모하지 않는다.

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
   [`scripts/cutover-shared-db-server14.sh`](../../scripts/cutover-shared-db-server14.sh)를 실행한다.
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
   `kor-travel-airport-net`과 원래 `14001:8000`/`14002:3000` publish를 검증·복원한다. deploy
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

Dagster gateway는 `127.0.0.1:14003`에만 bind한다. 외부 UI가 필요하면 Manager가 TLS를 종단하고
그 loopback endpoint만 upstream으로 지정해야 한다. 운영 값은 최소한 `DATABASE_URL`,
`DAGSTER_POSTGRES_URL`, `DAGSTER_UI_PASSWORD`를 요구한다.
KRIC 파일 수집은 `RAIL_REFERENCE_COLLECTION_ENABLED=true`와 RustFS endpoint·bucket·접근키가,
여객항구 기준정보는 `MARITIME_REFERENCE_COLLECTION_ENABLED=true`와
`DATA_GO_KR_SERVICE_KEY`가 모두 있을 때만 실행한다. 휴게소 기준정보는
`REST_AREA_REFERENCE_COLLECTION_ENABLED=true`와 `DATA_GO_KR_SERVICE_KEY`가 있을 때만
3일 주기 job이 실행한다. Manager의 RustFS 초기화는
`kor-travel-transport-raw` bucket도 idempotent하게 준비한다. 비활성 상태는 실패가 아니라
명시적인 `skipped` run으로 남긴다.

provider는 HTTPS RustFS endpoint를 기본 요구한다. 현재 Manager RustFS는 host loopback의
사설 연결만 제공하므로 `RUSTFS_ALLOW_INSECURE_HTTP=true`는 그 host-gateway 경로에만
명시한다. 공용 인터넷 endpoint에는 이 값을 사용하지 않는다.

기존 `docker-compose.db.yml`은 기존 n150 데이터의 rollback과 local 개발 격리용이다.
공용 DB cutover가 완료되고 live E2E가 수용될 때까지 기존 DB volume을 삭제하거나 그 compose를
내리지 않는다.
