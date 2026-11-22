import { describe, expect, it, vi } from "vitest";
import {
  distributionSummary, fuelDistributionPath, fuelPriceDistributionSchema, gradeTone, histogramValues,
  displayedRegion, loadFuelPriceDistribution, pinnedPercent, priceAxisRange, signedWon,
} from "./fuel-price-distribution";
import { sampleDistribution } from "./fuel-price-distribution.fixture";

describe("시군구 가격 분포 계약", () => {
  it("API 응답을 검증하고 지역·주유소 경로를 만든다", async () => {
    expect(fuelPriceDistributionSchema.parse(sampleDistribution).sigungu?.station_count).toBe(29);
    expect(() => fuelPriceDistributionSchema.parse({ ...sampleDistribution, sigungu: { station_count: "x" } })).toThrow();
    expect(fuelDistributionPath({ kind: "region", sido_value: "15", sigungu_value: "1501", label: "옥천군" }, "D047"))
      .toBe("transport/fuel/price-distribution?product_code=D047&sido_value=15&sigungu_value=1501");
    expect(fuelDistributionPath({ kind: "station", station_id: 7 }, "B027"))
      .toBe("transport/fuel/price-distribution?product_code=B027&station_id=7");
    const load = vi.fn().mockResolvedValue(sampleDistribution);
    await loadFuelPriceDistribution(load, { kind: "station", station_id: 7 }, "B027");
    expect(load).toHaveBeenCalledWith("transport/fuel/price-distribution?product_code=B027&station_id=7", undefined);
  });

  it("지역 칩은 고른 곳 하나만, 고르기 전에는 화면에서 주유소가 가장 많은 곳 하나", () => {
    const viewport = [
      { sido_value: "15", sido_name: "충북", sigungu_value: "3", sigungu_name: "옥천군", station_count: 9 },
      { sido_value: "01", sido_name: "서울", sigungu_value: "1", sigungu_name: "중구", station_count: 3 },
    ];
    expect(displayedRegion(undefined, viewport)).toEqual({ sido_value: "15", sigungu_value: "3", label: "충북 옥천군", station_count: 9, selected: false });
    expect(displayedRegion(undefined, [])).toBeNull();
    // 고른 곳이 화면 안이면 화면 안 주유소 수를, 화면 밖이면 수 없이 이름만.
    expect(displayedRegion({ sido_value: "01", sigungu_value: "1", label: "서울 중구" }, viewport))
      .toEqual({ sido_value: "01", sigungu_value: "1", label: "서울 중구", station_count: 3, selected: true });
    expect(displayedRegion({ sido_value: "02", sigungu_value: "2", label: "부산 중구" }, viewport))
      .toEqual({ sido_value: "02", sigungu_value: "2", label: "부산 중구", station_count: null, selected: true });
    expect(displayedRegion({ sido_value: "02", sigungu_value: "2", label: "부산 중구" }, [])?.label).toBe("부산 중구");
  });

  it("막대는 개수 또는 백분율, 축은 전국 비교선과 핀을 담는다", () => {
    const local = sampleDistribution.sigungu;
    expect(histogramValues(local, false)).toEqual([1, 4, 14, 0, 8, 2]);
    expect(histogramValues(local, true)[0]).toBe(3.4);
    const plain = priceAxisRange(local, sampleDistribution.nationwide, false);
    expect(plain.min).toBeLessThanOrEqual(1819); expect(plain.max).toBeGreaterThanOrEqual(1998); expect(plain.max).toBeLessThan(2549);
    const compared = priceAxisRange(local, sampleDistribution.nationwide, true);
    expect(compared.min).toBeLessThanOrEqual(1765); expect(compared.max).toBeGreaterThanOrEqual(2549);
    expect(priceAxisRange(local, null, false, 1500).min).toBeLessThanOrEqual(1500);
  });

  it("핀은 정렬 곡선 위 같은 가격 위치에 놓인다", () => {
    const local = sampleDistribution.sigungu;
    expect(pinnedPercent(local, 1700)).toBe(0);
    expect(pinnedPercent(local, 1819)).toBe(0);
    expect(pinnedPercent(local, 1819 + 17.9 * 2.5)).toBeCloseTo(25);
    expect(pinnedPercent(local, 3000)).toBe(100);
  });

  it("차이·등급 색·화면 읽기 요약", () => {
    expect(signedWon(-64.4)).toBe("−64원");
    expect(signedWon(12.6)).toBe("+13원");
    expect(signedWon(0.2)).toBe("평균과 같음");
    expect([gradeTone("A+"), gradeTone("B"), gradeTone("C+"), gradeTone("D"), gradeTone(null)])
      .toEqual(["cheap", "fair", "pricey", "expensive", "none"]);
    const summary = distributionSummary(sampleDistribution.sigungu, "휘발유", false);
    expect(summary).toContain("옥천군 29개 주유소의 휘발유 가격은 최저 1,819원, 평균 1,883원, 최고 1,998원");
    expect(summary).toContain("1,840원~ 1,860원 미만으로 14개");
    expect(distributionSummary(sampleDistribution.sigungu, "휘발유", true)).toContain("48.3%");
  });
});
