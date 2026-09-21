export const TRANSPORT_ENDPOINTS = [
  "transport/collector-status",
  "transport/statistics",
  "transport/highways/traffic",
  "transport/highways/incidents",
  "transport/fuel/stations",
] as const;

export function isAllowedTransportPath(path: string[]) {
  return TRANSPORT_ENDPOINTS.includes(path.join("/") as (typeof TRANSPORT_ENDPOINTS)[number]);
}
