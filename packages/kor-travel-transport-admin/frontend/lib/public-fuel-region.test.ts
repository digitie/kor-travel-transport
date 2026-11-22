import { expect, test } from "vitest";
import { fuelRegionDefault } from "./public-fuel-region";

const catalog = { items: [
  { sido_value: "강원특별자치도", sigungu: [{ sigungu_value: "강릉시", bounds: [128.80, 37.61, 129.04, 37.90] as const }] },
  { sido_value: "서울특별시", sigungu: [
    { sigungu_value: "종로구", bounds: [126.95, 37.56, 127.02, 37.60] as const },
    { sigungu_value: "중구", bounds: [126.96, 37.54, 127.02, 37.57] as const },
  ] },
  { sido_value: "경기도", sigungu: [{ sigungu_value: "고양시 덕양구", bounds: [126.80, 37.58, 126.95, 37.72] as const }] },
] };

test("지역 칩이 목록에 있으면 그대로 미리 고른다", () => {
  expect(fuelRegionDefault(catalog, { sido_value: "서울특별시", sigungu_value: "중구" }, [128.9, 37.7]))
    .toEqual({ sido_value: "서울특별시", sigungu_value: "중구" });
});

test("칩이 없으면 지도 중심을 담는 시군구 중 범위가 가장 작은 곳(강원 첫 항목이 아니다)", () => {
  // 126.99, 37.565는 종로구·중구 범위에 모두 들고 중구 범위가 더 작다.
  expect(fuelRegionDefault(catalog, undefined, [126.99, 37.565])).toEqual({ sido_value: "서울특별시", sigungu_value: "중구" });
  expect(fuelRegionDefault(catalog, undefined, [126.99, 37.59])).toEqual({ sido_value: "서울특별시", sigungu_value: "종로구" });
});

test("중심을 담는 시군구가 없으면(바다 등) 범위 가운데가 가장 가까운 곳", () => {
  expect(fuelRegionDefault(catalog, undefined, [126.5, 37.65])).toEqual({ sido_value: "경기도", sigungu_value: "고양시 덕양구" });
  expect(fuelRegionDefault(catalog, undefined, [129.5, 37.8])).toEqual({ sido_value: "강원특별자치도", sigungu_value: "강릉시" });
});

test("칩이 목록에 없으면 중심으로, 중심도 없으면 시/도만 또는 없음", () => {
  expect(fuelRegionDefault(catalog, { sido_value: "서울특별시", sigungu_value: "없는구" }, [128.9, 37.7]))
    .toEqual({ sido_value: "강원특별자치도", sigungu_value: "강릉시" });
  expect(fuelRegionDefault(catalog, { sido_value: "서울특별시", sigungu_value: "없는구" })).toEqual({ sido_value: "서울특별시" });
  expect(fuelRegionDefault(catalog)).toBeUndefined();
  expect(fuelRegionDefault(undefined, undefined, [126.99, 37.565])).toBeUndefined();
  expect(fuelRegionDefault(catalog, undefined, [Number.NaN, 37])).toBeUndefined();
});
