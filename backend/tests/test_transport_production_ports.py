"""Odroid 실제 포트와 공식 배포·gateway·관리 UI의 단일 계약."""
from pathlib import Path

from test_dagster_healthcheck_contract import ROOT, _ComposeLoader
import yaml

BACKEND = Path(__file__).resolve().parents[1]
SCRIPTS = BACKEND / "scripts" if (BACKEND / "scripts").is_dir() else ROOT / "scripts"


def test_prod_deployment_and_env_use_current_backend_and_frontend_ports():
    remote = (SCRIPTS / "deploy-prod-remote.sh").read_text()
    env = (ROOT / ".env.prod.example").read_text()
    assert "require_exact PUBLIC_API_PORT 12302" in remote
    assert "require_exact PUBLIC_WEB_PORT 12303" in remote
    assert "require_exact BACKEND_INTERNAL_URL http://127.0.0.1:12302" in remote
    assert "PUBLIC_API_PORT=12302" in env
    assert "PUBLIC_WEB_PORT=12303" in env
    assert "TRANSPORT_API_INTERNAL_URL=http://127.0.0.1:12302" in env


def test_gateway_and_admin_capability_use_current_api_port():
    gateway = (ROOT / "deploy/transport-admin/api-gateway.conf.template").read_text()
    admin = (SCRIPTS / "deploy-transport-admin-prod.sh").read_text()
    assert gateway.count("proxy_pass http://127.0.0.1:12302;") == 3
    assert "http://127.0.0.1:12302/v1/transport/admin/place-locations/capability" in admin
    assert "127.0.0.1:14001" not in gateway + admin


def test_shared_and_admin_defaults_follow_current_role_ports():
    shared = yaml.load((ROOT / "docker-compose.shared.yml").read_text(), Loader=_ComposeLoader)["services"]
    admin = yaml.load((ROOT / "docker-compose.transport-admin.yml").read_text(), Loader=_ComposeLoader)["services"]
    assert shared["backend"]["command"][-1] == "${PUBLIC_API_PORT:-12302}"
    assert shared["frontend"]["command"][-1] == "${PUBLIC_WEB_PORT:-12303}"
    assert shared["frontend"]["environment"]["BACKEND_INTERNAL_URL"] == "http://127.0.0.1:${PUBLIC_API_PORT:-12302}"
    assert admin["transport-admin-web"]["environment"]["TRANSPORT_API_INTERNAL_URL"] == "${TRANSPORT_API_INTERNAL_URL:-http://127.0.0.1:12302}"


def test_admin_deploy_uses_existing_project_without_removing_other_roles():
    script = (SCRIPTS / "deploy-transport-admin-prod.sh").read_text()
    assert "--project-name kor-travel-transport " in script
    assert "--project-name kor-travel-transport-admin" not in script
    commands = [line for line in script.splitlines() if line.startswith("TRANSPORT_ADMIN_RELEASE_SHA=")]
    assert len(commands) == 1
    assert commands[0].endswith("transport-api-gateway transport-admin-web")
    assert "--remove-orphans" not in commands[0]
    assert " down" not in commands[0]
