import { describe, it, expect } from "vitest";
import { readResult, querySchema, queryFromResult, mapUrl, money, distance } from "./model";
import { FuelController } from "./controller";
export const fixture = { scope: "radius", latitude: 37.5, longitude: 127, radius_m: 5000, sort_by: "price",
    collection: { status: "ready", generated_at: "2026-11-28T00:00:00Z", last_success_at: "2026-11-28T00:00:00Z", stale: false, update_pending: false, last_attempt_failed: false },
    products: [{ product_code: "B027", product_name: "휘발유", station_count: 2, average_price: 1600, minimum_price: 1500, cheapest_station_count: 1, truncated: false,
            cheapest_stations: [{ station_key: "1", name: "<img src=x onerror=alert(1)>", price: 1500, distance_m: 0, latitude: 37.5, longitude: 127 }],
            ranked_stations: [{ station_key: "1", name: "<img src=x onerror=alert(1)>", price: 1500, distance_m: 0, latitude: 37.5, longitude: 127 }], ranking_truncated: false }] };
describe("신뢰 경계와 누락값", () => {
    it("유효 응답과 0m 거리를 보존한다", () => { const data = readResult({ structuredContent: fixture }); expect(data.products[0].ranked_stations?.[0].distance_m).toBe(0); expect(queryFromResult(data)?.latitude).toBe(37.5); });
    it.each([NaN, Infinity, -Infinity, 91])("잘못된 위도 %s를 거부한다", latitude => expect(querySchema.safeParse({ latitude, longitude: 127 }).success).toBe(false));
    it.each([0, -10, 50001])("범위 밖 반경 %s를 거부한다", radius_m => expect(querySchema.safeParse({ latitude: 0, longitude: 0, radius_m }).success).toBe(false));
    it("최대20곳·다섯 유종과 위치0을 검증한다", () => { expect(querySchema.parse({ latitude: 0, longitude: 0 }).product_codes).toHaveLength(5); expect(querySchema.safeParse({ latitude: 0, longitude: 0, limit_per_product: 21 }).success).toBe(false); });
    it("원문 오류를 화면 메시지로 전달하지 않는다", () => { expect(() => readResult({ isError: true, structuredContent: { secret: "not-a-user-message" } })).toThrow("유가 조회에 실패"); expect(() => readResult({ structuredContent: {} })).toThrow("응답을 확인"); });
    it("양수가 아닌 가격을 거부하고 null을 미제공으로 남긴다", () => { expect(() => readResult({ structuredContent: { ...fixture, products: [{ ...fixture.products[0], average_price: 0 }] } })).toThrow(); expect(money(null)).toBe("미제공"); expect(distance(null)).toBe("거리 미제공"); expect(distance(0)).toBe("0m"); });
    it("임의 URL을 받지 않고 검증한 좌표로 지도 주소를 만든다", () => { expect(mapUrl({ station_key: "1", name: "x", price: 1, latitude: 0, longitude: 0 })).toContain("mlat=0&mlon=0"); expect(mapUrl({ station_key: "1", name: "x", price: 1 })).toBeNull(); });
});
describe("조회 수명", () => {
    it("늦게 도착한 이전 반경 응답을 버린다", async () => { const pending: ((v: {
        structuredContent: unknown;
    }) => void)[] = []; const controller = new FuelController(() => new Promise(resolve => pending.push(resolve))); const seen: number[] = []; const query = querySchema.parse({ latitude: 37.5, longitude: 127 }); const old = controller.search(query, r => seen.push(r.radius_m!), () => { }); const latest = controller.search({ ...query, radius_m: 10000 }, r => seen.push(r.radius_m!), () => { }); pending[1]({ structuredContent: { ...fixture, radius_m: 10000 } }); await latest; pending[0]({ structuredContent: fixture }); await old; expect(seen).toEqual([10000]); });
    it("닫힘·새 호스트 입력 뒤에는 이전 오류도 전파하지 않는다", async () => { let reject!: (e: Error) => void; const c = new FuelController(() => new Promise((_, r) => { reject = r; })); const messages: string[] = []; const task = c.search(querySchema.parse({ latitude: 37.5, longitude: 127 }), () => { }, m => messages.push(m)); c.invalidate(); reject(new Error("private")); await task; expect(messages).toEqual([]); });
});
it("응답이 다른 위치·반경이면 현재 위치 결과로 표시하지 않는다", async () => { const q = querySchema.parse({ latitude: 37.5, longitude: 127 }); let accepted = false; const failures: string[] = []; const c = new FuelController(async () => ({ structuredContent: { ...fixture, latitude: 36 } })); await c.search(q, () => { accepted = true; }, m => failures.push(m)); expect(accepted).toBe(false); expect(failures).toHaveLength(1); });
it("기존 중계의 live 봉투와 native 결과를 같은 검증 경계에서 읽는다", () => { expect(readResult({ structuredContent: { mode: "live", result: fixture } }).scope).toBe("radius"); expect(() => readResult({ structuredContent: { mode: "live", result: { private: "hidden" } } })).toThrow("응답을 확인"); });
