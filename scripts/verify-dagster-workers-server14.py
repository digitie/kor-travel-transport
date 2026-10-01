"""n150의 Dagster STARTED 실행과 실제 code-server worker 생존을 대조한다.

읽기 전용 사후 검증이다. 배포·브라우저 E2E 뒤 n150에서 실행하며,
GraphQL 상태만 STARTED로 남고 worker가 사라진 고아 실행을 실패 처리한다.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from urllib.request import Request, urlopen


CONTAINER = "kor-travel-transport-dagster-code-server-1"
GRAPHQL_URL = "http://127.0.0.1:14004/graphql"
QUERY = "{runsOrError(filter:{statuses:[STARTED,STARTING,CANCELING]},limit:1000){__typename ... on Runs{results{runId status}}}}"


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


def main() -> int:
    for attempt in range(3):
        runs = active_runs()
        table = subprocess.run(
            ["docker", "top", CONTAINER, "-eo", "pid,ppid,args"],
            check=True, capture_output=True, text=True,
        ).stdout
        missing = missing_started_workers(runs, table)
        if not missing:
            print(f"Dagster 활성 실행 {len(runs)}건: STARTED worker 확인")
            return 0
        if attempt < 2:
            time.sleep(10)
    print("Dagster 고아 실행 의심: " + ", ".join(missing), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
