export type PlaceKind = "fuel_station" | "rail_station" | "ferry_port" | "bus_terminal" | "airport" | "rest_area" | "highway_incident";
export type FuelPrice = { product_code: string; price: number | null; observed_at: string; provider_updated_at?: string | null };
export function hasFuelPrice(row: FuelPrice) {
  return row.price !== null && Number.isFinite(row.price) && row.price > 0;
}
export type Place = { id: number; kind: PlaceKind; source: string; provider_id?: string | null; name: string; city_name?: string | null; longitude: number | null; latitude: number | null; subtitle?: string | null; brand_name?: string | null; latest_price?: number | null; price_product_code?: string | null; prices: FuelPrice[]; line_names: string[]; facilities: string[]; phone?: string | null; station_type?: string | null; address?: string | null; updated_at: string; location_source?: string | null; manual_location_revision?: string | null; location_point_count?: number | null };
export type FerryOperation = { vessel_name: string | null; departure_port_name: string | null; arrival_port_name: string | null; departure_planned_time: string | null; arrival_planned_time: string | null; fare: string | null };
export type FerryTimetable = { port_id: string; port_name?: string | null; service_date: string; fetched_at: string; items: FerryOperation[] };
export type StoredFerry = { service_date: string; items: FerryTimetable[]; missing_port_ids: string[] };

export function seoulDate(offset = 0, now = Date.now()) {
  const date = new Date(now + 9 * 3600_000);
  date.setUTCDate(date.getUTCDate() + offset);
  return date.toISOString().slice(0, 10);
}
export function serviceTime(value: string | null | undefined, referenceDate?: string) {
  if (!value) return "시각 미제공";
  const text = value.trim();
  const match = /^(?:\d{8})?(\d{2})(\d{2})(\d{2})?$/.exec(text) ?? /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(text);
  if (!match || Number(match[1]) > 29 || Number(match[2]) > 59 || Number(match[3] ?? "0") > 59) return "시각 확인 필요";
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
export function hasCoordinates<T extends Pick<Place, "longitude" | "latitude">>(place: T): place is T & { longitude: number; latitude: number } {
  return typeof place.longitude === "number" && typeof place.latitude === "number"
    && Number.isFinite(place.longitude) && Number.isFinite(place.latitude)
    && Math.abs(place.longitude) <= 180 && Math.abs(place.latitude) <= 90;
}
// 확대 수준과 현재 화면 면적당 장소 수로 묶음 반경을 선택한다.
export function clusterAtScale(zoom: number, latitude: number, count = 0, width = 800, height = 540) {
  // 광역 지도에서는 유지하고, 동네 수준에서도 화면 면적 대비 과밀하면 묶는다.
  // 작은 모바일 화면에서 데스크톱과 같은 수의 가격표가 한꺼번에 펼쳐지지 않는다.
  if (![zoom, latitude, count, width, height].every(Number.isFinite)) return true;
  const budget = Math.max(6, Math.min(60, Math.floor(width * height / 22_000)));
  return zoom < 11 || count > budget;
}
export class TransportError extends Error {
  constructor(message: string, public status: number, public retryAfter: number) { super(message); }
}
export async function transportGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/transport/${path}`, { cache: "no-store", signal });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: unknown } | null;
    const seconds = Number(response.headers.get("retry-after") ?? "0");
    const fallback = response.status === 401 ? "로그인 상태를 다시 확인해 주세요." : response.status === 404 ? "요청한 정보를 찾을 수 없습니다." : response.status === 422 ? "검색 조건을 다시 확인해 주세요." : "정보를 불러오지 못했습니다. 다시 확인해 주세요.";
    const message = typeof body?.detail === "string" && /[가-힣]/.test(body.detail) ? body.detail : fallback;
    throw new TransportError(message, response.status, Number.isFinite(seconds) ? Math.max(0, seconds) : 0);
  }
  return response.json() as Promise<T>;
}
