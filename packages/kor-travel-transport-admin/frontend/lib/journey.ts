export type PlaceKind = "fuel_station" | "rail_station" | "ferry_port" | "airport" | "rest_area" | "highway_incident";
export type FuelPrice = { product_code: string; price: number | null; observed_at: string; provider_updated_at?: string | null };
export type Place = { id: number; kind: PlaceKind; source: string; provider_id?: string | null; name: string; longitude: number | null; latitude: number | null; subtitle?: string | null; brand_name?: string | null; latest_price?: number | null; price_product_code?: string | null; prices: FuelPrice[]; line_names: string[]; facilities: string[]; phone?: string | null; station_type?: string | null; address?: string | null; updated_at: string; location_source?: string | null; location_point_count?: number | null };
export type FerryOperation = { vessel_name: string | null; departure_port_name: string | null; arrival_port_name: string | null; departure_planned_time: string | null; arrival_planned_time: string | null; fare: string | null };
export type FerryTimetable = { port_id: string; service_date: string; fetched_at: string; items: FerryOperation[] };
export type StoredFerry = { service_date: string; items: FerryTimetable[]; missing_port_ids: string[] };

export function seoulDate(offset = 0, now = Date.now()) {
  const date = new Date(now + 9 * 3600_000);
  date.setUTCDate(date.getUTCDate() + offset);
  return date.toISOString().slice(0, 10);
}
export function serviceTime(value: string | null | undefined, referenceDate?: string) {
  if (!value) return "시각 미제공";
  const text = value.trim();
  const match = /^(?:\d{8})?(\d{2})(\d{2})(?:\d{2})?$/.exec(text) ?? /^(\d{1,2}):(\d{2})(?::\d{2})?$/.exec(text);
  if (!match || Number(match[1]) > 29 || Number(match[2]) > 59) return "시각 확인 필요";
  const hour = Number(match[1]);
  let days = hour >= 24 ? 1 : 0;
  if (referenceDate && /^\d{12}(?:\d{2})?$/.test(text)) {
    const day = `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`;
    const base = referenceDate.includes("-") ? referenceDate.slice(0, 10) : `${referenceDate.slice(0, 4)}-${referenceDate.slice(4, 6)}-${referenceDate.slice(6, 8)}`;
    const difference = (Date.parse(day) - Date.parse(base)) / 86400_000;
    if (Number.isFinite(difference)) days += difference;
  }
  return `${days === 1 ? "익일 " : days > 1 ? `${days}일 뒤 ` : days < 0 ? "전일 " : ""}${String(hour % 24).padStart(2, "0")}:${match[2]}`;
}
export function money(value: string | number | null | undefined, suffix = "원") {
  if (value == null || value === "") return "요금 미제공";
  const numeric = Number(String(value).replace(/[,원\s]/g, ""));
  return Number.isFinite(numeric) && numeric >= 0 ? `${numeric.toLocaleString("ko-KR")}${suffix}` : "요금 확인 필요";
}
export function dateTime(value: string | null | undefined) {
  return value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "short", timeStyle: "short" }) : "확인되지 않음";
}
export function hasCoordinates(place: Place): place is Place & { longitude: number; latitude: number } {
  return typeof place.longitude === "number" && typeof place.latitude === "number" && Number.isFinite(place.longitude) && Number.isFinite(place.latitude);
}
// MapLibre 축척 막대의 최대 폭(100px)에 해당하는 거리. 화면 폭/단말과 무관하다.
export function clusterAtScale(zoom: number, latitude: number) {
  return 100 * 40075.016686 * Math.cos(latitude * Math.PI / 180) / (512 * 2 ** zoom) > 30;
}
export class TransportError extends Error {
  constructor(message: string, public status: number, public retryAfter: number) { super(message); }
}
export async function transportGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/transport/${path}`, { cache: "no-store", signal });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    const seconds = Number(response.headers.get("retry-after") ?? "0");
    throw new TransportError(body?.detail ?? "정보를 불러오지 못했습니다. 다시 확인해 주세요.", response.status, Number.isFinite(seconds) ? Math.max(0, seconds) : 0);
  }
  return response.json() as Promise<T>;
}
