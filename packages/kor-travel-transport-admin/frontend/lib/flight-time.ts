type TimedFlight = { scheduled_at: string; estimated_at: string | null };

/** DTO의 UTC/KST offset을 그대로 사용한다. 변경 시각이 잘못됐으면 유효한 예정 시각으로 조회한다. */
export function flightMoment(row: TimedFlight): number {
  const estimated = row.estimated_at ? Date.parse(row.estimated_at) : Number.NaN;
  return Number.isFinite(estimated) ? estimated : Date.parse(row.scheduled_at);
}
