import { z } from "zod";
export const PRODUCTS = [
    ["B027", "휘발유"], ["D047", "경유"], ["B034", "고급휘발유"], ["K015", "LPG"], ["C004", "등유"],
] as const;
const code = z.enum(["B027", "D047", "B034", "K015", "C004"]);
const price = z.number().finite().positive().nullable();
const station = z.object({ station_key: z.string().max(200), name: z.string().max(2000), address: z.string().max(2000).nullable().optional(), brand_name: z.string().max(200).nullable().optional(),
    latitude: z.number().finite().min(-90).max(90).nullable().optional(), longitude: z.number().finite().min(-180).max(180).nullable().optional(),
    price: z.number().finite().positive(), distance_m: z.number().finite().nonnegative().nullable().optional() });
const product = z.object({ product_code: code, product_name: z.string().max(100), station_count: z.number().int().nonnegative().nullable(),
    average_price: price, minimum_price: price, cheapest_station_count: z.number().int().nonnegative().nullable(), cheapest_stations: z.array(station).max(20),
    truncated: z.boolean(), ranked_stations: z.array(station).max(20).optional(), ranking_truncated: z.boolean().optional() });
export const responseSchema = z.object({ scope: z.enum(["radius", "nationwide", "sigungu"]), latitude: z.number().finite().min(-90).max(90).nullable().optional(),
    longitude: z.number().finite().min(-180).max(180).nullable().optional(), radius_m: z.number().int().min(1).max(50000).nullable().optional(),
    collection: z.object({ status: z.enum(["ready", "unavailable"]), generated_at: z.iso.datetime({ offset: true }).nullable(), last_success_at: z.iso.datetime({ offset: true }).nullable(),
        stale: z.boolean(), update_pending: z.boolean(), last_attempt_failed: z.boolean(), public_source_stale: z.boolean().optional(), reason: z.string().nullable().optional() }),
    products: z.array(product).max(5), region: z.object({ status: z.enum(["resolved", "unavailable"]), label: z.string().nullable().optional() }).nullable().optional(),
    sort_by: z.enum(["price", "distance"]).optional() });
export const querySchema = z.object({ latitude: z.number().finite().min(-90).max(90), longitude: z.number().finite().min(-180).max(180),
    radius_m: z.number().int().min(1).max(50000).default(5000), product_codes: z.array(code).min(1).max(5).default(PRODUCTS.map(([c]) => c)),
    limit_per_product: z.number().int().min(1).max(20).default(20), sort_by: z.enum(["price", "distance"]).default("price") });
export type Query = z.infer<typeof querySchema>;
export type FuelResponse = z.infer<typeof responseSchema>;
export type Station = z.infer<typeof station>;
export type Product = z.infer<typeof product>;
export const money = (value: number | null | undefined) => value == null ? "미제공" : new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2 }).format(value);
export const distance = (value: number | null | undefined) => value == null ? "거리 미제공" : value < 1000 ? `${Math.round(value)}m` : `${(value / 1000).toFixed(1)}km`;
export function collectedAt(value: string | null) { return value ? new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value)) + " KST" : "수집 시각 미제공"; }
export function rowsFor(result: FuelResponse, code: string) { return result.products.find(p => p.product_code === code); }
export function mapUrl(station: Station) { return station.latitude != null && station.longitude != null ? `https://www.openstreetmap.org/?mlat=${station.latitude}&mlon=${station.longitude}#map=17/${station.latitude}/${station.longitude}` : null; }
/** 호스트/도구 응답도 신뢰 경계다. 원문 오류·HTML을 사용자 화면으로 전달하지 않는다. */
export function readResult(result: {
    structuredContent?: unknown;
    isError?: boolean;
}): FuelResponse {
    if (result.isError)
        throw new Error("유가 조회에 실패했습니다. 잠시 후 다시 확인해 주세요.");
    const raw = result.structuredContent;
    const content = raw && typeof raw === "object" && "mode" in raw && raw.mode === "live" && "result" in raw ? raw.result : raw;
    const parsed = responseSchema.safeParse(content);
    if (!parsed.success)
        throw new Error("유가 응답을 확인하지 못했습니다. 다시 조회해 주세요.");
    return parsed.data;
}
export function queryFromResult(result: FuelResponse): Query | null {
    const parsed = querySchema.safeParse({ latitude: result.latitude, longitude: result.longitude, radius_m: result.radius_m ?? 5000, sort_by: result.sort_by ?? "price" });
    return parsed.success ? parsed.data : null;
}
