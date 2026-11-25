"""T3 본문 코드 지문 계약(ADR-016): 본문을 바꿀 수 있는 코드만 namespace를 바꾸고, 같은 코드는 어디서나 같은 값이다."""
# ruff: noqa: F811
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select

from app.models import ReferenceExportArtifact as Artifact
from app.services import export_references as refs
from app.services import reference_payload_fingerprint as fp
from test_reference_export_reuse import _get, _prepare
from test_service_exports import HEADERS, _run, export_client  # noqa: F401

_BACKEND = Path(__file__).resolve().parents[1]


async def _builder_a(session, heads):
    yield [{"name": "a"}]


async def _builder_b(session, heads):
    yield [{"name": "b", "extra": True}]


class _PageA(BaseModel):
    name: str


class _PageB(BaseModel):
    name: str
    extra: bool = False


def _fingerprint(code=(_builder_a,), page_models=(_PageA,), constant_modules=(), distributions=("pydantic",)):
    return fp.payload_code_fingerprint(code=code, page_models=page_models, constant_modules=constant_modules,
                                       distributions=distributions)


def test_production_fingerprint_is_computed_at_import_and_is_sha256():
    value = refs.REFERENCE_PAYLOAD_FINGERPRINT
    assert isinstance(value, str) and len(value) == 64 and int(value, 16) >= 0


def test_same_inputs_give_same_fingerprint_and_order_does_not_matter():
    assert _fingerprint() == _fingerprint()
    both = _fingerprint(code=(_builder_a, _builder_b))
    assert both == _fingerprint(code=(_builder_b, _builder_a))


def test_builder_source_change_changes_fingerprint(monkeypatch):
    base = _fingerprint()
    assert _fingerprint(code=(_builder_b,)) != base
    # 같은 함수 이름이어도 소스가 바뀌면(배포된 코드가 달라지면) 다른 값이다.
    original = fp._source
    monkeypatch.setattr(fp, "_source", lambda obj: original(obj) + "\n# changed")
    assert _fingerprint() != base


def test_production_builder_and_address_code_change_fingerprint(monkeypatch):
    """bus/ferry/rail/parking builder·export_admin_addresses 모듈의 소스가 지문에 들어간다."""
    kwargs = dict(code=(refs._bus_payload_batches, refs._ferry_payload_batches, refs._rail_payload_batches,
                        refs._parking_payload_batches, refs._export_addresses_module),
                  page_models=(), constant_modules=(), distributions=())
    base = fp.payload_code_fingerprint(**kwargs)
    original = fp._source
    for target in kwargs["code"]:
        monkeypatch.setattr(fp, "_source", lambda obj, target=target: original(obj) + ("#x" if obj is target else ""))
        assert fp.payload_code_fingerprint(**kwargs) != base, target
    monkeypatch.setattr(fp, "_source", original)
    assert fp.payload_code_fingerprint(**kwargs) == base


def test_page_model_schema_change_changes_fingerprint():
    assert _fingerprint(page_models=(_PageB,)) != _fingerprint(page_models=(_PageA,))


def test_production_page_model_schema_change_changes_fingerprint(monkeypatch):
    model = refs.RailStationExportPage
    base = fp.payload_code_fingerprint(code=(), page_models=(model,), distributions=())
    schema = model.model_json_schema()
    monkeypatch.setattr(model, "model_json_schema", classmethod(lambda cls: {**schema, "x-changed": True}))
    assert fp.payload_code_fingerprint(code=(), page_models=(model,), distributions=()) != base


def test_dependency_version_or_commit_change_changes_fingerprint(monkeypatch):
    class Dist:
        def __init__(self, version, commit):
            self.version, self._commit = version, commit

        def read_text(self, name):
            assert name == "direct_url.json"
            return json.dumps({"url": "https://example.invalid/x.git",
                               "vcs_info": {"vcs": "git", "commit_id": self._commit}})

    current = {"dist": Dist("0.1.0", "a" * 40)}
    monkeypatch.setattr(fp.metadata, "distribution", lambda name: current["dist"])
    kwargs = dict(code=(), distributions=("kor-travel-common", "python-krairport-api"))
    base = fp.payload_code_fingerprint(**kwargs)
    current["dist"] = Dist("0.1.1", "a" * 40)
    assert fp.payload_code_fingerprint(**kwargs) != base
    # git 의존성은 버전 문자열이 그대로여도 commit이 바뀌면 다른 값이다.
    current["dist"] = Dist("0.1.0", "b" * 40)
    assert fp.payload_code_fingerprint(**kwargs) != base
    current["dist"] = Dist("0.1.0", "a" * 40)
    assert fp.payload_code_fingerprint(**kwargs) == base


def test_installed_payload_dependencies_are_identified():
    for name in fp.PAYLOAD_DISTRIBUTIONS:
        identity = fp.distribution_identity(name)
        assert identity["installed"] and identity["version"], name


def test_module_constants_change_fingerprint_but_not_install_path():
    module = ModuleType("fake_builder_constants")
    module.SOURCE = "data_go_kr_tago"
    module.FIELDS = ("id", "name")
    module.__file__ = "/one/place.py"
    base = _fingerprint(constant_modules=(module,))
    module.__file__ = "/another/place.py"
    assert _fingerprint(constant_modules=(module,)) == base
    module.SOURCE = "other_source"
    assert _fingerprint(constant_modules=(module,)) != base


def test_unreadable_source_disables_artifacts_instead_of_failing(monkeypatch):
    def missing(_obj):
        raise OSError("could not get source code")
    monkeypatch.setattr(fp, "_source", missing)
    assert _fingerprint() is None


def test_same_code_gives_same_fingerprint_across_processes():
    """다른 프로세스(다른 hash seed, RELEASE_SHA 유무)에서도 같은 코드면 같은 값이다 — API와 code-server가 일치한다."""
    script = "from app.services.export_references import REFERENCE_PAYLOAD_FINGERPRINT as f; print(f)"
    values = set()
    for seed, release in (("1", "unknown"), ("2", "0123456789abcdef0123456789abcdef01234567")):
        env = {**os.environ, "PYTHONHASHSEED": seed, "RELEASE_SHA": release}
        out = subprocess.run([sys.executable, "-B", "-c", script], cwd=_BACKEND, env=env, capture_output=True,
                             text=True, timeout=120, check=True)
        values.add(out.stdout.strip().splitlines()[-1])
    assert values == {refs.REFERENCE_PAYLOAD_FINGERPRINT}


def test_artifact_is_not_reused_when_code_fingerprint_differs(export_client, monkeypatch):
    c = export_client
    _prepare(c)
    first = _get(c)
    assert first.status_code == 200, first.text

    async def artifacts(s):
        return list((await s.execute(select(Artifact.id, Artifact.content_digest))).all())

    before = _run(c, artifacts)
    assert len(before) == 1
    # 같은 지문이면(RELEASE_SHA가 무엇이든) 같은 본문을 재사용한다.
    c.app.state.settings.release_sha = "fedcba9876543210fedcba9876543210fedcba98"
    assert _get(c).status_code == 200
    assert _run(c, artifacts) == before
    # 본문 코드가 바뀌면(지문이 다르면) 같은 DB 입력이어도 새 본문을 만든다.
    monkeypatch.setattr(refs, "REFERENCE_PAYLOAD_FINGERPRINT", "f" * 64)
    changed = _get(c)
    assert changed.status_code == 200, changed.text
    after = _run(c, artifacts)
    assert len(after) == 2 and set(before) < set(after)
    assert changed.json()["items"] == first.json()["items"]

    async def count(s):
        return await s.scalar(select(func.count()).select_from(Artifact))
    assert _run(c, count) == 2


# --- 지문 범위 가드(적대적 리뷰 P1): builder에서 닿는 app.* 코드가 모두 지문 안에 있는가 ---------------------------

#: 지문(PAYLOAD_CODE)에 넣지 않는 app.* 모듈과 그 사유. 여기에 없고 PAYLOAD_CODE에도 없는 모듈에 builder가 닿으면 실패한다.
_EXEMPT_MODULES = {
    # 예외·문제 코드만 만든다(본문 값이 아니다).
    "app.core.problems": "오류 응답만",
    # 요청별 계측 카운터.
    "app.core.read_timing": "계측만",
    # ORM 정의. 열 값은 입력 revision(`reference_payload_revision`)이 모든 열을 해시해 이미 본다.
    "app.models": "열 값은 DB 입력 revision이 본다",
    # page model(중첩된 ExportAdminAddress·ServiceExportMeta 포함)의 JSON schema가 지문에 들어간다.
    "app.schemas": "page model schema로 본다",
    # batch·예산·경합 예외 같은 배관만(본문 값·직렬화가 아니다).
    "app.services.export_current": "batch·예산·경합 배관만",
}


def _codes(code):
    yield code
    for const in code.co_consts:
        if isinstance(const, type(code)):
            yield from _codes(const)


def _module_of(obj):
    return obj.__name__ if isinstance(obj, ModuleType) else getattr(obj, "__module__", None)


def _reachable_app_modules(entrypoints):
    """co_names를 따라 globals/sys.modules에서 app.* 함수·클래스·모듈을 찾는다(함수 안 지연 import 포함, 재귀)."""
    seen, found = set(), {}

    def walk(fn):
        if fn in seen:
            return
        seen.add(fn)
        for code in _codes(fn.__code__):
            for name in code.co_names:
                obj = fn.__globals__.get(name, sys.modules.get(name))
                module = _module_of(obj) if obj is not None else None
                if not isinstance(module, str) or not (module == "app" or module.startswith("app.")):
                    continue
                found.setdefault(module, set()).add(name)
                if inspect.isfunction(obj):
                    walk(inspect.unwrap(obj))

    for entry in entrypoints:
        walk(entry)
    return found


def _entrypoints():
    from app.core.config import Settings
    from app.services.reference_artifacts import prepare_artifact
    from app.services.reference_export_revision import reference_payload_revision
    specs = refs.reference_specs(Settings(database_url="sqlite+aiosqlite:///:memory:"))
    return [spec.payload_batches for spec in specs] + [prepare_artifact, reference_payload_revision], specs


def test_every_spec_builder_is_inside_the_fingerprinted_code():
    covered = {module.__name__ for module in refs.PAYLOAD_CODE}
    _, specs = _entrypoints()
    assert {spec.kind for spec in specs} >= {"bus-terminals-v1", "ferry-ports-v1", "rail-stations-v1"}
    for spec in specs:
        assert spec.payload_batches.__module__ in covered, spec.kind
        assert spec.page_model in refs.PAYLOAD_PAGE_MODELS, spec.kind


def test_builder_reachable_app_code_is_fingerprinted_or_explicitly_exempt():
    covered = {module.__name__ for module in refs.PAYLOAD_CODE}
    entrypoints, _ = _entrypoints()
    found = _reachable_app_modules(entrypoints)
    uncovered = {module: sorted(names) for module, names in found.items()
                 if module not in covered and module not in _EXEMPT_MODULES}
    assert not uncovered, f"builder가 지문 밖 app.* 코드에 닿는다 — PAYLOAD_CODE에 넣거나 사유와 함께 제외: {uncovered}"
    # 가드 자체가 동작하는지: 알려진 helper가 실제로 발견된다.
    assert {"serialize_utc"} <= found["app.core.time_utils"]
    assert {"export_admin_addresses"} <= found["app.services.export_addresses"]
    assert {"persisted_station_links"} <= found["app.services.rail_station_mapping"]


def test_guard_flags_a_new_uncovered_helper():
    fake = ModuleType("app.services.some_new_helper")

    def helper(value):
        return value

    helper.__module__ = fake.__name__
    namespace = {"helper": helper}
    exec("def builder(rows):\n    return [helper(r) for r in rows]\n", namespace)
    found = _reachable_app_modules([namespace["builder"]])
    assert "app.services.some_new_helper" in found


def test_full_module_sources_are_in_the_fingerprint(monkeypatch):
    """함수 단위가 아니라 모듈 전체: builder 밖 함수(spec 배선·time_utils)만 바뀌어도 지문이 바뀐다."""
    from app.core import time_utils
    from app.services import rail_station_mapping
    kwargs = dict(code=refs.PAYLOAD_CODE, page_models=(), constant_modules=(), distributions=())
    base = fp.payload_code_fingerprint(**kwargs)
    original = fp._source
    for target in (refs, time_utils, rail_station_mapping):
        monkeypatch.setattr(fp, "_source", lambda obj, target=target: original(obj) + ("#x" if obj is target else ""))
        assert fp.payload_code_fingerprint(**kwargs) != base, target.__name__
    monkeypatch.setattr(fp, "_source", original)
    assert fp.payload_code_fingerprint(**kwargs) == base


def test_runtime_distributions_and_python_version_are_inputs(monkeypatch):
    assert {"pydantic", "pydantic-core", "sqlalchemy", "asyncpg"} <= set(fp.PAYLOAD_DISTRIBUTIONS)
    base = fp.payload_code_fingerprint(code=(), distributions=())
    monkeypatch.setattr(fp.sys, "version_info", (3, 99, 0, "final", 0))
    assert fp.payload_code_fingerprint(code=(), distributions=()) != base


def test_non_finite_float_constants_are_skipped():
    module = ModuleType("fake_float_constants")
    module.FINITE, module.NAN, module.INF = 1.5, float("nan"), float("inf")
    assert fp.module_constants(module) == {"FINITE": 1.5}
    assert _fingerprint(constant_modules=(module,)) is not None


def test_editable_install_without_commit_hashes_sibling_source(monkeypatch):
    class Dist:
        version = "0.1.0"

        def read_text(self, name):
            return json.dumps({"url": "file:///src/kor-travel-common", "dir_info": {"editable": True}})

    monkeypatch.setattr(fp.metadata, "distribution", lambda name: Dist())
    sources = {"kortravelcommon.reverse_address": "a = 1\n"}
    monkeypatch.setattr(fp, "_package_sources", lambda module: {module: sources.get(module, "")})
    first = fp.distribution_identity("kor-travel-common")
    assert "source_sha256" in first and "commit_id" not in first
    sources["kortravelcommon.reverse_address"] = "a = 2\n"
    assert fp.distribution_identity("kor-travel-common")["source_sha256"] != first["source_sha256"]
    # PyPI 배포판(direct_url 없음)은 버전만 본다.
    assert fp.distribution_identity("pydantic").keys() == {"installed", "version"}


def test_etag_changes_when_the_fingerprint_changes(export_client, monkeypatch):
    """조회 경로·envelope가 바뀐 배포(지문 변경)에서 옛 ETag로 304를 내지 않는다."""
    c = export_client
    _prepare(c)
    first = _get(c)
    assert first.status_code == 200, first.text
    same = c.get("/v1/service/exports/rail-stations", headers={**HEADERS, "If-None-Match": first.headers["ETag"]},
                 params={"limit": 1})
    assert same.status_code == 304
    monkeypatch.setattr(refs, "REFERENCE_PAYLOAD_FINGERPRINT", "e" * 64)
    changed = c.get("/v1/service/exports/rail-stations", headers={**HEADERS, "If-None-Match": first.headers["ETag"]},
                    params={"limit": 1})
    assert changed.status_code == 200 and changed.headers["ETag"] != first.headers["ETag"]
