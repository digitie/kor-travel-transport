"""공용 DB 전환이 application/Dagster metadata 양쪽을 fail-close하는지 고정한다."""

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]


def test_cutover_requires_a_separate_empty_dagster_database() -> None:
    script = (_ROOT / "scripts" / "cutover-shared-db-server14.sh").read_text(encoding="utf-8")

    assert 'TARGET_DAGSTER_DATABASE_URL="${DAGSTER_POSTGRES_URL:?' in script
    assert 'if [[ "${TARGET_DATABASE_URL}" == "${TARGET_DAGSTER_DATABASE_URL}" ]]' in script
    assert 'assert_ready target-dagster "${TARGET_DAGSTER_DATABASE_URL}"' in script
    assert 'assert_empty_bootstrap_only target "${TARGET_DATABASE_URL}"' in script
    assert 'assert_empty_bootstrap_only target-dagster "${TARGET_DAGSTER_DATABASE_URL}"' in script
    assert "target_dagster_database=%s" in script


def test_deploy_receipt_binds_both_shared_database_names() -> None:
    script = (_ROOT / "scripts" / "deploy-server14.sh").read_text(encoding="utf-8")

    assert "target_database=kor_travel_transport" in script
    assert "target_dagster_database=kor_travel_transport_dagster" in script
