# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Youn-sok Choi (digitie)
"""정상 이미지 산출의 실제 Git/archive/OCI 경계. Docker·네트워크·DB는 호출하지 않는다."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import re
import shlex
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts" if (ROOT / "scripts").is_dir() else Path("/app/scripts")


@pytest.fixture
def builder():
    spec = importlib.util.spec_from_file_location(
        "transport_build_test", SCRIPTS / "build-images.py"
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def source(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    files = {
        ".gitignore": ".env\n",
        ".dockerignore": "**/.env.*\n!.env.prod.example\n",
        "frontend/Dockerfile": "FROM scratch\nCOPY frontend /app\n",
        "frontend/app.txt": "public",
        "frontend/src/shared.ts": "shared input",
        "frontend/.env.example": "public example",
        ".env.prod.example": "public root example",
        "backend/Dockerfile": "FROM scratch\nCOPY backend /app\n",
        "backend/app.txt": "backend",
        "backend/Dockerfile.dagster-gateway": "FROM scratch\nCOPY backend/app.txt /app/app.txt\n",
        "packages/kor-travel-transport-admin/frontend/Dockerfile": "FROM scratch\nCOPY frontend/src /frontend/src\nCOPY packages/kor-travel-transport-admin/frontend /app\n",
        "packages/kor-travel-transport-admin/frontend/app.txt": "admin",
    }
    for name, content in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(repo), *args], text=True
        ).strip()

    git("init", "-q")
    git("config", "user.name", "transport-build-test")
    git("config", "user.email", "build-test@example.invalid")
    git(
        "remote", "add", "origin", "https://github.com/digitie/kor-travel-transport.git"
    )
    git("add", "--", *files)
    git("-c", "core.hooksPath=/dev/null", "commit", "-qm", "fixture")
    return (repo, git)


def args(builder, source, tmp_path, *extra):
    repo, git = source
    return builder.arguments(
        [
            "--repo",
            str(repo),
            "--revision",
            git("rev-parse", "HEAD"),
            "--expected-tree",
            git("rev-parse", "HEAD^{tree}"),
            "--role",
            "frontend",
            "--architecture",
            "amd64",
            "--output-dir",
            str(tmp_path / "output"),
            *extra,
        ]
    )


class FakeDocker:
    """Docker를 실행하지 않고 정상 build 결과와 변조 결과를 분리한다."""

    def __init__(self, builder, monkeypatch, mutation=None):
        self.builder, self.calls, self.image = (builder, [], None)
        original = builder.run

        def build(command, env, log, values):
            self.calls.append(command)
            labels = {
                command[i + 1].split("=", 1)[0]: command[i + 1].split("=", 1)[1]
                for i, part in enumerate(command[:-1])
                if part == "--label"
            }
            role = labels["io.kor-travel-transport.build-role"]
            release_name = builder.contract.BUILD_RECIPES[role][2]
            self.image = {
                "Id": "sha256:" + "a" * 64,
                "Os": "linux",
                "Architecture": command[command.index("--platform") + 1].removeprefix(
                    "linux/"
                ),
                "Config": {
                    "User": "node"
                    if role in {"frontend", "transport-admin-web"}
                    else "",
                    "Labels": labels,
                    "Env": [release_name + "=" + env[release_name]],
                },
            }
            if mutation:
                mutation(self.image)
            if "--iidfile" in command:
                Path(command[command.index("--iidfile") + 1]).write_text(
                    "sha256:" + "a" * 64
                )
            else:
                output = command[command.index("--output") + 1]
                fields = next(csv.reader([output], strict=True))
                options = dict(field.split("=", 1) for field in fields)
                assert options["type"] == "oci"
                path = Path(options["dest"])
                write_oci(path, self.image["Architecture"], self.image["Config"])
            log.write_text("mock normal build; no Docker executed\n")

        def run(command, **kwargs):
            if command[:3] == ["docker", "image", "inspect"]:
                return json.dumps([self.image]).encode()
            return original(command, **kwargs)

        monkeypatch.setattr(builder, "execute_build", build)
        monkeypatch.setattr(builder, "run", run)


def test_clean_archive_excludes_ignored_untracked_and_covers_shared_admin(
    builder, source, tmp_path
):
    repo, git = source
    (repo / ".env").write_text("PRIVATE_NOT_IN_CONTEXT")
    revision, tree = (git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}"))
    builder.verify_source(repo, revision, tree)
    output = tmp_path / "archive"
    output.mkdir()
    snapshot = builder.materialize(repo, revision, output)
    assert ".env" not in snapshot["files"]
    assert not (output / "source/.env").exists()
    copied = builder.copy_inputs(
        output / "source",
        builder.contract.BUILD_RECIPES["transport-admin-web"][0],
        snapshot,
    )
    assert "frontend/src/shared.ts" in copied["files"]
    assert "packages/kor-travel-transport-admin/frontend/app.txt" in copied["files"]
    public = builder.copy_inputs(output / "source", "frontend/Dockerfile", snapshot)
    assert "frontend/.env.example" not in public["files"]
    assert "frontend/app.txt" in public["files"]


@pytest.mark.parametrize(
    "change", ["dirty", "untracked", "head", "tree", "origin", "alternates"]
)
def test_changed_or_noncanonical_source_fails_before_docker(
    builder, source, tmp_path, change
):
    repo, git = source
    a = args(builder, source, tmp_path)
    if change == "dirty":
        (repo / "frontend/app.txt").write_text("changed")
    if change == "untracked":
        (repo / "extra").write_text("changed")
    if change == "head":
        a.revision = "0" * 40
    if change == "tree":
        a.expected_tree = "0" * 40
    if change == "origin":
        git("remote", "set-url", "origin", "https://example.invalid/other.git")
    if change == "alternates":
        (repo / ".git/objects/info/alternates").write_text("/missing\n")
    with pytest.raises(builder.ContractError):
        builder.build(a, {})
    assert not a.output_dir.exists()


def test_context_mutation_rejected(builder, source, tmp_path):
    output = tmp_path / "archive"
    output.mkdir()
    repo, git = source
    snapshot = builder.materialize(repo, git("rev-parse", "HEAD"), output)
    (output / "source/frontend/app.txt").write_text("changed")
    with pytest.raises(builder.ContractError, match="bytes"):
        builder.verify_context(output / "source", snapshot)


def test_gitlink_is_recorded_without_checkout(builder, source, tmp_path):
    repo, git = source
    oid = git("rev-parse", "HEAD")
    git("update-index", "--add", "--cacheinfo", "160000," + oid + ",third_party/frozen")
    git("-c", "core.hooksPath=/dev/null", "commit", "-qm", "gitlink")
    output = tmp_path / "archive"
    output.mkdir()
    value = builder.materialize(repo, git("rev-parse", "HEAD"), output)
    assert value["gitlinks"] == {"third_party/frozen": oid}


@pytest.mark.parametrize(
    "inputs",
    [
        {"DATABASE_URL": "DO_NOT_PRINT_SECRET"},
        {"NEXT_PUBLIC_VWORLD_API_KEY": "wrong-role"},
        {"NEXT_PUBLIC_API_PORT": "0"},
        {"NEXT_PUBLIC_API_BASE_URL": "https://example.invalid:invalid"},
        {"NEXT_PUBLIC_API_BASE_URL": "https://user:password@example.invalid"},
        {"NEXT_PUBLIC_API_BASE_URL": "https://example.invalid/?key=secret"},
    ],
)
def test_wrong_public_role_and_credential_inputs_refuse(
    builder, source, tmp_path, inputs
):
    a = args(builder, source, tmp_path)
    with pytest.raises(builder.ContractError):
        builder.build(a, inputs)
    assert not a.output_dir.exists()


@pytest.mark.parametrize(
    "extra",
    [
        ["--role", "transport-api-gateway"],
        ["--architecture", "amd64,arm64"],
        ["--output", "registry"],
        ["--target", "builder"],
        ["--build-arg", "TOKEN=DO_NOT_PRINT_SECRET"],
        ["--revision", "HEAD"],
    ],
)
def test_invalid_cli_never_echoes_input_values(
    builder, capsys, source, tmp_path, extra
):
    with pytest.raises(SystemExit) as failure:
        args(builder, source, tmp_path, *extra)
    assert failure.value.code == 2
    assert "DO_NOT_PRINT_SECRET" not in capsys.readouterr().err


@pytest.mark.parametrize(
    "bad",
    [
        "id",
        "arch",
        "role",
        "revision",
        "source",
        "release",
        "duplicate-release",
        "root-user",
        "copy",
        "input",
        "tree",
    ],
)
def test_wrong_actual_image_is_not_receipted(
    builder, source, tmp_path, monkeypatch, bad
):
    a = args(builder, source, tmp_path)

    def mutate(image):
        labels = image["Config"]["Labels"]
        if bad == "id":
            image["Id"] = "sha256:" + "b" * 64
        if bad == "arch":
            image["Architecture"] = "arm64"
        if bad == "role":
            labels["io.kor-travel-transport.build-role"] = "backend"
        if bad == "revision":
            labels["org.opencontainers.image.revision"] = "0" * 40
        if bad == "source":
            labels["org.opencontainers.image.source"] = "https://example.invalid/wrong"
        if bad in {"copy", "input", "tree"}:
            name = {
                "copy": "copy-sha256",
                "input": "public-input-sha256",
                "tree": "source-tree",
            }[bad]
            labels["io.kor-travel-transport." + name] = "0" * 64
        if bad == "root-user":
            image["Config"]["User"] = "root"
        if bad == "release":
            image["Config"]["Env"] = ["RELEASE_SHA=unknown"]
        if bad == "duplicate-release":
            image["Config"]["Env"] *= 2

    FakeDocker(builder, monkeypatch, mutate)
    with pytest.raises(builder.ContractError):
        builder.build(a, {})
    assert not (a.output_dir / "build-receipt.json").exists()


def test_normal_build_uses_real_command_result_and_existing_image_mapping(
    builder, source, tmp_path, monkeypatch
):
    a = args(
        builder,
        source,
        tmp_path,
        "--role",
        "backend",
        "--role",
        "dagster-code-server",
        "--role",
        "migrate",
    )
    docker = FakeDocker(builder, monkeypatch)
    receipt = builder.build(a, {"NEXT_PUBLIC_API_PORT": "8000"})
    assert len(docker.calls) == 2
    assert (
        receipt["images"]["backend"]
        == receipt["images"]["dagster-code-server"]
        == receipt["images"]["migrate"]
    )
    assert (
        receipt["normalDockerBuild"] is True and receipt["actualApplyAllowed"] is False
    )
    assert all(cmd[:2] == ["docker", "build"] for cmd in docker.calls)
    assert all("tag" not in cmd and "push" not in cmd for cmd in docker.calls)
    assert "sourceManifestSHA256" in receipt


def test_source_moved_during_normal_build_refuses(
    builder, source, tmp_path, monkeypatch
):
    a = args(builder, source, tmp_path)
    repo, git = source
    docker = FakeDocker(builder, monkeypatch)
    real = builder.execute_build

    def moved(*values):
        real(*values)
        (repo / "frontend/app.txt").write_text("moved during build")
        git("add", "--", "frontend/app.txt")
        git("-c", "core.hooksPath=/dev/null", "commit", "-qm", "move")

    monkeypatch.setattr(builder, "execute_build", moved)
    with pytest.raises(builder.ContractError, match="HEAD"):
        builder.build(a, {})
    assert docker.calls and (not (a.output_dir / "build-receipt.json").exists())


def test_stdout_and_stderr_build_output_is_redacted(builder, monkeypatch, tmp_path):

    class Process:
        stdout = io.StringIO("value=PRIVATE_BROWSER_KEY\n")

        def wait(self):
            return 0

    monkeypatch.setattr(builder.subprocess, "Popen", lambda *a, **k: Process())
    log = tmp_path / "build.log"
    builder.execute_build(["docker", "build"], {}, log, ["PRIVATE_BROWSER_KEY"])
    assert "PRIVATE_BROWSER_KEY" not in log.read_text()
    assert "[REDACTED]" in log.read_text()


def test_owned_dockerfile_coverage_and_role_profiles(builder):
    if (ROOT / "backend/Dockerfile").is_file():
        actual = {
            str(p.relative_to(ROOT))
            for parent in [
                "backend",
                "frontend",
                "packages/kor-travel-transport-admin/frontend",
            ]
            for p in (ROOT / parent).glob("Dockerfile*")
            if p.is_file() and not p.name.endswith(".dockerignore")
        }
        paths = {name: ROOT / name for name in actual}
    else:
        paths = {
            "backend/Dockerfile": Path("/app/Dockerfile"),
            "backend/Dockerfile.dagster-gateway": Path(
                "/app/Dockerfile.dagster-gateway"
            ),
            "frontend/Dockerfile": Path("/app/compose-contract/frontend/Dockerfile"),
            "packages/kor-travel-transport-admin/frontend/Dockerfile": Path(
                "/app/compose-contract/packages/kor-travel-transport-admin/frontend/Dockerfile"
            ),
        }
    assert set(paths) == {value[0] for value in builder.contract.BUILD_RECIPES.values()}
    for role, (name, _, release_name) in builder.contract.BUILD_RECIPES.items():
        text = paths[name].read_text()
        target = builder.contract.BUILD_RECIPES[role][1]
        if target:
            assert re.search(
                r"^FROM .+ AS " + re.escape(target) + r"$", text, re.MULTILINE
            ), role
        if role in {"frontend", "transport-admin-web"}:
            assert target == "runner"
            runner = text.rsplit(" AS runner", 1)[1]
            assert re.search(r"^USER node$", runner, re.MULTILINE), role
        assert "ARG " + release_name + "=unknown" in text, role
        declarations = [
            token
            for line in text.replace(chr(92) + chr(10), " ").splitlines()
            if line.startswith("ENV ")
            for token in shlex.split(line)[1:]
        ]
        assert release_name + "=" + "$" + "{" + release_name + "}" in declarations, role


@pytest.mark.parametrize(
    "value", [{}, {"normalDockerBuild": False}, {"normalDockerBuild": 1}]
)
def test_unobserved_or_false_build_marker_refused(builder, value):
    with pytest.raises(builder.ContractError):
        builder.contract.validate_normal_build_marker(value)


def test_original_m30_and_metadata_only_copy_have_explicit_link(builder):
    fixture = json.loads(
        (Path(__file__).with_name("fixtures") / "normal-build-m30.json").read_text()
    )
    original = fixture["originalProjection"]
    assert original["source"] == "f30dbd823614399d6dc671eb1f1bf4d8f46c6064"
    assert original["architecture"] == "arm64" and original["buildExit"] == 0
    raw = json.dumps(original).encode()
    compatible = fixture["compatibleProjection"]
    with pytest.raises(builder.ContractError):
        builder.contract.validate_normal_build_marker(original)
    builder.contract.validate_normal_build_marker(
        compatible, raw, hashlib.sha256(raw).hexdigest()
    )
    with pytest.raises(builder.ContractError):
        builder.contract.validate_normal_build_marker(compatible, raw, "0" * 64)
    with pytest.raises(builder.ContractError):
        builder.contract.validate_normal_build_marker(
            {**compatible, "image": "other"}, raw, hashlib.sha256(raw).hexdigest()
        )


def write_oci(path, architecture, image_config, mutation=None):
    layer = b"image layer"
    config = {"os": "linux", "architecture": architecture, "config": image_config}

    def descriptor(data):
        return {
            "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }

    config_bytes = json.dumps(config).encode()
    manifest = {"config": descriptor(config_bytes), "layers": [descriptor(layer)]}
    if mutation == "size":
        manifest["layers"][0]["size"] += 1
    manifest_bytes = json.dumps(manifest).encode()
    index = {"manifests": [descriptor(manifest_bytes)]}
    with tarfile.open(path, "w") as t:
        for name, data in [
            ("index.json", json.dumps(index).encode()),
            (
                "blobs/sha256/" + descriptor(config_bytes)["digest"].split(":")[1],
                config_bytes,
            ),
            (
                "blobs/sha256/" + descriptor(manifest_bytes)["digest"].split(":")[1],
                manifest_bytes,
            ),
            (
                "blobs/sha256/" + descriptor(layer)["digest"].split(":")[1],
                b"wrong layer" if mutation == "bytes" else layer,
            ),
        ]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return descriptor(config_bytes)["digest"]


def test_oci_actual_config_and_layer_hash_not_filename_identity(builder, tmp_path):
    path = tmp_path / "result.oci.tar"
    config_id = write_oci(path, "arm64", {"Env": [], "Labels": {}})
    image = builder.oci_image(path)
    assert image["Architecture"] == "arm64"
    assert image["Id"] == config_id


@pytest.mark.parametrize("mutation", ["bytes", "size"])
def test_corrupt_oci_layer_never_counts_as_output(builder, tmp_path, mutation):
    path = tmp_path / "corrupt.oci.tar"
    write_oci(path, "arm64", {"Env": [], "Labels": {}}, mutation)
    with pytest.raises(builder.ContractError, match="layer"):
        builder.oci_image(path)


@pytest.mark.parametrize(
    "architecture,output", [("arm64", "docker"), ("amd64", "oci"), ("arm64", "oci")]
)
def test_single_architecture_outputs_use_actual_normal_build_result(
    builder, source, tmp_path, monkeypatch, architecture, output
):
    a = args(
        builder, source, tmp_path, "--architecture", architecture, "--output", output
    )
    docker = FakeDocker(builder, monkeypatch)
    receipt = builder.build(a, {})
    artifact = receipt["artifacts"]["frontend"]
    assert artifact["architecture"] == architecture
    assert artifact["loaded"] is (output == "docker")
    assert receipt["images"]["frontend"].startswith("sha256:")
    assert "--platform" in docker.calls[0]
    assert "linux/" + architecture in docker.calls[0]
    assert (
        docker.calls[0][:2] == ["docker", "build"]
        if output == "docker"
        else docker.calls[0][:3] == ["docker", "buildx", "build"]
    )
    assert receipt["actualApplyAllowed"] is False


def test_same_bytes_rewrite_is_not_hidden_by_hash_restore(builder, source, tmp_path):
    repo, git = source
    output = tmp_path / "archive"
    output.mkdir()
    snapshot = builder.materialize(repo, git("rev-parse", "HEAD"), output)
    p = output / "source/frontend/app.txt"
    value = p.read_bytes()
    p.write_bytes(b"changed")
    p.write_bytes(value)
    with pytest.raises(builder.ContractError, match="metadata"):
        builder.verify_context(output / "source", snapshot)


def test_interrupted_build_only_terminates_its_owned_group(
    builder, monkeypatch, tmp_path
):
    calls = []

    class BrokenOutput:
        def __iter__(self):
            raise KeyboardInterrupt()

        def close(self):
            calls.append("close")

    class Process:
        pid = 123456789
        stdout = BrokenOutput()

        def poll(self):
            return None

        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            return 0

    monkeypatch.setattr(builder.subprocess, "Popen", lambda *a, **k: Process())
    monkeypatch.setattr(builder.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    with pytest.raises(KeyboardInterrupt):
        builder.execute_build(["docker", "build"], {}, tmp_path / "build.log", [])
    assert calls[0] == (Process.pid, builder.signal.SIGTERM)
    assert ("wait", 15) in calls
    assert "close" in calls


def test_wrong_web_target_is_refused_before_docker(
    builder, source, tmp_path, monkeypatch
):
    a = args(builder, source, tmp_path)
    docker = FakeDocker(builder, monkeypatch)
    monkeypatch.setitem(
        builder.contract.BUILD_RECIPES,
        "frontend",
        ("frontend/Dockerfile", "builder", "RELEASE_SHA"),
    )
    with pytest.raises(builder.ContractError, match="production target"):
        builder.build(a, {})
    assert docker.calls == []
    assert not (a.output_dir / "build-receipt.json").exists()


def test_archive_explicitly_uses_canonical_lf_despite_local_git_setting(
    builder, source, tmp_path, monkeypatch
):
    repo, git = source
    git("config", "core.autocrlf", "true")
    commands = []
    original = builder.run

    def observe(command, **kwargs):
        commands.append(command)
        return original(command, **kwargs)

    monkeypatch.setattr(builder, "run", observe)
    output = tmp_path / "canonical-archive"
    output.mkdir()
    builder.materialize(repo, git("rev-parse", "HEAD"), output)
    archive = next(command for command in commands if "archive" in command)
    assert archive[archive.index("-c") + 1] == "core.autocrlf=false"
    assert archive.index("core.autocrlf=false") < archive.index("archive")
    assert (
        output / "source/.dockerignore"
    ).read_bytes() == b"**/.env.*\n!.env.prod.example\n"


def test_legacy_gateway_receipt_cannot_claim_current_api_gateway_build(
    builder, source, tmp_path, monkeypatch
):
    a = args(builder, source, tmp_path)
    a.role = ["dagster-gateway"]
    FakeDocker(builder, monkeypatch)
    receipt = builder.build(a, {})
    assert (
        receipt["artifacts"]["dagster-gateway"]["roleProfile"]
        == "legacy-disabled-owned-artifact"
    )
    assert "transport-api-gateway" not in receipt["images"]
    assert receipt["actualApplyAllowed"] is False and receipt["deployReady"] is False


@pytest.mark.parametrize("term_times_out", [False, True])
def test_eof_final_wait_interrupt_reclaims_owned_group(
    builder, monkeypatch, tmp_path, term_times_out
):
    calls = []

    class Process:
        pid = 123456789
        stdout = io.StringIO("")

        def poll(self):
            return None

        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            if len([x for x in calls if x[0] == "wait"]) == 1:
                raise InterruptedError("cancel during EOF wait")
            if timeout == 15 and term_times_out:
                raise subprocess.TimeoutExpired("owned-build", timeout)
            return 0

    process = Process()
    monkeypatch.setattr(builder.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(
        builder.os, "killpg", lambda pid, sig: calls.append(("kill", pid, sig))
    )
    with pytest.raises(InterruptedError, match="EOF wait"):
        builder.execute_build(["docker", "build"], {}, tmp_path / "eof.log", [])
    kills = [x for x in calls if x[0] == "kill"]
    assert kills == [("kill", process.pid, builder.signal.SIGTERM)] + (
        [("kill", process.pid, builder.signal.SIGKILL)] if term_times_out else []
    )
    assert [x for x in calls if x[0] == "wait"] == [
        ("wait", None),
        ("wait", 15),
        *([("wait", None)] if term_times_out else []),
    ]
    assert process.stdout.closed


def test_normal_eof_final_wait_never_kills_owned_group(builder, monkeypatch, tmp_path):
    calls = []

    class Process:
        stdout = io.StringIO("")

        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            return 0

    monkeypatch.setattr(builder.subprocess, "Popen", lambda *a, **k: Process())
    monkeypatch.setattr(
        builder.os, "killpg", lambda *args: calls.append(("kill", args))
    )
    builder.execute_build(["docker", "build"], {}, tmp_path / "normal-eof.log", [])
    assert calls == [("wait", None)]


@pytest.mark.parametrize("path_kind", ["normal", "comma", "quotes", "duplicate-dest"])
def test_oci_csv_preserves_single_destination_and_repo_boundary(
    builder, source, tmp_path, monkeypatch, path_kind
):
    repo, _ = source
    name = {
        "normal": "oci-output",
        "comma": "oci,output",
        "quotes": 'oci"output',
        "duplicate-dest": "oci-output,dest=" + str(repo / "frontend"),
    }[path_kind]
    a = args(builder, source, tmp_path, "--output", "oci")
    a.output_dir = tmp_path / name
    docker = FakeDocker(builder, monkeypatch)
    receipt = builder.build(a, {})
    command = docker.calls[0]
    option = command[command.index("--output") + 1]
    fields = next(csv.reader([option], strict=True))
    expected = a.output_dir / "frontend.oci.tar"
    assert fields == ["type=oci", "dest=" + str(expected)]
    assert len([field for field in fields if field.startswith("dest=")]) == 1
    if path_kind == "quotes":
        # Buildx의 CSV 인용부호 규약: 경로 안의 quote는 두 번 써야 한다.
        assert '""' in option
    assert expected.is_file()
    assert not (repo / "frontend/frontend.oci.tar").exists()
    assert builder.oci_image(expected)["Id"] == receipt["images"]["frontend"]
    assert receipt["actualApplyAllowed"] is False
