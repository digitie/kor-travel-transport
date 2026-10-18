"""운영 역할의 유한한 메모리와 동일한 memory+swap 한도를 검증한다."""
from pathlib import Path

import pytest
import yaml

_BACKEND = Path(__file__).resolve().parents[1]
_ROOT = _BACKEND / "compose-contract" if (_BACKEND / "compose-contract").is_dir() else _BACKEND.parent
_ROLES = {
    "docker-compose.shared.yml": {"backend": 512, "dagster-code-server": 2560, "frontend": 384},
    "docker-compose.transport-admin.yml": {"transport-admin-web": 512, "transport-api-gateway": 64},
}


def _validate(service: dict, expected_mib: int) -> None:
    assert service["mem_limit"] == f"{expected_mib}m"
    assert service["memswap_limit"] == service["mem_limit"]
    assert expected_mib > 0


@pytest.mark.parametrize("filename,roles", _ROLES.items())
def test_operating_roles_have_finite_equal_memory_and_swap(filename, roles):
    # Compose 전용 태그를 실행하지 않고 리터럴 계약을 읽는다.
    services = yaml.load((_ROOT / filename).read_text(), Loader=yaml.BaseLoader)["services"]
    for role, mib in roles.items():
        _validate(services[role], mib)
    assert {name for name, service in services.items() if "mem_limit" in service} == set(roles)


@pytest.mark.parametrize("patch", [
    {"mem_limit": "0", "memswap_limit": "0"},
    {"mem_limit": "512m", "memswap_limit": "1g"},
    {"mem_limit": "512m", "memswap_limit": "-1"},
    {"mem_limit": "512m"},
])
def test_unlimited_mismatched_or_missing_swap_is_rejected(patch):
    with pytest.raises((AssertionError, KeyError)):
        _validate(patch, 512)


def test_total_budget_is_explicit():
    assert sum(mib for roles in _ROLES.values() for mib in roles.values()) == 4032
