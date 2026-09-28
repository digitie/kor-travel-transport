# 192.168.1.13 → 192.168.1.14 migration runbook

> **포트 번호와 Compose project 이름은 이 문서가 기록한 시점 기준의 historical
> 기록이다.** 이 문서의 `14000`은 T-032(2026-08-23) 이전 API 포트를 가리키며,
> `--project-name parking-radar`는 저장소가 `kor-travel-airport`로 개명(2026-09-06)되기
> 전 이름이다. 지금 다시 이 문서를 참고해 명령을 실행한다면 현재 값(API `14001`, web
> `14002`, DB `14000`·별도 컨테이너·loopback 전용, Compose project `kor-travel-airport`/
> `kor-travel-airport-db`)으로 바꿔서 사용해야 한다. 이 컷오버 자체는
> `T-003`(`docs/tasks-done.md`)으로 이미 완료됐고, 이 문서는 향후 유사한 host 이전이
> 필요할 때의 절차 참고용으로만 남겨둔다.
>
> 2026-09 추가: 운영 식별자가 다시 개명됐다([ADR-010](../adr/010-deploy-identity-rename-transport.md)).
> 지금 값은 Compose project `kor-travel-transport`/`kor-travel-transport-db`, 앱 디렉터리
> `/home/digitie/apps/kor-travel-transport`이고, DB는 Manager 공용 PostgreSQL(`127.0.0.1:11000`)이다.
> 위 문단은 그 시점의 기록으로 둔다.

## 불변 조건

- 13번에는 Docker 명령을 실행하지 않는다. 기존 서비스와 DB volume은 변경하지 않고 HTTP API만 읽는다.
- Docker Compose와 PostgreSQL은 14번에서만 실행한다.
- 13번 수집기는 cutover 검증이 끝날 때까지 유지해 source of truth와 rollback 경로로 둔다.
- 14번 scheduler는 `COLLECT_INTERVAL_SECONDS=300` 계약으로 시작하며, 최초 수집은 scheduler 시작
  직후 실행된다. `SCHEDULER_SAFETY_BUFFER_SECONDS=120`으로 실제 tick 시작 간격은 180초로
  예약하여 upstream 응답 지연이 있어도 관측 commit 간격이 5분을 넘지 않게 한다.

## 데이터 경로 선택

1. 가장 정확한 경로: 운영자가 13번 SQLite 파일의 authorized copy 또는 PostgreSQL dump를 14번의 보호된 경로로 제공하고 `scripts/migrate_sqlite_to_postgres.py` 또는 `pg_restore`를 실행한다. 이 경로는 raw response, collection run, fee rule, analytics cache까지 보존한다.
2. 현재 SSH 권한에서 가능한 fallback: `scripts/migrate_http_history.py`가 13번 프론트 proxy의 `/api/backend/airports`와 parking history API를 읽어 공항·주차장·관측 시계열을 PostgreSQL에 upsert한다. source lot ID는 공항 코드와 함께 다루며, provider slug와 이름이 다른 경우 기존 lot을 재사용한다. 이 경로는 raw API body와 collection run ID를 복원할 수 없으므로 `migration_http` source로 명시한다. live source와 같은 lot·관측시각이 겹치면 importer가 migration 행을 제거하고, API/분석도 migration source를 중복 집계하지 않는다.

## 단계

### 1. 14번 사전 점검

```bash
ssh digitie@192.168.1.14 'ss -lntp | grep -E ":(14000|14001|5432) " || true'
ssh digitie@192.168.1.14 'docker compose version && docker ps --format "{{.Names}}" | head'
```

현재 확인 결과 3000/8000/5432는 비어 있고 Compose v5.2.0 및 Docker socket 접근이 가능했다. 다른 Compose project의 컨테이너는 중지하거나 재생성하지 않는다.

14번에 `/home/digitie/apps/parking-radar/.env.server14`를 만들고 `.env.server14.example`을 기준으로 실제 운영 키만 입력한다. `ENABLE_SCHEDULER=false`, `SEED_SAMPLE_DATA=false`로 시작한다.

### 2. 14번 PostgreSQL 준비

```bash
docker compose --project-name parking-radar --env-file .env.server14 up -d postgres
docker compose --project-name parking-radar --env-file .env.server14 run --rm --no-deps backend alembic upgrade head
```

위 명령은 모두 14번에서 실행한다. 13번에는 Docker 명령을 보내지 않는다.

### 3. prewarm import

```bash
docker compose --project-name parking-radar --env-file .env.server14 run --rm --no-deps \
  backend python /app/scripts/migrate_http_history.py \
  --source-base-url http://192.168.1.13:3000/api/backend \
  --days 7
```

프론트 proxy만 접근 가능하면 `http://192.168.1.13:3000/api/backend`를 사용한다. 출력의 `failures=0`, `imported_snapshots`, `deduplicated_snapshots`, source lot 수를 기록한다. 하나라도 history 요청이 실패하면 importer는 commit하지 않고 종료한다.

### 4. final delta와 5분 cutover

cutover 시작 전에 13번 proxy API에서 `/admin/collector-status`의 `latest_snapshot_observed_at`, `latest_snapshot_collected_at`, `last_run.id`를 기록한다. 그 다음 14번에서 아래 순서를 즉시 실행한다. 13번은 계속 동작시키며 HTTP 읽기만 한다.

```bash
date -Is
docker compose --project-name parking-radar --env-file .env.server14 run --rm --no-deps \
  backend python /app/scripts/migrate_http_history.py \
  --source-base-url http://192.168.1.13:3000/api/backend --days 1
docker compose --project-name parking-radar --env-file .env.server14 run --rm --no-deps \
  backend python /app/scripts/reconcile_parking_lots.py --dry-run
docker compose --project-name parking-radar --env-file .env.server14 run --rm --no-deps \
  backend python /app/scripts/reconcile_parking_lots.py --apply \
  --mapping-file /app/scripts/cutover-lot-map.json
sed -i 's/^ENABLE_SCHEDULER=false$/ENABLE_SCHEDULER=true/' .env.server14
docker compose --project-name parking-radar --env-file .env.server14 up -d backend frontend
until curl -fsS http://127.0.0.1:14000/health >/dev/null; do sleep 2; done
curl -fsS http://127.0.0.1:14000/admin/collector-status
```

14번 backend는 scheduler 활성화 직후 collector를 한 번 실행한다. scheduler는 collection duration을 더하지 않는 monotonic deadline으로 다음 tick을 예약한다. `date -Is`부터 14번의 `last_run.finished_at`까지 180초 시작 간격과 300초 freshness 이내인지 측정하고, 14번 latest observed/collected가 13번 cutover marker보다 늦거나 같은지 확인한다. 5분 기준을 넘거나 latest marker가 후퇴하면 14번 scheduler를 끄고 13번을 유지한 채 원인을 조사한다.

HTTP fallback의 경우 13번은 계속 실행 중이므로 source update가 중단되지 않는다. 14번이 live 수집을 시작한 뒤 두 시스템의 latest marker를 5분 동안 1분 간격으로 비교해 공백이 없는 것을 확인한다. 확인이 끝나기 전에는 13번을 중지하지 않는다.

전역 marker만으로 한 lot의 정체를 숨기지 않도록 per-lot verifier도 실행한다.

```bash
TMPDIR=/tmp uv run --project backend --extra dev python scripts/verify_cutover.py \
  --source-base-url http://192.168.1.13:3000/api/backend \
  --target-base-url http://192.168.1.14:14000 \
  --days 1 --max-age-seconds 300 --max-source-lag-seconds 300 \
  --max-run-gap-seconds 300 \
  --empty-lot-file scripts/cutover-empty-lots.json
```

이 명령은 source lot 수, target의 안정적인 legacy lot ID 중복, 각 lot의 latest observed,
source→target 지연, target scheduler/recent successful run 간격/freshness를 함께 검사한다.
release gate의 freshness·전파·run gap 한도는 호출자가 완화할 수 없도록 각각 정확히
`300초`로 고정되어 있다. `scripts/cutover-empty-lots.json` allowlist는 양쪽 모두 관측이
없는 lot에만 적용되며, source는 비어 있고 target만 관측되는 비대칭 상태는 allowlist가 있어도
실패한다. 이름만 같은 lot은 같은 lot으로 인정하지 않는다. `failure_count=0`이어야 한다.

단일 확인은 5분 연속성의 증거가 아니므로, cutover 승인 전에는 정확히 50초 간격 7회 반복
관찰을 실행한다. `samples`, `sample-interval-seconds`, 세 가지 300초 threshold는 release
gate에서 모두 고정되어 임의의 짧은 관찰이나 완화된 threshold로 green을 만들 수 없다. 이는
0분부터 5분까지의 gate를 만들고 source/target 모두 HTTP read만 수행한다.

```bash
TMPDIR=/tmp uv run --project backend --extra dev python scripts/observe_cutover.py \
  --source-base-url http://192.168.1.13:3000/api/backend \
  --target-base-url http://192.168.1.14:14000 \
  --days 1 --max-age-seconds 300 --max-source-lag-seconds 300 \
  --max-run-gap-seconds 300 --samples 7 --sample-interval-seconds 50 \
  --empty-lot-file scripts/cutover-empty-lots.json
```

`scripts/cutover-empty-lots.json`은 source `/airports`와 target의 `legacy_source_lot_id`를
대조해 실제 양쪽 무관측인 ICN lot만 기록한 검토 artifact다. 14번 scheduler의 계약은
configured 300초이고 실제 tick 시작 간격은 180초(`120초 safety buffer`)이며 verifier가 세 값을
모두 검사한다. freshness/lag/run gap 한도에는 시간 epsilon을 두지 않는다.
마지막 출력의 `failed_samples=0`과 각 verifier 출력의 `failure_count=0`을 journal에 기록한다.

배포 artifact는 `scripts/deploy-server14.sh`가 현재 Git `HEAD`의 full SHA로 만들고, 14번
health 응답의 `release_sha`와 일치하는지 확인한다. live E2E의 CI job도
`EXPECTED_RELEASE_SHA`를 같은 PR head SHA로 설정해, 다른 commit이 올라간 외부 사이트를
green으로 오인하지 않도록 한다.

### 5. 검증·보존

외부 reverse proxy가 웹 `https://pr.digitie.mywire.org`를 14번 `14001`로, API
`https://pr-api.digitie.mywire.org`를 14번 `14000`으로 전달해야 한다. 웹은 same-origin
`/api/backend` proxy를 사용하고, API 도메인은 운영 smoke와 직접 API 확인에 사용한다.
443 reverse proxy가 별도 호스트에서 실행된다면 14번 Compose만으로 DNS/게이트웨이 라우팅은
바뀌지 않으므로 live E2E 전에 web title과 API health 응답을 각각 확인한다.

```bash
curl -fsS http://192.168.1.14:14000/health
curl -fsS 'http://192.168.1.14:14000/dashboard/bootstrap' >/dev/null
curl -fsS 'http://192.168.1.14:14000/dashboard/analytics?airport_code=GMP' >/dev/null
```

검증 항목은 `docs/tasks.md`와 `docs/journal.md`에 source/target row count, stable lot identity,
latest observed, latest collected, last run ID, 실제 elapsed seconds를 남긴다. exact dump가
없었으면 raw/run/fee 보존 불가를 숨기지 않고 기록한다.

## rollback

14번 컨테이너만 `docker compose --project-name parking-radar ... stop`으로 중지할 수 있다. 13번은 이 runbook과 사용자 제약에 따라 Docker를 조작하지 않는다. 14번 PostgreSQL을 되돌릴 때는 복원 UI/API의 pre-restore backup 또는 `pg_restore`를 사용한다.
