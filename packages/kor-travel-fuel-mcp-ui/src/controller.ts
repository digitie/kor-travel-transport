import { queryFromResult, readResult, type FuelResponse, type Query } from "./model";
export type Caller = (name: string, args: Record<string, unknown>) => Promise<{
    structuredContent?: unknown;
    isError?: boolean;
}>;
/** 늦게 끝난 이전 조회는 최신 위치/반경의 결과와 오류를 덮지 않는다. */
export class FuelController {
    private epoch = 0;
    constructor(private call: Caller) { }
    invalidate() { this.epoch++; }
    async search(query: Query, done: (result: FuelResponse) => void, failed: (message: string) => void) {
        const epoch = ++this.epoch;
        try {
            const result = readResult(await this.call("query_fuel_widget", { query }));
            const received = queryFromResult(result);
            if (result.scope !== "radius" || !received || received.latitude !== query.latitude || received.longitude !== query.longitude || received.radius_m !== query.radius_m || received.sort_by !== query.sort_by)
                throw new Error("query_mismatch");
            if (epoch === this.epoch)
                done(result);
        }
        catch {
            if (epoch === this.epoch)
                failed("유가 조회에 실패했습니다. 다시 조회해 주세요.");
        }
    }
}
