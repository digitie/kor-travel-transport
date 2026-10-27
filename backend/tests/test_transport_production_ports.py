"""Odroid 실제 포트와 공식 배포·gateway·관리 UI의 단일 계약."""
import re
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


def _env_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key] = value
    return values


def test_env_example_satisfies_every_remote_require_exact():
    """`deploy-prod.sh`가 복사하라고 안내하는 예시가 원격 배포의 정확 일치 검사를 모두 통과한다."""
    remote = (SCRIPTS / "deploy-prod-remote.sh").read_text()
    required = re.findall(r"^require_exact (\w+) (\S+)$", remote, re.MULTILINE)
    assert len(required) >= 10, required  # 파서가 스크립트 모양을 놓치면 아무것도 재지 않는다.
    env = _env_values((ROOT / ".env.prod.example").read_text())
    mismatched = {name: (env.get(name), value) for name, value in required if env.get(name) != value}
    assert not mismatched, mismatched
    assert env.get("SCHEDULER_SAFETY_BUFFER_SECONDS") == "120"
    assert env.get("NEXT_PUBLIC_API_BASE_URL") == ""


def test_operational_tools_do_not_default_to_the_retired_api_port():
    """#90 이후 API는 12302다. 운영 스크립트와 관리 UI 서버 코드의 기본값이 옛 14001로 가지 않는다."""
    admin = ROOT / "packages/kor-travel-transport-admin/frontend"
    sources = [*SCRIPTS.rglob("*"), *(admin / "lib").rglob("*"), *(admin / "app").rglob("*")]
    scanned = [path for path in sources if path.is_file() and path.suffix in {".py", ".sh", ".ts", ".tsx", ".mjs", ".js"}]
    assert any(path.name == "upstream.ts" for path in scanned), "관리 UI lib을 찾지 못했다"
    stale = [str(path) for path in scanned if "127.0.0.1:14001" in path.read_text(encoding="utf-8", errors="ignore")]
    assert not stale, stale


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
