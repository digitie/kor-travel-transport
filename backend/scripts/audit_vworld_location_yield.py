"""운영 기준정보의 VWorld 좌표 보강 수율을 DB 변경 없이 측정한다."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

import httpx
from vworld import VworldClient, VworldNetworkError, VworldNoDataError, parse_search_response, process_search_response

from app.services.place_locations import choose_bus_location, choose_port_location


API = "https://pr-api.digitie.mywire.org/v1/transport"


def key_from_file(path: Path) -> str:
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("VWORLD_API_KEY="):
            return line.partition("=")[2].strip().strip('"').strip("'")
    raise ValueError("VWORLD_API_KEY is missing")


async def references() -> tuple[list[dict], list[dict]]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{API}/features/places", params={
            "kind": "ferry_port", "include_unlocated": "true", "limit": 1000,
        })
        response.raise_for_status()
        ports = response.json()["items"]
        terminals = []
        for service_type in ("express", "intercity"):
            offset = 0
            while True:
                response = await client.get(f"{API}/bus/terminals", params={
                    "service_type": service_type, "offset": offset, "limit": 100,
                })
                response.raise_for_status()
                page = response.json()
                terminals.extend(page["items"])
                if page["next_offset"] is None:
                    break
                offset = page["next_offset"]
    return ports, terminals


def candidates(ports: list[dict], terminals: list[dict]) -> list[tuple[str, str, str, dict]]:
    port_names = Counter(port["name"] for port in ports)
    terminal_names = Counter((terminal["service_type"], terminal["terminal_name"],
                              terminal["city_name"]) for terminal in terminals)
    rows = []
    for port in ports:
        name = port["name"].strip()
        if port["latitude"] is None and name and "_" not in name and port_names[port["name"]] == 1:
            rows.append(("ferry_port", str(port["provider_id"]), name if name.endswith("항") else name + "항", port))
    for terminal in terminals:
        name = terminal["terminal_name"].strip()
        if (terminal.get("latitude") is None and name and "_" not in name and
                terminal_names[(terminal["service_type"], terminal["terminal_name"], terminal["city_name"])] == 1):
            suffix = "고속버스터미널" if terminal["service_type"] == "express" else "시외버스터미널"
            rows.append((terminal["service_type"], str(terminal["terminal_id"]),
                         name if "터미널" in name else name + suffix, terminal))
    return rows


async def audit(key_file: Path, max_calls: int) -> None:
    ports, terminals = await references()
    rows = candidates(ports, terminals)
    summary = {"baseline": {"ports": len(ports), "located_ports": sum(p["latitude"] is not None for p in ports),
                            "express": sum(t["service_type"] == "express" for t in terminals),
                            "intercity": sum(t["service_type"] == "intercity" for t in terminals)},
               "candidates": dict(Counter(kind for kind, *_ in rows)),
               "attempted": 0, "matched": Counter(), "no_result": Counter(),
               "ambiguous_or_mismatch": Counter(), "incomplete_page": Counter(),
               "error": Counter(), "examples": {"matched": [], "ambiguous": []}}
    consecutive_errors = 0
    async with VworldClient(api_key=key_from_file(key_file), max_retries=0, max_rps=100.0, timeout=20) as client:
        for kind, identifier, query, row in rows[:max_calls]:
            summary["attempted"] += 1
            try:
                try:
                    for retry in range(3):
                        try:
                            raw = await client.search_place(query, size=100)
                            break
                        except VworldNetworkError:
                            if retry == 2:
                                raise
                            await asyncio.sleep(2 * (retry + 1))
                except VworldNoDataError:
                    consecutive_errors = 0
                    summary["no_result"][kind] += 1
                    continue
                consecutive_errors = 0
                parsed = process_search_response(parse_search_response(raw))
                if parsed.status == "NOT_FOUND":
                    summary["no_result"][kind] += 1
                    continue
                if parsed.status != "OK":
                    summary["error"][kind] += 1
                    break
                total = (parsed.record or {}).get("total")
                if total is None or int(total) > len(parsed.items):
                    summary["incomplete_page"][kind] += 1
                    continue
                selected = (choose_port_location(parsed.items, name=row["name"]) if kind == "ferry_port"
                            else choose_bus_location(parsed.items, name=row["terminal_name"],
                                                     service_type=kind, city_name=row["city_name"]))
                if selected is None:
                    summary["ambiguous_or_mismatch"][kind] += 1
                    if len(summary["examples"]["ambiguous"]) < 8:
                        summary["examples"]["ambiguous"].append({"kind": kind, "id": identifier, "query": query})
                else:
                    summary["matched"][kind] += 1
                    if len(summary["examples"]["matched"]) < 8:
                        summary["examples"]["matched"].append({"kind": kind, "id": identifier, "query": query,
                                                                  "latitude": selected["latitude"], "longitude": selected["longitude"]})
            except Exception as exc:
                summary["error"][kind] += 1
                consecutive_errors += 1
                print(f"VWorld search error at attempt {summary['attempted']}: {type(exc).__name__}", file=sys.stderr, flush=True)
                if consecutive_errors >= 10:
                    print("VWorld search stopped after 10 consecutive errors", file=sys.stderr, flush=True)
                    break
            finally:
                await asyncio.sleep(0.01)
                if summary["attempted"] % 100 == 0:
                    print(f"audited {summary['attempted']}/{min(len(rows), max_calls)}", file=sys.stderr, flush=True)
    summary["matched"] = dict(summary["matched"])
    summary["no_result"] = dict(summary["no_result"])
    summary["ambiguous_or_mismatch"] = dict(summary["ambiguous_or_mismatch"])
    summary["incomplete_page"] = dict(summary["incomplete_page"])
    summary["error"] = dict(summary["error"])
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--key-env-file", type=Path, required=True)
    parser.add_argument("--max-calls", type=int, default=10000)
    args = parser.parse_args()
    if not 1 <= args.max_calls <= 10000:
        parser.error("--max-calls must be between 1 and 10000")
    asyncio.run(audit(args.key_env_file, args.max_calls))
