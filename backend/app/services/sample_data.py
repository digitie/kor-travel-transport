from __future__ import annotations

import math
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import align_to_ten_minutes, ensure_tz, now_utc
from app.models import Airport, ParkingFeeRule, ParkingLot, ParkingSnapshot


SAMPLE_AIRPORTS = [
    {
        "code": "GMP",
        "name_ko": "김포국제공항",
        "name_en": "Gimpo International Airport",
        "source": "kac",
        "lots": [
            {"source_lot_id": "gmp-domestic-1", "name": "국내선 제1주차장", "terminal": "국내선", "category": "short", "total": 510},
            {"source_lot_id": "gmp-domestic-2", "name": "국내선 제2주차장", "terminal": "국내선", "category": "short", "total": 640},
            {
                "source_lot_id": "gmp-international-underground",
                "name": "국제선 지하주차장",
                "terminal": "국제선",
                "category": "short",
                "total": 210,
                "legacy_source_lot_ids": ["gmp-international-1"],
            },
            {
                "source_lot_id": "gmp-international-building",
                "name": "국제선 주차빌딩",
                "terminal": "국제선",
                "category": "building",
                "total": 360,
            },
        ],
    },
    {
        "code": "PUS",
        "name_ko": "김해국제공항",
        "name_en": "Gimhae International Airport",
        "source": "kac",
        "lots": [
            {
                "source_lot_id": "pus-p1",
                "name": "P1 여객주차장",
                "terminal": "여객",
                "category": "passenger",
                "total": 2005,
                "legacy_source_lot_ids": ["pus-main-1"],
                "legacy_names": ["여객주차장"],
            },
            {"source_lot_id": "pus-p2", "name": "P2 여객주차장", "terminal": "여객", "category": "passenger", "total": 2453},
            {"source_lot_id": "pus-p3", "name": "P3 여객(화물)주차장", "terminal": "여객/화물", "category": "cargo", "total": 878},
        ],
    },
    {
        "code": "CJU",
        "name_ko": "제주국제공항",
        "name_en": "Jeju International Airport",
        "source": "kac",
        "lots": [
            {"source_lot_id": "cju-p1", "name": "P1 주차장", "terminal": "여객", "category": "main", "total": 820},
            {"source_lot_id": "cju-p2", "name": "P2 장기주차장", "terminal": "여객", "category": "long", "total": 420},
            {"source_lot_id": "cju-cargo", "name": "화물터미널주차장", "terminal": "화물", "category": "cargo", "total": 180},
        ],
    },
    {
        "code": "ICN",
        "name_ko": "인천국제공항",
        "name_en": "Incheon International Airport",
        "source": "incheon",
        "lots": [
            {"source_lot_id": "icn-t1-short", "name": "T1 단기주차장", "terminal": "T1", "category": "short", "total": 640},
            {"source_lot_id": "icn-t1-long-p1", "name": "T1 장기주차장 P1", "terminal": "T1", "category": "long", "total": 1280},
            {"source_lot_id": "icn-t1-long-p2", "name": "T1 장기주차장 P2", "terminal": "T1", "category": "long", "total": 1420},
            {"source_lot_id": "icn-t1-long-p3", "name": "T1 장기주차장 P3", "terminal": "T1", "category": "long", "total": 1290},
            {"source_lot_id": "icn-t1-reserved", "name": "T1 예약주차장", "terminal": "T1", "category": "reserved", "total": 460},
            {"source_lot_id": "icn-t2-short", "name": "T2 단기주차장", "terminal": "T2", "category": "short", "total": 780},
            {"source_lot_id": "icn-t2-long", "name": "T2 장기주차장", "terminal": "T2", "category": "long", "total": 910},
            {"source_lot_id": "icn-t2-reserved", "name": "T2 예약주차장", "terminal": "T2", "category": "reserved", "total": 320},
        ],
    },
]


def _sample_available(total: int, day_offset: int, hour: int, minute: int, lot_index: int, airport_code: str) -> int:
    hour_position = hour + (minute / 60)
    peak = math.sin((hour_position / 24) * math.pi * 2 + lot_index * 0.7)
    weekend_bias = 0.12 if airport_code == "CJU" else 0.05
    weekday_bias = 0.02 if airport_code == "ICN" else 0.0
    day_effect = weekend_bias if day_offset % 7 in (0, 1) else weekday_bias
    load_ratio = 0.58 + (peak * 0.18) + day_effect + (lot_index * 0.03)
    load_ratio = max(0.32, min(load_ratio, 0.97))
    occupied = int(total * load_ratio)
    return max(total - occupied, 0)


def _recent_override(total: int, airport_code: str, lot_name: str, index: int) -> int | None:
    scripted = {
        ("GMP", "국내선 제1주차장"): [96, 64, 48, 27, 14, 8],
        ("CJU", "P1 주차장"): [160, 124, 82, 54, 41, 18],
        ("ICN", "T1 단기주차장"): [220, 160, 120, 92, 78, 65],
    }
    values = scripted.get((airport_code, lot_name))
    if values is None or index >= len(values):
        return None
    return min(values[index], total)


async def seed_sample_database(session: AsyncSession) -> None:
    now = align_to_ten_minutes(now_utc())
    now_seoul = now.astimezone(ZoneInfo("Asia/Seoul"))
    created_airports: dict[str, Airport] = {}
    created_lots: list[tuple[Airport, ParkingLot, int]] = []

    await session.execute(
        delete(ParkingSnapshot).where(
            ParkingSnapshot.collection_run_id.is_(None),
            ParkingSnapshot.observed_at > now,
        )
    )

    for airport_data in SAMPLE_AIRPORTS:
        airport = await session.scalar(select(Airport).where(Airport.code == airport_data["code"]))
        if airport is None:
            airport = Airport(
                code=airport_data["code"],
                name_ko=airport_data["name_ko"],
                name_en=airport_data["name_en"],
                source=airport_data["source"],
                created_at=now,
                updated_at=now,
            )
            session.add(airport)
            await session.flush()
        else:
            airport.name_ko = airport_data["name_ko"]
            airport.name_en = airport_data["name_en"]
            airport.source = airport_data["source"]
            airport.updated_at = now

        created_airports[airport.code] = airport

        for index, lot_data in enumerate(airport_data["lots"]):
            candidate_source_ids = [lot_data["source_lot_id"], *lot_data.get("legacy_source_lot_ids", [])]
            lot = await session.scalar(
                select(ParkingLot).where(
                    ParkingLot.airport_id == airport.id,
                    ParkingLot.source_lot_id.in_(candidate_source_ids),
                )
            )
            if lot is None and lot_data.get("legacy_names"):
                lot = await session.scalar(
                    select(ParkingLot).where(
                        ParkingLot.airport_id == airport.id,
                        ParkingLot.name.in_(lot_data["legacy_names"]),
                    )
                )

            if lot is None:
                lot = ParkingLot(
                    airport_id=airport.id,
                    source_lot_id=lot_data["source_lot_id"],
                    name=lot_data["name"],
                    terminal=lot_data["terminal"],
                    category=lot_data["category"],
                    total_spaces_hint=lot_data["total"],
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                session.add(lot)
                await session.flush()
            else:
                lot.source_lot_id = lot_data["source_lot_id"]
                lot.name = lot_data["name"]
                lot.terminal = lot_data["terminal"]
                lot.category = lot_data["category"]
                lot.total_spaces_hint = lot_data["total"]
                lot.is_active = True
                lot.updated_at = now

            created_lots.append((airport, lot, index))

    await session.flush()

    for airport, lot, index in created_lots:
        total = lot.total_spaces_hint or 100
        source = airport.source if airport.code == "ICN" else "kac_parking"
        # 동일 lot/source의 실제 생성 구간만 한 번 읽는다. SQLite는 UTC를 naive로
        # 돌려주므로 aware UTC로 맞추며, 아래 신규 시각도 즉시 넣어 최근 override와
        # 겹치는 반시간 관측을 기존처럼 먼저 생성한 값으로 유지한다.
        first_observed_at = (now_seoul - timedelta(days=7)).replace(
            hour=0, minute=0, second=0, microsecond=0,
        ).astimezone(ZoneInfo("UTC"))
        existing_times = {
            ensure_tz(value, "UTC")
            for value in await session.scalars(
                select(ParkingSnapshot.observed_at).where(
                    ParkingSnapshot.parking_lot_id == lot.id,
                    ParkingSnapshot.source == source,
                    ParkingSnapshot.observed_at >= first_observed_at,
                    ParkingSnapshot.observed_at <= now,
                )
            )
        }

        for day_offset in range(7, -1, -1):
            day = now_seoul - timedelta(days=day_offset)
            for half_hour_index in range(48):
                hour = half_hour_index // 2
                minute = 30 if half_hour_index % 2 else 0
                observed_at = day.replace(
                    hour=hour,
                    minute=minute,
                    second=0,
                    microsecond=0,
                ).astimezone(ZoneInfo("UTC"))
                if observed_at > now:
                    continue

                if observed_at in existing_times:
                    continue

                available = _sample_available(total, day_offset, hour, minute, index, airport.code)
                occupied = total - available
                ratio = round((occupied / total) * 100, 2) if total else None
                session.add(
                    ParkingSnapshot(
                        collection_run_id=None,
                        airport_id=airport.id,
                        parking_lot_id=lot.id,
                        source=source,
                        observed_at=observed_at,
                        collected_at=observed_at,
                        occupied_spaces=occupied,
                        total_spaces=total,
                        available_spaces=available,
                        congestion_label="혼잡" if available < 50 else "원활",
                        congestion_ratio=ratio,
                        raw_item_json={"seeded": True},
                    )
                )
                existing_times.add(observed_at)

        for offset_index in range(6):
            observed_at = now - timedelta(minutes=(50 - (offset_index * 10)))
            override_available = _recent_override(total, airport.code, lot.name, offset_index)
            if override_available is None:
                continue

            if observed_at in existing_times:
                continue

            session.add(
                ParkingSnapshot(
                    collection_run_id=None,
                    airport_id=airport.id,
                    parking_lot_id=lot.id,
                    source=source,
                    observed_at=observed_at,
                    collected_at=observed_at,
                    occupied_spaces=total - override_available,
                    total_spaces=total,
                    available_spaces=override_available,
                    congestion_label="만차임박" if override_available < 10 else "혼잡",
                    congestion_ratio=round(((total - override_available) / total) * 100, 2),
                    raw_item_json={"seeded": True, "recent": True},
                )
            )
            existing_times.add(observed_at)

    fee_updated_at = now
    for airport in created_airports.values():
        weekday_pairs = [("small", 30, 30, 1000, 15, 500, 20000), ("large", 30, 30, 1200, 15, 600, 25000)]
        holiday_pairs = [("small", 30, 30, 1500, 15, 700, 25000), ("large", 30, 30, 1800, 15, 800, 30000)]

        for lot in [entry[1] for entry in created_lots if entry[0].code == airport.code]:
            for vehicle_size, free_m, basic_m, basic_fee, unit_m, unit_fee, daily_max in weekday_pairs:
                existing_rule = await session.scalar(
                    select(ParkingFeeRule).where(
                        ParkingFeeRule.airport_id == airport.id,
                        ParkingFeeRule.parking_lot_id == lot.id,
                        ParkingFeeRule.vehicle_size == vehicle_size,
                        ParkingFeeRule.day_type == "weekday",
                    )
                )
                if existing_rule is None:
                    session.add(
                        ParkingFeeRule(
                            airport_id=airport.id,
                            parking_lot_id=lot.id,
                            vehicle_size=vehicle_size,
                            day_type="weekday",
                            free_minutes=free_m,
                            basic_minutes=basic_m,
                            basic_fee=basic_fee,
                            unit_minutes=unit_m,
                            unit_fee=unit_fee,
                            daily_max_fee=daily_max,
                            source_updated_at=fee_updated_at,
                            raw_item_json={"seeded": True},
                        )
                    )
                else:
                    existing_rule.free_minutes = free_m
                    existing_rule.basic_minutes = basic_m
                    existing_rule.basic_fee = basic_fee
                    existing_rule.unit_minutes = unit_m
                    existing_rule.unit_fee = unit_fee
                    existing_rule.daily_max_fee = daily_max
                    existing_rule.source_updated_at = fee_updated_at
                    existing_rule.raw_item_json = {"seeded": True}

            for vehicle_size, free_m, basic_m, basic_fee, unit_m, unit_fee, daily_max in holiday_pairs:
                existing_rule = await session.scalar(
                    select(ParkingFeeRule).where(
                        ParkingFeeRule.airport_id == airport.id,
                        ParkingFeeRule.parking_lot_id == lot.id,
                        ParkingFeeRule.vehicle_size == vehicle_size,
                        ParkingFeeRule.day_type == "holiday",
                    )
                )
                if existing_rule is None:
                    session.add(
                        ParkingFeeRule(
                            airport_id=airport.id,
                            parking_lot_id=lot.id,
                            vehicle_size=vehicle_size,
                            day_type="holiday",
                            free_minutes=free_m,
                            basic_minutes=basic_m,
                            basic_fee=basic_fee,
                            unit_minutes=unit_m,
                            unit_fee=unit_fee,
                            daily_max_fee=daily_max,
                            source_updated_at=fee_updated_at,
                            raw_item_json={"seeded": True},
                        )
                    )
                else:
                    existing_rule.free_minutes = free_m
                    existing_rule.basic_minutes = basic_m
                    existing_rule.basic_fee = basic_fee
                    existing_rule.unit_minutes = unit_m
                    existing_rule.unit_fee = unit_fee
                    existing_rule.daily_max_fee = daily_max
                    existing_rule.source_updated_at = fee_updated_at
                    existing_rule.raw_item_json = {"seeded": True}

    await session.commit()
