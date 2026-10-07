import os
import re
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
    assert compose.count("network_mode: host") == 2
    assert "TRANSPORT_PUBLIC_API_PORT:-12301" in compose
    assert "TRANSPORT_PUBLIC_WEB_PORT:-12305" in compose
    assert "http://127.0.0.1:14001" in compose
    # Dagster는 공용 제어 평면이다(Manager ADR-54) — 공용 webserver의 loopback을 부르고, 옛 전용
    # webserver(14004)와 그 앞의 12302 gateway는 없다.
    assert 'TRANSPORT_DAGSTER_INTERNAL_URL: "${TRANSPORT_DAGSTER_INTERNAL_URL:-http://127.0.0.1:11002}"' in compose
    assert "127.0.0.1:14004" not in compose
    assert "\n  transport-dagster-gateway:" not in compose  # 서비스 정의가 없다(주석의 언급은 무관)
    assert "TRANSPORT_DAGSTER_PORT" not in compose
    assert "기본 `kor-travel-transport` Compose와 독립된" in compose


def test_provider_status_and_worker_share_bus_collection_switch() -> None:
    compose = (ROOT / "docker-compose.shared.yml").read_text(encoding="utf-8")
    before_services, services = compose.split("\nservices:\n", 1)
    backend = services.split("  backend:\n", 1)[1].split("  dagster-migrate:\n", 1)[0]
    contract = 'BUS_REFERENCE_COLLECTION_ENABLED: "${BUS_REFERENCE_COLLECTION_ENABLED:-false}"'
    assert contract in before_services
    assert contract in backend


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
    frontend = ROOT / "packages/kor-travel-transport-admin/frontend"
    map_view = (frontend / "components/transport-map.tsx").read_text(encoding="utf-8")
    style = (frontend / "lib/vworld-style.ts").read_text(encoding="utf-8")

    assert 'NEXT_PUBLIC_VWORLD_API_KEY: "${NEXT_PUBLIC_VWORLD_API_KEY:?' in compose
    assert "ARG NEXT_PUBLIC_VWORLD_API_KEY" in dockerfile
    assert "ENV NEXT_PUBLIC_VWORLD_API_KEY=${NEXT_PUBLIC_VWORLD_API_KEY}" in dockerfile
    # Next.js는 정적 참조만 번들에 넣는다. 지도는 Map in-repo style builder 사본으로 WMTS URL에 키를 넣는다.
    assert "process.env.NEXT_PUBLIC_VWORLD_API_KEY" in map_view
    assert "https://api.vworld.kr/req/wmts/1.0.0/" in style
    assert '"maplibre-gl"' in package
    assert '"vworld-map-web"' not in package


def test_transport_gateway_contract_has_bounded_upstreams() -> None:
    api_gateway = (ROOT / "deploy/transport-admin/api-gateway.conf.template").read_text(encoding="utf-8")
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
    assert "isAllowedTransportPath" in upstream
    assert "fetchNoStore" in proxy
    # 옛 전용 Dagster gateway(12302)는 공용 plane 합류로 없어졌다. 외부 Dagster UI는 공용 gateway다.
    assert not (ROOT / "deploy/transport-admin/dagster-gateway.conf.template").exists()
    assert not (ROOT / "deploy/transport-admin/Dockerfile.dagster-gateway").exists()


def test_transport_admin_dagster_proxy_forwards_only_scoped_named_operations() -> None:
    """공용 webserver에는 다른 프로젝트의 run·schedule이 있다 — 브라우저의 GraphQL 문서를 넘기지 않는다."""

    frontend = ROOT / "packages/kor-travel-transport-admin/frontend"
    route = (frontend / "app/api/dagster/graphql/route.ts").read_text(encoding="utf-8")
    scope = (frontend / "lib/dagster-scope.ts").read_text(encoding="utf-8")

    assert "scopedDagsterRequest(parsed)" in route
    assert "body: scoped.body" in route
    # 원문 body를 그대로 넘기지 않는다 — upstream fetch의 본문은 scope가 만든 것뿐이다.
    assert re.findall(r"\bbody(?::\s*[\w.]+)?\s*[,}]", route.split("await fetch(", 1)[1].split(");", 1)[0]) == ["body: scoped.body,"]
    assert "readBounded(response.body, 4_194_304)" in route
    assert "AbortSignal.timeout(10_000)" in route
    assert 'TRANSPORT_DAGSTER_INTERNAL_URL ?? "http://127.0.0.1:11002"' in route
    assert "repositoriesOrError" not in scope.split("*/", 1)[1]
    assert 'process.env.NEXT_PUBLIC_TRANSPORT_DAGSTER_URL ?? "https://dagster.digitie.mywire.org"' in scope


def test_transport_runtime_forwards_port_guideline_and_timetable_limits() -> None:
    base_compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    shared_compose = (ROOT / "docker-compose.shared.yml").read_text(encoding="utf-8")

    for variable in (
        "PORT_GUIDELINE_COLLECTION_ENABLED",
        "FERRY_TIMETABLE_COLLECTION_ENABLED",
        "FERRY_TIMETABLE_STORAGE_DAYS",
        "FERRY_TIMETABLE_COLLECTION_MAX_PROVIDER_CALLS",
        "FERRY_TIMETABLE_COLLECTION_INTERVAL_SECONDS",
        "FERRY_TIMETABLE_CACHE_SECONDS",
        "FERRY_TIMETABLE_CACHE_MAX_ENTRIES",
        "FERRY_TIMETABLE_MIN_INTERVAL_SECONDS",
        "FERRY_TIMETABLE_MAX_DAYS_AHEAD",
        "BUS_TIMETABLE_CACHE_SECONDS",
        "BUS_TIMETABLE_CACHE_MAX_ENTRIES",
        "BUS_TIMETABLE_MIN_INTERVAL_SECONDS",
    ):
        assert variable in base_compose
        assert variable in shared_compose

    assert "BUS_REFERENCE_COLLECTION_ENABLED" in shared_compose
    assert 'DATA_GO_KR_SERVICE_KEY: "${DATA_GO_KR_SERVICE_KEY:-}"' in shared_compose
