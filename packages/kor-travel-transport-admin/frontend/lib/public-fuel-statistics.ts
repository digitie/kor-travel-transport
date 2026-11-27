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
/** 한국도로공사 휴게소 유가가 주는 유종(휘발유·경유·LPG). 고급유·등유는 고속도로 범위에서 고를 수 없다. */
export const HIGHWAY_PRODUCTS = ["B027", "D047", "K015"];
/** 고속도로 노선 선택의 "전체 노선". */
export const ALL_ROUTES = "all";
const MAX_REGION_LENGTH = 512;

export const formatPrice = (value: number) => value.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
/**
 * 지도의 통계 단추가 붙이는 query(`from=map`). 이 주소로 열린 화면의 "유가 지도"는 새 지도를 쌓지 않고 뒤로 가 지도 화면(위치·선택)을
 * 그대로 돌려준다. 화면은 첫 렌더에 읽고 주소에서 지운다 — 새로고침·다른 경로로 다시 연 화면은 지도에서 온 것이 아니다.
 */
export const FROM_MAP_PARAM = "from";

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

/**
 * 범위에 없는 유종을 맞춘다. 고속도로 휴게소에는 고급유·등유가 없어 휘발유로 바꾸고, 바꾼 유종을 돌려준다(화면이 알린다).
 */
export function fitProductToArea(view: PublicFuelStatisticsView): { view: PublicFuelStatisticsView; replaced: string | null } {
  if (view.area !== "highway" || HIGHWAY_PRODUCTS.includes(view.product)) return { view, replaced: null };
  return { view: { ...view, product: "B027" }, replaced: view.product };
}

/**
 * 화면 상태 → URL query(기본값은 생략해 짧게 둔다). keepProduct면 기본 유종(휘발유)도 남긴다 — 사용자가 고른 휘발유가 새로고침·
 * 앞으로 가기 뒤에도 "고른 유종"으로 남아 지도 링크에 실린다.
 */
export function statisticsViewQuery(view: PublicFuelStatisticsView, { keepProduct = false }: { keepProduct?: boolean } = {}) {
  const search = new URLSearchParams();
  if (view.area !== DEFAULT_VIEW.area) search.set("scope", view.area);
  if (view.region && view.region !== ALL_ROUTES && view.area !== "nationwide") search.set("region", view.region);
  if (keepProduct || view.product !== DEFAULT_VIEW.product) search.set("product", view.product);
  if (view.period !== DEFAULT_VIEW.period) search.set("period", view.period);
  return search.toString();
}

export type PublicFuelMetrics = {
  scope_key: string; label: string; product_code?: string; generated_at: string;
  station_count: number; average_price: number; minimum_price: number; maximum_price: number;
  cheapest_station_count?: number | null; cheapest_station?: (FuelChartStation & { address?: string | null }) | null;
  /** 가격순 최대 10곳. 응답의 선택 범주(history_scope_key)에만 채워진다. */
  cheapest_stations?: (FuelChartStation & { address?: string | null; station_key: string; price: number })[] | null;
};
export type PublicFuelStatistics = { scope?: string; generated_at: string | null; update_pending: boolean; history_scope_key?: string | null; items: PublicFuelMetrics[] };
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
/** 현재 값(카드)을 읽는 API scope. `region`은 응답에 맞춘 지역(resolveRegion)이다. */
export function currentScope(view: Pick<PublicFuelStatisticsView, "area" | "region">) {
  if (view.area === "highway") return !view.region || view.region === ALL_ROUTES ? "highways" : "highway";
  return view.area;
}

/** 현재 지표·선택지. 30일 이력은 장기 추이 API로 따로 읽으므로 받지 않는다(옛 backend는 이 query를 무시한다). */
export function statisticsPath(scope: string, product: string) {
  return `fuel/statistics?${new URLSearchParams({ scope, product_code: product, include_history: "false" })}`;
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

/** 원천이 노선을 주지 않은 휴게소 묶음의 이름. 화면에는 풀어 쓴 이름으로 보이고 목록 맨 뒤에 둔다. */
const UNKNOWN_ROUTE_LABEL = "노선 미제공";
const UNKNOWN_ROUTE_DISPLAY = "노선 정보가 없는 휴게소";
export function displayRegionLabel(label: string) {
  return label === UNKNOWN_ROUTE_LABEL ? UNKNOWN_ROUTE_DISPLAY : label;
}
/** 시도·고속도로 노선 선택지(이름순, "노선 미제공"은 맨 뒤). */
export function regionOptions(items: PublicFuelMetrics[]): RegionOption[] {
  return [...new Map(items.map(item => [item.scope_key, {
    key: item.scope_key, label: displayRegionLabel(item.label),
  }])).values()].sort((a, b) => Number(a.label === UNKNOWN_ROUTE_DISPLAY) - Number(b.label === UNKNOWN_ROUTE_DISPLAY) || collator.compare(a.label, b.label));
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

/**
 * 평균에서 너무 먼 최저·최고(원천 입력 오류로 보이는 값). 운영 고속도로 자료에 평균 1,830원인 날 최저 184원·1,037원 같은 값이 있다.
 * 2026-11-27 운영 공개 통계(전국·시군구 5유종, 고속도로 전체·노선·방향)의 실제 범위는 최저/평균 0.83 이상, 최고/평균 1.38 이하였다.
 * 그보다 넉넉히 평균의 70% 미만 최저, 160% 초과 최고만 뺀다.
 */
export const IMPLAUSIBLE_MINIMUM_RATIO = 0.7;
export const IMPLAUSIBLE_MAXIMUM_RATIO = 1.6;
export function isImplausibleMinimum(minimum: number | null | undefined, average: number) {
  return minimum != null && Number.isFinite(minimum) && average > 0 && minimum < average * IMPLAUSIBLE_MINIMUM_RATIO;
}
export function isImplausibleMaximum(maximum: number | null | undefined, average: number) {
  return maximum != null && Number.isFinite(maximum) && average > 0 && maximum > average * IMPLAUSIBLE_MAXIMUM_RATIO;
}
/** 차트·요약용 점: 믿기 어려운 최저·최고를 null로 둔다(표에는 원래 값을 그대로 보인다). */
export function plausiblePoints(points: PublicFuelTrendPoint[]) {
  let excluded = 0;
  const cleaned = points.map(point => {
    const minimum = isImplausibleMinimum(point.minimum_price, point.average_price) ? null : point.minimum_price;
    const maximum = isImplausibleMaximum(point.maximum_price, point.average_price) ? null : point.maximum_price;
    excluded += Number(minimum !== point.minimum_price) + Number(maximum !== point.maximum_price);
    return minimum === point.minimum_price && maximum === point.maximum_price ? point : { ...point, minimum_price: minimum, maximum_price: maximum };
  });
  return { points: cleaned, excluded };
}

export type TrendSummary = {
  first: PublicFuelTrendPoint; last: PublicFuelTrendPoint; change: number; changePercent: number | null;
  lowest: { price: number; point: PublicFuelTrendPoint } | null; highest: { price: number; point: PublicFuelTrendPoint } | null;
  dayCount: number;
};

/** 기간 요약: 처음·마지막 평균과 변화, 기간 최저가·최고가(제공된 값만, 믿기 어려운 값 제외), 기록 일수. 점이 없으면 null. */
export function trendSummary(points: PublicFuelTrendPoint[]): TrendSummary | null {
  const ordered = plausiblePoints(points.filter(point => Number.isFinite(point.average_price) && point.average_price > 0)).points
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

/**
 * 요청한 지역이 이번 응답에 없어 다른 지역을 보이는지. 이름은 앞서 받은 응답에서 찾은 표시 이름만 쓴다(`knownLabel`) —
 * URL의 글자를 그대로 안내에 넣지 않는다. 이름을 모르면(잘못된·오래된 링크) `name: null`이다. 그대로 보이면 null.
 */
export function regionSubstitution(view: Pick<PublicFuelStatisticsView, "area" | "region">, resolved: string | null, knownLabel?: string | null) {
  if (!resolved || !view.region || view.region === ALL_ROUTES || view.area === "nationwide" || view.region === resolved) return null;
  return { name: knownLabel ? displayRegionLabel(knownLabel) : null };
}

/** 통계 세대가 이만큼 오래되면 "갱신 지연"을 알린다(오피넷 하루 3회·도로공사 매시 공개보다 넉넉히). */
export const STALE_STATISTICS_HOURS = 36;
export function statisticsAgeHours(generatedAt: string | null | undefined, now = Date.now()) {
  const instant = generatedAt ? Date.parse(generatedAt) : Number.NaN;
  return Number.isFinite(instant) ? Math.max(0, (now - instant) / 3_600_000) : null;
}

/**
 * 공개 지도 주소의 유종(`product`, 통계 화면과 같은 이름·코드). 통계 화면에서 지도로 가는 링크가 붙여, 지도는 이 유종 하나로 열린다.
 * 이 브라우저에 저장한 유종 선택은 바꾸지 않는다 — 지도에서 유종을 직접 고르면 그때 저장하고 주소에서 이 값을 지운다.
 */
export const MAP_PRODUCT_PARAM = "product";
export function mapProductFromSearch(search: Pick<URLSearchParams, "get"> | null | undefined): string | null {
  const code = search?.get(MAP_PRODUCT_PARAM) ?? null;
  return code && PUBLIC_FUEL_PRODUCTS.includes(code) ? code : null;
}
function withMapProduct(search: URLSearchParams, product?: string | null) {
  if (product && PUBLIC_FUEL_PRODUCTS.includes(product)) search.set(MAP_PRODUCT_PARAM, product);
  return search;
}

/** 통계 화면에서 지도를 새로 여는 주소(지도에서 오지 않았을 때의 "유가 지도"). 지금 보는 유종으로 연다. */
export function publicMapHomeHref(product?: string | null) {
  const query = withMapProduct(new URLSearchParams(), product).toString();
  return query ? `/?${query}` : "/";
}

export function publicMapHref(station?: FuelChartStation | null, product?: string | null) {
  return station && Number.isFinite(station.longitude) && Number.isFinite(station.latitude)
    && station.longitude! >= 124 && station.longitude! <= 132 && station.latitude! >= 32 && station.latitude! <= 39.5
    ? `/?${withMapProduct(new URLSearchParams({ longitude: String(station.longitude), latitude: String(station.latitude) }), product)}` : null;
}

/* 응답 형식 검사. 화면이 쓰는 필드만 확인하고 나머지는 그대로 둔다(새 필드 추가에 깨지지 않는다).
 * 형식이 다르면(배포 중 옛 backend·중간 장비 오류 page) 화면을 깨뜨리지 않고 조회 실패로 보인다. */
const price = z.number();
const station = z.looseObject({ name: z.string(), address: z.string().nullish(), longitude: z.number().nullish(), latitude: z.number().nullish() });
const metricsSchema = z.looseObject({
  scope_key: z.string(), label: z.string(), generated_at: z.string(), station_count: z.number().int().nonnegative(),
  average_price: price, minimum_price: price, maximum_price: price, cheapest_station_count: z.number().int().nullish(),
  cheapest_station: station.nullish(),
  cheapest_stations: z.array(station.extend({ station_key: z.string(), price })).nullish(),
});
export const statisticsSchema = z.looseObject({
  generated_at: z.string().nullable(), update_pending: z.boolean(), history_scope_key: z.string().nullish(), items: z.array(metricsSchema),
});
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
/** Retry-After 없이 온 혼잡·연결 실패에도 이만큼은 다시 조회를 막는다(연타가 혼잡한 gateway를 더 누르지 않게). */
const MIN_BUSY_WAIT_SECONDS = 5;
export type StatisticsLoadError = { message: string; retryAfter: number };
/** 서버 본문에 한국어 안내가 없을 때 읽기 함수가 쓰는 일반 문구(공개 지도 reader와 같다). 화면에서는 상태별 문구로 바꾼다. */
export const GENERIC_FUEL_ERROR = "유가 정보를 불러오지 못했습니다. 다시 확인해 주세요.";
const BUSY_STATUSES = new Set([429, 503]);

/**
 * 실패 안내 문구. 서버의 한국어 안내는 혼잡·시한(429·503·504)에만 그대로 쓴다 — 그 밖(422 등)의 안내는 개발자용이라 일반 문구로 바꾼다.
 * 502는 BFF가 upstream에 닿지 못했거나 30초 상한에 걸린 경우다(느린 조회일 수 있다).
 */
export function describeStatisticsError(reason: unknown): StatisticsLoadError {
  const wait = (seconds: number, floor = 0) => Math.min(Math.max(floor, seconds), MAX_RETRY_WAIT_SECONDS);
  if (reason instanceof DOMException && reason.name === "TimeoutError") {
    return { message: "통계 조회가 제시간에 끝나지 않았습니다. 잠시 후 다시 조회해 주세요.", retryAfter: MIN_BUSY_WAIT_SECONDS };
  }
  // 200인데 JSON이 아닌 본문(중간 장비의 HTML 등)도 형식 오류다.
  if (reason instanceof ZodError || reason instanceof SyntaxError) return { message: "받은 통계 형식이 올바르지 않습니다. 잠시 후 다시 조회해 주세요.", retryAfter: 0 };
  if (!(reason instanceof TransportError)) return { message: "유가 통계를 불러오지 못했습니다. 네트워크 연결을 확인한 뒤 다시 조회해 주세요.", retryAfter: 0 };
  const korean = reason.message !== GENERIC_FUEL_ERROR && /[가-힣]/.test(reason.message) ? reason.message : null;
  if (BUSY_STATUSES.has(reason.status)) {
    return { message: korean ?? "지금 유가 통계 조회가 몰려 있습니다. 잠시 후 다시 조회해 주세요.", retryAfter: wait(reason.retryAfter, MIN_BUSY_WAIT_SECONDS) };
  }
  if (reason.status === 504) {
    return { message: korean ?? "통계 조회가 제시간에 끝나지 않았습니다. 잠시 후 다시 조회해 주세요.", retryAfter: wait(reason.retryAfter, MIN_BUSY_WAIT_SECONDS) };
  }
  if (reason.status === 502) {
    return { message: "유가 서버 응답이 늦거나 연결되지 않았습니다. 잠시 후 다시 조회해 주세요.", retryAfter: wait(reason.retryAfter, MIN_BUSY_WAIT_SECONDS) };
  }
  return { message: "유가 통계를 불러오지 못했습니다. 다시 조회해 주세요.", retryAfter: wait(reason.retryAfter) };
}

/** 자동 재조회 상한(초). 이보다 긴 Retry-After는 사용자가 직접 다시 조회한다. */
const AUTO_RETRY_MAX_SECONDS = 5;
/**
 * 혼잡(429·503) 한 번 자동 재조회 대기(ms). Retry-After를 지키고 그만큼 흩뜨린다. Retry-After가 없으면 3~6초 —
 * 장소 지도의 1초보다 길게 두어, 동시 상한에 걸린 gateway에 여러 사용자가 곧바로 다시 몰리지 않게 한다. 504·그 밖은 null.
 */
export function statisticsRetryDelay(reason: unknown, random: () => number = Math.random): number | null {
  if (!(reason instanceof TransportError) || !BUSY_STATUSES.has(reason.status) || reason.retryAfter > AUTO_RETRY_MAX_SECONDS) return null;
  const base = reason.retryAfter > 0 ? reason.retryAfter * 1000 : 3000;
  return base + random() * base;
}
