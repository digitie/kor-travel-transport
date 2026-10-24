export const TRANSPORT_ENDPOINTS = [
  "transport/collector-status",
  "transport/providers",
  "transport/statistics",
  "transport/highways/traffic",
  "transport/highways/roads",
  "transport/highways/road-traffic",
  "transport/highways/incidents",
  "transport/fuel/stations",
  "transport/fuel/statistics",
  "transport/features/places",
  "transport/bus/terminals",
  "transport/bus/timetable",
  "transport/bus/connections",
  "transport/ports/timetables",
  "transport/rail/timetables",
  "transport/rail/departures",
  "transport/rail/general/catalog", "transport/rail/general/guide",
  "transport/rail/general/stations",
  "transport/rail/general/timetable",
  "airports",
  "flights/status",
  "parking/current",
  "parking/outlook",
] as const;

export function isAllowedTransportPath(path: string[]) {
  return TRANSPORT_ENDPOINTS.includes(path.join("/") as (typeof TRANSPORT_ENDPOINTS)[number]) || (path.length === 4 && path[0] === "transport" && path[1] === "ports" && path[3] === "timetable");
}


export type AddressItem = {
  target_key: string; name?: string; status: string; stale: boolean;
  address?: { full?: string } | null; region?: { legal_code?: string; admin_code?: string } | null;
  provider?: string | null; resolved_at?: string | null; next_refresh_at?: string | null; error_code?: string | null;
};
export type AddressRefreshSummary = {
  total: number; due: number; failed: number; refresh_months: number;
  configured: boolean; auto_enabled: boolean; in_progress: boolean; manual_cycle: boolean;
  last_resolved_at: string | null; items: AddressItem[];
};
