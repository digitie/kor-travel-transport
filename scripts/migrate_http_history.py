"""Import parking history from a running kor-travel-transport HTTP API into PostgreSQL.

This is the least-privilege fallback for a source host whose Docker volume is not
readable by the SSH account. It intentionally imports airports, parking lots, and
observations only. Use the exact SQLite/PostgreSQL dump path when raw API responses,
collection runs, fee rules, and analytics cache must also be preserved.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import Settings
from app.db.session import create_engine_and_session_factory
from app.models import Airport, ParkingLot, ParkingSnapshot


MIGRATION_SOURCE = "migration_http"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-base-url", required=True, help="13번 서버의 /api/backend 또는 백엔드 API URL")
    parser.add_argument("--days", type=int, default=7, choices=range(1, 31))
    parser.add_argument("--concurrency", type=int, default=4, choices=range(1, 9))
    parser.add_argument("--source", default=MIGRATION_SOURCE)
    return parser.parse_args()


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


async def fetch_json(client: httpx.AsyncClient, base_url: str, path: str, params: dict[str, Any] | None = None) -> Any:
    response = await client.get(f"{base_url}/{path.lstrip('/')}", params=params)
    response.raise_for_status()
    return response.json()


async def fetch_lot_history(
    client: httpx.AsyncClient,
    base_url: str,
    airport_code: str,
    lot: dict[str, Any],
    days: int,
    semaphore: asyncio.Semaphore,
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    async with semaphore:
        payload = await fetch_json(
            client,
            base_url,
            "/parking/history",
            {"parking_lot_id": lot["id"], "days": days},
        )
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError(f"{airport_code}/{lot['id']} history response has no items list")
    items = payload["items"]
    required_fields = {"observed_at", "occupied_spaces", "total_spaces", "available_spaces"}
    for index, item in enumerate(items):
        if not isinstance(item, dict) or not required_fields.issubset(item):
            raise ValueError(f"{airport_code}/{lot['id']} history item {index} has an invalid shape")
    return airport_code, lot, items


async def upsert_reference_data(session: AsyncSession, airport_payload: dict[str, Any]) -> tuple[Airport, dict[int, ParkingLot]]:
    airport = await session.scalar(select(Airport).where(Airport.code == airport_payload["code"].upper()))
    now = datetime.now(timezone.utc)
    if airport is None:
        airport = Airport(
            code=airport_payload["code"].upper(),
            name_ko=airport_payload["name_ko"],
            name_en=airport_payload.get("name_en"),
            source=airport_payload.get("source", MIGRATION_SOURCE),
            created_at=now,
            updated_at=now,
        )
        session.add(airport)
        await session.flush()
    else:
        airport.name_ko = airport_payload["name_ko"]
        airport.name_en = airport_payload.get("name_en")
        airport.updated_at = now

    lots_by_source_id: dict[int, ParkingLot] = {}
    for lot_payload in airport_payload.get("parking_lots", []):
        source_lot_id = str(lot_payload["id"])
        lot = await session.scalar(
            select(ParkingLot).where(
                ParkingLot.airport_id == airport.id,
                or_(
                    ParkingLot.source_lot_id == source_lot_id,
                    ParkingLot.legacy_source_lot_id == source_lot_id,
                ),
            )
        )
        if lot is None:
            named_lots = (
                await session.scalars(
                    select(ParkingLot)
                    .where(ParkingLot.airport_id == airport.id, ParkingLot.name == lot_payload["name"])
                    .order_by(ParkingLot.id)
                )
            ).all()
            if named_lots:
                raise ValueError(
                    f"unmatched stable lot identity for {airport.code}/{lot_payload['name']!r}; "
                    "refusing an implicit name-based merge"
                )
        if lot is None:
            lot = ParkingLot(
                airport_id=airport.id,
                source_lot_id=source_lot_id,
                legacy_source_lot_id=source_lot_id,
                name=lot_payload["name"],
                terminal=lot_payload.get("terminal"),
                category=lot_payload.get("category"),
                is_active=lot_payload.get("is_active", True),
                created_at=now,
                updated_at=now,
            )
            session.add(lot)
            await session.flush()
        else:
            if lot.legacy_source_lot_id is not None and lot.legacy_source_lot_id != source_lot_id:
                raise ValueError(
                    f"conflicting legacy source identity for {airport.code}/{lot_payload['name']!r}: "
                    f"existing={lot.legacy_source_lot_id} incoming={source_lot_id}"
                )
            lot.legacy_source_lot_id = source_lot_id
            lot.name = lot_payload["name"]
            lot.terminal = lot_payload.get("terminal")
            lot.category = lot_payload.get("category")
            lot.is_active = lot_payload.get("is_active", True)
            lot.updated_at = now
        lots_by_source_id[int(lot_payload["id"])] = lot
    return airport, lots_by_source_id


async def import_history(args: argparse.Namespace) -> int:
    settings = Settings()
    engine, session_factory = create_engine_and_session_factory(settings.database_url)
    base_url = args.source_base_url.rstrip("/")
    imported = 0
    deduplicated = 0
    failures: list[str] = []

    async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
        airports_payload = await fetch_json(client, base_url, "/airports")
        if not isinstance(airports_payload, list) or not airports_payload:
            raise ValueError("/airports returned no airport list")
        for airport in airports_payload:
            if not isinstance(airport, dict) or not airport.get("code") or not isinstance(airport.get("parking_lots"), list):
                raise ValueError("/airports returned an invalid airport or parking_lots shape")
            seen_source_identities: set[tuple[str, str]] = set()
            airport_code = str(airport["code"]).upper()
            for lot in airport["parking_lots"]:
                if not isinstance(lot, dict) or lot.get("id") is None or not lot.get("name"):
                    raise ValueError("/airports returned an invalid parking lot shape")
                identity = (airport_code, str(lot["id"]))
                if identity in seen_source_identities:
                    raise ValueError(
                        f"/airports returned duplicate source identity {airport_code}/{lot['id']}"
                    )
                seen_source_identities.add(identity)
        history_tasks = []
        semaphore = asyncio.Semaphore(args.concurrency)
        for airport in airports_payload:
            for lot in airport.get("parking_lots", []):
                history_tasks.append(
                    fetch_lot_history(
                        client,
                        base_url,
                        airport["code"].upper(),
                        lot,
                        args.days,
                        semaphore,
                    )
                )
        histories = await asyncio.gather(*history_tasks, return_exceptions=True)

    histories_by_source_lot: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for result in histories:
        if isinstance(result, Exception):
            failures.append(str(result))
            continue
        airport_code, lot, items = result
        histories_by_source_lot[(airport_code, int(lot["id"]))] = items

    if failures:
        await engine.dispose()
        print(f"imported_snapshots=0 source_lots={len(histories_by_source_lot)} failures={len(failures)}")
        for failure in failures[:10]:
            print(f"migration_warning={failure}")
        return 2

    async with session_factory() as session:
        lots_by_source_lot: dict[tuple[str, int], tuple[int, int]] = {}
        for airport_payload in airports_payload:
            airport, lots = await upsert_reference_data(session, airport_payload)
            for source_lot_id, lot in lots.items():
                lots_by_source_lot[(airport.code, source_lot_id)] = (airport.id, lot.id)

        for (airport_code, source_lot_id), items in histories_by_source_lot.items():
            reference = lots_by_source_lot.get((airport_code, source_lot_id))
            if reference is None:
                failures.append(f"source parking lot {airport_code}/{source_lot_id} was not found in /airports")
                continue
            airport_id, parking_lot_id = reference
            rows = []
            for item in items:
                observed_at = parse_timestamp(item["observed_at"])
                collected_at = parse_timestamp(item.get("collected_at", item["observed_at"]))
                rows.append(
                    {
                        "airport_id": airport_id,
                        "parking_lot_id": parking_lot_id,
                        "source": args.source,
                        "observed_at": observed_at,
                        "collected_at": collected_at,
                        "occupied_spaces": int(item["occupied_spaces"]),
                        "total_spaces": int(item["total_spaces"]),
                        "available_spaces": int(item["available_spaces"]),
                        "congestion_label": None,
                        "congestion_ratio": None,
                        "raw_item_json": {
                            **item,
                            "migration": "http",
                            "source_airport_code": airport_code,
                            "source_lot_id": source_lot_id,
                        },
                    }
                )
            if not rows:
                continue
            statement = insert(ParkingSnapshot).values(rows)
            statement = statement.on_conflict_do_update(
                constraint="uq_parking_snapshot",
                set_={
                    "airport_id": statement.excluded.airport_id,
                    "collected_at": statement.excluded.collected_at,
                    "occupied_spaces": statement.excluded.occupied_spaces,
                    "total_spaces": statement.excluded.total_spaces,
                    "available_spaces": statement.excluded.available_spaces,
                    "raw_item_json": statement.excluded.raw_item_json,
                },
            )
            await session.execute(statement)
            imported += len(rows)
        if failures:
            await session.rollback()
            imported = 0
        else:
            if args.source.startswith("migration_"):
                canonical_snapshot = aliased(ParkingSnapshot)
                cleanup = delete(ParkingSnapshot).where(
                    ParkingSnapshot.source == args.source,
                    select(canonical_snapshot.id)
                    .where(
                        canonical_snapshot.parking_lot_id == ParkingSnapshot.parking_lot_id,
                        canonical_snapshot.observed_at == ParkingSnapshot.observed_at,
                        canonical_snapshot.source != args.source,
                    )
                    .exists(),
                )
                cleanup_result = await session.execute(cleanup)
                deduplicated = cleanup_result.rowcount or 0
            await session.commit()

    await engine.dispose()
    print(
        f"imported_snapshots={imported} deduplicated_snapshots={deduplicated} "
        f"source_lots={len(histories_by_source_lot)} failures={len(failures)}"
    )
    for failure in failures[:10]:
        print(f"migration_warning={failure}")
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(import_history(parse_args())))
