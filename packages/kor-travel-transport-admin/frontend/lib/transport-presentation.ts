export const FUEL_PRODUCT_LABELS: Record<string, string> = {
  B027: "휘발유",
  B034: "고급유",
  D047: "경유",
  C004: "등유",
  K015: "LPG",
};

export function fuelProductLabel(productCode: string | null | undefined) {
  if (!productCode) return "유종 미상";
  return FUEL_PRODUCT_LABELS[productCode] ?? `유종 ${productCode}`;
}

export function highwayRouteLabel(routeNo: string | null | undefined, routeName?: string | null) {
  if (routeName?.trim()) return routeNo ? `${routeNo} · ${routeName.trim()}` : routeName.trim();
  return routeNo ? `${routeNo}번 고속도로` : "노선 정보 없음";
}

export function collectionSourceLabel(source: string) {
  if (source === "kac") return "한국공항공사";
  if (source === "incheon") return "인천국제공항공사";
  if (source.includes("krex")) return "한국도로공사 고속도로 정보";
  if (source.includes("rest_area")) return "고속도로 휴게소 기준정보";
  if (source.includes("tago")) return "국토교통부 대중교통 정보";
  if (source.includes("highway")) return "고속도로 소통·돌발 정보";
  if (source.includes("fuel") || source.includes("opinet")) return "전국 주유소·유가 정보";
  if (source.includes("rail") || source.includes("kric")) return "철도·도시철도 기초정보";
  if (source.includes("maritime") || source.includes("ferry")) return "항구·여객선 기초정보";
  return source;
}

export function placeKindLabel(kind: string) {
  return ({ fuel_station: "주유소", rail_station: "철도역", ferry_port: "항구", airport: "공항", rest_area: "휴게소", bus_terminal: "버스터미널", highway_incident: "도로 돌발" } as Record<string, string>)[kind] ?? kind;
}
