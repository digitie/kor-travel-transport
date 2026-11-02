import type { Place } from "./journey";

export type PublicParkingHours = {
  weekday_open: string | null; weekday_close: string | null;
  saturday_open: string | null; saturday_close: string | null;
  holiday_open: string | null; holiday_close: string | null;
};
export type PublicParkingItem = {
  id: number; source: string; provider_id: string | null; name: string;
  category: string | null; parking_type: string | null;
  road_address: string | null; land_address: string | null;
  longitude: number | null; latitude: number | null; capacity: number | null;
  fee_info: string | null; basic_minutes: number | null; basic_fee: number | null;
  additional_minutes: number | null; additional_fee: number | null;
  daily_minutes: number | null; daily_fee: number | null; monthly_fee: number | null;
  operating_days: string | null; opening_hours: PublicParkingHours;
  payment_methods: string | null; notes: string | null; phone: string | null;
  institution_name: string | null; institution_code: string | null;
  disabled_parking: string | null; reference_date: string | null;
  collected_at: string; is_current: boolean;
};
export type PublicParkingPage = {
  generated_at: string;
  collection: { source: string; last_success_at: string | null; failed: boolean; stale: boolean; last_attempt_failed: boolean };
  items: PublicParkingItem[]; next_cursor: string | null; has_more: boolean;
};

export function publicParkingPlace(item: PublicParkingItem): Place {
  return {
    id: item.id, kind: "public_parking_lot", source: item.source, provider_id: item.provider_id,
    name: item.name, longitude: item.longitude, latitude: item.latitude,
    address: item.road_address || item.land_address,
    subtitle: [item.category, item.parking_type].filter(Boolean).join(" · "),
    phone: item.phone, parking_capacity: item.capacity, parking_fee_info: item.fee_info,
    line_names: [], facilities: [], prices: [], updated_at: item.collected_at,
  };
}

export function parkingNumber(value: number | null | undefined, unit: string): string {
  return value != null && Number.isFinite(value) && value >= 0
    ? `${value.toLocaleString("ko-KR")}${unit}` : "미제공";
}

export function parkingHours(open: string | null, close: string | null): string {
  if (!open && !close) return "미제공";
  return `${open || "시작 미제공"} ~ ${close || "종료 미제공"}`;
}

export function parkingPagePath(query: string, cursor = ""): string {
  const params = new URLSearchParams({ limit: "100" });
  if (query.trim()) params.set("q", query.trim());
  if (cursor) params.set("cursor", cursor);
  return `transport/parking-lots?${params}`;
}
