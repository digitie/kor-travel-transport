import { describe, expect, it } from "vitest";
import { abbreviateClusterCount, clusterBubbleSize, PLACE_MARKER_STYLE, placeMarkerColor, placeMarkerStyle, priceMarkerLabel, priceSpeech } from "./place-marker-style";
import { getMakiGlyph, PALETTE } from "./vendor/map-marker-react";
import { buildVWorldStyle, getVWorldTileUrl, redactVWorldUrl } from "./vworld-style";

const observed = "2026-10-08T00:00:00Z";
const prices = [
  { product_code: "C004", price: 1300, observed_at: observed },
  { product_code: "B034", price: 1900, observed_at: observed },
  { product_code: "D047", price: 1550, observed_at: observed },
  { product_code: "B027", price: 1650, observed_at: observed },
  { product_code: "K015", price: null, observed_at: observed },
];

describe("Map 마커 매핑", () => {
  it("Map provider가 같은 데이터에 쓰는 maki·팔레트를 그대로 쓴다", () => {
    expect(PLACE_MARKER_STYLE.fuel_station).toEqual({ markerIcon: "fuel", markerColor: "P-08" });
    expect(PLACE_MARKER_STYLE.rest_area).toEqual({ markerIcon: "fast-food", markerColor: "P-06" });
    expect(PLACE_MARKER_STYLE.highway_incident).toEqual({ markerIcon: "roadblock", markerColor: "P-13" });
    expect(PLACE_MARKER_STYLE.airport).toEqual({ markerIcon: "airport", markerColor: "P-10" });
  });
  it("Map 고유 provider가 없는 종류도 알려진 maki 글리프와 서로 다른 색을 받는다", () => {
    for (const kind of ["rail_station", "ferry_port", "bus_terminal"]) expect(getMakiGlyph(placeMarkerStyle(kind).markerIcon)).not.toBeNull();
    const colors = Object.values(PLACE_MARKER_STYLE).map((style) => style.markerColor);
    expect(new Set(colors).size).toBe(colors.length);
    expect(placeMarkerColor("rail_station")).toBe(PALETTE["P-01"]);
  });
  it("모르는 종류는 Map 기본 마커로 떨어진다", () => expect(placeMarkerStyle("unknown")).toEqual({ markerIcon: "marker", markerColor: null }));
});

describe("가격 라벨", () => {
  it("Map과 같은 짧은 표기·순서로 한 줄에 한 유종을 쓰고 값 없는 행은 뺀다", () => expect(priceMarkerLabel(prices)).toBe("휘 1,650\n경 1,550\n고 1,900\n등유 1,300"));
  it("표시 유종 필터를 따른다", () => expect(priceMarkerLabel(prices, ["D047"])).toBe("경 1,550"));
  it("표시할 가격이 없으면 라벨을 만들지 않는다", () => {
    expect(priceMarkerLabel([])).toBeNull();
    expect(priceMarkerLabel(prices, ["K015"])).toBeNull();
  });
  it("화면 낭독기에는 유종 이름과 단위를 준다", () => expect(priceSpeech(prices, ["B027", "B034"])).toBe("휘발유 1,650원, 고급유 1,900원"));
});

describe("클러스터", () => {
  it.each([[1, 36], [99, 36], [100, 46], [999, 46], [1000, 58]])("%s건은 %spx", (count, size) => expect(clusterBubbleSize(count)).toBe(size));
  it.each([[999, "999"], [1234, "1.2k"], [12_345, "12k"]])("%s건 축약은 %s", (count, label) => expect(abbreviateClusterCount(count)).toBe(label));
});

describe("VWorld 배경지도 style", () => {
  it("키가 있으면 VWorld WMTS raster를 직접 쓴다", () => {
    const style = buildVWorldStyle(" test-key ", "Base");
    expect(style.sources["vworld-base"]).toMatchObject({ type: "raster", tiles: [getVWorldTileUrl("test-key", "Base")], tileSize: 256, maxzoom: 19 });
    expect(getVWorldTileUrl("test-key", "Base")).toBe("https://api.vworld.kr/req/wmts/1.0.0/test-key/Base/{z}/{y}/{x}.png");
  });
  it.each(["", "   ", "CHANGE_ME", undefined])("키가 %j이면 배경색만 그린다", (key) => {
    const style = buildVWorldStyle(key);
    expect(style.sources).toEqual({});
    expect(style.layers).toEqual([{ id: "bg", type: "background", paint: { "background-color": "#edf1f5" } }]);
  });
  it("오류 로그에서 키를 가린다", () => expect(redactVWorldUrl("https://api.vworld.kr/req/wmts/1.0.0/secret/Base/7/1/2.png")).toBe("https://api.vworld.kr/req/wmts/1.0.0/***/Base/7/1/2.png"));
});
