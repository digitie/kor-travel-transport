"""n150의 Dagster 실행·worker·앱 수집 실행 상태를 교차 검증한다.

읽기 전용 사후 검증이다. 배포·브라우저 E2E 뒤 n150에서 실행하며,
GraphQL 상태만 STARTED로 남고 worker가 사라진 고아 실행을 실패 처리한다.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from urllib.request import Request, urlopen


CONTAINER = "kor-travel-transport-dagster-code-server-1"
GRAPHQL_URL = "http://127.0.0.1:14004/graphql"
COLLECTOR_URL = "http://127.0.0.1:14001/v1/transport/collector-status"
QUERY = "{runsOrError(filter:{statuses:[STARTED,STARTING,CANCELING]},limit:1000){__typename ... on Runs{results{runId jobName status startTime}}}}"
TRANSPORT_JOBS = {
    "transport_dagster_highway": "highway_collection_job",
    "transport_dagster_fuel": "fuel_collection_job",
}


def active_runs() -> list[dict[str, str]]:
    request = Request(GRAPHQL_URL, data=json.dumps({"query": QUERY}).encode(),
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=20) as response:
        payload = json.load(response)
    if payload.get("errors"):
        raise RuntimeError("Dagster GraphQL 실행 조회 오류")
    result = payload.get("data", {}).get("runsOrError", {})
    if result.get("__typename") != "Runs":
        raise RuntimeError("Dagster 실행 목록을 읽지 못함")
    runs = result["results"]
    if len(runs) >= 1000:
        raise RuntimeError("활성 실행이 1000건 이상이라 전체 검증 불가")
    return runs


def missing_started_workers(runs: list[dict[str, str]], process_table: str) -> list[str]:
    processes: dict[str, tuple[str, str]] = {}
    for line in process_table.splitlines()[1:]:
        fields = line.split(maxsplit=2)
        if len(fields) == 3:
            processes[fields[0]] = (fields[1], fields[2])
    missing = []
    for run in runs:
        if run["status"] != "STARTED":
            continue
        marker = f"/storage/{run['runId']}/"
        alive = any(marker in command and parent in processes
                    and "multiprocessing.spawn" in processes[parent][1]
                    for parent, command in processes.values())
        if not alive:
            missing.append(run["runId"])
    return missing


def untracked_workers(runs: list[dict[str, str]], process_table: str) -> list[str]:
    active_ids = {run["runId"] for run in runs}
    processes: dict[str, tuple[str, str]] = {}
    for line in process_table.splitlines()[1:]:
        fields = line.split(maxsplit=2)
        if len(fields) == 3:
            processes[fields[0]] = (fields[1], fields[2])
    spawn_pids = {pid for pid, (_parent, command) in processes.items()
                  if "multiprocessing.spawn" in command}
    orphaned: set[str] = set()
    matched_spawns: set[str] = set()
    for parent, command in processes.values():
        if parent not in spawn_pids:
            continue
        marker = re.search(r"/storage/([^/]+)/", command)
        if marker:
            matched_spawns.add(parent)
            if marker.group(1) not in active_ids:
                orphaned.add(marker.group(1))
    orphaned.update(f"worker-pid:{pid}" for pid in spawn_pids - matched_spawns)
    return sorted(orphaned)


def running_app_runs() -> list[dict[str, object]]:
    with urlopen(COLLECTOR_URL, timeout=20) as response:
        status = json.load(response)
    rows = status["running_runs"]
    if status["running_run_count"] != len(rows):
        raise RuntimeError("앱 수집 실행 목록이 잘려 전체 검증 불가")
    return rows


def orphaned_app_runs(app_runs: list[dict[str, object]], dagster_runs: list[dict[str, object]]) -> list[int]:
    from datetime import datetime

    matched: set[str] = set()
    orphaned: list[int] = []
    for app_run in sorted(app_runs, key=lambda row: str(row["started_at"])):
        job = TRANSPORT_JOBS.get(str(app_run["trigger"]))
        if job is None:
            orphaned.append(int(app_run["id"]))
            continue
        started = datetime.fromisoformat(str(app_run["started_at"]).replace("Z", "+00:00")).timestamp()
        candidates = [run for run in dagster_runs
                      if run["jobName"] == job and run["status"] == "STARTED"
                      and run["runId"] not in matched
                      and run.get("startTime") is not None
                      and -60 <= started - float(run["startTime"]) <= 600]
        if not candidates:
            orphaned.append(int(app_run["id"]))
            continue
        best = min(candidates, key=lambda run: abs(started - float(run["startTime"])))
        matched.add(str(best["runId"]))
    return orphaned


def main() -> int:
    for attempt in range(3):
        runs = active_runs()
        app_runs = running_app_runs()
        table = subprocess.run(
            ["docker", "top", CONTAINER, "-eo", "pid,ppid,args"],
            check=True, capture_output=True, text=True,
        ).stdout
        missing = missing_started_workers(runs, table)
        extra = untracked_workers(runs, table)
        orphaned = orphaned_app_runs(app_runs, runs)
        if not missing and not extra and not orphaned:
            print(f"Dagster 활성 실행 {len(runs)}건, 앱 수집 실행 {len(app_runs)}건: worker·실행 상태 확인")
            return 0
        if attempt < 2:
            time.sleep(10)
    print("Dagster 고아 실행 의심: " + ", ".join(missing)
          + "; 추적되지 않은 worker 의심: " + ", ".join(extra)
          + "; 앱 고아 수집 실행 의심: " + ", ".join(map(str, orphaned)), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
