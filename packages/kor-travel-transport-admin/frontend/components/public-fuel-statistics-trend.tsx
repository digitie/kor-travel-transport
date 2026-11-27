"use client";

import { VirtualTable, type ColumnDef } from "@kor-travel/ui/virtual-table";
import { useId, useMemo, useRef, useState } from "react";
import FuelPriceChart from "./fuel-price-chart-loader";
import { EmptyState } from "./empty-state";
import { Pending, RetryAlert, Segmented } from "./public-fuel-statistics-parts";
import type { ResourceView } from "./public-fuel-statistics-data";
import { StatStrip } from "./stat-strip";
import {
  PUBLIC_FUEL_PERIODS, daysBefore, formatPrice as money, plausiblePoints, trendSummary,
  type PublicFuelMetrics, type PublicFuelPeriod, type PublicFuelStatisticsView, type PublicFuelTrend, type PublicFuelTrendBucket, type PublicFuelTrendPoint,
} from "@/lib/public-fuel-statistics";
import { fuelProductLabel } from "@/lib/transport-presentation";

const signed = (value: number, unit: string) => `${value > 0 ? "+" : value < 0 ? "−" : "±"}${money(Math.abs(value))}${unit}`;
const shortDay = (day: string) => day.slice(2).replaceAll("-", ".");
const periodHeading: Record<PublicFuelPeriod, string> = { "30": "최근 30일", "90": "최근 90일", "365": "최근 1년", all: "전체 기간" };
const bucketNote: Record<PublicFuelTrendBucket, string> = {
  day: "하루 단위(그날 마지막으로 모은 가격)",
  week: "주 단위(월요일 시작) · 평균은 그 주 하루 평균들의 평균",
  month: "월 단위 · 평균은 그 달 하루 평균들의 평균",
};
const bucketGapDays: Record<PublicFuelTrendBucket, number> = { day: 1, week: 7, month: 31 };

export function TrendSection({ view, trend, selected, to, onPeriod, onRetry }: { view: PublicFuelStatisticsView; trend: ResourceView<PublicFuelTrend>; selected?: PublicFuelMetrics; to: string | null; onPeriod: (period: string) => void; onRetry: () => void }) {
  const headingId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const product = fuelProductLabel(view.product);
  let body;
  if (trend.error) body = <RetryAlert error={trend.error} onRetry={onRetry} what="추이" focusTarget={heading} />;
  // 현재 값을 기다리는 동안에도 같은 높이 자리를 둔다(값이 오면서 아래 내용이 밀리지 않게).
  else if (!selected || trend.pending) body = <div className="public-fuel-stats-chart-placeholder"><Pending retrying={trend.retrying}>가격 추이를 불러오는 중…</Pending></div>;
  else if (!trend.data?.points.length) body = <EmptyState title="이 기간에는 가격 기록이 없습니다" description="더 긴 기간을 골라 보세요." />;
  else body = <TrendBody trend={trend.data} period={view.period} label={`${selected.label} ${product}`} requestedFrom={to && view.period !== "all" ? daysBefore(to, Number(view.period) - 1) : null} />;
  return <section className="public-fuel-stats-card" aria-labelledby={headingId} aria-busy={!selected || trend.pending}>
    <div className="public-fuel-stats-trend-head">
      <h2 id={headingId} ref={heading} tabIndex={-1}>{periodHeading[view.period]} {product} 평균 가격 변화</h2>
      <Segmented legend="기간" name="period" options={PUBLIC_FUEL_PERIODS} value={view.period} onChange={onPeriod} />
    </div>
    {body}
  </section>;
}

function TrendBody({ trend, period, label, requestedFrom }: { trend: PublicFuelTrend; period: PublicFuelPeriod; label: string; requestedFrom: string | null }) {
  const points = useMemo(() => [...trend.points].sort((a, b) => a.day.localeCompare(b.day)), [trend.points]);
  // 평균과 너무 먼 최저·최고(원천 오류로 보이는 값)는 차트·요약에서 뺀다. 차트 y축이 그 값에 끌려 평균 변화가 안 보이지 않게 한다.
  const plausible = useMemo(() => plausiblePoints(points), [points]);
  const span = trend.from_day && trend.to_day ? (Date.parse(trend.to_day) - Date.parse(trend.from_day)) / 86_400_000 : 0;
  // 점이 많으면 세로선이 면처럼 겹친다. 그때는 최저·최고를 점선으로 그린다(관리 통계 화면과 같은 기준).
  const rangeAsLines = points.length > 40;
  const series = useMemo(() => [{ product: points[0]?.product_code ?? "B027", points: plausible.points.map(point => ({ time: point.day, average: point.average_price, minimum: point.minimum_price, maximum: point.maximum_price, generated_at: point.generated_at })) }], [points, plausible]);
  return <>
    <TrendSummaryStrip points={points} period={period} daily={trend.bucket === "day"} />
    <TrendNotes trend={trend} points={points} requestedFrom={requestedFrom} rangeAsLines={rangeAsLines} excluded={plausible.excluded} />
    <FuelPriceChart label={`${label} ${periodHeading[period]} 평균·최저·최고 가격`} series={series} maxGapDays={bucketGapDays[trend.bucket]} longRange={span > 120} rangeAsLines={rangeAsLines} />
    <TrendTable points={points} daily={trend.bucket === "day"} />
  </>;
}

function pointLabel(point: PublicFuelTrendPoint, daily: boolean) {
  return daily || point.first_day === point.last_day ? shortDay(point.day) : `${shortDay(point.first_day)}~${shortDay(point.last_day)}`;
}

function TrendSummaryStrip({ points, period, daily }: { points: PublicFuelTrendPoint[]; period: PublicFuelPeriod; daily: boolean }) {
  const summary = useMemo(() => trendSummary(points), [points]);
  if (!summary) return null;
  const { first, last, change, changePercent, lowest, highest } = summary;
  return <StatStrip ariaLabel={`${periodHeading[period]} 가격 요약`} items={[
    { label: "최근 평균", value: money(last.average_price), unit: "원/L", caption: pointLabel(last, daily) },
    changePercent === null ? { label: "기간 변화", value: "—", caption: "비교할 기록 없음" }
      : { label: "기간 변화", value: signed(change, "원"), caption: `${pointLabel(first, daily)} 대비 ${signed(changePercent, "%")}` },
    { label: "기간 최저가", value: lowest ? money(lowest.price) : null, unit: "원/L", caption: lowest ? pointLabel(lowest.point, daily) : "미제공" },
    { label: "기간 최고가", value: highest ? money(highest.price) : null, unit: "원/L", caption: highest ? pointLabel(highest.point, daily) : "미제공" },
  ]} />;
}

function TrendNotes({ trend, points, requestedFrom, rangeAsLines, excluded }: { trend: PublicFuelTrend; points: PublicFuelTrendPoint[]; requestedFrom: string | null; rangeAsLines: boolean; excluded: number }) {
  const dayCount = points.reduce((sum, point) => sum + Math.max(1, point.day_count || 1), 0);
  const range = trend.from_day && trend.to_day ? ` · ${trend.from_day} ~ ${trend.to_day}` : "";
  // 응답의 from_day는 "이 기간 안의 첫 기록"이다. 그 전 기록이 없다는 뜻은 아니므로 그렇게만 말한다.
  const later = Boolean(requestedFrom && trend.from_day && trend.from_day > requestedFrom);
  const missingExtremes = points.some(point => point.minimum_price == null || point.maximum_price == null);
  return <>
    <p className="public-fuel-stats-meta">{bucketNote[trend.bucket]}{range} · 기록 {dayCount.toLocaleString("ko-KR")}일</p>
    {later ? <p className="public-fuel-stats-meta">이 기간의 첫 기록은 {trend.from_day}입니다. 그 앞 날짜는 기록이 없어 비워 둡니다.</p> : null}
    <p className="public-fuel-stats-meta">{rangeAsLines ? "실선: 평균 · 같은 색 점선: 그날의 최저·최고" : "선: 평균 · 세로선 양 끝: 최저·최고"} (원/L)</p>
    {missingExtremes ? <p className="public-fuel-stats-meta">일부 날짜의 최저·최고가는 제공되지 않았습니다. 평균가로 대신 채우지 않습니다.</p> : null}
    {excluded ? <p className="public-fuel-stats-meta">평균과 크게 동떨어진 최저·최고 {excluded}건은 입력 오류로 보고 그래프와 기간 최저·최고에서 뺐습니다(아래 표에는 그대로 있습니다).</p> : null}
  </>;
}

const columns = (daily: boolean): ColumnDef<PublicFuelTrendPoint, unknown>[] => [
  { id: "period", header: daily ? "날짜" : "기간", cell: ({ row: { original: point } }) => daily ? point.day : `${point.first_day} ~ ${point.last_day}` },
  { id: "average", header: "평균(원/L)", cell: ({ row: { original: point } }) => money(point.average_price) },
  { id: "minimum", header: "최저", cell: ({ row: { original: point } }) => point.minimum_price == null ? "미제공" : money(point.minimum_price) },
  { id: "maximum", header: "최고", cell: ({ row: { original: point } }) => point.maximum_price == null ? "미제공" : money(point.maximum_price) },
  { id: "stations", header: daily ? "주유소" : "주유소(하루 평균)", cell: ({ row: { original: point } }) => point.station_count.toLocaleString("ko-KR") },
];

function TrendTable({ points, daily }: { points: PublicFuelTrendPoint[]; daily: boolean }) {
  const [open, setOpen] = useState(false);
  const definition = useMemo(() => columns(daily), [daily]);
  const rows = useMemo(() => [...points].reverse(), [points]);
  return <details className="public-fuel-stats-table" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>{daily ? "날짜별" : "기간별"} 가격 표 · {points.length.toLocaleString("ko-KR")}건</summary>
    {/* 닫혀 있는 동안에는 표를 그리지 않는다(1년·전체 수백 행). */}
    {open ? <VirtualTable ariaLabel={daily ? "날짜별 평균·최저·최고 가격" : "기간별 평균·최저·최고 가격"} data={rows} getRowId={point => point.day} virtualized={false} columns={definition} /> : null}
  </details>;
}
