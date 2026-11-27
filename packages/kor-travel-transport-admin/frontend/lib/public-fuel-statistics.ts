/**
 * 공개 유가 통계 화면(`/statistics`)의 순수 모델. 화면 상태(범위·지역·유종·기간)를 URL과 주고받고,
 * 공개 통계 API 두 개(`/v1/transport/fuel/statistics`, `/v1/transport/fuel/statistics/history`)의 요청 경로를 만들고,
 * 응답에서 지역 선택지·기간 요약을 계산한다. 가격을 보간하거나 빠진 값을 다른 값으로 채우지 않는다.
 */
import { ZodError, z } from "zod";
import { TransportError } from "./journey";
import { FUEL_CHART_ORDER, type FuelChartStation } from "./fuel-chart-model";
import { FUEL_PRODUCT_LABELS } from "./transport-presentation";

/** 화면의 범위. 고속도로는 노선 선택이 "전체"면 API scope `highways`, 노선이면 `highway`다. */
export type PublicFuelArea = "nationwide" | "sido" | "sigungu" | "highway";
export type PublicFuelPeriod = "30" | "90" | "365" | "all";
export type PublicFuelStatisticsView = { area: PublicFuelArea; region: string; product: string; period: PublicFuelPeriod };

export const PUBLIC_FUEL_AREAS: [PublicFuelArea, string][] = [["nationwide", "전국"], ["sido", "시도"], ["sigungu", "시군구"], ["highway", "고속도로"]];
export const PUBLIC_FUEL_PERIODS: [PublicFuelPeriod, string][] = [["30", "30일"], ["90", "90일"], ["365", "1년"], ["all", "전체"]];
export const PUBLIC_FUEL_PRODUCTS = FUEL_CHART_ORDER.filter(code => Object.hasOwn(FUEL_PRODUCT_LABELS, code));
/** 고속도로 노선 선택의 "전체 노선". */
export const ALL_ROUTES = "all";
const MAX_REGION_LENGTH = 512;

export const DEFAULT_VIEW: PublicFuelStatisticsView = { area: "nationwide", region: "", product: "B027", period: "30" };

type SearchInput = URLSearchParams | Record<string, string | string[] | undefined>;
function first(search: SearchInput, name: string) {
  const value = search instanceof URLSearchParams ? search.get(name) : search[name];
  return (Array.isArray(value) ? value[0] : value) ?? null;
}

/** URL query → 화면 상태. 모르는 값은 기본값으로 둔다(오류로 막지 않는다). */
export function parseStatisticsView(search: SearchInput, fallbackProduct?: string): PublicFuelStatisticsView {
  const area = first(search, "scope"), product = first(search, "product"), period = first(search, "period");
  const region = first(search, "region") ?? "";
  const validProduct = (code: string | null | undefined) => code && PUBLIC_FUEL_PRODUCTS.includes(code) ? code : null;
  return {
    area: PUBLIC_FUEL_AREAS.some(([value]) => value === area) ? area as PublicFuelArea : DEFAULT_VIEW.area,
    region: region.length <= MAX_REGION_LENGTH ? region : "",
    product: validProduct(product) ?? validProduct(fallbackProduct) ?? DEFAULT_VIEW.product,
    period: PUBLIC_FUEL_PERIODS.some(([value]) => value === period) ? period as PublicFuelPeriod : DEFAULT_VIEW.period,
  };
}

/** 화면 상태 → URL query(기본값은 생략해 짧게 둔다). */
export function statisticsViewQuery(view: PublicFuelStatisticsView) {
  const search = new URLSearchParams();
  if (view.area !== DEFAULT_VIEW.area) search.set("scope", view.area);
  if (view.region && view.area !== "nationwide") search.set("region", view.region);
  if (view.product !== DEFAULT_VIEW.product) search.set("product", view.product);
  if (view.period !== DEFAULT_VIEW.period) search.set("period", view.period);
  return search.toString();
}

export type PublicFuelMetrics = {
  scope_key: string; label: string; product_code?: string; generated_at: string;
  station_count: number; average_price: number; minimum_price: number; maximum_price: number;
  cheapest_station_count?: number; cheapest_station?: (FuelChartStation & { address?: string | null }) | null;
};
export type PublicFuelStatistics = { scope?: string; generated_at: string | null; update_pending: boolean; items: PublicFuelMetrics[] };
export type PublicFuelTrendPoint = {
  product_code: string; day: string; first_day: string; last_day: string; day_count: number; generated_at: string;
  average_price: number; minimum_price: number | null; maximum_price: number | null; station_count: number;
};
export type PublicFuelTrendBucket = "day" | "week" | "month";
export type PublicFuelTrend = {
  scope?: string; scope_key?: string; label: string | null; bucket: PublicFuelTrendBucket; from_day: string | null; to_day: string | null;
  generated_at: string | null; update_pending?: boolean; points: PublicFuelTrendPoint[];
};

/** 목록(선택지)을 읽는 API scope. 고속도로는 노선별 목록을 읽는다. */
export function listScope(area: PublicFuelArea) {
  return area === "highway" ? "highway" : area;
}
/** 현재 값(카드)을 읽는 API scope. */
export function currentScope(view: Pick<PublicFuelStatisticsView, "area" | "region">) {
  if (view.area === "highway") return !view.region || view.region === ALL_ROUTES ? "highways" : "highway";
  return view.area;
}

export function statisticsPath(scope: string, product: string) {
  return `fuel/statistics?${new URLSearchParams({ scope, product_code: product })}`;
}

/** 공개 통계 세대 시각의 KST 날짜(통계 일자와 같은 기준). */
export function kstDay(value: string | null | undefined) {
  const instant = value ? Date.parse(value) : Number.NaN;
  return Number.isFinite(instant) ? new Date(instant + 9 * 3_600_000).toISOString().slice(0, 10) : null;
}
export function daysBefore(day: string, days: number) {
  return new Date(Date.parse(`${day}T00:00:00Z`) - days * 86_400_000).toISOString().slice(0, 10);
}

/**
 * 장기 추이 요청 경로. 공개 세대 날짜(`to`)까지만 묻는다. 30일·90일·1년은 일 단위,
 * 전체는 `auto`(기록 범위가 유종당 400점 안에 드는 가장 작은 단위: 일→주→월)다.
 */
export function historyPath(scope: string, scopeKey: string, product: string, period: PublicFuelPeriod, to: string) {
  const search = new URLSearchParams({ scope, scope_key: scopeKey, product_code: product, to, bucket: period === "all" ? "auto" : "day" });
  if (period !== "all") search.set("from", daysBefore(to, Number(period) - 1));
  return `fuel/statistics/history?${search}`;
}

const collator = new Intl.Collator("ko");
function parseKey(key: string): string[] {
  try {
    const value: unknown = JSON.parse(key);
    return Array.isArray(value) && value.every(part => typeof part === "string") ? value : [];
  } catch { return []; }
}

export type RegionOption = { key: string; label: string };
export type SidoGroup = { sido: string; label: string; sigungu: RegionOption[] };

/** 시도·고속도로 노선 선택지(이름순). */
export function regionOptions(items: PublicFuelMetrics[]): RegionOption[] {
  return [...new Map(items.map(item => [item.scope_key, { key: item.scope_key, label: item.label }])).values()]
    .sort((a, b) => collator.compare(a.label, b.label));
}

/**
 * 시군구 목록을 시도별로 묶는다. scope_key는 `["시도 정식 이름","시군구"]`, label은 `"시도 약칭 시군구"`다.
 * 시도 이름은 label에서 시군구를 뗀 앞부분(없으면 정식 이름)을 쓴다.
 */
export function sigunguGroups(items: PublicFuelMetrics[]): SidoGroup[] {
  const groups = new Map<string, SidoGroup>();
  for (const item of items) {
    const [sido, sigungu] = parseKey(item.scope_key);
    if (!sido || !sigungu) continue;
    const short = item.label.endsWith(sigungu) ? item.label.slice(0, -sigungu.length).trim() : "";
    const group = groups.get(sido) ?? { sido, label: short || sido, sigungu: [] };
    if (!group.sigungu.some(option => option.key === item.scope_key)) group.sigungu.push({ key: item.scope_key, label: sigungu });
    groups.set(sido, group);
  }
  return [...groups.values()].map(group => ({ ...group, sigungu: group.sigungu.sort((a, b) => collator.compare(a.label, b.label)) }))
    .sort((a, b) => collator.compare(a.label, b.label));
}
export function sidoOfSigungu(key: string) {
  return parseKey(key)[0] ?? null;
}

/** 처음 고를 지역: 서울을 우선하고 없으면 이름순 첫 항목. */
function preferSeoul<T extends { label: string }>(options: T[]) {
  return options.find(option => option.label.startsWith("서울")) ?? options[0];
}

/**
 * 고른 지역 key를 응답에 맞춘다. URL의 key가 이번 응답에 없으면(오래된 링크·유종 변경) 기본 지역으로 바꾼다.
 * 전국·고속도로 전체는 응답의 유일한 범주(`all`)다.
 */
export function resolveRegion(view: Pick<PublicFuelStatisticsView, "area" | "region">, items: PublicFuelMetrics[]): string {
  if (view.area === "nationwide") return items[0]?.scope_key ?? "all";
  if (view.area === "highway") {
    if (!view.region || view.region === ALL_ROUTES) return ALL_ROUTES;
    return items.some(item => item.scope_key === view.region) ? view.region : ALL_ROUTES;
  }
  if (items.some(item => item.scope_key === view.region)) return view.region;
  if (view.area === "sido") return preferSeoul(regionOptions(items))?.key ?? "";
  const groups = sigunguGroups(items);
  const sido = groups.find(group => group.sido === sidoOfSigungu(view.region)) ?? preferSeoul(groups);
  return sido?.sigungu[0]?.key ?? "";
}

export type TrendSummary = {
  first: PublicFuelTrendPoint; last: PublicFuelTrendPoint; change: number; changePercent: number | null;
  lowest: { price: number; point: PublicFuelTrendPoint } | null; highest: { price: number; point: PublicFuelTrendPoint } | null;
  dayCount: number;
};

/** 기간 요약: 처음·마지막 평균과 변화, 기간 최저가·최고가(제공된 값만), 기록 일수. 점이 없으면 null. */
export function trendSummary(points: PublicFuelTrendPoint[]): TrendSummary | null {
  const ordered = points.filter(point => Number.isFinite(point.average_price) && point.average_price > 0)
    .sort((a, b) => a.day.localeCompare(b.day));
  const first = ordered[0], last = ordered.at(-1);
  if (!first || !last) return null;
  let lowest: TrendSummary["lowest"] = null, highest: TrendSummary["highest"] = null;
  for (const point of ordered) {
    if (point.minimum_price != null && Number.isFinite(point.minimum_price) && (!lowest || point.minimum_price < lowest.price)) lowest = { price: point.minimum_price, point };
    if (point.maximum_price != null && Number.isFinite(point.maximum_price) && (!highest || point.maximum_price > highest.price)) highest = { price: point.maximum_price, point };
  }
  const change = Math.round((last.average_price - first.average_price) * 100) / 100;
  return { first, last, change, changePercent: first === last ? null : Math.round(change / first.average_price * 10_000) / 100, lowest, highest,
    dayCount: ordered.reduce((sum, point) => sum + Math.max(1, point.day_count || 1), 0) };
}

/** 통계 세대가 이만큼 오래되면 "갱신 지연"을 알린다(오피넷 하루 3회·도로공사 매시 공개보다 넉넉히). */
export const STALE_STATISTICS_HOURS = 36;
export function statisticsAgeHours(generatedAt: string | null | undefined, now = Date.now()) {
  const instant = generatedAt ? Date.parse(generatedAt) : Number.NaN;
  return Number.isFinite(instant) ? Math.max(0, (now - instant) / 3_600_000) : null;
}

export function publicMapHref(station?: FuelChartStation | null) {
  return station && Number.isFinite(station.longitude) && Number.isFinite(station.latitude)
    && station.longitude! >= 124 && station.longitude! <= 132 && station.latitude! >= 32 && station.latitude! <= 39.5
    ? `/?${new URLSearchParams({ longitude: String(station.longitude), latitude: String(station.latitude) })}` : null;
}

/* 응답 형식 검사. 화면이 쓰는 필드만 확인하고 나머지는 그대로 둔다(새 필드 추가에 깨지지 않는다).
 * 형식이 다르면(배포 중 옛 backend·중간 장비 오류 page) 화면을 깨뜨리지 않고 조회 실패로 보인다. */
const price = z.number();
const station = z.looseObject({ name: z.string(), address: z.string().nullish(), longitude: z.number().nullish(), latitude: z.number().nullish() });
const metricsSchema = z.looseObject({
  scope_key: z.string(), label: z.string(), generated_at: z.string(), station_count: z.number().int().nonnegative(),
  average_price: price, minimum_price: price, maximum_price: price, cheapest_station_count: z.number().int().nullish(),
  cheapest_station: station.nullish(),
});
export const statisticsSchema = z.looseObject({ generated_at: z.string().nullable(), update_pending: z.boolean(), items: z.array(metricsSchema) });
const trendPointSchema = z.looseObject({
  product_code: z.string(), day: z.string(), first_day: z.string(), last_day: z.string(), day_count: z.number().int().nonnegative(),
  generated_at: z.string(), average_price: price, minimum_price: price.nullable(), maximum_price: price.nullable(), station_count: z.number().nonnegative(),
});
export const trendSchema = z.looseObject({
  label: z.string().nullable(), bucket: z.enum(["day", "week", "month"]), from_day: z.string().nullable(), to_day: z.string().nullable(),
  generated_at: z.string().nullable(), points: z.array(trendPointSchema),
});

/** 화면에서 다시 조회를 막는 최대 시간. 서버 Retry-After가 더 길어도 이만큼만 기다리게 한다. */
const MAX_RETRY_WAIT_SECONDS = 60;
const GENERIC_PUBLIC_FUEL_ERROR = "유가 정보를 불러오지 못했습니다. 다시 확인해 주세요.";
export type StatisticsLoadError = { message: string; retryAfter: number };

/** 실패 안내 문구. 혼잡(429·503)·시한(504·브라우저 시한)은 기다렸다 다시 조회하라고 알린다. */
export function describeStatisticsError(reason: unknown): StatisticsLoadError {
  if (reason instanceof DOMException && reason.name === "TimeoutError" || reason instanceof TransportError && reason.status === 504) {
    return { message: "통계 조회가 제시간에 끝나지 않았습니다. 잠시 후 다시 조회해 주세요.", retryAfter: reason instanceof TransportError ? Math.min(reason.retryAfter, MAX_RETRY_WAIT_SECONDS) : 0 };
  }
  if (reason instanceof TransportError) {
    const busy = reason.status === 429 || reason.status === 503;
    const serverMessage = reason.message && reason.message !== GENERIC_PUBLIC_FUEL_ERROR && /[가-힣]/.test(reason.message) ? reason.message : null;
    return {
      message: serverMessage ?? (busy ? "지금 유가 통계 조회가 몰려 있습니다. 잠시 후 다시 조회해 주세요." : "유가 통계를 불러오지 못했습니다. 다시 조회해 주세요."),
      retryAfter: Math.min(Math.max(0, reason.retryAfter), MAX_RETRY_WAIT_SECONDS),
    };
  }
  if (reason instanceof ZodError) return { message: "받은 통계 형식이 올바르지 않습니다. 잠시 후 다시 조회해 주세요.", retryAfter: 0 };
  return { message: "유가 통계를 불러오지 못했습니다. 네트워크 연결을 확인한 뒤 다시 조회해 주세요.", retryAfter: 0 };
}
