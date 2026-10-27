"""Map current 플래그와 수집 범위 env가 API(backend)와 code-server에 같은 정본으로 들어가는지 본다.

플래그가 code-server에만 있으면 수집기는 Map 모드(head 승격·엄격 주차 경로)로 바뀌는데 API의
`/v1/service/exports/*`는 Settings 기본값 False로 계속 503이다. 주차·교통 export의 scope hash도
`AIRPORT_CODES_CSV`·`ENABLE_INCHEON_COLLECTION`·`TRANSPORT_ROUTE_NOS_CSV`·`TRANSPORT_CONZONE_IDS_CSV`로
프로세스마다 따로 계산하므로, env 파일에서 키가 빠졌을 때의 기본값까지 같아야 API가 수집기의 head를 찾는다.
운영 렌더(`docker-compose.yml` + `docker-compose.shared.yml`)의 서비스별 유효 env를 비교한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
# Docker regression image에는 무비밀 compose 파일만 compose-contract/에 복사된다.
ROOT = (
    _BACKEND_ROOT / "compose-contract"
    if (_BACKEND_ROOT / "compose-contract" / "docker-compose.shared.yml").is_file()
    else _BACKEND_ROOT.parent
)

#: API와 수집기가 함께 읽어야 export 활성·scope hash가 맞는 키.
_SCOPE_KEYS = (
    "TRANSPORT_MAP_CURRENT_ENABLED",
    "AIRPORT_CODES_CSV",
    "ENABLE_INCHEON_COLLECTION",
    "TRANSPORT_ROUTE_NOS_CSV",
    "TRANSPORT_CONZONE_IDS_CSV",
)


class _ComposeLoader(yaml.SafeLoader):
    """Compose 전용 `!reset`·`!override` 태그를 태그 없는 값처럼 읽는다."""


def _construct_tagged(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    return loader.construct_scalar(node)


for _tag in ("!reset", "!override"):
    _ComposeLoader.add_constructor(_tag, _construct_tagged)


def _services(name: str) -> dict[str, dict[str, Any]]:
    document = yaml.load((ROOT / name).read_text(encoding="utf-8"), Loader=_ComposeLoader) or {}
    return document.get("services") or {}


def _environment(service: dict[str, Any] | None) -> dict[str, str]:
    value = (service or {}).get("environment") or {}
    if isinstance(value, list):  # `KEY=value` 목록 형식
        return dict(str(item).split("=", 1) for item in value)
    return {str(key): str(item) for key, item in value.items()}


def _effective(name: str) -> dict[str, str]:
    """운영 렌더의 서비스 env — compose는 같은 키를 뒤 파일(shared overlay) 값으로 덮는다."""
    environment = _environment(_services("docker-compose.yml").get(name))
    environment.update(_environment(_services("docker-compose.shared.yml").get(name)))
    return environment


def test_api_and_code_server_read_the_same_map_flag_and_scope() -> None:
    api, code_server = _effective("backend"), _effective("dagster-code-server")
    missing = [(name, key) for name, env in (("backend", api), ("dagster-code-server", code_server))
               for key in _SCOPE_KEYS if key not in env]
    assert not missing, missing
    different = {key: (api[key], code_server[key]) for key in _SCOPE_KEYS if api[key] != code_server[key]}
    assert not different, different
    # 운영 기본은 꺼짐이다. 켤 때는 env 파일의 한 값이 두 프로세스에 함께 닿는다.
    assert api["TRANSPORT_MAP_CURRENT_ENABLED"] == "${TRANSPORT_MAP_CURRENT_ENABLED:-false}"


def test_local_backend_reads_the_map_flag_too() -> None:
    backend = _environment(_services("docker-compose.yml").get("backend"))
    assert backend.get("TRANSPORT_MAP_CURRENT_ENABLED") == "${TRANSPORT_MAP_CURRENT_ENABLED:-false}"
