export const FUEL_PRODUCT_LABELS: Record<string, string> = {
  B027: "휘발유",
  B034: "고급휘발유",
  D047: "자동차용경유",
  C004: "실내등유",
  K015: "자동차용부탄(LPG)",
};

export function fuelProductLabel(productCode: string | null | undefined) {
  if (!productCode) return "유종 미상";
  return FUEL_PRODUCT_LABELS[productCode] ?? `유종 ${productCode}`;
}

export function highwayRouteLabel(routeNo: string | null | undefined, routeName?: string | null) {
  if (routeName?.trim()) return routeName.trim();
  return routeNo ? `${routeNo}번 고속도로` : "노선 정보 없음";
}

export function collectionSourceLabel(source: string) {
  if (source.includes("highway")) return "고속도로 소통·돌발 정보";
  if (source.includes("fuel") || source.includes("opinet")) return "전국 주유소·유가 정보";
  if (source.includes("rail") || source.includes("kric")) return "철도·도시철도 기초정보";
  if (source.includes("maritime") || source.includes("ferry")) return "항구·여객선 기초정보";
  return source;
}

export function placeKindLabel(kind: "fuel_station" | "rail_station" | "ferry_port") {
  return { fuel_station: "주유소", rail_station: "철도역", ferry_port: "항구" }[kind];
}
