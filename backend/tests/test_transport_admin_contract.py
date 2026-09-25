import os
from pathlib import Path


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
# Docker regression image에는 계약 검증에 필요한 무비밀 admin 파일만 복사한다.
ROOT = (
    _BACKEND_ROOT / "compose-contract"
    if (_BACKEND_ROOT / "compose-contract" / "docker-compose.transport-admin.yml").is_file()
    else Path(__file__).resolve().parents[2]
)


def iter_typescript_sources(root: Path):
    for directory, directories, filenames in os.walk(root):
        directories[:] = [name for name in directories if name not in {"node_modules", ".next"}]
        for filename in filenames:
            if filename.endswith(".ts"):
                yield Path(directory) / filename


def test_transport_admin_is_a_separate_host_network_stack() -> None:
    compose = (ROOT / "docker-compose.transport-admin.yml").read_text(encoding="utf-8")

    assert "name: kor-travel-transport-admin" in compose
    assert compose.count("network_mode: host") == 3
    assert "TRANSPORT_PUBLIC_API_PORT:-12301" in compose
    assert "TRANSPORT_DAGSTER_PORT:-12302" in compose
    assert "TRANSPORT_PUBLIC_WEB_PORT:-12305" in compose
    assert "http://127.0.0.1:14001" in compose
    assert "http://127.0.0.1:14004" in compose
    assert "parking-radar" in compose


def test_transport_admin_does_not_receive_provider_or_database_credentials() -> None:
    compose = (ROOT / "docker-compose.transport-admin.yml").read_text(encoding="utf-8")
    admin_root = ROOT / "packages/kor-travel-transport-admin/frontend"
    admin_sources = "\n".join(
        source.read_text(encoding="utf-8") for source in iter_typescript_sources(admin_root)
    )

    assert "DATABASE_URL" not in compose
    assert "DATA_GO_KR_SERVICE_KEY" not in compose
    assert "KEX_EX_API_KEY" not in compose
    assert "RUSTFS_SECRET_ACCESS_KEY" not in compose
    assert "DATA_GO_KR_SERVICE_KEY" not in admin_sources
    assert "RUSTFS_SECRET_ACCESS_KEY" not in admin_sources


def test_transport_admin_builds_the_vworld_browser_key_into_the_map_bundle() -> None:
    compose = (ROOT / "docker-compose.transport-admin.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "packages/kor-travel-transport-admin/frontend/Dockerfile").read_text(encoding="utf-8")
    package = (ROOT / "packages/kor-travel-transport-admin/frontend/package.json").read_text(encoding="utf-8")

    assert "NEXT_PUBLIC_VWORLD_API_KEY" in compose
    assert "ARG NEXT_PUBLIC_VWORLD_API_KEY" in dockerfile
    assert "ENV NEXT_PUBLIC_VWORLD_API_KEY=${NEXT_PUBLIC_VWORLD_API_KEY}" in dockerfile
    assert '"vworld-map-web"' in package


def test_transport_gateway_contract_has_bounded_upstreams_and_dagster_auth() -> None:
    api_gateway = (ROOT / "deploy/transport-admin/api-gateway.conf.template").read_text(encoding="utf-8")
    dagster_gateway = (ROOT / "deploy/transport-admin/dagster-gateway.conf.template").read_text(encoding="utf-8")
    proxy = (ROOT / "packages/kor-travel-transport-admin/frontend/app/api/transport/[...path]/route.ts").read_text(encoding="utf-8")
    upstream = (ROOT / "packages/kor-travel-transport-admin/frontend/lib/upstream.ts").read_text(encoding="utf-8")

    assert "proxy_pass http://127.0.0.1:14001" in api_gateway
    assert "location ~ ^/v1/transport/" in api_gateway
    assert "features/places" in api_gateway
    assert "bus/(terminals|timetable)" in api_gateway
    assert "ports/[^/]+/timetable" in api_gateway
    assert "limit_except GET" in api_gateway
    assert "location / { return 404; }" in api_gateway
    assert "/admin/backups" not in api_gateway
    assert "proxy_set_header Host 127.0.0.1" in api_gateway
    assert "proxy_pass http://127.0.0.1:14004" in dagster_gateway
    assert "auth_basic" in dagster_gateway
    assert "transport_dagster_csrf_block" in dagster_gateway
    assert "isAllowedTransportPath" in upstream
    assert "fetchNoStore" in proxy


def test_transport_runtime_forwards_port_guideline_and_timetable_limits() -> None:
    base_compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    shared_compose = (ROOT / "docker-compose.shared.yml").read_text(encoding="utf-8")

    for variable in ("PORT_GUIDELINE_COLLECTION_ENABLED", "FERRY_TIMETABLE_CACHE_SECONDS", "FERRY_TIMETABLE_MAX_DAYS_AHEAD"):
        assert variable in base_compose
        assert variable in shared_compose

    assert "BUS_REFERENCE_COLLECTION_ENABLED" in shared_compose
