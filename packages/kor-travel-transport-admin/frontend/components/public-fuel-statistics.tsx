"use client";

import { VirtualTable, type ColumnDef } from "@kor-travel/ui/virtual-table";
import { ArrowLeft, MapPin } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import FuelPriceChart from "./fuel-price-chart-loader";
import { EmptyState } from "./empty-state";
import { StatStrip } from "./stat-strip";
import { Button } from "./ui/button";
import { buttonVariants } from "./ui/button-variants";
import { NativeSelect } from "./ui/native-select";
import { loadWithTransientRetry } from "@/lib/place-retry";
import { publicFuelGet } from "@/lib/public-fuel";
import {
  ALL_ROUTES, PUBLIC_FUEL_AREAS, describeStatisticsError, type StatisticsLoadError as LoadError, PUBLIC_FUEL_PERIODS, PUBLIC_FUEL_PRODUCTS, STALE_STATISTICS_HOURS, currentScope, daysBefore,
  historyPath, kstDay, listScope, publicMapHref, regionOptions, resolveRegion, sidoOfSigungu, sigunguGroups, statisticsAgeHours,
  statisticsPath, statisticsSchema, statisticsViewQuery, trendSchema, trendSummary,
  type PublicFuelArea, type PublicFuelMetrics, type PublicFuelPeriod, type PublicFuelStatistics, type PublicFuelStatisticsView,
  type PublicFuelTrend, type PublicFuelTrendBucket, type PublicFuelTrendPoint,
} from "@/lib/public-fuel-statistics";
import { fuelProductLabel } from "@/lib/transport-presentation";

const money = (value: number) => value.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
const signed = (value: number, unit: string) => `${value > 0 ? "+" : value < 0 ? "−" : "±"}${money(Math.abs(value))}${unit}`;
const timeFormat = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
function kstTimestamp(value?: string | null) {
  const instant = value ? new Date(value) : null;
  if (!instant || !Number.isFinite(instant.getTime())) return null;
  const parts = Object.fromEntries(timeFormat.formatToParts(instant).map(({ type, value: part }) => [type, part]));
  return `${parts.year}.${parts.month}.${parts.day} ${parts.hour}:${parts.minute}`;
}
const shortDay = (day: string) => day.slice(2).replaceAll("-", ".");
const periodHeading: Record<PublicFuelPeriod, string> = { "30": "최근 30일", "90": "최근 90일", "365": "최근 1년", all: "전체 기간" };
const bucketNote: Record<PublicFuelTrendBucket, string> = {
  day: "하루 단위 · 그날 마지막 정상 수집 기준",
  week: "주 단위(월요일 시작) · 평균은 그 주 일별 평균의 단순 평균",
  month: "월 단위 · 평균은 그 달 일별 평균의 단순 평균",
};
const bucketGapDays: Record<PublicFuelTrendBucket, number> = { day: 1, week: 7, month: 31 };
const REQUEST_TIMEOUT_MS = 40_000;
type Resource<T> = { key: string; data?: T; error?: LoadError; retrying?: boolean };
type ResourceView<T> = { pending: boolean; retrying: boolean; data?: T; error?: LoadError };

/** 공개 유가 BFF 읽기 하나. 같은 경로·reload의 응답만 보인다. 혼잡(Retry-After 5초 이하)은 한 번 자동으로 다시 묻는다. */
function usePublicFuelResource<T>(path: string | null, reload: number, schema: { parse: (value: unknown) => unknown }): ResourceView<T> {
  const key = path ? `${reload}:${path}` : "";
  const [state, setState] = useState<Resource<T>>({ key: "" });
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(REQUEST_TIMEOUT_MS)]);
    loadWithTransientRetry<unknown>(publicFuelGet, path, signal, Math.random, () => {
      if (!controller.signal.aborted) setState({ key, retrying: true });
    }).then(value => schema.parse(value) as T)
      .then(data => { if (!controller.signal.aborted) setState({ key, data }); })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setState({ key, error: describeStatisticsError(reason) }); });
    return () => controller.abort();
  }, [key, path, schema]);
  const current = state.key === key && key ? state : undefined;
  return { pending: Boolean(path) && !current?.data && !current?.error, retrying: Boolean(current?.retrying), data: current?.data, error: current?.error };
}

/** 화면 상태를 URL에 남긴다(공유·새로고침 시 같은 화면). 뒤로 가기 기록은 늘리지 않는다. */
function useViewInUrl(view: PublicFuelStatisticsView) {
  const query = statisticsViewQuery(view);
  useEffect(() => {
    try {
      const next = `${window.location.pathname}${query ? `?${query}` : ""}`;
      if (`${window.location.pathname}${window.location.search}` !== next) window.history.replaceState(window.history.state, "", next);
    } catch { /* 주소를 바꿀 수 없는 환경에서도 화면은 그대로 쓴다. */ }
  }, [query]);
}

function usePublicFuelStatistics(initialView: PublicFuelStatisticsView) {
  const [view, setView] = useState(initialView);
  const [reload, setReload] = useState(0);
  useViewInUrl(view);
  const list = usePublicFuelResource<PublicFuelStatistics>(statisticsPath(listScope(view.area), view.product), reload, statisticsSchema);
  // 고속도로 "전체 노선"은 노선 목록(highway)과 다른 범주(highways)를 따로 읽는다.
  const scope = currentScope(view);
  const separateCurrent = scope !== listScope(view.area);
  const allRoutes = usePublicFuelResource<PublicFuelStatistics>(separateCurrent ? statisticsPath(scope, view.product) : null, reload, statisticsSchema);
  const current = separateCurrent ? allRoutes : list;
  const region = list.data ? resolveRegion(view, list.data.items) : null;
  const selected = current.data ? (separateCurrent || view.area === "nationwide" ? current.data.items[0] : current.data.items.find(item => item.scope_key === region)) : undefined;
  const to = kstDay(current.data?.generated_at);
  const trend = usePublicFuelResource<PublicFuelTrend>(selected && to ? historyPath(scope, selected.scope_key, view.product, view.period, to) : null, reload, trendSchema);
  const update = (patch: Partial<PublicFuelStatisticsView>) => setView(previous => ({ ...previous, ...patch }));
  return { view, update, list, current, selected, region, trend, to, retry: () => setReload(value => value + 1) };
}

export function PublicFuelStatisticsPage({ initialView }: { initialView: PublicFuelStatisticsView }) {
  const state = usePublicFuelStatistics(initialView);
  const { view, update, list, current, selected, trend } = state;
  const product = fuelProductLabel(view.product);
  return <main className="public-fuel-stats" aria-labelledby="public-fuel-stats-title">
    <header className="public-fuel-stats-header">
      <Link className={buttonVariants({ variant: "outline", size: "sm" })} href="/"><ArrowLeft aria-hidden="true" size={16} />유가 지도</Link>
      <div>
        <h1 id="public-fuel-stats-title">지역별 유가 통계</h1>
        <p>전국·시도·시군구·고속도로의 평균·최저·최고 가격과 기간별 추이</p>
      </div>
    </header>
    <section className="public-fuel-stats-controls" aria-label="조회 조건">
      <Segmented legend="범위" name="area" options={PUBLIC_FUEL_AREAS} value={view.area}
        onChange={area => update({ area: area as PublicFuelArea, region: "" })} />
      <RegionPicker view={view} items={list.data?.items} pending={list.pending} region={state.region} onChange={region => update({ region })} />
      <Segmented legend="유종" name="product" options={PUBLIC_FUEL_PRODUCTS.map(code => [code, fuelProductLabel(code)])} value={view.product}
        onChange={code => update({ product: code })} />
    </section>
    <CurrentStatistics resource={current} list={list} selected={selected} product={product} area={view.area} onRetry={state.retry} />
    {selected ? <TrendSection view={view} trend={trend} selected={selected} to={state.to} onPeriod={period => update({ period: period as PublicFuelPeriod })} onRetry={state.retry} /> : null}
    <footer className="public-fuel-stats-notes">
      <p>전국·시도·시군구는 오피넷, 고속도로는 한국도로공사 휴게소 가격입니다. 주유소마다 같은 비중으로 집계한 유효 판매 가격이며 할인·적립은 반영하지 않습니다.</p>
      <p>일별 값은 그날(한국 시각) 마지막 정상 수집 기준입니다. 기록이 없는 날은 선을 끊고 다른 값으로 채우지 않습니다.</p>
    </footer>
  </main>;
}

/** 라디오 묶음(분절 버튼 모양). 방향키로 옮겨 다닌다(브라우저 기본 라디오 동작). */
function Segmented({ legend, name, options, value, onChange }: { legend: string; name: string; options: [string, string][]; value: string; onChange: (value: string) => void }) {
  const id = useId();
  return <fieldset className="public-fuel-segmented">
    <legend>{legend}</legend>
    <div role="presentation">
      {options.map(([option, label]) => <label key={option} data-checked={option === value || undefined}>
        <input type="radio" name={`${id}-${name}`} value={option} checked={option === value} onChange={() => onChange(option)} />
        <span>{label}</span>
      </label>)}
    </div>
  </fieldset>;
}

function RegionPicker({ view, items, pending, region, onChange }: { view: PublicFuelStatisticsView; items?: PublicFuelMetrics[]; pending: boolean; region: string | null; onChange: (region: string) => void }) {
  if (view.area === "nationwide") return null;
  if (view.area === "sigungu") return <SigunguPicker items={items} pending={pending} region={region} onChange={onChange} />;
  return <SingleRegionPicker highway={view.area === "highway"} items={items} pending={pending} region={region} onChange={onChange} />;
}

type PickerProps = { items?: PublicFuelMetrics[]; pending: boolean; region: string | null; onChange: (region: string) => void };
function placeholderOption(pending: boolean, items?: PublicFuelMetrics[]) {
  if (pending) return <option value="">불러오는 중…</option>;
  return items?.length ? null : <option value="">선택할 지역 없음</option>;
}

/** 시도 → 시군구 두 단계. 시도를 바꾸면 그 시도의 첫 시군구(이름순)를 고른다. */
function SigunguPicker({ items, pending, region, onChange }: PickerProps) {
  const id = useId();
  const groups = useMemo(() => items ? sigunguGroups(items) : [], [items]);
  const placeholder = placeholderOption(pending, items);
  const sido = region ? sidoOfSigungu(region) : null;
  const group = groups.find(entry => entry.sido === sido);
  return <div className="public-fuel-stats-region">
    <label htmlFor={`${id}-sido`}>시도 선택</label>
    <NativeSelect id={`${id}-sido`} value={placeholder ? "" : sido ?? ""} disabled={Boolean(placeholder)}
      onChange={event => onChange(groups.find(entry => entry.sido === event.target.value)?.sigungu[0]?.key ?? "")}>
      {placeholder ?? groups.map(entry => <option key={entry.sido} value={entry.sido}>{entry.label}</option>)}
    </NativeSelect>
    <label htmlFor={`${id}-sigungu`}>시군구 선택</label>
    <NativeSelect id={`${id}-sigungu`} value={placeholder ? "" : region ?? ""} disabled={Boolean(placeholder)} onChange={event => onChange(event.target.value)}>
      {placeholder ?? group?.sigungu.map(entry => <option key={entry.key} value={entry.key}>{entry.label}</option>)}
    </NativeSelect>
  </div>;
}

/** 시도 하나 또는 고속도로 노선 하나. 고속도로는 목록을 읽는 동안에도 "전체 노선"을 고를 수 있다. */
function SingleRegionPicker({ highway, items, pending, region, onChange }: PickerProps & { highway: boolean }) {
  const id = useId();
  const options = useMemo(() => items ? regionOptions(items) : [], [items]);
  const placeholder = highway ? null : placeholderOption(pending, items);
  const routes = highway && !pending ? options : [];
  return <div className="public-fuel-stats-region">
    <label htmlFor={`${id}-region`}>{highway ? "노선 선택" : "시도 선택"}</label>
    <NativeSelect id={`${id}-region`} value={highway ? region ?? ALL_ROUTES : placeholder ? "" : region ?? ""} disabled={Boolean(placeholder)} onChange={event => onChange(event.target.value)}>
      {highway ? <><option value={ALL_ROUTES}>전체 노선</option>{routes.map(entry => <option key={entry.key} value={entry.key}>{entry.label}</option>)}</>
        : placeholder ?? options.map(entry => <option key={entry.key} value={entry.key}>{entry.label}</option>)}
    </NativeSelect>
  </div>;
}

function RetryAlert({ error, onRetry, what }: { error: LoadError; onRetry: () => void; what: string }) {
  const [retryIn, setRetryIn] = useState(error.retryAfter);
  useEffect(() => {
    if (retryIn <= 0) return;
    const timer = setTimeout(() => setRetryIn(value => Math.max(0, value - 1)), 1000);
    return () => clearTimeout(timer);
  }, [retryIn]);
  return <div className="public-fuel-stats-alert" role="alert">
    <p>{error.message}</p>
    <Button type="button" variant="outline" size="sm" disabled={retryIn > 0} onClick={onRetry}>
      {what} 다시 조회{retryIn > 0 ? ` (${retryIn}초 후)` : ""}
    </Button>
  </div>;
}

function Pending({ retrying, children }: { retrying: boolean; children: ReactNode }) {
  return <p className="public-fuel-stats-pending" role="status">{retrying ? "조회가 몰려 잠시 뒤 다시 조회하는 중…" : children}</p>;
}

function CurrentStatistics({ resource, list, selected, product, area, onRetry }: { resource: ResourceView<PublicFuelStatistics>; list: ResourceView<PublicFuelStatistics>; selected?: PublicFuelMetrics; product: string; area: PublicFuelArea; onRetry: () => void }) {
  const headingId = useId();
  const failed = resource.error ?? list.error;
  const pending = resource.pending || list.pending;
  const data = resource.data;
  let body: ReactNode;
  if (failed) body = <RetryAlert error={failed} onRetry={onRetry} what="통계" />;
  else if (pending) body = <><Pending retrying={resource.retrying || list.retrying}>현재 통계를 불러오는 중…</Pending><StatStrip ariaLabel="현재 유가" isLoading items={[{ label: "평균 가격", value: null }, { label: "최저 가격", value: null }, { label: "최고 가격", value: null }, { label: "주유소", value: null }]} /></>;
  else if (!data?.generated_at) body = <EmptyState title="아직 공개된 유가 통계가 없습니다" description="첫 수집이 끝나면 통계가 생깁니다. 잠시 뒤 다시 확인해 주세요." />;
  else if (!selected) body = <EmptyState title={`이 범위에는 ${product} 통계가 없습니다`} description={area === "highway" ? "고속도로 휴게소는 휘발유·경유·LPG 가격만 제공합니다. 다른 유종을 골라 보세요." : "다른 유종이나 지역을 골라 보세요."} />;
  else body = <CurrentValues data={data} selected={selected} />;
  return <section className="public-fuel-stats-card" aria-labelledby={headingId} aria-busy={pending}>
    <h2 id={headingId}>{selected && !pending && !failed ? `${selected.label} · ${product} 현재 가격` : `현재 ${product} 가격`}</h2>
    {body}
  </section>;
}

function CurrentValues({ data, selected }: { data: PublicFuelStatistics; selected: PublicFuelMetrics }) {
  return <>
    <StatStrip ariaLabel="현재 유가" items={[
      { label: "평균 가격", value: money(selected.average_price), unit: "원/L" },
      { label: "최저 가격", value: money(selected.minimum_price), unit: "원/L" },
      { label: "최고 가격", value: money(selected.maximum_price), unit: "원/L" },
      { label: "주유소", value: selected.station_count, unit: "곳", caption: "가격을 집계한 곳" },
    ]} />
    <CheapestStation selected={selected} />
    <Freshness generatedAt={selected.generated_at ?? data.generated_at} updatePending={data.update_pending} />
  </>;
}

function CheapestStation({ selected }: { selected: PublicFuelMetrics }) {
  const station = selected.cheapest_station;
  const href = publicMapHref(station);
  const others = (selected.cheapest_station_count ?? 1) - 1;
  return <div className="public-fuel-stats-cheapest">
    <h3>최저가 주유소</h3>
    {station ? <p>
      <strong>{station.name}</strong>{others > 0 ? ` 외 ${others}곳` : ""} · {money(selected.minimum_price)}원/L
      {station.address ? <><br /><span className="public-fuel-stats-address">{station.address}</span></> : null}
      {href ? <><br /><Link className="public-fuel-stats-link" href={href}><MapPin aria-hidden="true" size={14} />지도에서 보기</Link></> : null}
    </p> : <p>최저가 주유소 정보가 없습니다.</p>}
  </div>;
}

function ageText(hours: number) {
  return hours >= 24 ? `${Math.floor(hours / 24)}일` : `${Math.floor(hours)}시간`;
}

function Freshness({ generatedAt, updatePending }: { generatedAt: string | null; updatePending: boolean }) {
  const generated = kstTimestamp(generatedAt);
  const age = statisticsAgeHours(generatedAt);
  return <>
    <p className="public-fuel-stats-freshness">
      통계 기준 {generated ? <time dateTime={generatedAt ?? undefined}>{generated} KST</time> : "시각 미확인"}
    </p>
    {updatePending ? <p className="public-fuel-stats-notice" role="status">새로 수집한 가격을 통계에 반영하는 중입니다. 잠시 뒤 다시 확인하면 최신 값이 보입니다.</p> : null}
    {age !== null && age >= STALE_STATISTICS_HOURS ? <p className="public-fuel-stats-notice" data-tone="warning" role="status">통계가 {ageText(age)} 전 기준입니다. 최근 수집이 늦어지고 있어 지금 가격과 다를 수 있습니다.</p> : null}
  </>;
}

function TrendSection({ view, trend, selected, to, onPeriod, onRetry }: { view: PublicFuelStatisticsView; trend: ResourceView<PublicFuelTrend>; selected: PublicFuelMetrics; to: string | null; onPeriod: (period: string) => void; onRetry: () => void }) {
  const headingId = useId();
  const product = fuelProductLabel(view.product);
  let body: ReactNode;
  if (trend.error) body = <RetryAlert error={trend.error} onRetry={onRetry} what="추이" />;
  else if (trend.pending) body = <div className="public-fuel-stats-chart-placeholder"><Pending retrying={trend.retrying}>가격 추이를 불러오는 중…</Pending></div>;
  else if (!trend.data?.points.length) body = <EmptyState title="이 기간에는 가격 기록이 없습니다" description="더 긴 기간을 골라 보세요." />;
  else body = <TrendBody trend={trend.data} period={view.period} label={`${selected.label} ${product}`} requestedFrom={to && view.period !== "all" ? daysBefore(to, Number(view.period) - 1) : null} />;
  return <section className="public-fuel-stats-card" aria-labelledby={headingId} aria-busy={trend.pending}>
    <div className="public-fuel-stats-trend-head">
      <h2 id={headingId}>{periodHeading[view.period]} {product} 평균 가격 추이</h2>
      <Segmented legend="기간" name="period" options={PUBLIC_FUEL_PERIODS} value={view.period} onChange={onPeriod} />
    </div>
    {body}
  </section>;
}

function TrendBody({ trend, period, label, requestedFrom }: { trend: PublicFuelTrend; period: PublicFuelPeriod; label: string; requestedFrom: string | null }) {
  const points = useMemo(() => [...trend.points].sort((a, b) => a.day.localeCompare(b.day)), [trend.points]);
  const span = trend.from_day && trend.to_day ? (Date.parse(trend.to_day) - Date.parse(trend.from_day)) / 86_400_000 : 0;
  // 점이 많으면 세로선이 면처럼 겹친다. 그때는 최저·최고를 점선으로 그린다(관리 통계 화면과 같은 기준).
  const rangeAsLines = points.length > 40;
  const series = useMemo(() => [{ product: points[0]?.product_code ?? "B027", points: points.map(point => ({ time: point.day, average: point.average_price, minimum: point.minimum_price, maximum: point.maximum_price, generated_at: point.generated_at })) }], [points]);
  return <>
    <TrendSummaryStrip points={points} period={period} daily={trend.bucket === "day"} />
    <TrendNotes trend={trend} points={points} requestedFrom={requestedFrom} rangeAsLines={rangeAsLines} />
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

function TrendNotes({ trend, points, requestedFrom, rangeAsLines }: { trend: PublicFuelTrend; points: PublicFuelTrendPoint[]; requestedFrom: string | null; rangeAsLines: boolean }) {
  const dayCount = points.reduce((sum, point) => sum + Math.max(1, point.day_count || 1), 0);
  const range = trend.from_day && trend.to_day ? ` · ${trend.from_day} ~ ${trend.to_day}` : "";
  const shorter = Boolean(requestedFrom && trend.from_day && trend.from_day > requestedFrom);
  const missingExtremes = points.some(point => point.minimum_price == null || point.maximum_price == null);
  return <>
    <p className="public-fuel-stats-meta">{bucketNote[trend.bucket]}{range} · 기록 {dayCount.toLocaleString("ko-KR")}일</p>
    {shorter ? <p className="public-fuel-stats-meta">가격 기록은 {trend.from_day}부터 있습니다. 그 전 기간은 비어 있습니다.</p> : null}
    <p className="public-fuel-stats-meta">{rangeAsLines ? "실선: 평균 · 같은 색 점선: 그날의 최저·최고" : "선: 평균 · 세로선 양 끝: 최저·최고"} (원/L)</p>
    {missingExtremes ? <p className="public-fuel-stats-meta">일부 날짜의 최저·최고가는 제공되지 않았습니다. 평균가로 대신 채우지 않습니다.</p> : null}
  </>;
}

const columns = (daily: boolean): ColumnDef<PublicFuelTrendPoint, unknown>[] => [
  { id: "period", header: daily ? "날짜" : "기간", cell: ({ row: { original: point } }) => daily ? point.day : `${point.first_day} ~ ${point.last_day}` },
  { id: "average", header: "평균(원/L)", cell: ({ row: { original: point } }) => money(point.average_price) },
  { id: "minimum", header: "최저", cell: ({ row: { original: point } }) => point.minimum_price == null ? "미제공" : money(point.minimum_price) },
  { id: "maximum", header: "최고", cell: ({ row: { original: point } }) => point.maximum_price == null ? "미제공" : money(point.maximum_price) },
  { id: "stations", header: daily ? "주유소" : "주유소(일평균)", cell: ({ row: { original: point } }) => point.station_count.toLocaleString("ko-KR") },
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
