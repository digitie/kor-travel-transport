"""다중 종류 장소의 정확한 총계·제한된 투영을 한 왕복으로 읽는다."""
from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import JSON, DateTime, cast, func, literal, or_, select, union_all
from sqlalchemy.dialects.postgresql import aggregate_order_by

from app.models import (
    BusTerminalReference,
    FerryPort,
    FuelStation,
    HighwayIncidentSnapshot,
    PublicParkingLot,
    RailStationReference,
    RestAreaReference,
)

RAIL_FACILITY_KEYS = ("환승역 여부", "유실물 취급여부", "안전발판 유무", "스크린도어 설치유무", "승강장 연결여부")


def place_queries(requested, coordinate_conditions, include_unlocated, has_bounds, now, limit):
    specs = {
        "fuel_station": (FuelStation, "id source name longitude latitude address brand_name brand_code phone is_self is_24h has_carwash has_maintenance has_cvs last_seen_at", (FuelStation.last_seen_at.desc(), FuelStation.id.desc())),
        "rail_station": (RailStationReference, "id source station_name longitude latitude rail_operator_name operating_line_name station_phone_number station_type road_address lot_address last_seen_at", (RailStationReference.last_seen_at.desc(), RailStationReference.id.desc())),
        "ferry_port": (FerryPort, "id source port_id port_name longitude latitude location_source location_point_count last_seen_at", (FerryPort.last_seen_at.desc(), FerryPort.id.desc())),
        "bus_terminal": (BusTerminalReference, "id source terminal_id terminal_name city_name longitude latitude service_type location_source last_seen_at", (BusTerminalReference.last_seen_at.desc(), BusTerminalReference.id.desc())),
        "public_parking_lot": (PublicParkingLot, "id source provider_id name longitude latitude road_address land_address phone capacity fee_info last_seen_at", (PublicParkingLot.id,)),
        "rest_area": (RestAreaReference, "id source name longitude latitude direction route_name phone_number has_gas_station has_lpg_station has_ev_charger last_seen_at", (RestAreaReference.name, RestAreaReference.id)),
        "highway_incident": (HighwayIncidentSnapshot, "id source identity_key point_name incident_type longitude latitude route_no route_name process_status direction message collected_at observed_at", (HighwayIncidentSnapshot.observed_at.desc(), HighwayIncidentSnapshot.id.desc())),
    }
    plans = {}
    for kind in requested:
        if kind not in specs:
            continue
        model, names, order = specs[kind]
        columns = [getattr(model, name) for name in names.split()]
        if kind == "rail_station":
            columns.append(func.json_build_object(*[part for key in RAIL_FACILITY_KEYS
                for part in (key, model.raw_item_json[key].as_string())]).label("raw_item_json"))
        elif kind in {"ferry_port", "bus_terminal"}:
            columns.append(func.json_build_object("_manual_location", func.json_build_object(
                "revision", model.raw_item_json["_manual_location"]["revision"])).label("raw_item_json"))
        conditions = coordinate_conditions(model)
        statement = select(*columns)
        if kind == "ferry_port" and (not include_unlocated or has_bounds):
            conditions.append(or_(model.location_source.is_(None), model.location_source != "data_go_kr_port_guideline"))
        if kind == "highway_incident":
            ranked = select(model.id, func.row_number().over(
                partition_by=(model.source, model.identity_key),
                order_by=(model.observed_at.desc(), model.collected_at.desc(), model.id.desc()),
            ).label("rank")).where(model.collected_at.between(now - timedelta(days=1), now)).subquery()
            # COUNT와 제한 페이지의 최신 ID 집합을 한 번 계산한다. MATERIALIZED는
            # 작은 표본에서도 planner가 window를 PK별 nested loop 안에 반복하지 않게 한다.
            latest_ids = select(ranked.c.id).where(ranked.c.rank == 1).cte(
                "latest_place_incident_ids",
            ).prefix_with("MATERIALIZED")
            statement = statement.join(latest_ids, model.id == latest_ids.c.id)
        plans[kind] = (statement.where(*conditions), order, limit)
    return plans


async def read_place_plans(session, plans):
    arms, dates = [], {}
    for kind, (query, order, limit) in plans.items():
        bounded = query.add_columns(func.row_number().over(order_by=order).label("_position")).order_by(*order).limit(limit).subquery()
        fields = [column for column in bounded.c if column.key != "_position"]
        dates[kind] = [column.key for column in fields if isinstance(column.type, DateTime)]
        body = func.json_build_object(*[part for column in fields for part in (column.key, column)])
        items = select(func.coalesce(func.json_agg(aggregate_order_by(body, bounded.c._position)),
                                     cast(literal("[]"), JSON))).select_from(bounded).scalar_subquery()
        total = select(func.count()).select_from(query.subquery()).scalar_subquery()
        arms.append(select(literal(kind).label("kind"), total.label("total"), items.label("items")))
    result = {}
    if arms:
        for kind, total, items in (await session.execute(union_all(*arms))).all():
            for row in items:
                for key in dates[kind]:
                    if row[key] is not None:
                        row[key] = datetime.fromisoformat(row[key])
            result[kind] = (int(total), [SimpleNamespace(**row) for row in items])
    return result


async def place_sources(session, requested, models):
    queries = [select(models[kind].source) for kind in requested]
    union = union_all(*queries).subquery()
    return set((await session.scalars(select(union.c.source).distinct())).all())
