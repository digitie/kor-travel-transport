"""공개/관리자 UI의 loopback HTTP health를 interpreter 없이 확인한다."""

from pathlib import Path

import pytest
import yaml

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = (
    _BACKEND_ROOT / "compose-contract"
    if (_BACKEND_ROOT / "compose-contract" / "docker-compose.shared.yml").is_file()
    else _BACKEND_ROOT.parent
)
_ROLES = [
    ("docker-compose.shared.yml", "frontend", "http://127.0.0.1:${PUBLIC_WEB_PORT:-14002}/", "10s", "10"),
    ("docker-compose.transport-admin.yml", "transport-admin-web", "http://127.0.0.1:${TRANSPORT_PUBLIC_WEB_PORT:-12305}/login", "15s", "5"),
]


def _health(filename: str, role: str) -> dict:
    # BaseLoader는 Compose의 !reset 태그도 데이터로 읽고 env 보간 원문을 유지한다.
    document = yaml.load((ROOT / filename).read_text(), Loader=yaml.BaseLoader)
    health = document["services"][role]["healthcheck"]
    if filename == "docker-compose.shared.yml":
        base = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
        health = {**base["services"][role]["healthcheck"], **health}
    return health


@pytest.mark.parametrize(("filename", "role", "url", "interval", "retries"), _ROLES)
def test_ui_health_uses_one_exec_form_bounded_get(
    filename: str, role: str, url: str, interval: str, retries: str,
) -> None:
    health = _health(filename, role)
    # Node/셸 시작 비용·timeout 고아를 피하고 HEAD 대신 원래 GET을 유지한다.
    assert health["test"] == ["CMD", "/usr/bin/wget", "-q", "-T5", "-O/dev/null", url]
    assert str(health["timeout"]) == "5s"


@pytest.mark.parametrize(("filename", "role", "url", "interval", "retries"), _ROLES)
def test_ui_health_preserves_endpoint_and_docker_observation_window(
    filename: str, role: str, url: str, interval: str, retries: str,
) -> None:
    health = _health(filename, role)
    assert health["test"][-1] == url
    assert health["interval"] == interval
    assert str(health["retries"]) == retries
    assert health["start_period"] == "20s"
