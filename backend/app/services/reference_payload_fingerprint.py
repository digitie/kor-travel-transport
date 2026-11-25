"""T3 기준정보 본문을 만드는 코드의 지문(ADR-016). 배포 식별자(RELEASE_SHA)가 아니라 본문을 바꿀 수 있는 코드만 본다.

입력 revision(`reference_export_revision`)의 namespace에 들어간다. 같은 코드면 어느 프로세스·호스트·배포에서도 같은
값이라 관계없는 배포는 본문(artifact)을 그대로 재사용하고, API와 code-server의 RELEASE_SHA가 달라도 head가
뒤집히지 않는다. 지문에 들어가는 것:

- 본문을 만드는 모듈의 **전체** 소스(`inspect.getsource`) — 함수 단위 허용 목록이 아니라 모듈 단위다(덜 무효화되는
  것보다 더 무효화되는 편이 싸다). 어떤 모듈을 넣는지는 `export_references.PAYLOAD_CODE`가 정하고, 시험
  (`test_reference_payload_fingerprint.py`)이 builder에서 닿는 `app.*` 함수·모듈이 모두 그 안(또는 사유가 적힌 제외
  목록)에 있는지 검사한다.
- builder 모듈의 단순 상수(str·int·유한 float·bool·None과 그 tuple) — 다른 모듈에서 가져온 source 이름 등.
  dunder(`__file__` 등 설치 경로)는 넣지 않는다.
- page model의 JSON schema(`model_json_schema`) — 읽기 때 같은 model로 다시 검증하지만, schema가 바뀌면 옛 본문을
  재사용하지 않는다.
- 본문 값·직렬화에 영향을 주는 배포판(형제 라이브러리·pydantic·SQLAlchemy·asyncpg)의 설치 버전과 VCS commit, Python
  major.minor. commit이 없는 git/경로 설치(editable 개발 환경)는 형제 라이브러리의 해당 모듈 소스를 대신 해시한다.

지문을 만들 수 없으면(소스 없는 배포 등) None이고, 호출자는 artifact 없는 완전 구성 경로로 간다(느리지만 정확하다).
이 상태는 `/health`의 `reference_artifacts: "disabled"`로 드러난다.
"""
from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import logging
import math
import sys
from collections.abc import Iterable, Mapping
from importlib import metadata
from pathlib import Path
from types import ModuleType

logger = logging.getLogger(__name__)

#: 지문 구성 방식을 바꾸면 올린다(구성 규칙 자체의 변경도 다른 지문이 되게).
FINGERPRINT_SCHEME = "reference-payload-code-v2"
#: 본문 값·직렬화에 영향을 주는 배포판. 형제 라이브러리(주소 행정구역 DTO·공항 좌표)와 model 직렬화·DB 값 변환.
PAYLOAD_DISTRIBUTIONS = ("kor-travel-common", "python-krairport-api", "pydantic", "pydantic-core", "sqlalchemy", "asyncpg")
#: commit_id가 없는 설치(editable·경로)에서 버전 대신 해시할 형제 라이브러리 모듈. 운영 이미지는 git commit이 있다.
SOURCE_FALLBACK_MODULES = {
    "kor-travel-common": ("kortravelcommon.reverse_address", "kortravelcommon.address_providers"),
    "python-krairport-api": ("krairport",),
}

_SIMPLE = (str, int, bool, type(None))


def _qualified_name(obj) -> str:
    if isinstance(obj, ModuleType):
        return obj.__name__
    return f"{obj.__module__}.{obj.__qualname__}"


def _source(obj) -> str:
    return inspect.getsource(obj)


def _simple_constant(value):
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, _SIMPLE):
        return True
    return isinstance(value, tuple) and all(_simple_constant(item) for item in value)


def module_constants(module: ModuleType) -> dict:
    """모듈 전역의 단순 상수. 다른 모듈에서 import한 source 이름(예: TAGO_BUS_SOURCE)도 값으로 들어간다."""
    return {name: value for name, value in sorted(vars(module).items())
            if not name.startswith("__") and _simple_constant(value)}


def _package_sources(module_name: str) -> dict:
    """모듈(패키지면 그 아래 .py 전부)의 소스. 줄바꿈은 universal newline으로 읽는다."""
    module = importlib.import_module(module_name)
    path = Path(module.__file__)
    if path.name != "__init__.py":
        return {module_name: _source(module)}
    root = path.parent
    return {str(file.relative_to(root.parent)).replace("\\", "/"): file.read_text(encoding="utf-8")
            for file in sorted(root.rglob("*.py"))}


def distribution_identity(name: str) -> dict:
    """설치 버전과 VCS commit. git 의존성은 버전 문자열이 그대로여도 commit이 바뀌면 다른 값이 된다."""
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return {"installed": False}
    identity = {"installed": True, "version": dist.version}
    raw = dist.read_text("direct_url.json")
    vcs = {}
    if raw:
        try:
            vcs = json.loads(raw).get("vcs_info") or {}
        except (ValueError, AttributeError):
            vcs = {}
    # URL은 넣지 않는다(같은 commit을 https·ssh로 받아도 같은 코드다).
    if vcs.get("commit_id"):
        identity["commit_id"] = str(vcs["commit_id"])
    elif raw and name in SOURCE_FALLBACK_MODULES:
        # commit 없는 경로/editable 설치(개발 환경): 버전 문자열이 그대로여도 소스가 바뀌면 다른 값이 되게 한다.
        identity["source_sha256"] = hashlib.sha256(json.dumps(
            {module: _package_sources(module) for module in SOURCE_FALLBACK_MODULES[name]},
            sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return identity


def collect_payload_components(*, code: Iterable, constant_modules: Iterable[ModuleType] = (),
                               page_models: Iterable[type] = (),
                               distributions: Iterable[str] = PAYLOAD_DISTRIBUTIONS) -> dict:
    """지문에 들어가는 구성요소를 이름 → 값으로 모은다. 순서와 무관하게 같은 입력이면 같은 dict다."""
    return {
        "scheme": FINGERPRINT_SCHEME,
        "python": list(sys.version_info[:2]),
        "code": {_qualified_name(obj): _source(obj) for obj in code},
        "constants": {module.__name__: module_constants(module) for module in constant_modules},
        "schemas": {_qualified_name(model): model.model_json_schema() for model in page_models},
        "distributions": {name: distribution_identity(name) for name in distributions},
    }


def fingerprint_components(components: Mapping) -> str:
    body = json.dumps(components, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(body.encode()).hexdigest()


def payload_code_fingerprint(**kwargs) -> str | None:
    """구성요소를 모아 sha256 hex를 낸다. 소스를 읽을 수 없으면 None(호출자는 artifact 경로를 쓰지 않는다)."""
    try:
        return fingerprint_components(collect_payload_components(**kwargs))
    except (OSError, TypeError, ValueError, ImportError) as exc:
        logger.warning("reference payload code fingerprint unavailable (%s); reference artifacts disabled",
                       type(exc).__name__)
        return None
