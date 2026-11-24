"""Map export에 붙일 파생 주소만 같은 읽기 snapshot에서 일괄 조회한다."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from kortravelcommon.address_providers import VworldKakaoAddressResolver
from kortravelcommon.reverse_address import AddressTarget, reverse_address_tables
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import serialize_utc
from app.models import Base
from app.schemas import ExportAdminAddress


def _text(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


async def export_admin_addresses(
    session: AsyncSession, kind: str, rows: Sequence[Any],
) -> dict[int, ExportAdminAddress]:
    return build_admin_addresses(await fetch_admin_address_rows(session, kind, rows))


async def fetch_admin_address_rows(
    session: AsyncSession, kind: str, rows: Sequence[Any],
) -> list[tuple[int, Any, Any]]:
    """현재 좌표와 일치하는 주소 행만 `(row_id, payload, resolved_at)`으로 읽는다(DB 단계).

    DTO 구성(`build_admin_addresses`)과 나눠 두어, 호출자가 읽기 transaction을 끝낸 뒤 worker thread에서
    구성할 수 있게 한다(감사 T1-03·T1-04).
    """
    targets: dict[str, tuple[int, AddressTarget]] = {}
    for row in rows:
        if row.longitude is None or row.latitude is None:
            continue
        try:
            target = AddressTarget(f"{kind}:{row.id}", float(row.longitude), float(row.latitude))
        except (ValueError, TypeError):
            continue
        targets[target.key] = (row.id, target)
    if not targets:
        return []
    entries, _ = reverse_address_tables(Base.metadata)
    payload = entries.c.payload
    if session.bind.dialect.name == "postgresql":
        payload = func.jsonb_build_object("provider", payload["provider"], "address", payload["address"], "region", payload["region"])
    query = select(entries.c.target_key, entries.c.coordinate_key,
                   payload.label("payload"), entries.c.resolved_at).where(
        entries.c.provider_id == VworldKakaoAddressResolver.provider_id,
        entries.c.status.in_(("ok", "error")),
        entries.c.target_key.in_(targets),
    )
    fetched: list[tuple[int, Any, Any]] = []
    for row in (await session.execute(query)).mappings():
        row_id, target = targets[row["target_key"]]
        if row["coordinate_key"] != target.coordinate_key:
            continue
        fetched.append((row_id, row["payload"], row["resolved_at"]))
    return fetched


def build_admin_addresses(fetched: Sequence[tuple[int, Any, Any]]) -> dict[int, ExportAdminAddress]:
    """`fetch_admin_address_rows` 결과로 export 주소 DTO를 만든다. 세션을 쓰지 않아 thread에서 불러도 된다."""
    result: dict[int, ExportAdminAddress] = {}
    for row_id, payload, resolved_at in fetched:
        if not isinstance(payload, dict) or not isinstance(resolved_at, datetime):
            continue
        provider = payload.get("provider")
        if not isinstance(provider, str) or provider not in {"vworld", "kakao"}:
            continue
        address = payload.get("address")
        region = payload.get("region")
        if not isinstance(address, dict):
            continue
        region = region if isinstance(region, dict) else {}
        legal_code = _text(address.get("legal_dong_code"))
        if legal_code is not None and (len(legal_code) != 10 or not legal_code.isascii()
                                       or not legal_code.isdecimal()):
            legal_code = None
        result[row_id] = ExportAdminAddress(
            legal_dong_code=legal_code, admin_dong_code=_text(address.get("admin_dong_code")),
            sido_name=_text(region.get("sido")), sigungu_name=_text(region.get("sigungu")),
            legal_dong_name=_text(region.get("legal_dong")),
            road_address=_text(address.get("road_address")),
            parcel_address=_text(address.get("parcel_address")),
            postal_code=_text(address.get("postal_code")), provider=provider,
            resolved_at=serialize_utc(resolved_at),
        )
    return result
