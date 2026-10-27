"""한 SQL snapshot에서 archive와 필요한 raw만 읽는 내부 pattern 어댑터.

API/캐시 연결은 별도 단계다. caller transaction의 격리수준·commit·lease는 바꾸지 않는다.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import case, cast, literal, null, or_, select, true, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Airport, ParkingLot, ParkingSnapshot, ParkingStatisticsBucket
from app.services.parking_archive_reader import ParkingPatternStatistics, _utc, read_pattern_statistics
from app.services.parking_statistics_archive import BUCKET_INTERVAL, _bucket_expression, bucket_start

_RAW_NAMES = ("id", "airport_id", "parking_lot_id", "source", "observed_at", "collected_at",
              "available_spaces", "occupied_spaces", "total_spaces", "congestion_label",
              "congestion_ratio", "raw_item_json")
_ARCHIVE = ParkingStatisticsBucket.__table__
_RAW = ParkingSnapshot.__table__


def _project(kind, archive=None, raw=None):
    columns = [literal(kind).label("kind")]
    for prefix, table, names, values in (
        ("archive_", _ARCHIVE, tuple(_ARCHIVE.c.keys()), archive),
        ("raw_", _RAW, _RAW_NAMES, raw),
    ):
        for name in names:
            value = values.c[name] if values is not None else cast(null(), table.c[name].type)
            columns.append(value.label(prefix + name))
    return columns


def build_pattern_statistics_query(
    *, start: datetime, end: datetime, airport_id: int | None = None, parking_lot_id: int | None = None,
):
    """공항 PK 범위·seal PK 등가 조회를 한 statement로 합친다. lot가 공항보다 우선한다."""
    start, end = _utc(start), _utc(end)
    if start >= end:
        raise ValueError("통계 시작은 종료보다 앞서야 합니다.")
    first = bucket_start(start)
    final = bucket_start(end)
    expanded_end = end if final == end else final + BUCKET_INTERVAL
    airports = select(Airport.id)
    if parking_lot_id is not None:
        airports = airports.where(Airport.id == select(ParkingLot.airport_id).where(
            ParkingLot.id == parking_lot_id,
        ).scalar_subquery())
    elif airport_id is not None:
        airports = airports.where(Airport.id == airport_id)
    scopes = airports.subquery("pattern_airports")
    # 전국도 공항별 PK의 시간 범위만 탐색한다. 영구 전체 이력을 hash할 이유가 없다.
    archived = select(*_ARCHIVE.c).where(
        _ARCHIVE.c.airport_id == scopes.c.id,
        _ARCHIVE.c.bucket_at >= first, _ARCHIVE.c.bucket_at < end,
    ).correlate(scopes).offset(0).lateral("pattern_archive")
    archive_rows = select(*_project("archive", archive=archived)).select_from(scopes.join(archived, true()))

    seal = select(_ARCHIVE.c.airport_id, _ARCHIVE.c.bucket_at, _ARCHIVE.c.bucket_end,
                  _ARCHIVE.c.max_snapshot_id).where(
        _ARCHIVE.c.airport_id == _RAW.c.airport_id,
        _ARCHIVE.c.bucket_at == _bucket_expression(_RAW.c.observed_at, "postgresql"),
    ).correlate(_RAW).offset(0).lateral("pattern_seal")
    boundary = or_(seal.c.bucket_at < start, seal.c.bucket_end > end)
    raw_columns = [
        (case((boundary, _RAW.c.raw_item_json), else_=cast(null(), _RAW.c.raw_item_json.type)).label(name)
         if name == "raw_item_json" else _RAW.c[name]) for name in _RAW_NAMES
    ]
    needed_raw = select(*raw_columns).select_from(_RAW.outerjoin(seal, true())).where(
        _RAW.c.airport_id == scopes.c.id,
        _RAW.c.observed_at >= first, _RAW.c.observed_at < expanded_end,
        or_(seal.c.airport_id.is_(None), _RAW.c.id > seal.c.max_snapshot_id, boundary),
    ).correlate(scopes).offset(0).lateral("pattern_raw")
    raw_rows = select(*_project("raw", raw=needed_raw)).select_from(scopes.join(needed_raw, true()))
    return union_all(archive_rows, raw_rows)


async def load_pattern_statistics(
    session: AsyncSession, *, start: datetime, end: datetime,
    airport_id: int | None = None, parking_lot_id: int | None = None,
) -> ParkingPatternStatistics:
    """현재 세 pattern API와 같은 KST 기준이다. 정확하지 않은 절단은 내부 예외로 남긴다.

    두 쿼리 사이 backfill 발행으로 자료가 양쪽에서 빠지는 READ COMMITTED 경쟁을 피한다.
    제공된 기간의 완전성은 추정하지 않으며 API의 에러/부분범위 계약은 여기서 결정하지 않는다.
    """
    if session.get_bind().dialect.name != "postgresql":
        raise ValueError("영구 통계 DB reader는 PostgreSQL에서 검증해야 합니다.")
    statement = build_pattern_statistics_query(start=start, end=end, airport_id=airport_id,
                                                parking_lot_id=parking_lot_id)
    rows = (await session.execute(statement)).mappings().all()
    records, raw = [], []
    for row in rows:
        if row["kind"] == "archive":
            records.append(ParkingStatisticsBucket(**{name: row["archive_" + name] for name in _ARCHIVE.c.keys()}))
        else:
            raw.append(SimpleNamespace(**{name: row["raw_" + name] for name in _RAW_NAMES}))
    result = read_pattern_statistics(records, raw, start=start, end=end,
                                     airport_id=None if parking_lot_id is not None else airport_id,
                                     parking_lot_id=parking_lot_id)
    return replace(result, metadata={**result.metadata, "database_snapshot": "single_statement"})
