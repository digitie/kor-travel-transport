"""실제 앱 RUN의 pip cache·locked 입력 경계를 작은 shell stub으로 확인한다."""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = Path(os.environ.get("TRANSPORT_DOCKERFILE_UNDER_TEST", ROOT / "backend/Dockerfile"))
CACHE_MOUNT = "--mount=type=cache,id=transport-pip-py312,target=/root/.cache/pip,sharing=locked"


def runs(text: str) -> list[str]:
    result = []
    lines = iter(text.splitlines(keepends=True))
    for line in lines:
        if not line.startswith("RUN "):
            continue
        block = line
        while line.rstrip().endswith("\\"):
            line = next(lines)
            block += line
        result.append(block)
    return result


def app_runs(text: str) -> list[str]:
    return [block for block in runs(text) if "--no-emit-project" in block or '-e ".[dev]"' in block]


def validate(text: str) -> None:
    blocks = app_runs(text)
    assert len(blocks) == 2
    for block in blocks:
        assert block.startswith("RUN " + CACHE_MOUNT + " \\\n")
        assert "--no-cache-dir" not in block
        assert 'GDAL_VERSION="$(gdal-config --version)"' in block
        assert 'sysconfig.get_config_var("SOABI")' in block
        assert 'os.confstr("CS_GNU_LIBC_VERSION")' in block
        assert "assert abi and libc" in block
        assert "env -u PIP_NO_CACHE_DIR" in block
        expected = 'PIP_CACHE_DIR="/root/.cache/pip/' + '$' + '{WHEEL_CACHE_ABI}-gdal-' + '$' + '{GDAL_VERSION}"'
        assert expected in block
        assert "--no-deps" in block
    assert "--locked --extra dev --no-emit-project --no-hashes" in blocks[0]
    assert "--format requirements.txt --output-file /tmp/backend-requirements.txt" in blocks[0]
    assert "-r /tmp/backend-requirements.txt" in blocks[0]
    assert 'install -e ".[dev]" --no-deps && pip check' in blocks[1]


class AppPipCacheContract(unittest.TestCase):
    def test_two_locked_abi_scoped_app_installers(self):
        validate(DOCKERFILE.read_text())

    def test_actual_shell_unsets_global_disable_and_shares_only_compatible_scope(self):
        with tempfile.TemporaryDirectory(prefix="transport-pip-cache-") as folder:
            temp = Path(folder)
            bin_dir = temp / "bin"
            bin_dir.mkdir()
            python = bin_dir / "python"
            python.write_text(
                "#!/usr/bin/python3\nimport json,os,sys\n"
                "if sys.argv[1:3]==['-I','-c']:\n print(os.environ['TEST_ABI']);sys.exit(0)\n"
                "with open(os.environ['TEST_RECORD'],'a') as f: f.write(json.dumps({"
                "'args':sys.argv[1:],'noCache':os.environ.get('PIP_NO_CACHE_DIR'),"
                "'cache':os.environ.get('PIP_CACHE_DIR')})+'\\n')\n"
            )
            python.chmod(0o755)
            for name, body in [
                ("uv", "exit 0"),
                ("gdal-config", 'printf "%s\\n" "$TEST_GDAL"'),
                ("pip", 'exec python -m pip "$@"'),
            ]:
                stub = bin_dir / name
                stub.write_text("#!/bin/sh\n" + body + "\n")
                stub.chmod(0o755)
            scopes = []
            for abi, gdal in [
                ("cpython-312-aarch64-linux-gnu-glibc-2.41", "3.13.3"),
                ("cpython-312-x86_64-linux-gnu-glibc-2.41", "3.13.3"),
                ("cpython-312-aarch64-linux-gnu-glibc-2.42", "3.13.3"),
                ("cpython-312-aarch64-linux-gnu-glibc-2.41", "3.14.0"),
            ]:
                record = temp / (str(len(scopes)) + ".jsonl")
                env = {
                    "PATH": str(bin_dir) + ":/usr/bin:/bin", "HOME": str(temp),
                    "PIP_NO_CACHE_DIR": "1", "PIP_CACHE_DIR": "/wrong-parent-cache",
                    "TEST_RECORD": str(record), "TEST_ABI": abi, "TEST_GDAL": gdal,
                }
                for block in app_runs(DOCKERFILE.read_text()):
                    shell = block.removeprefix("RUN ").replace("\\\n", " ")
                    shell = re.sub(r"^--mount=\S+\s*", "", shell)
                    subprocess.run(
                        ["/bin/sh", "-ec", shell], env=env, check=True,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
                    )
                rows = [json.loads(line) for line in record.read_text().splitlines()]
                installs = [row for row in rows if "install" in row["args"]]
                self.assertEqual(len(installs), 2)
                expected = f"/root/.cache/pip/{abi}-gdal-{gdal}"
                self.assertEqual([row["cache"] for row in installs], [expected, expected])
                self.assertEqual([row["noCache"] for row in installs], [None, None])
                self.assertTrue(all("--no-cache-dir" not in row["args"] for row in installs))
                scopes.append(expected)
            self.assertEqual(len(set(scopes)), 4)

    def test_missing_scope_or_lock_guards_are_rejected(self):
        text = DOCKERFILE.read_text()
        validate(text)
        changes = [
            ("sharing=locked", "sharing=shared"),
            ('sysconfig.get_config_var("SOABI")', '"fixed-abi"'),
            ('os.confstr("CS_GNU_LIBC_VERSION")', '"fixed-libc"'),
            ('GDAL_VERSION="$(gdal-config --version)"', 'GDAL_VERSION="3.13.3"'),
            ("env -u PIP_NO_CACHE_DIR", "env"),
            ("--locked --extra dev", "--extra dev"),
            ("--no-deps -r", "-r"),
            ('python -m pip install --no-deps', 'python -m pip install --no-cache-dir --no-deps'),
        ]
        for old, new in changes:
            with self.subTest(mutation=old):
                self.assertIn(old, text)
                with self.assertRaises(AssertionError):
                    validate(text.replace(old, new))


    def test_non_app_run_instructions_remain_exact(self):
        # 앞의 무비밀 UI 빌더는 별개 stage다. 기존 Python runtime RUN의 지문은 그대로 고정한다.
        runtime = DOCKERFILE.read_text().split("FROM ghcr.io/astral-sh/uv:", 1)[1]
        others = [block for block in runs(runtime) if block not in app_runs(runtime)]
        self.assertEqual(hashlib.sha256("\n---\n".join(others).encode()).hexdigest(), "3cdd9d82dd38f1cd98f86931ec8403bd2af54469ad1fa8999cfe18681c9106a2")

    def test_existing_final_interpreter_order_contract(self):
        filename = ROOT / "backend/tests/test_health_cpu_contract.py"
        module = ast.parse(filename.read_text())
        function = next(node for node in module.body if isinstance(node, ast.FunctionDef)
                        and node.name == "test_stdlib_compile_uses_final_image_interpreter_after_installs")
        scope = {"BACKEND_ROOT": ROOT / "backend"}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(filename), "exec"), scope)
        scope[function.name]()


if __name__ == "__main__":
    unittest.main()
