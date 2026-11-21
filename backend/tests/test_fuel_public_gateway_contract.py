"""fuel 공개 쌍의 좁은 경로·method·고정 upstream과 compose 분리를 검증한다."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
if not (ROOT / "docker-compose.fuel.yml").is_file():
    ROOT = Path("/app/compose-contract")
KIND_QUERY_CASES = [
    ("kinds=fuel_station", 422),
    ("kind=fuel_station", 200),
    ("kind=rail_station", 200),
    ("kind=fuel_station&kind=rail_station", 200),
    ("%6bind=rail_station", 200),
    ("kind=rail_station%26kind%3Dferry_port", 200),
    ("kinds=rail_station", 422),
    ("%6bind%73=rail_station", 422),
    ("kind=fuel_station&kinds=", 422),
    ("kinds=rail_station&kinds=fuel_station", 422),
    ("KiNd=rail_station", 200),
    ("kind=rail_station;kind=ferry_port", 200),
]


def test_fuel_compose_is_separate_two_role_reader_without_database_or_secrets():
    config = yaml.safe_load((ROOT / "docker-compose.fuel.yml").read_text())
    assert config["name"] == "kor-travel-transport-fuel"
    services = config["services"]
    assert set(services) == {"fuel-api-gateway", "fuel-web"}
    assert all(service["network_mode"] == "host" for service in services.values())
    assert all("env_file" not in service and "volumes" not in service for service in services.values())
    gateway, web = services["fuel-api-gateway"], services["fuel-web"]
    assert set(gateway["environment"]) == {"TRANSPORT_FUEL_API_PORT"}
    assert gateway["environment"]["TRANSPORT_FUEL_API_PORT"].endswith(":-12307}")
    assert web["environment"]["TRANSPORT_UI_MODE"] == "fuel"
    assert web["environment"]["BACKEND_INTERNAL_URL"].startswith("http://127.0.0.1:")
    assert web["environment"]["BACKEND_INTERNAL_URL"].endswith(":-12307}")
    assert web["environment"]["TRANSPORT_FUEL_WEB_PORT"].endswith(":-12308}")
    assert not any(
        name in service["environment"]
        for service in services.values()
        for name in ["DATABASE_URL", "DAGSTER_HOME", "TRANSPORT_UI_PASSWORD", "TRANSPORT_UI_SESSION_SECRET"]
    )
    assert gateway["build"]["dockerfile"] == "deploy/transport-fuel/Dockerfile.gateway"
    assert web["build"]["dockerfile"] == "packages/kor-travel-transport-admin/frontend/Dockerfile"


def test_gateway_uses_fixed_fuel_alias_and_rejects_other_readers_and_credentials():
    text = (ROOT / "deploy/transport-fuel/api-gateway.conf.template").read_text()
    assert "location = /v1/transport/fuel/places" in text
    assert "http://127.0.0.1:12302/v1/transport/features/places?$args&kind=fuel_station;" in text
    assert "proxy_method GET;" in text
    assert "proxy_set_header Host 127.0.0.1;" in text
    assert 'proxy_set_header Authorization "";' in text
    assert 'proxy_set_header Cookie "";' in text
    assert 'proxy_set_header X-Forwarded-For "";' in text
    assert "proxy_hide_header Set-Cookie;" in text
    assert "location / { return 404; }" in text
    assert "if ($fuel_read_method = 0) { return 405; }" in text
    assert text.count("proxy_pass ") == 3
    assert "stations/[1-9][0-9]*/price-history" in text
    assert "|price-distribution|" in text
    assert "regions" not in text and "/mcp" not in text and "/exports/" not in text
    assert "$arg_zoom" not in text and "zoom=" not in text


def test_public_cors_is_exact_and_preflight_never_reaches_upstream():
    text = (ROOT / "deploy/transport-fuel/api-gateway.conf.template").read_text()
    assert '"https://fuel.digitie.mywire.org" "https://fuel.digitie.mywire.org";' in text
    assert '"OPTIONS:https://fuel.digitie.mywire.org:GET" 1;' in text
    assert '"OPTIONS:https://fuel.digitie.mywire.org:HEAD" 1;' in text
    assert "~^OPTIONS: 2;" in text
    assert text.count("if ($fuel_preflight = 1) { return 204; }") == 3
    assert text.count("if ($fuel_preflight = 2) { return 403; }") == 3
    assert "add_header Access-Control-Allow-Credentials" not in text
    assert 'add_header Access-Control-Allow-Origin "*"' not in text


def test_fuel_gateway_image_has_no_python_or_migration_role():
    text = (ROOT / "deploy/transport-fuel/Dockerfile.gateway").read_text()
    assert text.startswith("FROM nginx:1.27-alpine")
    assert "org.opencontainers.image.revision=$RELEASE_SHA" in text
    assert "COPY --chmod=0644 deploy/transport-fuel/api-gateway.conf.template" in text
    assert "RUN " not in text and "uvicorn" not in text and "alembic" not in text
