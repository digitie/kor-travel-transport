"""Verify per-lot freshness and identity during the 13 → 14 cutover.

This verifier is HTTP-only: it reads the running source proxy and target API,
does not touch Docker on server13, and fails if any source lot is missing or
if the target's latest observation exceeds the five-minute propagation limit.
Legacy source IDs are the migration identity; names are display metadata only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


STRICT_MAX_AGE_SECONDS = 300
STRICT_MAX_SOURCE_LAG_SECONDS = 300
STRICT_MAX_RUN_GAP_SECONDS = 300


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-base-url", required=True)
    parser.add_argument("--target-base-url", required=True)
    parser.add_argument("--days", type=int, default=1, choices=range(1, 8))
    parser.add_argument("--max-age-seconds", type=int, default=300, choices=range(60, 1801))
    parser.add_argument("--max-source-lag-seconds", type=int, default=300, choices=range(60, 1801))
    parser.add_argument("--max-run-gap-seconds", type=int, default=300, choices=range(60, 1801))
    parser.add_argument(
        "--allow-empty-source-lot",
        action="append",
        default=[],
        metavar="AIRPORT/LEGACY_ID",
        help="explicitly allow a source lot with no history; repeat for each known empty lot",
    )
    parser.add_argument(
        "--empty-lot-file",
        type=Path,
        help="JSON file with an allow_empty_source_lots array for the reviewed cutover allowlist",
    )
    args = parser.parse_args()
    try:
        validate_release_gate_args(args)
    except ValueError as exc:
        parser.error(str(exc))
    return args


def validate_release_gate_args(args: argparse.Namespace) -> None:
    expected_values = {
        "max_age_seconds": STRICT_MAX_AGE_SECONDS,
        "max_source_lag_seconds": STRICT_MAX_SOURCE_LAG_SECONDS,
        "max_run_gap_seconds": STRICT_MAX_RUN_GAP_SECONDS,
    }
    for name, expected in expected_values.items():
        actual = getattr(args, name, None)
        if actual != expected:
            raise ValueError(f"{name} is fixed at {expected} seconds for the release cutover gate")


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_empty_lot_allowlist(values: list[str]) -> set[tuple[str, str]]:
    allowed: set[tuple[str, str]] = set()
    for value in values:
        airport_code, separator, legacy_id = value.partition("/")
        if not separator or not airport_code or not legacy_id:
            raise ValueError(f"invalid --allow-empty-source-lot value: {value!r}")
        allowed.add((airport_code.upper(), legacy_id))
    return allowed


def load_empty_lot_file(path: Path | None) -> list[str]:
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload.get("allow_empty_source_lots", [])
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError(f"invalid allow_empty_source_lots in {path}")
    return values


async def fetch_json(client: httpx.AsyncClient, base_url: str, path: str, **params: Any) -> Any:
    response = await client.get(f"{base_url.rstrip('/')}/{path.lstrip('/')}", params=params or None)
    response.raise_for_status()
    return response.json()


async def fetch_target_json(client: httpx.AsyncClient, base_url: str, path: str, **params: Any) -> Any:
    # Target is server14, which serves the /v1-versioned API (ADR-005). Source
    # (server13) stays on the old unversioned legacy API and must NOT get this
    # prefix.
    return await fetch_json(client, base_url, f"/v1/{path.lstrip('/')}", **params)


async def latest_lot_history(
    client: httpx.AsyncClient,
    base_url: str,
    airport_code: str,
    lot: dict[str, Any],
    days: int,
    *,
    is_target: bool = False,
) -> tuple[str, str, str, datetime | None, str | None, datetime]:
    identity = str(lot.get("legacy_source_lot_id") or lot["id"])
    fetch = fetch_target_json if is_target else fetch_json
    try:
        payload = await fetch(
            client,
            base_url,
            "/parking/history",
            parking_lot_id=lot["id"],
            days=days,
            limit=1,
        )
        checked_at = datetime.now(timezone.utc)
        items = payload.get("items", [])
        latest = max((parse_timestamp(item.get("observed_at")) for item in items), default=None)
        return airport_code, identity, lot["name"], latest, None, checked_at
    except Exception as exc:  # pragma: no cover - exercised against live systems
        return airport_code, identity, lot["name"], None, str(exc), datetime.now(timezone.utc)


async def verify(args: argparse.Namespace) -> int:
    validate_release_gate_args(args)
    allowed_empty_lots = parse_empty_lot_allowlist(
        [*args.allow_empty_source_lot, *load_empty_lot_file(args.empty_lot_file)]
    )
    async with httpx.AsyncClient(timeout=30) as client:
        source_airports, target_airports, target_status = await asyncio.gather(
            fetch_json(client, args.source_base_url, "/airports"),
            fetch_target_json(client, args.target_base_url, "/airports"),
            fetch_target_json(client, args.target_base_url, "/admin/collector-status"),
        )
        target_status_checked_at = datetime.now(timezone.utc)

        failures: list[str] = []
        target_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for airport in target_airports:
            airport_code = airport["code"].upper()
            for lot in airport.get("parking_lots", []):
                legacy_id = lot.get("legacy_source_lot_id")
                if legacy_id is None:
                    failures.append(
                        f"{airport_code}/{lot.get('name', lot.get('id'))}: target has no legacy source identity"
                    )
                    continue
                target_by_key.setdefault((airport_code, str(legacy_id)), []).append(lot)

        source_checks = [
            latest_lot_history(client, args.source_base_url, airport["code"].upper(), lot, args.days)
            for airport in source_airports
            for lot in airport.get("parking_lots", [])
        ]
        source_results = await asyncio.gather(*source_checks)

        source_keys: set[tuple[str, str]] = set()
        source_by_key: dict[tuple[str, str], tuple[str, datetime | None, datetime]] = {}
        target_checks = []
        for airport_code, legacy_id, lot_name, source_latest, error, source_checked_at in source_results:
            key = (airport_code, legacy_id)
            if key in source_keys:
                failures.append(f"{airport_code}/{legacy_id}: duplicate source identity")
            source_keys.add(key)
            source_by_key[key] = (lot_name, source_latest, source_checked_at)
            if error:
                failures.append(f"{airport_code}/{legacy_id}/{lot_name}: source request failed: {error}")
                continue
            if source_latest is not None and source_latest > source_checked_at:
                failures.append(
                    f"{airport_code}/{legacy_id}/{lot_name}: source observation is future-dated by "
                    f"{(source_latest - source_checked_at).total_seconds():.1f}s"
                )
            candidates = target_by_key.get(key, [])
            if len(candidates) != 1:
                failures.append(f"{airport_code}/{legacy_id}/{lot_name}: target identity count={len(candidates)}")
                continue
            target_checks.append(
                latest_lot_history(
                    client,
                    args.target_base_url,
                    airport_code,
                    candidates[0],
                    args.days,
                    is_target=True,
                )
            )

        for target_key in sorted(target_by_key):
            if target_key not in source_keys:
                failures.append(f"{target_key[0]}/{target_key[1]}: unexpected target parking lot")

        target_results = await asyncio.gather(*target_checks)
        for airport_code, legacy_id, lot_name, target_latest, error, target_checked_at in target_results:
            key = (airport_code, legacy_id)
            source_name, source_latest, source_checked_at = source_by_key[key]
            if error:
                failures.append(f"{airport_code}/{legacy_id}/{lot_name}: target request failed: {error}")
                continue
            if target_latest is None:
                if source_latest is not None:
                    failures.append(f"{airport_code}/{legacy_id}/{source_name}: target has no observation")
                elif key not in allowed_empty_lots:
                    failures.append(
                        f"{airport_code}/{legacy_id}/{source_name}: both sides have no observation; "
                        "add an explicit --allow-empty-source-lot entry if this is intentional"
                    )
                continue
            if source_latest is None:
                failures.append(
                    f"{airport_code}/{legacy_id}/{lot_name}: source has no observation but target does; "
                    "the empty-lot allowlist applies only when both sides have no observation"
                )
                continue
            if source_latest > source_checked_at:
                continue
            if target_latest > target_checked_at:
                failures.append(
                    f"{airport_code}/{legacy_id}/{lot_name}: target observation is future-dated by "
                    f"{(target_latest - target_checked_at).total_seconds():.1f}s"
                )
                continue
            source_lag_seconds = (source_latest - target_latest).total_seconds()
            if source_lag_seconds > args.max_source_lag_seconds:
                failures.append(
                    f"{airport_code}/{legacy_id}/{lot_name}: source leads target by {source_lag_seconds:.1f}s "
                    f"> {args.max_source_lag_seconds}s"
                )
            if (target_checked_at - target_latest).total_seconds() > args.max_age_seconds:
                failures.append(
                    f"{airport_code}/{legacy_id}/{lot_name}: target freshness is {(target_checked_at - target_latest).total_seconds():.1f}s "
                    f"> {args.max_age_seconds}s"
                )

        latest_target_observed = parse_timestamp(target_status.get("latest_snapshot_observed_at"))
        if latest_target_observed is None:
            failures.append("target has no global latest observation")
        elif latest_target_observed > target_status_checked_at:
            failures.append(
                "target global latest observation is future-dated by "
                f"{(latest_target_observed - target_status_checked_at).total_seconds():.1f}s"
            )
        elif (target_status_checked_at - latest_target_observed).total_seconds() > args.max_age_seconds:
            failures.append(
                f"target global freshness is {(target_status_checked_at - latest_target_observed).total_seconds():.1f}s "
                f"> {args.max_age_seconds}s"
            )
        if not target_status.get("scheduler_enabled"):
            failures.append("target scheduler is disabled")
        if target_status.get("collect_interval_seconds") != 300:
            failures.append(f"target interval={target_status.get('collect_interval_seconds')}s, expected 300s")
        if target_status.get("effective_collect_interval_seconds") != 180:
            failures.append(
                f"target effective interval={target_status.get('effective_collect_interval_seconds')}s, expected 180s"
            )
        if target_status.get("scheduler_safety_buffer_seconds") != 120:
            failures.append(
                f"target scheduler safety buffer={target_status.get('scheduler_safety_buffer_seconds')}s, expected 120s"
            )
        last_run = target_status.get("last_run") or {}
        if last_run.get("status") != "success":
            failures.append(f"target last run status={last_run.get('status')!r}")
        recent_runs = target_status.get("recent_runs") or []
        successful_runs = []
        for run in recent_runs:
            if run.get("status") != "success":
                failures.append(f"target recent run id={run.get('id')} status={run.get('status')!r}")
                continue
            started_at = parse_timestamp(run.get("started_at"))
            if started_at is not None:
                successful_runs.append((started_at, run.get("id")))
        for newer, older in zip(successful_runs, successful_runs[1:]):
            gap_seconds = (newer[0] - older[0]).total_seconds()
            if gap_seconds > args.max_run_gap_seconds:
                failures.append(
                    f"target successful run gap between ids {newer[1]} and {older[1]} is "
                    f"{gap_seconds:.1f}s > {args.max_run_gap_seconds}s"
                )

    result = {
        "source_lots": len(source_results),
        "target_lots_checked": len(target_results),
        "failure_count": len(failures),
        "failures": failures[:20],
        "target_latest_observed_at": target_status.get("latest_snapshot_observed_at"),
        "target_last_run_id": last_run.get("id"),
        "max_age_seconds": args.max_age_seconds,
        "max_source_lag_seconds": args.max_source_lag_seconds,
        "max_run_gap_seconds": args.max_run_gap_seconds,
        "allowed_empty_source_lots": sorted(f"{code}/{legacy_id}" for code, legacy_id in allowed_empty_lots),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(verify(parse_args())))
