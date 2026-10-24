import { describe, expect, it } from "vitest";
import { highwayFeatures, highwaySpeedColor, HIGHWAY_SPEED_COLORS } from "./highway-map";

describe("ITS 경로와 소통 속도", () => {
  it("미제공과 0을 구분하고 범례의 경계를 지킨다", () => {
    expect(highwaySpeedColor(null)).toBe(HIGHWAY_SPEED_COLORS.unknown);
    for (const speed of [0, 40]) expect(highwaySpeedColor(speed)).toBe(HIGHWAY_SPEED_COLORS.slow);
    for (const speed of [40.1, 79.9]) expect(highwaySpeedColor(speed)).toBe(HIGHWAY_SPEED_COLORS.moderate);
    expect(highwaySpeedColor(80)).toBe(HIGHWAY_SPEED_COLORS.fast);
  });
  it("경로 누락 링크를 추측하지 않고 반복 링크 ID도 별개로 선택한다", () => {
    const row = { link_id: "same", section_id: "s", section_name: "구간", direction: "1", speed_kmh: 0, length_m: 1, path: [[127, 37], [128, 38]] as [number, number][] };
    const result = highwayFeatures([row, { ...row, path: [] }, row]);
    expect(result.features.map((feature) => feature.id)).toEqual([0, 2]);
    expect(result.features[0].geometry.coordinates).toEqual(row.path);
    expect(result.features[0].properties.color).toBe(HIGHWAY_SPEED_COLORS.slow);
  });
});
