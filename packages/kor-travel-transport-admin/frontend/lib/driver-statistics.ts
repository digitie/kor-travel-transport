export type SpeedObservation = { identity_key: string; route_no: string | null; route_name?: string | null; speed: number | null; observed_at: string };

/** 마지막 구간 관측만 사용한다. 오래된 속도와 결측치를 현재 속도에 섞지 않는다. */
export function currentSpeeds(rows: SpeedObservation[], now = Date.now()) {
  const latest = new Map<string, SpeedObservation>();
  for (const row of rows) {
    if (!latest.has(row.identity_key) || Date.parse(row.observed_at) > Date.parse(latest.get(row.identity_key)!.observed_at)) latest.set(row.identity_key, row);
  }
  const current = [...latest.values()].filter((row) => {
    const age = now - Date.parse(row.observed_at);
    return age >= 0 && age <= 15 * 60_000 && row.speed !== null && Number.isFinite(row.speed) && row.speed >= 0;
  });
  const values = current.map((row) => row.speed!).sort((a, b) => a - b);
  const percentile = (fraction: number) => {
    if (!values.length) return null;
    const index = (values.length - 1) * fraction;
    const low = Math.floor(index);
    return values[low] + (values[Math.ceil(index)] - values[low]) * (index - low);
  };
  const ratio = (test: (speed: number) => boolean) => values.length ? values.filter(test).length / values.length * 100 : null;
  return {
    rows: current, excluded: latest.size - current.length,
    mean: values.length ? values.reduce((a, b) => a + b, 0) / values.length : null,
    median: percentile(.5), p10: percentile(.1), p90: percentile(.9),
    minimum: values[0] ?? null, maximum: values.at(-1) ?? null,
    stopped: values.filter((v) => v === 0).length,
    slow: values.filter((v) => v <= 40).length,
    slowRatio: ratio((v) => v <= 40), mediumRatio: ratio((v) => v > 40 && v < 80), fastRatio: ratio((v) => v >= 80),
    routes: new Set(current.map((row) => row.route_no).filter(Boolean)).size,
  };
}

export function fuelDrivingCosts(metrics: { average_price: number; minimum_price: number; maximum_price: number }, liters: number, kmPerLiter: number) {
  const volume = Number.isFinite(liters) && liters > 0 && liters <= 1000 ? liters : null;
  const efficiency = Number.isFinite(kmPerLiter) && kmPerLiter > 0 && kmPerLiter <= 100 ? kmPerLiter : null;
  return {
    averageFill: volume === null ? null : metrics.average_price * volume,
    minimumFill: volume === null ? null : metrics.minimum_price * volume,
    maximumFill: volume === null ? null : metrics.maximum_price * volume,
    saving: volume === null ? null : (metrics.average_price - metrics.minimum_price) * volume,
    savingPercent: metrics.average_price > 0 ? (metrics.average_price - metrics.minimum_price) / metrics.average_price * 100 : null,
    costPer100Km: efficiency === null ? null : metrics.average_price * 100 / efficiency,
    minimumCostPer100Km: efficiency === null ? null : metrics.minimum_price * 100 / efficiency,
  };
}
