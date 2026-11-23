"use client";

import { VirtualTable } from "@kor-travel/ui/virtual-table";

import { CircleHelp, Clock, ClockAlert, LoaderCircle } from "lucide-react";
import Link from "next/link";
import { InfoButton } from "./info-button";
import { useEffect, useId, useRef, useState, type RefObject } from "react";
import { dateTime, transportGet } from "@/lib/journey";
import { fuelProductLabel } from "@/lib/transport-presentation";
import { fuelDrivingCosts } from "@/lib/driver-statistics";
import { FilterBar, FilterField } from "@/components/filter-bar";
import { SectionCard } from "./section-card";
import FuelPriceChart from "./fuel-price-chart-loader";
import { FUEL_CHART_ORDER, fuelStationHref, type FuelChartStation } from "@/lib/fuel-chart-model";
import { StatStrip } from "./stat-strip";
import { FuelRegionStats } from "./fuel-price-distribution";
import { PublicFuelFilterMenu, PublicFuelRegionButton, type FuelAreaChoice, type FuelSelectedRegion } from "./public-fuel-controls";
import { displayedRegion, type FuelCenterSigungu, type FuelRegionChip, type FuelViewportSigungu } from "@/lib/fuel-price-distribution";
import type { PublicFuelFilters } from "@/lib/public-fuel-filters";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "./ui/tooltip";

export type FuelMetrics = {
  cheapest_stations?: (FuelChartStation & { station_key: string; price: number })[]; ranking_complete?: boolean;
  update_pending?: boolean; station_count: number; average_price: number; minimum_price: number; maximum_price: number;
  price_spread: number; standard_deviation: number; saving_50l: number; cheapest_station_count: number;
  cheapest_station: { name: string; address: string | null; longitude?: number | null; latitude?: number | null } | null; generated_at: string;
};
export type FuelViewportStatistics = FuelMetrics & { product_code: string };
type Group = FuelMetrics & { scope_key: string; label: string; product_code?: string };
type History = { day: string; generated_at: string; average_price: number; station_count: number; product_code?: string; minimum_price?: number | null; maximum_price?: number | null; cheapest_station?: FuelChartStation | null };
type Statistics = { generated_at: string | null; update_pending: boolean; history_scope_key: string | null; items: Group[]; history: History[] };
const money = (value: number) => value.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
const priceTimeFormat = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Seoul", year: "2-digit", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
function priceTimestamp(value?: string | null) {
  const instant = value ? new Date(value) : null;
  if (!instant || !Number.isFinite(instant.getTime())) return null;
  const parts = Object.fromEntries(priceTimeFormat.formatToParts(instant).map(({ type, value }) => [type, value]));
  return `${parts.year}.${parts.month}.${parts.day} ${parts.hour}:${parts.minute} KST`;
}
const scopes = [["nationwide", "전국"], ["sido", "시도"], ["sigungu", "시군구"], ["highways", "고속도로 전체"], ["highway", "고속도로별"], ["highway_direction", "고속도로·방향별"]];
const inlineLink = "rounded-control text-sm font-medium text-brand underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

function historyComparison(rows: History[]) {
  const latest = [...rows].sort((left, right) => left.day.localeCompare(right.day)).at(-1);
  const before = (days: number) => latest ? new Date(Date.parse(`${latest.day}T00:00:00Z`) - days * 86_400_000).toISOString().slice(0, 10) : null;
  const previousDay = before(1), periodStart = before(6);
  return { latest, previousDay, periodStart,
    previous: rows.find((row) => row.day === previousDay),
    start: rows.find((row) => row.day === periodStart) };
}

function averageDifference(current?: History, baseline?: History) {
  if (!current || !baseline) return null;
  const difference = current.average_price - baseline.average_price;
  return `${difference > 0 ? "+" : ""}${money(difference)}`;
}

function historyRange(start: string, end: string) {
  const full = `${start} → ${end}`;
  return <span role="group" aria-label={full} title={full}>{start.slice(5).replace("-", ".")} → {end.slice(5).replace("-", ".")}</span>;
}

export function FuelDriverStatistics({ metrics }: { metrics: FuelMetrics }) {
  const [liters, setLiters] = useState("50");
  const [efficiency, setEfficiency] = useState("10");
  const costs = fuelDrivingCosts(metrics, Number(liters), Number(efficiency));
  const amount = (n: number | null) => n === null ? null : money(n);
  return <SectionCard title="차량 운영비 비교" description="현재 선택한 범주의 유효 가격과 입력한 주유량·연비로 계산합니다. 주행 조건·할인·주유소까지의 이동 비용은 포함하지 않습니다.">
    <FilterBar>
      <FilterField label="주유량(L)"><Input aria-label="주유량(L)" type="number" min="1" max="1000" value={liters} onChange={(event) => setLiters(event.target.value)} /></FilterField>
      <FilterField label="차량 연비(km/L)"><Input aria-label="차량 연비(km/L)" type="number" min="0.1" max="100" step="0.1" value={efficiency} onChange={(event) => setEfficiency(event.target.value)} /></FilterField>
    </FilterBar>
    <StatStrip ariaLabel="유가 운전 지표" items={[
      { label: "평균 가격", value: money(metrics.average_price), unit: "원/L" },
      { label: "최저 가격", value: money(metrics.minimum_price), unit: "원/L" },
      { label: "최고 가격", value: money(metrics.maximum_price), unit: "원/L" },
      { label: "최고·최저 가격 차이", value: money(metrics.price_spread), unit: "원/L" },
      { label: "가격 표준편차", value: money(metrics.standard_deviation), unit: "원/L" },
      { label: "평균가 주유 비용", value: amount(costs.averageFill), unit: "원", caption: `${liters || "—"}L 기준` },
      { label: "최저가 주유 비용", value: amount(costs.minimumFill), unit: "원", caption: `${liters || "—"}L 기준` },
      { label: "최고가 주유 비용", value: amount(costs.maximumFill), unit: "원", caption: `${liters || "—"}L 기준` },
      { label: "평균 대비 절약액", value: amount(costs.saving), unit: "원", caption: "최저가 주유 시" },
      { label: "평균 대비 절약률", value: amount(costs.savingPercent), unit: "%" },
      { label: "100km 평균 연료비", value: amount(costs.costPer100Km), unit: "원", caption: `연비 ${efficiency || "—"}km/L 가정` },
      { label: "100km 최저 연료비", value: amount(costs.minimumCostPer100Km), unit: "원", caption: "동일 연비·최저가 가정" },
    ]} />
  </SectionCard>;
}

export function FuelStatisticsCard({ metrics, title, history }: { metrics: FuelMetrics; title: string; history?: History[] }) {
  return <article className="fuel-stat-card flex flex-col gap-3 rounded-panel border border-border bg-card p-4 text-sm" aria-label={title}>
    <header className="flex flex-wrap items-baseline justify-between gap-2"><h3 className="text-sm font-semibold text-text-primary">{title}</h3><span className="text-xs text-text-secondary">{metrics.station_count.toLocaleString()}개 주유소</span></header>
    <dl className="fuel-stat-values grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3 [&_dd]:font-semibold [&_dd]:tabular-nums [&_dd_small]:ml-1 [&_dd_small]:text-xs [&_dd_small]:font-normal [&_dd_small]:text-text-secondary [&_dt]:text-xs [&_dt]:text-text-secondary">
      <div><dt>평균</dt><dd>{money(metrics.average_price)}<small>원/L</small></dd></div>
      <div><dt>최저</dt><dd>{money(metrics.minimum_price)}<small>원/L</small></dd></div>
      <FuelPriceComparison metrics={metrics} history={history} />
      <div><dt>50L 평균 대비 절감</dt><dd>{money(metrics.saving_50l)}<small>원</small></dd></div>
    </dl>
    <p>최저가 · <strong>{metrics.cheapest_station?.name ?? "정보 없음"}</strong>{metrics.cheapest_station_count > 1 ? ` 외 ${metrics.cheapest_station_count - 1}곳` : ""}</p>
    {metrics.cheapest_station?.address ? <p className="text-text-secondary">{metrics.cheapest_station.longitude != null && metrics.cheapest_station.latitude != null ? <Link className={inlineLink} href={`/fuel?longitude=${metrics.cheapest_station.longitude}&latitude=${metrics.cheapest_station.latitude}`}>{metrics.cheapest_station.address} · 지도</Link> : metrics.cheapest_station.address}</p> : null}
    <small className="text-xs text-text-secondary">수집 기준 {dateTime(metrics.generated_at)}</small>
    {metrics.update_pending ? <p role="status" className="text-text-secondary">최신 수집 통계 반영 대기</p> : null}
  </article>;
}

export function FuelPriceStatus({ stale, lastRefreshedAt }: { stale: boolean; lastRefreshedAt?: string | null }) {
  const timestamp = priceTimestamp(lastRefreshedAt);
  const time = timestamp ? <time dateTime={lastRefreshedAt!} title={`가격 갱신 ${dateTime(lastRefreshedAt)} KST`}>{timestamp}</time> : "시각 미확인";
  return stale ? <p className="error" role="status" aria-label={`유가 갱신 지연 · 가격 갱신 ${timestamp ?? "확인되지 않음"}`}>갱신 지연 {time}</p>
    : timestamp ? <p className="fuel-viewport-context">가격 갱신 {time}</p> : null;
}

type FuelViewportSummaryProps = {
  items: FuelViewportStatistics[];
  pending: boolean;
  failed?: boolean;
  pricesStale?: boolean;
  pricesLastRefreshedAt?: string | null;
  detailOpen?: boolean;
  detailExpanded?: boolean;
  onDetailExpandedChange?: (expanded: boolean) => void;
  publicFuel?: {
    products: string[];
    onProductsChange: (products: string[]) => void;
    onRefresh?: () => void;
    refreshing?: boolean;
    /** 지도 범위 업데이트를 지금 쓸 수 없는 이유(가격이 오래됐는데 onRefresh가 없을 때 버튼 툴팁·접근 이름에 쓴다). */
    refreshBlocked?: PublicFuelRefreshBlock;
    /** 가격 읽기 모델의 신선도(마지막으로 받은 값). 없으면 아직 모른다(첫 조회 중·실패) — 가격 아이콘이 "확인 중/확인 못 함"을 보인다. */
    priceFreshness?: { stale: boolean; lastRefreshedAt?: string | null };
    /** 공개 유가 전용: 지금 지도에 보이는 시군구(주유소 수 내림차순)와 그 통계를 읽는 공개 reader. */
    sigungu?: FuelViewportSigungu[];
    /** 공개 유가 전용: 지도 중심 시군구(가까운 주유소 근사). 고른 지역이 없을 때 칩 기본값, null·없음이면 sigungu 1순위. */
    center?: FuelCenterSigungu | null;
    /** 공개 유가 서버 필터 query. 시군구 통계도 같은 조건으로 읽는다. */
    filterQuery?: string;
    /** 맨 위 유종·필터 선택에 함께 담는 주유소 필터(없으면 유종만 고른다). */
    filters?: PublicFuelFilters;
    onFiltersChange?: (filters: PublicFuelFilters) => void;
    /** 지역 이동에서 고른 시군구. 지역 칩은 이것 하나만(고르기 전에는 지도 중심 시군구 하나) 보인다. */
    selectedRegion?: FuelSelectedRegion;
    onClearRegion?: () => void;
    onOpenRegion?: (current?: FuelAreaChoice, opener?: HTMLElement | null) => void;
    load?: <T>(path: string, signal?: AbortSignal) => Promise<T>;
  };
};

export function FuelViewportSummary({ publicFuel, ...props }: FuelViewportSummaryProps) {
  return publicFuel ? <PublicFuelViewportSummary {...props} publicFuel={publicFuel} /> : <AdminFuelViewportSummary {...props} />;
}

function AdminFuelViewportSummary({ items, pending, failed = false, pricesStale = false, pricesLastRefreshedAt, detailOpen = false, detailExpanded, onDetailExpandedChange }: Omit<FuelViewportSummaryProps, "publicFuel">) {
  const { expanded, bodyId, setLocalDetailExpanded, detailScopeExpanded, selected, productId, setProduct } = useFuelViewportSummary({ items, pending, failed, pricesStale, pricesLastRefreshedAt, detailOpen, detailExpanded, onDetailExpandedChange });
  return <section className="fuel-viewport-summary" aria-label="현재 지도 범위 유가 통계" aria-busy={pending}>
    <header><h2>{detailOpen ? <button type="button" className="fuel-summary-toggle" aria-expanded={expanded} aria-controls={bodyId} onClick={() => { setLocalDetailExpanded(!detailScopeExpanded); onDetailExpandedChange?.(!detailScopeExpanded); }}>{expanded ? "범위 접기" : "현재 지도 범위"}</button> : "범위"}</h2>{expanded ? <small>원/L</small> : null}
      {expanded && !pending && !failed && selected ? items.length > 1 ? <><label className="sr-only" htmlFor={productId}>지도 통계 유종</label><select id={productId} value={selected.product_code} onChange={(event) => setProduct(event.target.value)}>{items.map((item) => <option key={item.product_code} value={item.product_code}>{fuelProductLabel(item.product_code)}</option>)}</select></> : <span>{fuelProductLabel(selected.product_code)}</span> : null}
      <FuelViewportHelp pending={pending} failed={failed} selected={selected} pricesStale={pricesStale} />
    </header>
    <FuelViewportValues bodyId={bodyId} expanded={expanded} pending={pending} failed={failed} detailOpen={detailOpen} pricesStale={pricesStale} pricesLastRefreshedAt={pricesLastRefreshedAt} selected={selected} />
  </section>;
}

// 공개 유가는 범위 요약을 접지 않는다. 맨 위 줄은 지역 이동 아이콘과 유종·필터 선택(제목 글자 없음 — 소유자 지시
// 2026-11-22 "'지도 범위' 글씨 제거"; 영역 이름은 aria-label로 남는다), 그 아래 고른 지역 칩 하나와 평균·최저가.
function PublicFuelViewportSummary({
  items, pending, failed, pricesStale, pricesLastRefreshedAt, publicFuel,
}: Omit<FuelViewportSummaryProps, "publicFuel"> & { publicFuel: NonNullable<FuelViewportSummaryProps["publicFuel"]> }) {
  const regionButton = useRef<HTMLButtonElement>(null);
  const selectedProducts = new Set(publicFuel.products);
  const displayed = selectedProducts.size ? items.filter(item => selectedProducts.has(item.product_code)) : items;
  const region = displayedRegion(publicFuel.selectedRegion, publicFuel.sigungu ?? [], publicFuel.center);
  return <section className="fuel-viewport-summary public-fuel-summary" aria-label="현재 지도 범위 유가 통계" aria-busy={pending}>
    <PublicFuelSummaryHeader controls={publicFuel} region={region} regionButton={regionButton}
      priceState={publicPriceState(publicFuel.priceFreshness ?? (pricesStale === undefined ? undefined : { stale: pricesStale, lastRefreshedAt: pricesLastRefreshedAt }), pending, failed)}
      lastRefreshedAt={publicFuel.priceFreshness?.lastRefreshedAt ?? pricesLastRefreshedAt} />
    {publicFuel.load ? <FuelRegionStats region={region} product={FUEL_CHART_ORDER.find(code => selectedProducts.has(code)) ?? "B027"}
      load={publicFuel.load} filterQuery={publicFuel.filterQuery} onClear={publicFuel.onClearRegion} focusFallback={regionButton} /> : null}
    <div className="fuel-summary-body public-fuel-summary-body">
      {pending ? <p role="status">통계 조회 중…</p> : failed ? <p role="alert">통계를 불러오지 못했습니다.</p> :
        <PublicFuelRangeValues items={displayed} />}
    </div>
  </section>;
}

/** 가격 아이콘 상태. 신선도를 아직 모르면 조회 중(checking)·실패(unknown)로 나눈다 — 모르는 것을 "최신"이라 말하지 않는다. */
type PublicPriceState = "stale" | "fresh" | "checking" | "unknown";
function publicPriceState(freshness: { stale: boolean } | undefined, pending: boolean, failed?: boolean): PublicPriceState {
  if (freshness) return freshness.stale ? "stale" : "fresh";
  return failed && !pending ? "unknown" : "checking";
}

function PublicFuelSummaryHeader({
  priceState, lastRefreshedAt, controls, region, regionButton,
}: {
  priceState: PublicPriceState; lastRefreshedAt?: string | null;
  controls: NonNullable<FuelViewportSummaryProps["publicFuel"]>;
  region: FuelRegionChip | null; regionButton: RefObject<HTMLButtonElement | null>;
}) {
  const { products, onProductsChange, filters, onFiltersChange, onOpenRegion } = controls;
  return <header className="public-fuel-summary-header">
    {onOpenRegion ? <PublicFuelRegionButton buttonRef={regionButton} onOpen={opener => onOpenRegion(region ?? undefined, opener)} /> : null}
    <div className="public-fuel-summary-products">
      <PublicFuelFilterMenu products={products} onProductsChange={onProductsChange} filters={filters} onFiltersChange={onFiltersChange} />
    </div>
    <PublicFuelPriceButton state={priceState} lastRefreshedAt={lastRefreshedAt} onRefresh={controls.onRefresh}
      refreshing={controls.refreshing} blocked={controls.refreshBlocked} />
  </header>;
}

/**
 * 지도 범위 업데이트를 못 쓰는 이유. disabled: 이 실행에 업데이트가 꺼져 있음, filters: 필터 사용 중,
 * loading·failed: 지금 화면 조회 중·실패(범위를 아직 모른다), range: 보이는 주유소가 1~9곳이 아님.
 */
export type PublicFuelRefreshBlock = "disabled" | "filters" | "loading" | "failed" | "range";
const REFRESH_BLOCK_REASON: Record<PublicFuelRefreshBlock, string> = {
  disabled: "이 화면에서는 유가 업데이트를 쓸 수 없습니다",
  loading: "지도 범위 가격을 불러오는 중입니다. 잠시 뒤 다시 누르세요",
  failed: "지도 범위 가격을 불러오지 못했습니다. 다시 조회한 뒤 업데이트할 수 있습니다",
  filters: "필터를 켠 동안은 지도 범위 업데이트를 할 수 없습니다. 필터를 끄거나 주유소 상세에서 업데이트하세요",
  range: "지도에 보이는 주유소가 1~9곳일 때만 업데이트할 수 있습니다. 지도를 확대하세요",
};

/**
 * 공개 유가 맨 위 줄의 가격 상태·업데이트 단추 하나(소유자 지시 2026-11-23: "오래됨"과 "업데이트"를 아이콘 하나로).
 * - 가격이 오래됨: 빨간 시계(!) 아이콘. 업데이트할 수 있으면 눌러 지도 범위 가격을 업데이트한다.
 * - 최신이거나 지금 업데이트할 수 없으면 회색(최신)·빨간(오래됨) 아이콘의 비활성 단추. 포커스는 받는다(aria-disabled) —
 *   키보드·스크린리더 사용자도 이유를 듣고, 툴팁(터치는 누르면 열림)에 이유와 마지막 가격 갱신 시각을 보인다.
 */
const PRICE_STATE_TEXT: Record<PublicPriceState, { name: string; reason?: string }> = {
  stale: { name: "가격 오래됨" },
  fresh: { name: "가격 최신", reason: "가격이 최신이라 업데이트할 필요가 없습니다" },
  checking: { name: "가격 상태 확인 중", reason: "가격 상태를 확인하는 중입니다" },
  unknown: { name: "가격 상태 확인 못 함", reason: "가격 상태를 확인하지 못했습니다" },
};

/** 가격 아이콘의 모양·이름·툴팁(순수 함수). 신선도를 모를 때(checking·unknown)는 회색 "최신"·비활성 모양을 쓰지 않는다
 * (조정자 지시 2026-11-23): 조회 중은 도는 아이콘(aria-busy), 실패는 물음표, 둘 다 aria-disabled 없이 누르면 이유 툴팁만 연다. */
function priceButtonView(state: PublicPriceState, canRefresh: boolean, blocked: PublicFuelRefreshBlock | undefined,
  refreshing: boolean, lastRefreshedAt?: string | null) {
  const stale = state === "stale";
  const unknownState = state === "checking" || state === "unknown";
  const enabled = stale && canRefresh;
  const time = `마지막 가격 갱신 ${priceTimestamp(lastRefreshedAt) ?? "시각 미확인"}`;
  const reason = PRICE_STATE_TEXT[state].reason ?? REFRESH_BLOCK_REASON[blocked ?? "disabled"];
  const icons = { stale: ClockAlert, fresh: Clock, checking: LoaderCircle, unknown: CircleHelp } as const;
  return {
    stale, enabled, Icon: icons[state],
    label: enabled ? "가격 오래됨 · 지도 범위 유가 업데이트" : `${PRICE_STATE_TEXT[state].name} · 업데이트할 수 없음: ${reason}`,
    tipText: enabled ? `가격이 오래됐습니다. 눌러 지도에 보이는 주유소 가격을 업데이트합니다. ${time}` : `${reason}. ${time}`,
    ariaDisabled: (!enabled && !unknownState) || refreshing,
    // 업데이트 진행 중(loading)의 aria-busy를 덮어쓰지 않는다.
    busy: state === "checking" || refreshing,
    iconClass: state === "checking" ? "public-fuel-price-spin" : undefined,
  };
}

function PublicFuelPriceButton({ state, lastRefreshedAt, onRefresh, refreshing = false, blocked }: {
  state: PublicPriceState; lastRefreshedAt?: string | null; onRefresh?: () => void; refreshing?: boolean; blocked?: PublicFuelRefreshBlock;
}) {
  const [tip, setTip] = useState(false);
  const view = priceButtonView(state, Boolean(onRefresh), blocked, refreshing, lastRefreshedAt);
  const { Icon, enabled } = view;
  return <>
  <TooltipProvider delayDuration={300}>
    <Tooltip open={tip} onOpenChange={setTip}>
      <TooltipTrigger asChild>
        <Button type="button" variant="outline" size="icon" className="public-fuel-price-button" data-stale={view.stale || undefined} data-state-kind={state}
          aria-label={view.label} aria-disabled={view.ariaDisabled || undefined} loading={refreshing}
          aria-busy={view.busy || undefined}
          onClick={event => {
            if (enabled) { onRefresh?.(); return; }
            // Radix 툴팁은 트리거를 누르면 닫는다. 누를 수 없는 단추에서는 그 기본 동작을 막고 이유 툴팁을 연다(터치·키보드).
            event.preventDefault();
            setTip(true);
          }}>
          <Icon aria-hidden="true" size={18} className={view.iconClass} />
        </Button>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="public-fuel-price-tip">{view.tipText}</TooltipContent>
    </Tooltip>
  </TooltipProvider>
  {/* 예전 "오래됨"(role=status)처럼 가격이 오래되면 화면 읽기 프로그램에 알린다. 늘 붙여 두고 글자만 바꾼다. */}
  <span className="sr-only public-fuel-price-status" role="status">{view.stale ? "가격이 오래됐습니다" : ""}</span>
  </>;
}

function PublicFuelRangeValues({ items }: { items: FuelViewportStatistics[] }) {
  if (!items.length) return <p>선택한 범위의 유가 통계가 없습니다.</p>;
  return <div className="public-fuel-summary-values">
    {items.map(item => {
      const label = fuelProductLabel(item.product_code);
      return <div key={item.product_code} className="public-fuel-summary-product">
        <h3>{label} <small>{money(item.station_count)}개 주유소</small></h3>
        <dl aria-label={label}>
          <div><dt>평균</dt><dd>{money(item.average_price)}<small>원/L</small></dd></div>
          <div><dt>최저</dt><dd>{money(item.minimum_price)}<small>원/L</small></dd></div>
        </dl>
      </div>;
    })}
    {items.some(item => item.update_pending) ? <p role="status">최신 수집 통계 반영 대기</p> : null}
  </div>;
}

export function FuelPriceTrend({ rows }: { rows: History[] }) {
  if (!rows.length) return <p className="text-sm text-text-secondary">추이 데이터가 없습니다.</p>;
  const products = [...new Set(rows.map(row => row.product_code ?? "B027"))].sort((a, b) => productOrder(a) - productOrder(b) || a.localeCompare(b));
  return <><p className="fuel-stat-chart-key">선: 평균 · 세로선 양 끝: 최저·최고 (원/L)</p>
    {rows.some(row => row.minimum_price == null || row.maximum_price == null) ? <p className="fuel-stat-extremes-note text-xs text-text-secondary">일부 날짜의 최저·최고가는 미제공입니다. 평균가로 대신 채우지 않습니다.</p> : null}
    <FuelPriceChart label="최근 30일 유종별 평균·최저·최고 유가" series={products.map(product => ({ product, points: rows.filter(row => (row.product_code ?? "B027") === product).map(row => ({ time: row.day, average: row.average_price, minimum: row.minimum_price, maximum: row.maximum_price, cheapest: row.cheapest_station, generated_at: row.generated_at })) }))} />
    <details className="fuel-stat-table overflow-x-auto"><summary className="flex min-h-11 cursor-pointer items-center text-sm text-text-secondary">일별 가격 표</summary><VirtualTable ariaLabel="30일 유가 관측값" data={rows} getRowId={row => `${row.product_code ?? "B027"}:${row.day}`} virtualized={false} columns={[
      { id: "date", header: "날짜(KST)", cell: ({ row: { original: row } }) => row.day },
      { id: "product", header: "유종", cell: ({ row: { original: row } }) => fuelProductLabel(row.product_code ?? "B027") },
      { id: "average", header: "평균(원/L)", cell: ({ row: { original: row } }) => money(row.average_price) },
      { id: "minimum", header: "최저", cell: ({ row: { original: row } }) => row.minimum_price == null ? "미제공" : money(row.minimum_price) },
      { id: "maximum", header: "최고", cell: ({ row: { original: row } }) => row.maximum_price == null ? "미제공" : money(row.maximum_price) },
      { id: "station", header: "최저가 주유소", cell: ({ row: { original: row } }) => <StationAddress station={row.cheapest_station} /> },
    ]} /></details></>;
}
const productOrder = (code: string) => FUEL_CHART_ORDER.includes(code) ? FUEL_CHART_ORDER.indexOf(code) : FUEL_CHART_ORDER.length;
function StationAddress({ station }: { station?: FuelChartStation | null }) {
  const href = fuelStationHref(station);
  return station ? <><span>{station.name}</span>{station.address ? <> · {href ? <Link className={inlineLink} href={href}>{station.address}</Link> : station.address}</> : href ? <> · <Link className={inlineLink} href={href}>지도</Link></> : null}</> : <>미제공</>;
}
function FuelCheapestTables({ items, allProducts = false }: { items: Group[]; allProducts?: boolean }) {
  const groups = new Map(items.map(item => [item.product_code ?? "B027", item]));
  const products = [...new Set([...(allProducts ? FUEL_CHART_ORDER.slice(0, 4) : []), ...groups.keys()])].sort((a, b) => productOrder(a) - productOrder(b) || a.localeCompare(b));
  return <div className="fuel-cheapest-tables">{products.map(product => {
    const item = groups.get(product);
    const ranked = item?.cheapest_stations?.length ? item.cheapest_stations : item?.cheapest_station ? [{ ...item.cheapest_station, station_key: "legacy", price: item.minimum_price }] : [];
    return <section key={product} aria-label={`${fuelProductLabel(product)} 최저가 주유소`}><h3 className="font-semibold text-text-primary">{fuelProductLabel(product)} · 최저가 주유소</h3>
      {!item ? <p className="text-xs text-text-secondary">이 유종의 통계가 없습니다.</p> : <>
        {!item.ranking_complete ? <p className="text-xs text-text-secondary">이전 집계에는 10곳 순위가 저장되지 않았습니다. 해당 범주의 당시 전체 순위를 확인할 수 없어 알려진 최저가만 표시합니다.</p> : null}
        <VirtualTable ariaLabel={`${fuelProductLabel(product)} 가격순 주유소`} data={[...ranked].sort((a, b) => a.price - b.price || a.station_key.localeCompare(b.station_key)).slice(0, 10)} getRowId={row => row.station_key} virtualized={false} columns={[
          { id: "rank", header: "순위", cell: ({ row }) => row.index + 1 },
          { id: "price", header: "가격(원/L)", cell: ({ row: { original: row } }) => money(row.price) },
          { id: "station", header: "주유소 · 주소", cell: ({ row: { original: row } }) => <StationAddress station={row} /> },
        ]} />
      </>}
    </section>;
  })}</div>;
}

export function FuelStatisticsPage() {
  const { pending, scope, setScope, setScopeKey, product, setProduct, setReload, shownData, categoryKey, error, selected, comparisonRows } = useFuelStatistics();
  return <section className="fuel-stat-section flex flex-col gap-6" aria-label="유가 통계" aria-busy={pending}>
    <div className="fuel-stat-filters">
      <label>범위<select aria-label="범위" value={scope} onChange={(event) => { setScope(event.target.value); setScopeKey(""); }} >{scopes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>유종<select aria-label="유종" value={product} onChange={(event) => { setProduct(event.target.value); setScopeKey(""); }}>{["ALL", ...FUEL_CHART_ORDER].map((code) => <option key={code} value={code}>{code === "ALL" ? "전체" : fuelProductLabel(code)}</option>)}</select></label>
      {shownData?.items.length ? <label className="fuel-stat-category">추이 범주<select aria-label="추이 범주" value={categoryKey} onChange={event => setScopeKey(event.target.value)}>{[...new Map(shownData.items.map(row => [row.scope_key, row])).values()].map(row => <option key={row.scope_key} value={row.scope_key}>{row.label}</option>)}</select></label> : null}
      <Button className="fuel-stat-refresh" type="button" variant="outline" size="sm" onClick={() => setReload((value) => value + 1)}>새로고침</Button>
    </div>
    <FuelStatisticsResult pending={pending} error={error} shownData={shownData} selected={selected} product={product} comparisonRows={comparisonRows} />
    {shownData?.items.length ? <div className="fuel-stat-table overflow-x-auto"><FuelCategoryTable shownData={shownData} setScopeKey={setScopeKey} /></div> : null}
    {!pending && !error && selected ? <details className="fuel-driving-details"><summary>차량 운영비 비교 · {fuelProductLabel(selected.product_code ?? "B027")}</summary><FuelDriverStatistics metrics={selected} /></details> : null}
  </section>;
}


// 조회·선택·요청 수명은 이 도메인 훅이, 아래 컴포넌트는 표현을 소유한다.
function useFuelStatistics() {
  const [scope, setScope] = useState("nationwide");
  const [product, setProduct] = useState("ALL");
  const [scopeKey, setScopeKey] = useState("");
  const [reload, setReload] = useState(0);
  const [dataContext, setDataContext] = useState("");
  const [data, setData] = useState<Statistics | null>(null);
  const [error, setError] = useState(false);
  const [pending, setPending] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    setPending(true); setError(false);
    const search = new URLSearchParams({ scope, product_code: product });
    if (scopeKey) search.set("scope_key", scopeKey);
    transportGet<Statistics>(`transport/fuel/statistics?${search}`, controller.signal).then((value) => {
      if (!controller.signal.aborted) { setData(value); setDataContext(`${scope}/${product}`); setPending(false); }
    }).catch(() => { if (!controller.signal.aborted) { setError(true); setPending(false); } });
    return () => controller.abort();
  }, [scope, product, scopeKey, reload]);
  const shownData = dataContext === `${scope}/${product}` ? data : null;
  const selected = shownData?.items.find((row) => row.scope_key === shownData.history_scope_key);
  const comparison = historyComparison(shownData?.history.filter(row => (row.product_code ?? "B027") === (selected?.product_code ?? "B027")) ?? []);
  const comparisonRows = comparison.latest ? [
    { day: comparison.latest.day, row: comparison.latest },
    { day: comparison.previousDay!, row: comparison.previous },
    { day: comparison.periodStart!, row: comparison.start },
  ] : [];
  const categoryKey = shownData?.items.some((row) => row.scope_key === scopeKey) ? scopeKey : selected?.scope_key ?? "";
  return { pending, scope, setScope, setScopeKey, product, setProduct, setReload, shownData, categoryKey, error, selected, comparisonRows };
}


// 조회·선택·요청 수명은 이 도메인 훅이, 아래 컴포넌트는 표현을 소유한다.
function useFuelViewportSummary({ items, detailOpen = false, detailExpanded }: { items: FuelViewportStatistics[]; pending: boolean; failed?: boolean; pricesStale?: boolean; pricesLastRefreshedAt?: string | null; detailOpen?: boolean; detailExpanded?: boolean; onDetailExpandedChange?: (expanded: boolean) => void }) {
  const productId = useId();
  const bodyId = useId();
  const [product, setProduct] = useState("B027");
  const [localDetailExpanded, setLocalDetailExpanded] = useState(false);
  const detailScopeExpanded = detailExpanded ?? localDetailExpanded;
  const expanded = !detailOpen || detailScopeExpanded;
  const selected = items.find((item) => item.product_code === product) ?? items[0];
  return { expanded, bodyId, setLocalDetailExpanded, detailScopeExpanded, selected, productId, setProduct };
}


function FuelViewportHelp({ pending, failed, selected, pricesStale }: Pick<ReturnType<typeof useFuelViewportSummary>, "selected"> & Pick<NonNullable<Parameters<typeof FuelViewportSummary>[0]>, "pending" | "failed" | "pricesStale">) {
  return (<InfoButton label="지도 범위 유가 통계">
        {pending ? <p role="status">통계 조회 중…</p> : failed ? <p role="alert">통계를 불러오지 못했습니다.</p> : <>
          {selected ? <>
          <p>현재 지도 범위와 검색·출처·유종 조건에 맞는 전체 주유소의 유효 가격을 집계합니다. 묶음 마커 개수와는 다릅니다.</p>
          <p>통계 기준은 공개된 통계 세대의 수집 시각이고, 가격 갱신은 가격 읽기 모델의 마지막 성공 갱신 시각입니다. 개별 가격의 관측 시각은 주유소 상세에서 확인할 수 있습니다.</p>
          </> : null}
          {pricesStale ? <p>가격 갱신이 지연되어 현재 유종·가격·판매 여부가 표시된 자료와 다를 수 있습니다.</p> : null}
          {selected ? <>
          <FuelStatisticsCard title={fuelProductLabel(selected.product_code)} metrics={selected} />
          <Link className={inlineLink} href="/fuel/statistics">지역·기간별 유가 통계</Link>
          </> : <p>통계 없음 · 수집 완료 후 반영됩니다.</p>}
        </>}
      </InfoButton>);
}


function FuelViewportValues({ bodyId, expanded, pending, failed, detailOpen, pricesStale = false, pricesLastRefreshedAt, selected }: Pick<ReturnType<typeof useFuelViewportSummary>, "bodyId" | "expanded" | "selected"> & Pick<NonNullable<Parameters<typeof FuelViewportSummary>[0]>, "pending" | "failed" | "detailOpen" | "pricesStale" | "pricesLastRefreshedAt">) {
  return (<div id={bodyId} className="fuel-summary-body" hidden={!expanded}>
    <FuelRangeContent pending={pending} failed={failed} detailOpen={detailOpen} pricesStale={pricesStale} pricesLastRefreshedAt={pricesLastRefreshedAt} selected={selected} />
    </div>);
}


function FuelHistoryContext({ selected, comparisonRows }: Pick<ReturnType<typeof useFuelStatistics>, "selected" | "comparisonRows">) {
  return (<div className="section-title-row flex flex-wrap items-center gap-2"><h2 className="text-base font-semibold text-text-primary">최근 30일 평균 유가 · {selected?.label}</h2><InfoButton label="유가 집계 기준">
          <p>KST 일별 마지막 정상 수집 기준이며 수집 기록이 있는 날짜만 표시합니다. 전국·지역은 오피넷, 고속도로는 한국도로공사 기준입니다. 유효 가격을 주유소별 동일 비중으로 집계합니다. 절감액은 범주 평균과 최저가의 차이입니다.</p>
          <p>아래 비교 관측은 {fuelProductLabel(selected?.product_code ?? "B027")} 기준입니다. 평균 차이는 마지막 집계일과 정확한 전일·6일 전을 비교합니다. 날짜별 대상 주유소가 달라질 수 있습니다. 비교 관측이 없으면 가까운 날짜나 0으로 대체하지 않습니다.</p>
          {comparisonRows.map(({ day, row }) => <p key={day}>{day} · {row ? <>평균 {money(row.average_price)}원/L · 유효 {row.station_count.toLocaleString("ko-KR")}개 · 수집 <time dateTime={row.generated_at}>{dateTime(row.generated_at)} KST</time></> : "비교 관측 없음"}</p>)}
          {selected ? <p>선택 범주 가격 차이 {money(selected.price_spread)}원/L · 표준편차 {money(selected.standard_deviation)}원/L</p> : null}
        </InfoButton></div>);
}


function FuelCategoryTable({ shownData, setScopeKey }: Pick<ReturnType<typeof useFuelStatistics>, "setScopeKey"> & { shownData: Statistics }) {
  return (<VirtualTable ariaLabel="조회 결과" data={shownData.items} getRowId={(row) => `${row.scope_key}:${row.product_code ?? "B027"}`} virtualized={false} columns={[{ id: 'column0', header: '범주', cell: ({ row: { original: row } }) => <><Button type="button" variant="link" size="sm" className="h-auto p-0" onClick={() => setScopeKey(row.scope_key)}>{row.label} · {fuelProductLabel(row.product_code ?? "B027")}</Button></> },
{ id: 'column1', header: '주유소', cell: ({ row: { original: row } }) => <>{row.station_count}</> },
{ id: 'column2', header: '평균', cell: ({ row: { original: row } }) => <>{money(row.average_price)}</> },
{ id: 'column3', header: '최저', cell: ({ row: { original: row } }) => <>{money(row.minimum_price)}</> },
{ id: 'column4', header: '최저가 주유소', cell: ({ row: { original: row } }) => <StationAddress station={row.cheapest_station} /> },
{ id: 'column5', header: '가격 차이', cell: ({ row: { original: row } }) => <>{money(row.price_spread)}</> },
{ id: 'column6', header: '50L 절감(원)', cell: ({ row: { original: row } }) => <>{money(row.saving_50l)}</> }]} />);
}

function FuelPriceComparison({ metrics, history }: Pick<Parameters<typeof FuelStatisticsCard>[0], "metrics" | "history">) {
  const comparison = history ? historyComparison(history) : null;
  const dayDifference = averageDifference(comparison?.latest, comparison?.previous);
  const periodDifference = averageDifference(comparison?.latest, comparison?.start);
  return <>
      {comparison ? <>
        <div><dt>전일 평균 차이{comparison.latest ? <small className="block">{historyRange(comparison.previousDay!, comparison.latest.day)}</small> : null}</dt><dd>{dayDifference === null ? "비교 관측 없음" : <>{dayDifference}<small>원/L</small></>}</dd></div>
        <div><dt>7일 구간 변화{comparison.latest ? <small className="block">{historyRange(comparison.periodStart!, comparison.latest.day)}</small> : null}</dt><dd>{periodDifference === null ? "비교 관측 없음" : <>{periodDifference}<small>원/L</small></>}</dd></div>
      </> : <>
        <div><dt>최고−최저</dt><dd>{money(metrics.price_spread)}<small>원/L</small></dd></div>
        <div><dt>가격 표준편차</dt><dd>{money(metrics.standard_deviation)}<small>원/L</small></dd></div>
      </>}
  </>;
}

function FuelStatisticsResult({ pending, error, shownData, selected, product, comparisonRows }: Pick<ReturnType<typeof useFuelStatistics>, "pending" | "error" | "shownData" | "selected" | "product" | "comparisonRows">) {
  if (pending) return <p role="status" className="text-sm text-text-secondary">통계 조회 중…</p>;
  if (error) return <p role="alert" className="text-sm text-destructive">통계를 불러오지 못했습니다. 새로고침해 주세요.</p>;
  if (!shownData) return null;
  return <>
      <p className="fuel-collection-basis">{shownData.generated_at ? `수집 기준 ${dateTime(shownData.generated_at)}` : "첫 수집 완료 후 통계가 생성됩니다."}{shownData.update_pending ? " · 최신 수집 통계 반영 대기" : ""}</p>
      {shownData.items.length ? <>
        <FuelHistoryContext selected={selected} comparisonRows={comparisonRows} /><FuelPriceTrend rows={shownData.history} />
        <FuelCheapestTables allProducts={product === "ALL"} items={shownData.items.filter(row => row.scope_key === shownData.history_scope_key)} />

      </> : <p className="text-sm text-text-secondary">{product === "ALL" ? "선택한 범위의 전체 유종 통계가 없습니다." : "선택한 유종의 통계가 없습니다."}</p>}

  </>;
}

function FuelRangeContent({ pending, failed, detailOpen, pricesStale = false, pricesLastRefreshedAt, selected }: Omit<Parameters<typeof FuelViewportValues>[0], "bodyId" | "expanded">) {
  if (pending) return <p role="status">통계 조회 중…</p>;
  if (failed) return <p role="alert">통계를 불러오지 못했습니다.</p>;
  return <>
      {detailOpen ? <FuelPriceStatus stale={pricesStale} lastRefreshedAt={pricesLastRefreshedAt} /> : null}
      {selected ? <dl><div><dt>평균</dt><dd>{money(selected.average_price)}</dd></div><div><dt>최저</dt><dd>{money(selected.minimum_price)}</dd></div></dl> : null}
      {!detailOpen ? <FuelPriceStatus stale={pricesStale} lastRefreshedAt={pricesLastRefreshedAt} /> : null}
      {selected ? <>
      {selected.update_pending ? <p role="status">최신 수집 통계 반영 대기</p> : null}
      </> : <p>통계 없음 · 수집 완료 후 반영됩니다.</p>}
  </>;
}
