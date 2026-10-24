import { resolveMarkerColor } from "./vendor/map-marker-react";

export type HighwayRoad = { road_id: string; road_number: string; name: string };
export type HighwayRoadCatalog = { fetched_at: string; source_url: string; stale: boolean; items: HighwayRoad[] };
export type HighwayTrafficLink = { link_id: string; section_id: string; section_name: string; direction: string | null; speed_kmh: number | null; length_m: number | null; path: [number, number][] };
export type HighwayRoadTraffic = { fetched_at: string; source_url: string; stale: boolean; road_id: string; road_number: string; road_name: string; direction: string; complete: false; items: HighwayTrafficLink[] };

export const HIGHWAY_SPEED_COLORS = {
  slow: resolveMarkerColor("P-04"), moderate: resolveMarkerColor("P-02"), fast: resolveMarkerColor("P-03"), unknown: resolveMarkerColor("P-08"),
};
export function highwaySpeedColor(speed: number | null) {
  return speed == null ? HIGHWAY_SPEED_COLORS.unknown : speed <= 40 ? HIGHWAY_SPEED_COLORS.slow : speed < 80 ? HIGHWAY_SPEED_COLORS.moderate : HIGHWAY_SPEED_COLORS.fast;
}
/** 같은 ITS LINK_INFO의 경로·속도만 사용한다. 제공되지 않은 경로는 추측하지 않는다. */
export function highwayFeatures(links: HighwayTrafficLink[]) {
  return { type: "FeatureCollection" as const, features: links.flatMap((link, index) => link.path.length < 2 ? [] : [{
    type: "Feature" as const, id: index, properties: { index, color: highwaySpeedColor(link.speed_kmh) },
    geometry: { type: "LineString" as const, coordinates: link.path },
  }]) };
}
