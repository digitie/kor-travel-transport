"""역명 추정 대신 원천의 상세 주소와 일치하는 VWorld 건물·필지 좌표만 보강한다."""

import hashlib
import json
import math
import re
from collections.abc import Mapping

_ROAD = re.compile(r"(?:^|\s)([가-힣A-Za-z0-9·.]+(?:대로|로|길))\s*(\d+(?:-\d+)?)(?=\D|$)")
_PARCEL = re.compile(r"(?:^|\s)([가-힣0-9]+(?:읍|면|동|리|가))\s+(산\s*)?(\d+(?:-\d+)?)(?=\D|$)")


def rail_address_query(row):
    for address in (row.road_address, row.lot_address):
        if not address:
            continue
        if _ROAD.search(address):
            return address, "road"
        if _PARCEL.search(address):
            return address, "parcel"
    return None


def rail_address_signature(name, road_address, lot_address):
    return hashlib.sha256(json.dumps([name, road_address, lot_address], ensure_ascii=False).encode()).hexdigest()


def choose_rail_address(response, *, address, address_type, province):
    """시도·시군구와 도로/법정동·본번/부번을 모두 확인한다. 동 중심점은 수용하지 않는다."""
    if response.get("status") != "OK":
        return None
    refined, result = response.get("refined"), response.get("result")
    if not isinstance(refined, Mapping) or not isinstance(result, Mapping) or result.get("crs") != "EPSG:4326":
        return None
    structure, point = refined.get("structure"), result.get("point")
    if not isinstance(structure, Mapping) or not isinstance(point, Mapping):
        return None
    source = address.split()
    if len(source) < 3 or not province(source[0]) or province(source[0]) != province(str(structure.get("level1", ""))):
        return None
    districts = [v for v in source[1:] if v.endswith(("시", "군", "구"))]
    actual_district = str(structure.get("level2", "")).split()
    if not districts or not all(v in actual_district for v in districts):
        return None
    number = str(structure.get("level5", "")).replace(" ", "")
    if address_type == "road":
        match = _ROAD.search(address)
        if not match or match[1] != structure.get("level4L") or match[2] != number:
            return None
    else:
        match = _PARCEL.search(address)
        if (not match or (str(match[2] or "").replace(" ", "") + match[3]) != number
                or match[1] not in str(refined.get("text", "")).split()):
            return None
    try:
        lon, lat = float(point["x"]), float(point["y"])
    except (KeyError, ValueError, TypeError, OverflowError):
        return None
    if not math.isfinite(lon) or not math.isfinite(lat) or not (124 <= lon <= 132 and 32 <= lat <= 39.5):
        return None
    return {"longitude": lon, "latitude": lat, "refined_address": refined.get("text"),
            "source_address": address, "address_type": address_type}


def preserve_rail_address_location(row, values):
    """공식 원천 좌표를 우선하고, 같은 역명·주소에 대한 검증된 보강만 다음 수집에도 유지한다."""
    if row is None or values.get("latitude") is not None or values.get("longitude") is not None:
        return
    proof = (row.raw_item_json or {}).get("_vworld_address")
    if (not isinstance(proof, Mapping) or proof.get("version") != 1
            or proof.get("input_signature") != rail_address_signature(
                values.get("station_name"), values.get("road_address"), values.get("lot_address"))
            or row.latitude is None or row.longitude is None
            or proof.get("latitude") != row.latitude or proof.get("longitude") != row.longitude):
        return
    values["latitude"], values["longitude"] = row.latitude, row.longitude
    values["raw_item_json"] = {**(values.get("raw_item_json") or {}), "_vworld_address": dict(proof),
                               "coordinate_source": "vworld_address"}
