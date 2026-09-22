"""공용 DB 전환이 application/Dagster metadata 양쪽을 fail-close하는지 고정한다."""

from pathlib import Path


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
# 로컬 체크아웃은 `<repo>/backend/tests`, Docker 이미지는 `/app/tests`에 있다.
# 두 환경 모두에서 Dockerfile이 복사한 scripts/를 우선해 계약 테스트를 실행한다.
_ROOT = _BACKEND_ROOT if (_BACKEND_ROOT / "scripts").is_dir() else _BACKEND_ROOT.parent
_GATEWAY_CONFIG = (
    _BACKEND_ROOT / "nginx" / "dagster-gateway.conf"
    if (_BACKEND_ROOT / "nginx" / "dagster-gateway.conf").is_file()
    else _ROOT / "backend" / "nginx" / "dagster-gateway.conf"
)
_SERVER_ENV_EXAMPLE = (
    _BACKEND_ROOT / "compose-contract" / ".env.server14.example"
    if (_BACKEND_ROOT / "compose-contract" / ".env.server14.example").is_file()
    else _ROOT / ".env.server14.example"
)


def test_cutover_requires_a_separate_empty_dagster_database() -> None:
    script = (_ROOT / "scripts" / "cutover-shared-db-server14.sh").read_text(encoding="utf-8")

    assert 'TARGET_DAGSTER_DATABASE_URL="${DAGSTER_POSTGRES_URL:?' in script
    assert 'if [[ "${TARGET_DATABASE_URL}" == "${TARGET_DAGSTER_DATABASE_URL}" ]]' in script
    assert "127\\.0\\.0\\.1:11000/kor_travel_transport$" in script
    assert "127\\.0\\.0\\.1:11000/kor_travel_transport_dagster$" in script
    assert 'LEGACY_HOST_DATABASE_URL="${LEGACY_HOST_DATABASE_URL:?' in script
    assert 'LEGACY_DAGSTER_HOST_DATABASE_URL="${LEGACY_DAGSTER_HOST_DATABASE_URL:-}"' in script
    assert 'legacy runtime and host DSNs must name the same database' in script
    assert 'legacy Dagster runtime and host DSNs must name the same database' in script
    assert 'TARGET_HOST_DATABASE_URL="${TARGET_DATABASE_URL/postgresql+asyncpg:/postgresql:}"' in script
    assert 'TARGET_DAGSTER_HOST_DATABASE_URL="${TARGET_DAGSTER_DATABASE_URL}"' in script
    assert 'assert_ready target-dagster "${TARGET_DAGSTER_HOST_DATABASE_PSQL_URL}"' in script
    assert 'assert_empty_bootstrap_only target "${TARGET_HOST_DATABASE_PSQL_URL}"' in script
    assert 'assert_empty_bootstrap_only target-dagster "${TARGET_DAGSTER_HOST_DATABASE_PSQL_URL}"' in script
    assert "target_dagster_database=%s" in script
    assert "LEGACY_DAGSTER_DATABASE_URL" in script
    assert "DAGSTER_METADATA_RESET_CONFIRM" in script
    assert "START_FRESH_DAGSTER_METADATA_WITH_NO_LEGACY_STORE" in script


def test_cutover_uses_disposable_postgres_clients_on_the_server_host_network() -> None:
    script = (_ROOT / "scripts" / "cutover-shared-db-server14.sh").read_text(encoding="utf-8")

    assert 'PG_CLIENT_IMAGE="${PG_CLIENT_IMAGE:-postgres:16-alpine}"' in script
    assert 'docker run --rm --network host -v "${CUTOVER_WORK_DIR}:/cutover"' in script
    assert '-v "${PGPASS_FILE}:/run/secrets/pgpass:ro"' in script
    assert '-e PGPASSFILE=/run/secrets/pgpass' in script
    assert 'prepare_client_dsn' in script
    assert 'from urllib.parse import quote, unquote, urlsplit' in script
    assert 'passwordless URI' in script
    assert 'password)) + "\\n")' in script
    assert 'pg_dump_client' in script
    assert 'pg_restore_client' in script


def test_empty_target_rejects_all_user_schema_objects_and_migration_rows() -> None:
    script = (_ROOT / "scripts" / "cutover-shared-db-server14.sh").read_text(encoding="utf-8")

    assert "pg_namespace" in script
    assert "pg_proc" in script
    assert "pg_type" in script
    assert "pg_operator" in script
    assert "pg_collation" in script
    assert "pg_conversion" in script
    assert "pg_extension" in script
    assert "SELECT count(*) FROM public.alembic_version" in script


def test_legacy_dagster_metadata_is_quiesced_before_the_final_dump() -> None:
    script = (_ROOT / "scripts" / "cutover-shared-db-server14.sh").read_text(encoding="utf-8")

    assert "legacy_dagster_services=()" in script
    assert "dagster-code-server dagster-webserver dagster-daemon dagster-gateway" in script
    assert "legacy-dagster-metadata-final.dump" in script
    assert "migrated-after-writer-quiescence" in script


def test_deploy_receipt_binds_both_shared_database_names() -> None:
    script = (_ROOT / "scripts" / "deploy-server14.sh").read_text(encoding="utf-8")
    remote_script = (_ROOT / "scripts" / "deploy-server14-remote.sh").read_text(encoding="utf-8")

    assert "target_database=kor_travel_transport" in remote_script
    assert "target_dagster_database=kor_travel_transport_dagster" in remote_script
    assert "@127\\.0\\.0\\.1:11000/kor_travel_transport$" in remote_script
    assert "@127\\.0\\.0\\.1:11000/kor_travel_transport_dagster$" in remote_script
    assert "DEPLOY_STAGE_ONLY" in script
    assert '--exclude=".env.server14.legacy"' in script
    assert "Candidate ${CANDIDATE_SHA} staged on n150; no containers were changed." in script
    assert "require_exact BACKEND_INTERNAL_URL http://127.0.0.1:14001" in remote_script
    assert "git rev-parse" not in remote_script
    assert "staged release manifest does not match candidate" in remote_script


def test_cutover_uses_staged_n150_deployment_and_does_not_hide_rollback_failures() -> None:
    script = (_ROOT / "scripts" / "cutover-shared-db-server14.sh").read_text(encoding="utf-8")

    assert "stage the reviewed candidate on n150 before writer quiescence" in script
    assert "deploy-server14-remote.sh" in script
    assert 'CANDIDATE_SHA="${TARGET_CANDIDATE_SHA}" "${TARGET_DEPLOY_SCRIPT}"' in script
    assert "automatic legacy writer rollback did not complete" in script
    assert 'source "${TARGET_ENV_FILE}"' in script
    assert 'docker commit --pause=false "${LEGACY_BACKEND_CONTAINER}" "${LEGACY_BACKEND_ROLLBACK_IMAGE}"' in script
    assert 'LEGACY_BACKEND_NETWORK_MODE="$(docker inspect -f' in script
    assert 'LEGACY_FRONTEND_NETWORK_MODE="$(docker inspect -f' in script
    assert 'network_args=(--network "${LEGACY_BACKEND_NETWORK_MODE}" --network-alias backend)' in script
    assert 'network_args=(--network "${LEGACY_FRONTEND_NETWORK_MODE}")' in script
    assert 'publish_args=(-p 14001:8000)' in script
    assert 'publish_args=(-p 14002:3000)' in script
    assert 'docker rm -f "${LEGACY_BACKEND_CONTAINER}"' in script
    assert "http://127.0.0.1:14002/api/backend/health" in script
    assert "preserved legacy frontend did not become healthy after rollback" in script
    assert "stop backend frontend dagster-code-server" in script
    assert 'docker compose --project-name "${LEGACY_PROJECT_NAME}" --env-file "${LEGACY_ENV_FILE}" -f docker-compose.yml stop backend' in script
    assert "docker rename" not in script
    assert "preserved legacy backend did not become healthy after rollback" in script
    assert "up -d backend" not in script


def test_dagster_gateway_is_loopback_only_and_has_no_dead_port_setting() -> None:
    gateway = _GATEWAY_CONFIG.read_text(encoding="utf-8")
    environment = _SERVER_ENV_EXAMPLE.read_text(encoding="utf-8")

    assert "listen 127.0.0.1:14003;" in gateway
    assert "DAGSTER_GATEWAY_PORT=" not in environment
