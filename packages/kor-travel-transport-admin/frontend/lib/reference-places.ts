import { seoulDate, hasCoordinates, type Place } from "./journey";

export function effectiveFerryServiceDate(serviceDate: string, today = seoulDate()) { return serviceDate < today ? today : serviceDate; }
export function referenceDescription(item: Pick<Place, "line_names" | "provider_id" | "latitude" | "longitude">, rail: boolean) {
  return item.line_names.join(" · ") || [
    item.provider_id ? `${rail ? "역" : "항구"} 코드 ${item.provider_id}` : null,
    hasCoordinates(item) ? "지도 위치 제공" : rail ? "좌표 미등록" : "좌표 미등록 · 운항 검색 가능",
  ].filter(Boolean).join(" · ");
}
