/** 고속도로 운영 E2E에서 최신 관측과 저장 시각을 함께 검증한다. */
export function isFreshHighwayObservation(
  item: { observed_at?: unknown; collected_at?: unknown },
  now: number = Date.now(),
): boolean {
  return [item.observed_at, item.collected_at].every((value) => {
    if (typeof value !== "string") return false;
    const timestamp = Date.parse(value);
    const age = now - timestamp;
    return Number.isFinite(timestamp) && age >= -60_000 && age <= 900_000;
  });
}
