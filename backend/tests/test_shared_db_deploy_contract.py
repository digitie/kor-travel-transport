"""공용 DB 배포가 application/Dagster metadata 양쪽 DB 이름에 묶이는지 고정한다.

한 번짜리 `cutover-shared-db-server14.sh`와 그 계약 테스트는 실행을 마쳐 지웠다(ADR-011).
"""

from pathlib import Path


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
# 로컬 체크아웃은 `<repo>/backend/tests`, Docker 이미지는 `/app/tests`에 있다.
# 두 환경 모두에서 Dockerfile이 복사한 scripts/를 우선해 계약 테스트를 실행한다.
_ROOT = _BACKEND_ROOT if (_BACKEND_ROOT / "scripts" / "deploy-server14-remote.sh").is_file() else _BACKEND_ROOT.parent
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


def test_deploy_receipt_binds_both_shared_database_names() -> None:
    script = (_ROOT / "scripts" / "deploy-server14.sh").read_text(encoding="utf-8")
    remote_script = (_ROOT / "scripts" / "deploy-server14-remote.sh").read_text(encoding="utf-8")

    assert "target_database=kor_travel_transport" in remote_script
    assert "target_dagster_database=kor_travel_transport_dagster" in remote_script
    assert "@127\\.0\\.0\\.1:11000/kor_travel_transport$" in remote_script
    assert "@127\\.0\\.0\\.1:11000/kor_travel_transport_dagster$" in remote_script
    # 운영 env와 .env.server14.example의 Dagster DSN은 `postgresql+psycopg2://`다(ADR-010).
    assert "^postgresql(\\+psycopg2)?://[^@]+@127\\.0\\.0\\.1:11000/kor_travel_transport_dagster$" in remote_script
    assert "DEPLOY_STAGE_ONLY" in script
    assert '--exclude=".env.server14.legacy"' in script
    assert "Candidate ${CANDIDATE_SHA} staged on n150; no containers were changed." in script
    assert "require_exact BACKEND_INTERNAL_URL http://127.0.0.1:14001" in remote_script
    assert "git rev-parse" not in remote_script
    assert "staged release manifest does not match candidate" in remote_script



def test_dagster_gateway_is_loopback_only_and_has_no_dead_port_setting() -> None:
    gateway = _GATEWAY_CONFIG.read_text(encoding="utf-8")
    environment = _SERVER_ENV_EXAMPLE.read_text(encoding="utf-8")

    assert "listen 127.0.0.1:14003;" in gateway
    assert "DAGSTER_GATEWAY_PORT=" not in environment
