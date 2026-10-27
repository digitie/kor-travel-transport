#!/usr/bin/env python3
"""외부 controller의 사전 빌드·최신 state handoff를 읽기 전용으로 검산한다."""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import urllib.request

LOCATION = "kor-travel-transport"
CODE_SERVER = LOCATION + "-dagster-code-server-1"
ROLES = {"backend", "frontend", "dagster-code-server"}
RUN_STATUSES = ("NOT_STARTED", "QUEUED", "STARTING", "STARTED", "CANCELING")
RECEIPT_UID = 0


class ContractError(RuntimeError):
    pass


def scan_state(root: Path) -> dict:
    """복사 원본에서 내용·metadata·재작성을 본다. symlink는 따라가지 않는다."""
    if not root.is_dir() or root.is_symlink():
        raise ContractError("state root absent or unsafe")
    def stable(info):
        return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode,
                info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)

    root_stat = root.stat()
    rows = {}
    pending = [root]
    while pending:
        parent = pending.pop()
        for item in os.scandir(parent):
            path, info = Path(item.path), item.stat(follow_symlinks=False)
            value = {"uid": info.st_uid, "gid": info.st_gid, "mode": stat.S_IMODE(info.st_mode),
                     "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}
            if stat.S_ISDIR(info.st_mode):
                value["kind"] = "directory"
                pending.append(path)
            elif stat.S_ISREG(info.st_mode):
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    while block := stream.read(1024 * 1024):
                        digest.update(block)
                    if stable(os.fstat(stream.fileno())) != stable(info):
                        raise ContractError("state file changed during scan")
                value.update(kind="file", bytes=info.st_size, sha256=digest.hexdigest())
            elif stat.S_ISLNK(info.st_mode):
                value.update(kind="symlink", target=os.readlink(path))
            else:
                raise ContractError("special state file refused")
            if stable(path.lstat()) != stable(info):
                raise ContractError("state entry changed during scan")
            rows[path.relative_to(root).as_posix()] = value
    if stable(root.stat()) != stable(root_stat):
        raise ContractError("state root changed during scan")
    return {"root": {"uid": root_stat.st_uid, "gid": root_stat.st_gid,
                     "mode": stat.S_IMODE(root_stat.st_mode), "mtime_ns": root_stat.st_mtime_ns,
                     "ctime_ns": root_stat.st_ctime_ns}, "entries": rows}


def state_manifest(fingerprint: dict) -> dict:
    return {key: {k: v for k, v in row.items() if k not in {"mtime_ns", "ctime_ns"}}
            for key, row in fingerprint["entries"].items()}


WORKER_PROBE = r'''
import json,os,pathlib
rows=[]
for p in pathlib.Path('/proc').iterdir():
 if not p.name.isdigit() or int(p.name)==os.getpid(): continue
 try:
  args=(p/'cmdline').read_bytes().split(b'\0')
  kind='execute_run' if b'execute_run' in args else ('spawn_worker' if any(a.startswith(b'from multiprocessing.spawn import spawn_main') for a in args) else None)
  if kind:
   fields=(p/'stat').read_text().rsplit(')',1)[1].split()
   rows.append({'pid':int(p.name),'ppid':int(fields[1]),'started_ticks':int(fields[19]),'kind':kind})
 except (FileNotFoundError,ProcessLookupError): pass
print(json.dumps(rows))
'''
SCHEMA_PROBE = r'''
import asyncio,json,os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
async def main():
 e=create_async_engine(os.environ['DATABASE_URL'])
 try:
  async with e.connect() as c:
   await c.execute(text('SET TRANSACTION READ ONLY'))
   await c.execute(text("SET LOCAL statement_timeout='5s'"))
   print(json.dumps(sorted((await c.execute(text('SELECT version_num FROM alembic_version'))).scalars().all())))
 finally: await e.dispose()
asyncio.run(main())
'''
HEADS_PROBE = "import json; from alembic.config import Config; from alembic.script import ScriptDirectory; print(json.dumps(sorted(ScriptDirectory.from_config(Config('/app/alembic.ini')).get_heads())))"


def state_probe() -> str:
    return ("import os,stat,hashlib,json\nfrom pathlib import Path\nclass ContractError(Exception): pass\n"
            + inspect.getsource(scan_state) + "\nprint(json.dumps(scan_state(Path('/opt/dagster/state'))))")


def command(args: list[str]):
    result = subprocess.run(args, capture_output=True, timeout=60, check=False)
    if result.returncode:
        raise ContractError("read-only Docker probe failed")
    return json.loads(result.stdout)


def graphql(query: str) -> dict:
    request = urllib.request.Request("http://127.0.0.1:11002/graphql",
        data=json.dumps({"query": query}).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024:
        raise ContractError("GraphQL response too large")
    payload = json.loads(data)
    if payload.get("errors") or not isinstance(payload.get("data"), dict):
        raise ContractError("GraphQL request/schema failed")
    return payload["data"]


def load_receipt(path: Path, expected_hash: str) -> dict:
    if not path.is_absolute() or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise ContractError("handoff path/hash missing or invalid")
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise ContractError("symlink handoff refused")
    parent = path.parent.stat()
    if parent.st_uid != RECEIPT_UID or stat.S_IMODE(parent.st_mode) != 0o711:
        raise ContractError("handoff requires a dedicated root-owned 0711 directory")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != RECEIPT_UID
                or stat.S_IMODE(before.st_mode) != 0o644 or before.st_nlink != 1):
            raise ContractError("handoff requires a root-owned single-link 0644 file")
        data = stream.read(32 * 1024 * 1024 + 1)
        after = os.fstat(stream.fileno())
        if len(data) > 32 * 1024 * 1024 or any(getattr(after, k) != getattr(before, k) for k in
                ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")):
            raise ContractError("handoff too large or changed during read")
    if hashlib.sha256(data).hexdigest() != expected_hash:
        raise ContractError("handoff checksum mismatch")
    return json.loads(data)


def validate_receipt(value: dict, revision: str) -> None:
    if (value["version"] != 1 or not re.fullmatch(r"[0-9a-f]{40}", revision)
            or value["release_sha"] != revision or set(value["images"]) != ROLES):
        raise ContractError("handoff release/role mismatch")
    if (any(not re.fullmatch(r"sha256:[0-9a-f]{64}", v) for v in value["images"].values())
            or value["images"]["backend"] != value["images"]["dagster-code-server"]):
        raise ContractError("handoff image identity mismatch")
    if not value["schema_revisions"] or any(not re.fullmatch(r"[a-z0-9_]+", v) for v in value["schema_revisions"]):
        raise ContractError("handoff schema missing")
    state = value["state"]
    if (not re.fullmatch(r"[0-9a-f]{64}", state["source_container"])
            or state_manifest(state["fingerprint"]) != state["manifest"]):
        raise ContractError("copied state and source fingerprint disagree")
    # timestamp 없는 옛 manifest를 최신성 근거로 재사용하지 않는다.
    for row in [state["fingerprint"]["root"], *state["fingerprint"]["entries"].values()]:
        if any(type(row.get(k)) is not int for k in ("mtime_ns", "ctime_ns")):
            raise ContractError("source state timestamps missing")


def state_map(rows: list[dict]) -> dict:
    result = {(r["location"], r["repository"], r["kind"], r["name"]): r["status"] for r in rows}
    if len(result) != len(rows) or any(v not in {"RUNNING", "STOPPED"} for v in result.values()):
        raise ContractError("invalid instigator catalog")
    own = {k[1] for k in result if k[0] == LOCATION}
    if len(own) != 1 or any(k[2] not in {"schedule", "sensor"} for k in result):
        raise ContractError("Transport repository absent or ambiguous")
    return result


def verify_drained(value: dict, run, request) -> None:
    repositories = request("{repositoriesOrError{__typename ... on RepositoryConnection{nodes{name location{name} "
                           "schedules{name scheduleState{status}} sensors{name sensorState{status}}}}}}") ["repositoriesOrError"]
    if repositories["__typename"] != "RepositoryConnection":
        raise ContractError("instigator catalog unavailable")
    if len([r for r in repositories["nodes"] if r["location"]["name"] == LOCATION]) != 1:
        raise ContractError("Transport repository absent or ambiguous")
    rows = []
    for repo in repositories["nodes"]:
        for kind in ("schedule", "sensor"):
            for item in repo[kind + "s"]:
                rows.append({"location": repo["location"]["name"], "repository": repo["name"], "kind": kind,
                             "name": item["name"], "status": item[kind + "State"]["status"]})
    expected = {k: "STOPPED" if k[0] == LOCATION else v for k, v in state_map(value["instigators"]).items()}
    if state_map(rows) != expected:
        raise ContractError("instigators not paused or catalog changed")
    runs = request("{runsOrError(filter:{statuses:[" + ",".join(RUN_STATUSES) + "]},limit:1000)"
        "{__typename ... on Runs{results{runId status repositoryOrigin{repositoryLocationName} tags{key value}}}}}")["runsOrError"]
    if runs["__typename"] != "Runs" or len(runs["results"]) >= 1000:
        raise ContractError("active runs unavailable or truncated")
    for row in runs["results"]:
        origin = (row.get("repositoryOrigin") or {}).get("repositoryLocationName")
        tags = [t["value"] for t in row.get("tags", []) if t["key"] == "dagster/code_location"]
        if len(tags) > 1 or (not origin and not tags) or (origin and tags and origin != tags[0]):
            raise ContractError("active run location unknown or disagrees")
        if (origin or tags[0]) == LOCATION:
            raise ContractError("Transport active run: immediate refusal")
    cid = value["state"]["source_container"]
    if run(["docker", "exec", cid, "python", "-I", "-c", WORKER_PROBE]) != []:
        raise ContractError("Transport active worker: immediate refusal")


def verify(value: dict, revision: str, run=command, request=graphql) -> None:
    validate_receipt(value, revision)
    tags = {"backend": LOCATION + "-backend:rel-" + revision[:12], "frontend": LOCATION + "-frontend"}
    for role, tag in tags.items():
        image = run(["docker", "image", "inspect", tag])[0]
        if image["Id"] != value["images"][role] or image["Architecture"] != "arm64":
            raise ContractError("prebuilt image tag/id/architecture mismatch")
    schema = run(["docker", "exec", LOCATION + "-backend-1", "python", "-I", "-c", SCHEMA_PROBE])
    heads = run(["docker", "run", "--rm", "--pull", "never", "--network", "none", "--entrypoint", "python",
                 value["images"]["backend"], "-I", "-c", HEADS_PROBE])
    if sorted(value["schema_revisions"]) != schema or schema != heads:
        raise ContractError("production schema is not the pinned release head")
    current = run(["docker", "inspect", CODE_SERVER])[0]
    labels = current["Config"]["Labels"]
    if (current["Id"] != value["state"]["source_container"] or not current["State"]["Running"]
            or labels.get("com.docker.compose.project") != LOCATION
            or labels.get("com.docker.compose.service") != "dagster-code-server"):
        raise ContractError("source code-server container changed")
    verify_drained(value, run, request)
    cid = value["state"]["source_container"]
    # run이 이미 끝났더라도 snapshot 뒤 쓴 artifact 또는 동일 bytes 재작성을 거절한다.
    if run(["docker", "exec", cid, "python", "-I", "-c", state_probe()]) != value["state"]["fingerprint"]:
        raise ContractError("source state changed after copy")
    verify_drained(value, run, request)


def admin_overlay(revision: str, admin_id: str, gateway_id: str, run=command) -> dict:
    """CS를 건드리지 않는 별도 두 역할 계약이다. CS state receipt는 받지 않는다."""
    if not re.fullmatch(r"[0-9a-f]{40}", revision or "") or any(
            not re.fullmatch(r"sha256:[0-9a-f]{64}", v or "") for v in (admin_id, gateway_id)):
        raise ContractError("admin handoff requires a full revision and two image IDs")
    admin = run(["docker", "image", "inspect", LOCATION + "-transport-admin-web"])[0]
    gateway = run(["docker", "image", "inspect", gateway_id])[0]
    release = [s.split("=", 1)[1] for s in admin["Config"]["Env"] if s.startswith("TRANSPORT_ADMIN_RELEASE_SHA=")]
    if (admin["Id"] != admin_id or admin["Architecture"] != "arm64" or release != [revision]
            or gateway["Id"] != gateway_id or gateway["Architecture"] != "arm64"):
        raise ContractError("admin prebuilt image ID/architecture/baked release mismatch")
    return {"services": {role: {"image": image, "labels": {
        "io.kor-travel-transport.prebuilt-release": revision}} for role, image in
        (("transport-admin-web", admin_id), ("transport-api-gateway", gateway_id))}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--revision")
    parser.add_argument("--overlay", action="store_true")
    parser.add_argument("--state-fingerprint", metavar="CONTAINER_ID")
    parser.add_argument("--admin-overlay", action="store_true")
    parser.add_argument("--admin-image-id")
    parser.add_argument("--gateway-image-id")
    args = parser.parse_args()
    try:
        if args.admin_overlay:
            print(json.dumps(admin_overlay(args.revision, args.admin_image_id, args.gateway_image_id)))
        elif args.state_fingerprint:
            if not re.fullmatch(r"[0-9a-f]{64}", args.state_fingerprint):
                raise ContractError("full source container ID required")
            print(json.dumps(command(["docker", "exec", args.state_fingerprint, "python", "-I", "-c", state_probe()])))
        else:
            if not args.receipt or not args.sha256 or not args.revision:
                raise ContractError("strict handoff receipt/hash/revision required")
            value = load_receipt(args.receipt, args.sha256)
            verify(value, args.revision)
            if args.overlay:
                print(json.dumps({"services": {role: {"image": value["images"][role], "labels": {
                    "io.kor-travel-transport.prebuilt-release": args.revision}} for role in sorted(ROLES)}}))
        return 0
    except Exception as exc:
        # 외부 응답·receipt 원문·환경·command stderr를 출력하지 않는다.
        print("Refusing prebuilt deployment: " + (str(exc) if isinstance(exc, ContractError) else type(exc).__name__), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
