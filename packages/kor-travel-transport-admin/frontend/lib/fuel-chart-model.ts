export type FuelChartStation = { name: string; address?: string | null; longitude?: number | null; latitude?: number | null };
export type FuelChartPoint = { time: string; average: number; minimum?: number | null; maximum?: number | null; cheapest?: FuelChartStation | null; generated_at?: string };
export type FuelChartSeries = { product: string; points: FuelChartPoint[] };
export const FUEL_CHART_ORDER = ["B027", "D047", "B034", "K015", "C004"];
export const fuelInstant = (value: string) => Date.parse(value.length === 10 ? `${value}T00:00:00+09:00` : value);
export function fuelChartTime(value: string | number) {
  const instant = typeof value === "number" ? value : fuelInstant(value);
  return Number.isFinite(instant) ? new Date(instant + 9 * 3600000).toISOString().slice(0, 16).replace("T", " ") : "시각 미제공";
}
export function fuelStationHref(station?: FuelChartStation | null) {
  return station && Number.isFinite(station.longitude) && Number.isFinite(station.latitude)
    && Math.abs(station.longitude!) <= 180 && Math.abs(station.latitude!) <= 90
    ? `/fuel?${new URLSearchParams({ longitude: String(station.longitude), latitude: String(station.latitude) })}` : null;
}
/** 관측 날짜가 비면 실제 시간축 위에 null만 넣는다. 가격을 보간하지 않는다. */
export function fuelLineValues(points: FuelChartPoint[]) {
  const ordered = points.filter(row => Number.isFinite(fuelInstant(row.time)) && Number.isFinite(row.average) && row.average > 0)
    .sort((a, b) => fuelInstant(a.time) - fuelInstant(b.time));
  const values: [number, number | null][] = [];
  for (const [index, point] of ordered.entries()) {
    const instant = fuelInstant(point.time), previous = ordered[index - 1];
    if (previous && Date.parse(fuelChartTime(instant).slice(0, 10)) - Date.parse(fuelChartTime(previous.time).slice(0, 10)) > 86400000)
      values.push([fuelInstant(previous.time) + (instant - fuelInstant(previous.time)) / 2, null]);
    values.push([instant, point.average]);
  }
  return values;
}
