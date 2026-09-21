/** 고속도로 운영 E2E에서 수집·저장 최신성과 KREX 관측 지연 상한을 함께 검증한다. */
export function isFreshHighwayObservation(
  item: { observed_at?: unknown; collected_at?: unknown },
  now: number = Date.now(),
): boolean {
  if (typeof item.observed_at !== "string" || typeof item.collected_at !== "string") {
    return false;
  }
  const observedAt = Date.parse(item.observed_at);
  const collectedAt = Date.parse(item.collected_at);
  const observedAge = now - observedAt;
  const collectedAge = now - collectedAt;
  return Number.isFinite(observedAt)
    && Number.isFinite(collectedAt)
    && observedAge >= -60_000
    && observedAge <= 2 * 3_600_000
    && collectedAge >= -60_000
    && collectedAge <= 900_000;
}
