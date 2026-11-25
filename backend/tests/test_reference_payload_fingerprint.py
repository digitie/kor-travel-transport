"""T3 본문 코드 지문 계약(ADR-016): 본문을 바꿀 수 있는 코드만 namespace를 바꾸고, 같은 코드는 어디서나 같은 값이다."""
# ruff: noqa: F811
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
from test_service_exports import _run, export_client  # noqa: F401

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
