"""원본 JSON 변환의 builtin/subclass/순서/오류 계약."""
from collections import OrderedDict, UserDict
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum, IntEnum
from types import MappingProxyType, SimpleNamespace

import pytest
from pydantic import BaseModel

from app.services.transport_collection import _plain_json, _provider_json


@pytest.mark.parametrize("value", [None, True, False, 0, -13, 2**80, 1.25, -0.0, "", "서울", float("inf"), float("nan")])
def test_exact_builtin_scalar_keeps_identity(value):
    assert _plain_json(value) is value


class TextCode(str, Enum):
    ROAD = "road"


class NumericCode(IntEnum):
    MAIN = 7


class TextSubclass(str):
    value = "text-subclass-value"


class IntSubclass(int):
    value = "int-subclass-value"


class FloatSubclass(float):
    value = "float-subclass-value"


@pytest.mark.parametrize("value, expected", [
    (TextCode.ROAD, "road"), (NumericCode.MAIN, 7),
    (TextSubclass("original"), "text-subclass-value"),
    (IntSubclass(4), "int-subclass-value"),
    (FloatSubclass(4.5), "float-subclass-value"),
])
def test_enum_and_scalar_subclass_keep_value_semantics(value, expected):
    converted = _plain_json(value)
    assert converted == expected
    assert type(converted) is type(expected)


def test_mapping_keys_order_containers_and_aliases_are_preserved():
    shared = {"scalar": 7}
    value = OrderedDict([(9, shared), ("tuple", (shared, Decimal("1.20"))), ("set", {3, 2})])
    converted = _plain_json(value)
    assert list(converted) == ["9", "tuple", "set"]
    assert converted == {"9": {"scalar": 7}, "tuple": [{"scalar": 7}, "1.20"], "set": list(value["set"])}
    assert converted["9"] is not shared
    assert converted["tuple"][0] is not shared
    assert converted["9"] is not converted["tuple"][0]
    assert value[9] is shared


@pytest.mark.parametrize("factory", [UserDict, MappingProxyType])
def test_mapping_interfaces_keep_recursive_copy(factory):
    original = factory({"raw": [TextCode.ROAD, Decimal("9.00"), None]})
    assert _plain_json(original) == {"raw": ["road", "9.00", None]}
    assert _plain_json(original) is not original


@pytest.mark.parametrize("value, expected", [
    (datetime(2026, 10, 26, 9, 15, tzinfo=timezone(timedelta(hours=9))), "2026-10-26T00:15:00+00:00"),
    (datetime(2026, 10, 26, 9, 15), "2026-10-26T09:15:00+00:00"),
    (date(2026, 10, 26), "2026-10-26"),
    (Decimal("1.2300"), "1.2300"),
])
def test_datetime_date_and_decimal_keep_existing_encoding(value, expected):
    assert _plain_json(value) == expected


def test_unknown_object_and_value_alias_keep_identity():
    unknown = object()
    alias = ["not-recursively-normalized", Decimal("2.00")]
    assert _plain_json(unknown) is unknown
    assert _plain_json(SimpleNamespace(value=alias)) is alias


def test_value_property_error_keeps_original_exception():
    error = RuntimeError("synthetic value access failure")

    class Broken:
        @property
        def value(self):
            raise error

    with pytest.raises(RuntimeError) as raised:
        _plain_json(Broken())
    assert raised.value is error


def test_mapping_items_error_keeps_original_exception():
    error = RuntimeError("synthetic mapping failure")

    class BrokenMapping(dict):
        def items(self):
            raise error

    with pytest.raises(RuntimeError) as raised:
        _plain_json(BrokenMapping())
    assert raised.value is error


def test_pydantic_provider_json_still_uses_json_mode_and_raw_copy():
    class ProviderPayload(BaseModel):
        raw: dict
        when: datetime
        code: TextCode

    provider = ProviderPayload(raw={"speed": 0, "absent": None, "valid": True},
                               when=datetime(2026, 10, 26, tzinfo=UTC), code=TextCode.ROAD)
    dumped = provider.model_dump(mode="json")
    assert _provider_json(provider) == dumped
    assert _provider_json(provider)["raw"] is not provider.raw
    # 직접 _plain_json은 모델 dump라는 별도 책임을 맡지 않는다.
    assert _plain_json(provider) is provider


def test_provider_mapping_and_plain_object_keep_entrypoint_contract():
    raw = {"name": "합성 원본", "values": (Decimal("2.00"), True)}
    expected = {"name": "합성 원본", "values": ["2.00", True]}
    assert _provider_json(MappingProxyType(raw)) == expected
    assert _provider_json(SimpleNamespace(**raw)) == expected


def test_scalar_subclass_mapping_still_takes_mapping_branch_first():
    class RawTextMapping(str, Mapping):
        def __iter__(self):
            return iter(["raw"])

        def __len__(self):
            return 1

        def __getitem__(self, key):
            assert key == "raw"
            return Decimal("3.00")

    assert _plain_json(RawTextMapping("original")) == {"raw": "3.00"}


def test_fallback_does_not_compare_user_metaclass_to_builtin_types():
    class EqualityTrap(type):
        __hash__ = type.__hash__

        def __eq__(cls, other):
            raise AssertionError("사용자 타입 동등성 비교가 없어야 한다")

    class Unknown(metaclass=EqualityTrap):
        pass

    value = Unknown()
    assert _plain_json(value) is value
