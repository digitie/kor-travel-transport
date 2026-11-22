import { describe, expect, it } from "vitest";
import {
  activeFilterCount, ALL_BRAND_KEYS, BRAND_FILTERS, brandRelevant, DEFAULT_PUBLIC_FUEL_FILTERS, isBrandChecked,
  parsePublicFuelFilters, publicFuelFilterQuery, toggleBrand,
} from "./public-fuel-filters";

describe("공개 유가 필터", () => {
  it("상표는 빈 목록이 전체이고, 하나를 끄면 나머지 목록, 다시 켜면 전체로 돌아간다", () => {
    const off = toggleBrand(DEFAULT_PUBLIC_FUEL_FILTERS, "SKE", false);
    expect(off.brands).toEqual(ALL_BRAND_KEYS.filter(key => key !== "SKE"));
    expect(isBrandChecked(off, "SKE")).toBe(false);
    expect(isBrandChecked(off, "GSC")).toBe(true);
    expect(toggleBrand(off, "SKE", true).brands).toEqual([]);
    // 마지막 하나는 끌 수 없다(빈 결과 대신).
    const only = { ...DEFAULT_PUBLIC_FUEL_FILTERS, brands: ["ALT"] };
    expect(toggleBrand(only, "ALT", false)).toBe(only);
    // 휘발유에서는 LPG 전용 상표만 남게 끌 수 없다(남으면 상표 조건이 사라져 전체가 보인다).
    const lpgLeft = { ...DEFAULT_PUBLIC_FUEL_FILTERS, brands: ["SKE", "SKG", "E1G"] };
    expect(toggleBrand(lpgLeft, "SKE", false, ["B027"])).toBe(lpgLeft);
    expect(toggleBrand(lpgLeft, "SKE", false, ["K015"]).brands).toEqual(["SKG", "E1G"]);
  });

  it("서버 query는 켠 조건만, 최저가 범위는 유종 하나일 때만 보낸다", () => {
    const filters = { ...DEFAULT_PUBLIC_FUEL_FILTERS, self_only: true, kpetro: true, brands: ["ALT", "NHO"], near_min: 70 };
    expect(publicFuelFilterQuery(filters, ["B027"])).toBe("brands=ALT%2CNHO&self_only=true&kpetro=true&near_min=70");
    expect(publicFuelFilterQuery(filters, [])).toBe("brands=ALT%2CNHO&self_only=true&kpetro=true");
    expect(publicFuelFilterQuery(DEFAULT_PUBLIC_FUEL_FILTERS, ["B027"])).toBe("");
    expect(activeFilterCount(filters)).toBe(4);
    expect(activeFilterCount({ ...filters, near_min: 70 }, ["B027", "D047"])).toBe(3);
    expect(activeFilterCount({ ...DEFAULT_PUBLIC_FUEL_FILTERS, brands: ["SKG"] }, ["B027"])).toBe(0);
  });

  it("LPG 충전 전용 상표는 LPG가 아닌 유종을 고르면 비활성", () => {
    const sk = BRAND_FILTERS.find(brand => brand.key === "SKG")!;
    const gs = BRAND_FILTERS.find(brand => brand.key === "GSC")!;
    expect(brandRelevant(sk, ["B027"])).toBe(false);
    expect(brandRelevant(sk, ["K015"])).toBe(true);
    expect(brandRelevant(sk, [])).toBe(true);
    expect(brandRelevant(gs, ["B027"])).toBe(true);
  });

  it("저장값은 알려진 키·허용 단계만 복원한다", () => {
    expect(parsePublicFuelFilters(JSON.stringify({ self_only: true, brands: ["SKE", "BAD"], near_min: 33, cvs: "yes" })))
      .toEqual({ ...DEFAULT_PUBLIC_FUEL_FILTERS, self_only: true, brands: ["SKE"] });
    expect(parsePublicFuelFilters(JSON.stringify({ near_min: 70, brands: ALL_BRAND_KEYS }))).toEqual({ ...DEFAULT_PUBLIC_FUEL_FILTERS, near_min: 70 });
    expect(parsePublicFuelFilters("{bad")).toEqual(DEFAULT_PUBLIC_FUEL_FILTERS);
    expect(parsePublicFuelFilters(null)).toEqual(DEFAULT_PUBLIC_FUEL_FILTERS);
  });
});
