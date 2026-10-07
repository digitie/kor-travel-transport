import { hasFuelPrice, type FuelPrice, type PlaceKind } from "./journey";
import { fuelProductLabel } from "./transport-presentation";
import { resolveMarkerColor, type PaletteCode } from "./vendor/map-marker-react";

// 장소 종류 → Map 마커(maki 이름 + P-01~P-16 팔레트 코드).
// Map이 같은 데이터를 그릴 때 쓰는 값을 그대로 가져온다(kor-travel-map origin/main 399d6b6a):
// - fuel_station: providers.opinet OPINET_STATION_MARKER_ICON/COLOR
// - rest_area: providers.krex REST_AREA_MARKER_ICON/COLOR
// - highway_incident: providers.krex TRAFFIC_NOTICE_MARKER_ICON/COLOR
// - airport: providers.krairport (category maki "airport", AIRPORT_MARKER_COLOR)
// 철도역·항구·버스터미널은 Map provider가 없다. maki 이름은 Map category catalog
// (TRANSPORT_STOP_TRAIN "rail", TOURISM_ACTIVITY_CRUISE "ferry", TRANSPORT_STOP_BUS "bus")에서,
// 색은 위 넷과 겹치지 않는 팔레트 코드에서 골랐다.
export const PLACE_MARKER_STYLE: Readonly<Record<PlaceKind, { markerIcon: string; markerColor: PaletteCode }>> = Object.freeze({
  fuel_station: { markerIcon: "fuel", markerColor: "P-08" },
  rest_area: { markerIcon: "fast-food", markerColor: "P-06" },
  highway_incident: { markerIcon: "roadblock", markerColor: "P-13" },
  airport: { markerIcon: "airport", markerColor: "P-10" },
  rail_station: { markerIcon: "rail", markerColor: "P-01" },
  ferry_port: { markerIcon: "ferry", markerColor: "P-15" },
  bus_terminal: { markerIcon: "bus", markerColor: "P-03" },
});

export function placeMarkerStyle(kind: string) {
  return PLACE_MARKER_STYLE[kind as PlaceKind] ?? { markerIcon: "marker", markerColor: null };
}

/** 겹친 지점 팝업의 색 점·종류 배지에 쓰는 hex. Map `coincidentEntryColor`와 같은 해석이다. */
export function placeMarkerColor(kind: string): string {
  return resolveMarkerColor(placeMarkerStyle(kind).markerColor);
}

// Map `lib/price-marker-label.ts`와 같은 짧은 표기·순서(휘발유 → 경유 → 고급유).
// Map은 세 유종만 싣지만 교통 지도는 "표시 유종" 필터로 LPG·등유도 고를 수 있어 그 뒤에 이름으로 붙인다.
const SHORT_FUEL_LABELS: Readonly<Record<string, string>> = { B027: "휘", D047: "경", B034: "고" };
const FUEL_ORDER = ["B027", "D047", "B034", "K015", "C004"];
const PRICE_FORMATTER = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });

function fuelOrder(code: string) {
  const index = FUEL_ORDER.indexOf(code);
  return index === -1 ? FUEL_ORDER.length : index;
}

/** 지도에 표시할 가격 행. 값이 없는 행과 선택하지 않은 유종은 뺀다. */
export function markerPrices(prices: readonly FuelPrice[] | null | undefined, products: readonly string[]) {
  return (prices ?? [])
    .filter((row) => hasFuelPrice(row) && (!products.length || products.includes(row.product_code)))
    .sort((left, right) => fuelOrder(left.product_code) - fuelOrder(right.product_code) || left.product_code.localeCompare(right.product_code));
}

/** Map 가격 마커 라벨과 같은 형식(`휘 1,650` 한 줄에 한 유종). 표시할 가격이 없으면 null. */
export function priceMarkerLabel(prices: readonly FuelPrice[] | null | undefined, products: readonly string[] = []): string | null {
  const rows = markerPrices(prices, products);
  if (!rows.length) return null;
  return rows.map((row) => `${SHORT_FUEL_LABELS[row.product_code] ?? fuelProductLabel(row.product_code)} ${PRICE_FORMATTER.format(row.price ?? 0)}`).join("\n");
}

/** 화면 낭독기용 가격 문구. 짧은 표기 대신 유종 이름을 쓴다. */
export function priceSpeech(prices: readonly FuelPrice[] | null | undefined, products: readonly string[] = []): string {
  return markerPrices(prices, products).map((row) => `${fuelProductLabel(row.product_code)} ${PRICE_FORMATTER.format(row.price ?? 0)}원`).join(", ");
}

/** Map `createClusterElement`의 크기 단계(100건 미만 36px, 1,000건 미만 46px, 그 이상 58px). */
export function clusterBubbleSize(count: number): number {
  return count < 100 ? 36 : count < 1000 ? 46 : 58;
}

/** supercluster `point_count_abbreviated`와 같은 축약(1,000 이상 `1.2k`, 10,000 이상 `12k`). */
export function abbreviateClusterCount(count: number): string {
  if (count >= 10_000) return `${Math.round(count / 1000)}k`;
  if (count >= 1000) return `${Math.round(count / 100) / 10}k`;
  return String(count);
}
