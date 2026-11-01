import { transportGet } from "./journey";

export type RailStation = { station_id: string; station_name: string };
export type RailCatalog = { fetched_at: string; stale: boolean; cities: {code:string;name:string}[]; train_classes:{code:string;name:string}[] };
export async function generalRailStations(signal: AbortSignal) {
  const catalog = await transportGet<RailCatalog>("transport/rail/general/catalog", signal);
  // 서로 다른 도시 코드 응답의 동일 ID는 한 번만 표시한다. 이름이 같아도 ID가 다르면 유지한다.
  const results = await Promise.allSettled(catalog.cities.map(city => transportGet<{items:RailStation[];stale:boolean}>(`transport/rail/general/stations?city_code=${encodeURIComponent(city.code)}`, signal)));
  const pages = results.flatMap(result=>result.status==="fulfilled"?[result.value]:[]);
  if(!pages.length) throw new Error("전체 역 목록을 불러오지 못했습니다. 다시 조회해 주세요.");
  return {catalog, stale:catalog.stale || pages.some(page=>page.stale), incomplete:pages.length!==results.length, stations:[...new Map(pages.flatMap(page=>page.items).map(station=>[station.station_id,station])).values()].sort((a,b)=>a.station_name.localeCompare(b.station_name,"ko"))};
}

export function uniqueStationByName(stations: RailStation[], name: string) {
  const normalized = (value:string)=>value.trim().replace(/역$/, "");
  const matches = stations.filter(row=>normalized(row.station_name)===normalized(name));
  return matches.length===1 ? matches[0] : null;
}
