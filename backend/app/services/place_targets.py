"""장소 보강은 100개 ID와 현재 한 행만 보유한다. 조회 이름 중복은 DB에서 확인한다."""

from sqlalchemy import func, select

from app.models import BusTerminalReference, FerryPort


def _missing(model, name):
    return select(model.id).where(model.latitude.is_(None), name.is_not(None))


async def _ids(session, model, name):
    cursor = 0
    while True:
        ids = (
            await session.scalars(
                _missing(model, name)
                .where(model.id > cursor)
                .order_by(model.id)
                .limit(100)
            )
        ).all()
        if not ids:
            return
        for value in ids:
            yield value
        cursor = ids[-1]


async def iter_missing_place_targets(session):
    streams = [
        (
            _ids(session, BusTerminalReference, BusTerminalReference.terminal_name),
            "bus",
            BusTerminalReference,
        ),
        (_ids(session, FerryPort, FerryPort.port_name), "port", FerryPort),
    ]
    while streams:
        remaining = []
        for stream, kind, model in streams:
            try:
                key = await anext(stream)
            except StopAsyncIteration:
                continue
            row = await session.get(model, key)
            if row is not None:
                yield kind, row
            remaining.append((stream, kind, model))
        streams = remaining


async def matching_place_names(session, kind, row):
    if kind == "bus":
        statement = (
            select(func.count())
            .select_from(BusTerminalReference)
            .where(
                BusTerminalReference.service_type == row.service_type,
                BusTerminalReference.terminal_name == row.terminal_name,
                BusTerminalReference.city_name == row.city_name,
            )
        )
    else:
        statement = (
            select(func.count())
            .select_from(FerryPort)
            .where(FerryPort.port_name == row.port_name)
        )
    return await session.scalar(statement)


async def missing_place_count(session):
    return sum(
        [
            await session.scalar(
                select(func.count()).select_from(_missing(model, name).subquery())
            )
            or 0
            for model, name in [
                (BusTerminalReference, BusTerminalReference.terminal_name),
                (FerryPort, FerryPort.port_name),
            ]
        ]
    )
