"""Copy the complete known legacy parking-radar SQLite schema into PostgreSQL.

Run this on 14 only, after placing an authorized copy of the 13 SQLite file on
14. The script preserves primary keys and resets PostgreSQL sequences. It never
connects to or runs Docker on 13.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from app.core.config import Settings
from app.db.session import create_engine_and_session_factory
from app.models import (
    Airport,
    AnalyticsCache,
    CollectionRun,
    ParkingFeeRule,
    ParkingLot,
    ParkingSnapshot,
    RawApiResponse,
)


TABLES = [Airport, ParkingLot, CollectionRun, RawApiResponse, ParkingSnapshot, AnalyticsCache, ParkingFeeRule]
JSON_COLUMNS = {"request_params_json", "raw_item_json", "payload_json"}
DATETIME_COLUMNS = {
    "created_at",
    "updated_at",
    "started_at",
    "finished_at",
    "received_at",
    "observed_at",
    "collected_at",
    "generated_at",
    "source_observed_at",
    "source_updated_at",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sqlite_path", type=Path)
    return parser.parse_args()


def normalize_value(column: str, value: Any) -> Any:
    if value is None:
        return None
    if column in JSON_COLUMNS and isinstance(value, str):
        return json.loads(value)
    if column in DATETIME_COLUMNS and isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return value


async def migrate(sqlite_path: Path) -> int:
    if not sqlite_path.is_file():
        raise FileNotFoundError(sqlite_path)

    settings = Settings()
    engine, session_factory = create_engine_and_session_factory(settings.database_url)
    sqlite = sqlite3.connect(sqlite_path)
    sqlite.row_factory = sqlite3.Row
    copied = 0
    try:
        async with session_factory() as session:
            for model in TABLES:
                rows = [dict(row) for row in sqlite.execute(f"SELECT * FROM {model.__tablename__}")]
                if not rows:
                    continue
                rows = [{key: normalize_value(key, value) for key, value in row.items()} for row in rows]
                statement = insert(model).values(rows)
                update_columns = {
                    column.name: getattr(statement.excluded, column.name)
                    for column in model.__table__.columns
                    if column.name != "id"
                }
                statement = statement.on_conflict_do_update(index_elements=[model.__table__.c.id], set_=update_columns)
                await session.execute(statement)
                copied += len(rows)

            await session.commit()
            for model in TABLES:
                await session.execute(
                    text(
                        f"SELECT setval(pg_get_serial_sequence('{model.__tablename__}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {model.__tablename__}), 1), true)"
                    )
                )
            await session.commit()
    finally:
        sqlite.close()
        await engine.dispose()

    print(f"copied_rows={copied} sqlite_path={sqlite_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(migrate(parse_args().sqlite_path)))
