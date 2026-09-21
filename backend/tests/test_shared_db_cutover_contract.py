"""공용 DB 전환이 application/Dagster metadata 양쪽을 fail-close하는지 고정한다."""

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]


def test_cutover_requires_a_separate_empty_dagster_database() -> None:
    script = (_ROOT / "scripts" / "cutover-shared-db-server14.sh").read_text(encoding="utf-8")

    assert 'TARGET_DAGSTER_DATABASE_URL="${DAGSTER_POSTGRES_URL:?' in script
    assert 'if [[ "${TARGET_DATABASE_URL}" == "${TARGET_DAGSTER_DATABASE_URL}" ]]' in script
    assert "host\\.docker\\.internal:11000/kor_travel_transport$" in script
    assert "host\\.docker\\.internal:11000/kor_travel_transport_dagster$" in script
    assert 'LEGACY_HOST_DATABASE_URL="${LEGACY_HOST_DATABASE_URL:?' in script
    assert 'LEGACY_DAGSTER_HOST_DATABASE_URL="${LEGACY_DAGSTER_HOST_DATABASE_URL:-}"' in script
    assert 'legacy runtime and host DSNs must name the same database' in script
    assert 'legacy Dagster runtime and host DSNs must name the same database' in script
    assert 'TARGET_HOST_DATABASE_URL="${TARGET_DATABASE_URL/postgresql+asyncpg:/postgresql:}"' in script
    assert 'TARGET_HOST_DATABASE_URL="${TARGET_HOST_DATABASE_URL/host.docker.internal:11000/127.0.0.1:11000}"' in script
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

    assert "target_database=kor_travel_transport" in script
    assert "target_dagster_database=kor_travel_transport_dagster" in script
