import { seoulDate, serviceTime } from "./journey";

export type RailSummary = {
  place_id: number; status: "unlinked" | "day_unresolved" | "not_collected" | "stored";
  stale: boolean; collected_at: string | null; departure_count: number;
  next_departure: { departure_time: string | null; destination_name: string | null } | null;
};
export type RailSummaries = { generated_at: string; basis: string; items: RailSummary[] };

export function railMarkerLabel(data: RailSummaries | undefined, row: RailSummary | undefined, now: number): string {
  if (!data || !row) return "예정 시각 확인 중";
  const generated = Date.parse(data.generated_at);
  if (!Number.isFinite(generated) || now - generated > 70_000 || generated - now > 5_000 || seoulDate(0, generated) !== seoulDate(0, now)) return "예정 시각 재확인 중";
  if (row.status === "unlinked") return "시간표 연결 전";
  if (data.basis !== "calendar" || row.status === "day_unresolved") return "운행일 확인 필요";
  if (row.status === "not_collected") return "시간표 수집 대기";
  const collected = row.collected_at ? Date.parse(row.collected_at) : NaN;
  if (row.stale || !Number.isFinite(collected) || now - collected > 48 * 3600_000 || collected > now + 5_000) return "시간표 갱신 필요";
  const value = row.next_departure?.departure_time;
  if (!value) return row.departure_count ? "다음 예정 확인 필요" : "저장 운행편 없음";
  if (!/^(?:0[5-9]|1\d|2[0-3])[0-5]\d[0-5]\d$/.test(value)) return "예정 시각 확인 필요";
  const departure = Date.parse(`${seoulDate(0, now)}T${value.slice(0, 2)}:${value.slice(2, 4)}:${value.slice(4)}+09:00`);
  if (departure < now) return "예정 시각 재확인 중";
  return `예정 ${serviceTime(value)} · ${row.next_departure?.destination_name ? `${row.next_departure.destination_name}행` : "행선지 미제공"}`;
}
