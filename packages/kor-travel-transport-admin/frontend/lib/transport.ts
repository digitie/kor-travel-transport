export const TRANSPORT_ENDPOINTS = [
  "transport/collector-status",
  "transport/statistics",
  "transport/highways/traffic",
  "transport/highways/incidents",
  "transport/fuel/stations",
  "transport/features/places",
  "transport/bus/terminals",
  "transport/bus/timetable",
] as const;

export function isAllowedTransportPath(path: string[]) {
  return TRANSPORT_ENDPOINTS.includes(path.join("/") as (typeof TRANSPORT_ENDPOINTS)[number]) || (path.length === 4 && path[0] === "transport" && path[1] === "ports" && path[3] === "timetable");
}
