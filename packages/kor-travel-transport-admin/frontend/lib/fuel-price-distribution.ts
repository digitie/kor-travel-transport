import { z } from "zod";

/**
 * 공개 유가 화면 전용: `GET /v1/transport/fuel/price-distribution` 계약(docs/openapi.json
 * `FuelPriceDistributionResponse`)을 그대로 옮긴 zod 스키마다. 저장소에는 OpenAPI → TS 생성기가 없어
 * 다른 공개 유가 응답(lib/public-fuel.ts)처럼 런타임 검증 스키마를 타입의 정본으로 둔다.
 */
const scopeSummary = z.object({
  scope: z.string(), label: z.string(), station_count: z.number().int().nonnegative(),
  minimum_price: z.number(), average_price: z.number(), maximum_price: z.number(),
});

export const fuelPriceDistributionSchema = z.object({
  product_code: z.string(),
  generated_at: z.string().nullable(),
  update_pending: z.boolean(),
  minimum_sample: z.number().int().positive(),
  sido_value: z.string(),
  sigungu_value: z.string(),
  sido_name: z.string().nullable(),
  sigungu_name: z.string().nullable(),
  grade_rule: z.array(z.object({ grade: z.string(), label: z.string(), percentile_below: z.number().nullable() })),
  filters_applied: z.array(z.string()).default([]),
  sigungu: scopeSummary.extend({
    sufficient: z.boolean(), bin_width: z.number(),
    histogram: z.array(z.object({ start: z.number(), end: z.number(), count: z.number().int().nonnegative() })),
    quantiles: z.array(z.object({ percent: z.number(), price: z.number() })),
  }).nullable(),
  sido: scopeSummary.nullable(),
  nationwide: scopeSummary.nullable(),
  station: z.object({
    station_id: z.number().int(), name: z.string(), price: z.number().nullable(), sells_product: z.boolean(),
    products: z.array(z.string()),
    comparisons: z.array(scopeSummary.extend({
      price: z.number(), difference: z.number(), percentile: z.number(),
      grade: z.string().nullable(), grade_label: z.string().nullable(), sufficient: z.boolean(),
    })),
  }).nullable(),
});

export type FuelPriceDistribution = z.infer<typeof fuelPriceDistributionSchema>;
export type FuelSigunguDistribution = NonNullable<FuelPriceDistribution["sigungu"]>;
export type FuelPriceScope = NonNullable<FuelPriceDistribution["nationwide"]>;
export type FuelPriceComparison = NonNullable<FuelPriceDistribution["station"]>["comparisons"][number];

export type FuelViewportSigungu = {
  sido_value: string; sido_name: string; sigungu_value: string; sigungu_name: string; station_count: number;
};

export type FuelDistributionTarget =
  | { kind: "region"; sido_value: string; sigungu_value: string; label: string }
  | { kind: "station"; station_id: number };

type Loader = <T>(path: string, signal?: AbortSignal) => Promise<T>;

export function fuelDistributionPath(target: FuelDistributionTarget, productCode: string, filterQuery = "") {
  const search = new URLSearchParams({ product_code: productCode });
  // 공개 화면 필터(셀프·상표 등)를 시군구·시도·전국에 같이 적용한다. 화면 최저가 상한은 서버가 분포에서 뺀다.
  for (const [key, value] of new URLSearchParams(filterQuery)) search.set(key, value);
  if (target.kind === "station") search.set("station_id", String(target.station_id));
  else { search.set("sido_value", target.sido_value); search.set("sigungu_value", target.sigungu_value); }
  return `transport/fuel/price-distribution?${search}`;
}

export async function loadFuelPriceDistribution(load: Loader, target: FuelDistributionTarget, productCode: string, signal?: AbortSignal, filterQuery = "") {
  return fuelPriceDistributionSchema.parse(await load<unknown>(fuelDistributionPath(target, productCode, filterQuery), signal));
}

export const won = (value: number) => `${Math.round(value).toLocaleString("ko-KR")}원`;
export const signedWon = (value: number) => {
  const rounded = Math.round(value);
  return rounded === 0 ? "평균과 같음" : `${rounded > 0 ? "+" : "−"}${Math.abs(rounded).toLocaleString("ko-KR")}원`;
};

/** 시군구 칩 이름: 같은 이름의 시군구(예: 중구)가 여러 시도에 보이면 시도를 붙인다. */
export function sigunguChipLabels(items: FuelViewportSigungu[]) {
  const counts = new Map<string, number>();
  for (const item of items) counts.set(item.sigungu_name, (counts.get(item.sigungu_name) ?? 0) + 1);
  return items.map(item => (counts.get(item.sigungu_name) ?? 0) > 1 ? `${item.sido_name} ${item.sigungu_name}` : item.sigungu_name);
}

/** 등급 색: 싼 쪽(A)은 brand, 중간(B)은 success, 비싼 쪽(C·D)은 warning/danger 토큰. */
export function gradeTone(grade: string | null) {
  if (!grade) return "none";
  if (grade.startsWith("A")) return "cheap";
  if (grade.startsWith("B")) return "fair";
  if (grade.startsWith("C")) return "pricey";
  return "expensive";
}

/** 막대 값: 개수 또는 백분율(소수 1자리). */
export function histogramValues(distribution: FuelSigunguDistribution, percent: boolean) {
  return distribution.histogram.map(bin => percent
    ? Math.round(bin.count / Math.max(1, distribution.station_count) * 1000) / 10 : bin.count);
}

export function binLabel(start: number) {
  return `${Math.round(start).toLocaleString("ko-KR")}원~`;
}

/** 왼쪽 가격축 범위: 시군구 분포(+전국 비교 시 전국 최저·평균·최고, 주유소 가격)를 모두 담는다. */
export function priceAxisRange(distribution: FuelSigunguDistribution, nationwide: FuelPriceScope | null, compare: boolean, pinned?: number | null) {
  const values = [distribution.minimum_price, distribution.maximum_price,
    ...(compare && nationwide ? [nationwide.minimum_price, nationwide.average_price, nationwide.maximum_price] : []),
    ...(pinned != null ? [pinned] : [])];
  const low = Math.min(...values), high = Math.max(...values);
  const span = Math.max(high - low, 20);
  // 눈금 4칸 안팎: 1·2·2.5·5×10^k원 간격, 최소·최대도 그 간격의 배수라 축 글자가 겹치지 않는다.
  const raw = span * 1.1 / 4;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const interval = Math.max(5, ([1, 2, 2.5, 5, 10].find(factor => factor * magnitude >= raw) ?? 10) * magnitude);
  return { min: Math.floor((low - span * .05) / interval) * interval, max: Math.ceil((high + span * .05) / interval) * interval, interval };
}

/** 주유소 가격이 정렬 곡선에서 놓이는 가로 위치(%): 곡선 위 같은 가격 지점에 선형 보간한다. */
export function pinnedPercent(distribution: FuelSigunguDistribution, price: number) {
  const points = distribution.quantiles;
  if (!points.length) return 0;
  if (price <= points[0].price) return points[0].percent;
  for (let index = 1; index < points.length; index++) {
    const left = points[index - 1], right = points[index];
    if (price <= right.price) {
      return right.price === left.price ? left.percent
        : left.percent + (right.percent - left.percent) * (price - left.price) / (right.price - left.price);
    }
  }
  return points.at(-1)!.percent;
}

/** 화면 읽기용 차트 요약 한 문장. */
export function distributionSummary(distribution: FuelSigunguDistribution, productLabel: string, percent: boolean) {
  const peak = distribution.histogram.reduce((best, bin) => bin.count > best.count ? bin : best, distribution.histogram[0]);
  const share = (count: number) => percent ? `${Math.round(count / distribution.station_count * 1000) / 10}%` : `${count}개`;
  return `${distribution.label} ${distribution.station_count}개 주유소의 ${productLabel} 가격은 최저 ${won(distribution.minimum_price)}, 평균 ${won(distribution.average_price)}, 최고 ${won(distribution.maximum_price)}입니다.`
    + (peak ? ` 가장 많은 가격 구간은 ${binLabel(peak.start)} ${won(peak.end)} 미만으로 ${share(peak.count)}입니다.` : "");
}

const stampFormat = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul", year: "numeric", month: "long", day: "numeric", weekday: "long", hour: "numeric",
});
const stampMinuteFormat = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul", year: "numeric", month: "long", day: "numeric", weekday: "long", hour: "numeric", minute: "numeric",
});
/** 통계 세대 시각(KST). 정각이면 "오전 7시", 아니면 "오전 7시 50분"까지 적는다. */
export function distributionTimestamp(value: string | null) {
  if (!value) return null;
  const instant = new Date(value);
  if (!Number.isFinite(instant.getTime())) return null;
  return `${(instant.getUTCMinutes() ? stampMinuteFormat : stampFormat).format(instant)} 기준`;
}
