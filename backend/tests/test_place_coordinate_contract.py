from datetime import datetime, timezone

import pytest

from app.schemas import TransportPlaceMapItem, TransportPlaceMapResponse


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("longitude,latitude", [
    (37.424805, 126.423637), (181, 37), (-181, 37), (127, -91),
    (float("inf"), 37), (127, float("nan")), (None, 37), (127, None),
])
def test_place_map_contract_excludes_invalid_coordinates(longitude, latitude, nested):
    values = dict(
        id=1, kind="rail_station", source="kric_public_file", name="용유",
        longitude=longitude, latitude=latitude, updated_at=datetime.now(timezone.utc),
    )
    item = TransportPlaceMapResponse(generated_at=values["updated_at"], kind="rail_station", total=1, truncated=False,
        items=[values if nested else TransportPlaceMapItem(**values)]).items[0]
    assert item.longitude is None and item.latitude is None
    assert item.name == "용유"
    assert '"longitude":null' in item.model_dump_json()


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("longitude,latitude", [(180, 90), (-180, -90), (127, 37), (0, 0)])
def test_place_map_contract_keeps_valid_coordinates(longitude, latitude, nested):
    values = dict(
        id=1, kind="rail_station", source="kric_public_file", name="역",
        longitude=longitude, latitude=latitude, updated_at=datetime.now(timezone.utc),
    )
    item = TransportPlaceMapResponse(generated_at=values["updated_at"], kind="rail_station", total=1, truncated=False,
        items=[values if nested else TransportPlaceMapItem(**values)]).items[0]
    assert (item.longitude, item.latitude) == (longitude, latitude)
