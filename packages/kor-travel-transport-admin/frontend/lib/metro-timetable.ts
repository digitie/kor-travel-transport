export type MetroDeparture = { train_number: string | null; departure_time: string | null; arrival_time: string | null; origin_name: string | null; destination_name: string | null };
export type MetroTimetable = { place_id: number | null; code_id?: number | null; station_name: string; line_name: string | null; status: "stored" | "unlinked" | "not_collected" | "day_unresolved"; collected_at: string | null; stale: boolean; collection_status?: "pending" | "stored" | "no_data" | "error" | null; last_attempt_at?: string | null; source_name?: string | null; time_precision?: "minute" | null; items: MetroDeparture[] };
export type MetroTimetableResponse = { generated_at: string; day_code: "7" | "8" | "9" | null; basis: "calendar" | "selected_period" | "calendar_unavailable" | "overnight_unresolved"; items: MetroTimetable[] };
export const dayNames = { "7": "토요일", "8": "평일", "9": "휴일" };
export function clockSeconds(value: string | null) {
  if (!value) return null;
  const match = /^([0-2][0-9])([0-5][0-9])([0-5][0-9])$/.exec(value) ?? /^([0-2][0-9]):([0-5][0-9])$/.exec(value);
  return match ? Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3] ?? 0) : null;
}
export function metroDestinationGroups(table: MetroTimetable) {
  const groups = new Map<string, MetroDeparture[]>();
  for (const row of table.items) {
    const name = row.destination_name || "행선지 미제공";
    const group = groups.get(name) ?? []; group.push(row); groups.set(name, group);
  }
  return [...groups].map(([name, rows]) => ({name,
    arrivalOnly: rows.every(row=>!row.departure_time) && rows.some(row=>Boolean(row.arrival_time)),
    rows: rows.sort((a,b) => (clockSeconds(a.departure_time || a.arrival_time) ?? Infinity) - (clockSeconds(b.departure_time || b.arrival_time) ?? Infinity))}));
}

