export type FuelChartStation = { name: string; address?: string | null; longitude?: number | null; latitude?: number | null };
/** 주·월 버킷 점의 실제 기록 범위(장기 추이 API first_day·last_day·day_count). 일 단위 점에는 주지 않는다. */
export type FuelChartSpan = { first_day: string; last_day: string; day_count: number };
/** span(선택)은 뒤에 붙인 필드라 기존 소비자(30일·주유소 이력·공개 화면)는 그대로 동작한다. */
export type FuelChartPoint = { time: string; average: number; minimum?: number | null; maximum?: number | null; cheapest?: FuelChartStation | null; generated_at?: string; span?: FuelChartSpan | null };
export type FuelChartSeries = { product: string; points: FuelChartPoint[] };
export const FUEL_CHART_ORDER = ["B027", "D047", "B034", "K015", "C004"];
export const fuelInstant = (value: string) => Date.parse(value.length === 10 ? `${value}T00:00:00+09:00` : value);
export function fuelChartTime(value: string | number) {
  const instant = typeof value === "number" ? value : fuelInstant(value);
  return Number.isFinite(instant) ? new Date(instant + 9 * 3600000).toISOString().slice(0, 16).replace("T", " ") : "시각 미제공";
}
/** 버킷 점의 기간·기록 일수(툴팁·키보드 안내). 예: `2026-01-05 → 2026-01-11 KST · 기록 7일`.
 * 일 단위 점에는 span을 주지 않는다(주면 `… KST · 기록 1일`·"마지막 기록일 수집"으로 바뀐다). 필드가 빠지거나 형식이 다르면
 * null(차트는 예전처럼 날짜를 보인다) — 부분 응답이 formatter·렌더를 깨지 않게 한다. */
export function fuelSpanText(span?: FuelChartSpan | null) {
  const day = /^\d{4}-\d{2}-\d{2}$/;
  if (!span || typeof span.first_day !== "string" || typeof span.last_day !== "string" || !day.test(span.first_day)
    || !day.test(span.last_day) || !Number.isInteger(span.day_count) || span.day_count < 1) return null;
  const range = span.first_day === span.last_day ? span.first_day : `${span.first_day} → ${span.last_day}`;
  return `${range} KST · 기록 ${span.day_count.toLocaleString("ko-KR")}일`;
}
export function fuelStationHref(station?: FuelChartStation | null) {
  return station && Number.isFinite(station.longitude) && Number.isFinite(station.latitude)
    && Math.abs(station.longitude!) <= 180 && Math.abs(station.latitude!) <= 90
    ? `/fuel?${new URLSearchParams({ longitude: String(station.longitude), latitude: String(station.latitude) })}` : null;
}
/** 관측 날짜가 비면 실제 시간축 위에 null만 넣는다. 가격을 보간하지 않는다.
 * maxGapDays: 이 간격(일)보다 먼 이웃 점은 끊는다. 일 단위 1, 주 단위 7, 월 단위 31(달 길이 28~31일). */
export function fuelLineValues(points: FuelChartPoint[], maxGapDays = 1) {
  const ordered = points.filter(row => Number.isFinite(fuelInstant(row.time)) && Number.isFinite(row.average) && row.average > 0)
    .sort((a, b) => fuelInstant(a.time) - fuelInstant(b.time));
  const values: [number, number | null][] = [];
  for (const [index, point] of ordered.entries()) {
    const instant = fuelInstant(point.time), previous = ordered[index - 1];
    if (previous && Date.parse(fuelChartTime(instant).slice(0, 10)) - Date.parse(fuelChartTime(previous.time).slice(0, 10)) > maxGapDays * 86400000)
      values.push([fuelInstant(previous.time) + (instant - fuelInstant(previous.time)) / 2, null]);
    values.push([instant, point.average]);
  }
  return values;
}
