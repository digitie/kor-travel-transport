"""운영 export 소비자 제한은 빈 값 거절·IPv4/CIDR 검증·쓰기 금지를 보존한다."""
from pathlib import Path
import re
import subprocess
import pytest

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND if (BACKEND / "scripts").is_dir() else BACKEND.parent
SCRIPT = ROOT / "deploy/transport-admin/19-export-allowlist.sh"

def run_script(tmp_path, value):
    destination = tmp_path / "allow.conf"
    destination.write_text("prior")
    source = SCRIPT.read_text().replace("/etc/nginx/transport-export-allow.conf", str(destination))
    env = {"PATH": "/usr/bin:/bin", "TRANSPORT_EXPORT_CONSUMER_CIDR": value}
    result = subprocess.run(["sh", "-c", source], env=env, capture_output=True, text=True)
    return result, destination.read_text()

@pytest.mark.parametrize("value", ["", "127.0.0.1", "192.0.2.10/32", "198.51.100.0/24"])
def test_allowlist_exact_validated_output(tmp_path, value):
    result, content = run_script(tmp_path, value)
    assert result.returncode == 0, result.stderr
    assert content == (f"allow {value};\n" if value else "") + "deny all;\n"

@pytest.mark.parametrize("value", [
    "127.0.0.1; allow all", "127.0.0.1\nallow all", "127.0.0.1\\nallow all",
    "127.0.0.1/33", "256.0.0.1", "1.2.3", "1.2.3.4/", "/24",
    "001.2.3.4", "1.2.3.4/01", "1.2.3.4/24/1", "example.org", "::1", "unix:",
])
def test_invalid_value_is_rejected_before_file_write(tmp_path, value):
    result, content = run_script(tmp_path, value)
    assert result.returncode != 0
    assert content == "prior"

def test_export_gateway_does_not_expand_admin_or_public_contract():
    template = (ROOT / "deploy/transport-admin/api-gateway.conf.template").read_text()
    export = template.split("location ^~ /v1/service/exports/ {", 1)[1].split("\n    }", 1)[0]
    assert "include /etc/nginx/transport-export-allow.conf;" in export
    assert "limit_except GET { deny all; }" in export
    assert 'proxy_set_header X-Forwarded-For "";' in export
    assert "proxy_pass http://127.0.0.1:12302;" in export
    assert "proxy_read_timeout 120s;" in export
    assert "location / { return 404; }" in template
    assert "/admin/" not in template
    compose = (ROOT / "docker-compose.transport-admin.yml").read_text()
    assert 'TRANSPORT_EXPORT_CONSUMER_CIDR: "${TRANSPORT_EXPORT_CONSUMER_CIDR:-}"' in compose
    assert "/docker-entrypoint.d/19-export-allowlist.sh:ro" in compose


@pytest.mark.parametrize("path,allowed", [
    ("/v1/transport/fuel/stations/1/price-history", True),
    ("/v1/transport/fuel/stations/9274/price-history", True),
    ("/v1/transport/fuel/stations", True),
    ("/v1/transport/fuel/statistics", True),
    ("/v1/transport/fuel/stations/0/price-history", False),
    ("/v1/transport/fuel/stations/-1/price-history", False),
    ("/v1/transport/fuel/stations/1x/price-history", False),
    ("/v1/transport/fuel/stations/1/price-history/delete", False),
    ("/v1/transport/fuel/stations/1/price-history/", False),
    ("/v1/transport/fuel/stations/1/prices", False),
    ("/v1/admin/backups", False),
    ("/v1/service/exports/fuel-stations/opinet:1/price-history", False),
])
def test_public_fuel_history_is_an_exact_read_route(path, allowed):
    template = (ROOT / "deploy/transport-admin/api-gateway.conf.template").read_text()
    location = next(line.strip() for line in template.splitlines()
                    if line.strip().startswith("location ~ ^/v1/transport/"))
    pattern = location.removeprefix("location ~ ").removesuffix(" {")
    assert bool(re.fullmatch(pattern, path)) is allowed
    block = template.split(location, 1)[1].split("\n    }", 1)[0]
    assert "limit_except GET { deny all; }" in block
    assert "proxy_read_timeout 30s;" in block
