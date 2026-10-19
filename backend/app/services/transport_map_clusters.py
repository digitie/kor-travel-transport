"""교통 지도 저배율 클러스터 SQL 구성."""

from __future__ import annotations

from collections.abc import Sequence
from math import floor
from typing import Any

from sqlalchemy import Integer, cast, func, literal, select
from sqlalchemy.sql import ColumnElement, Select


def viewport_cluster_grid_size(
    *,
    min_longitude: float,
    min_latitude: float,
    max_longitude: float,
    max_latitude: float,
    zoom: int,
) -> float:
    """화면에서 클러스터 수가 과도해지지 않도록 줌과 bbox로 격자 크기를 고른다."""

    zoom_level = min(max(int(zoom), 0), 22)
    longitude_span = max(max_longitude - min_longitude, 0.0)
    latitude_span = max(max_latitude - min_latitude, 0.0)
    # 18칸 정도가 화면을 채우도록 하고, 72px 반경보다 작은 셀은 만들지 않는다.
    screen_cell_degrees = 72.0 / (2**zoom_level)
    return max(0.02, screen_cell_degrees, longitude_span / 18, latitude_span / 18)


def coordinate_cluster_select(
    *,
    kind: str,
    longitude: ColumnElement[Any],
    latitude: ColumnElement[Any],
    conditions: Sequence[ColumnElement[bool]],
    grid_size: float,
    from_clause: Any | None = None,
) -> Select[Any]:
    """상세 행 대신 셀별 개수와 중심만 반환하는 SQL을 만든다."""

    cell_x = cast(func.floor(longitude / grid_size), Integer).label("cell_x")
    cell_y = cast(func.floor(latitude / grid_size), Integer).label("cell_y")
    statement = select(
        literal(kind).label("kind"),
        cell_x,
        cell_y,
        func.count().label("point_count"),
        func.avg(longitude).label("longitude"),
        func.avg(latitude).label("latitude"),
    )
    if from_clause is not None:
        statement = statement.select_from(from_clause)
    return statement.where(*conditions).group_by(cell_x, cell_y)


def cluster_cell(
    longitude: float, latitude: float, grid_size: float
) -> tuple[int, int]:
    """SQL에서 계산한 cell key와 동일한 Python key를 만든다(공항 소수 행 결합용)."""

    return floor(longitude / grid_size), floor(latitude / grid_size)
