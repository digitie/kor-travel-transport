import type { StyleSpecification } from "maplibre-gl";

export function vworldStyle(apiKey: string | undefined): StyleSpecification {
  const key = apiKey?.trim();
  if (!key || key === "CHANGE_ME") return { version: 8, sources: {}, layers: [{ id: "fallback", type: "background", paint: { "background-color": "#e9eef4" } }] };
  return { version: 8, sources: { base: { type: "raster", tiles: [`https://api.vworld.kr/req/wmts/1.0.0/${encodeURIComponent(key)}/Base/{z}/{y}/{x}.png`], tileSize: 256, attribution: "공간정보 오픈플랫폼 브이월드" } }, layers: [{ id: "base", type: "raster", source: "base" }] };
}
