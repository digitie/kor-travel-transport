import { afterEach, describe, expect, it, vi } from "vitest";
import { clusterAtScale, dateTime, hasCoordinates, money, seoulDate, serviceTime, transportGet, type Place } from "./journey";
import { getDagsterOverview, runStalled, statusLabel } from "./dagster";

afterEach(() => vi.unstubAllGlobals());
describe("여행 정보 표시 계약", () => {
  it.each([["0900", "09:00"], ["093000", "09:30"], ["202609270930", "09:30"], ["20260927093000", "09:30"], ["9:30", "09:30"], ["24:05", "익일 00:05"], ["29:59", "익일 05:59"], ["30:00", "시각 확인 필요"], ["12:60", "시각 확인 필요"], ["unknown", "시각 확인 필요"], [null, "시각 미제공"]])("시각 %s", (value, expected) => expect(serviceTime(value)).toBe(expected));
  it.each([[0, "0원"], [12000, "12,000원"], ["12,000원", "12,000원"], [null, "요금 미제공"], ["", "요금 미제공"], ["미정", "요금 확인 필요"], [-1, "요금 확인 필요"]])("요금 %s", (value, expected) => expect(money(value)).toBe(expected));
  it("한국 자정/월말/연말 기준을 사용한다", () => {
    expect(seoulDate(0, Date.parse("2026-09-26T15:00:00Z"))).toBe("2026-09-27");
    expect(seoulDate(9, Date.parse("2026-12-28T00:00:00Z"))).toBe("2027-01-06");
    expect(dateTime("bad-date")).toBe("확인되지 않음");
  });
  it("30km 축척 이하에서 클러스터링을 해제한다", () => {
    const threshold = Math.log2(100 * 40075.016686 * Math.cos(37 * Math.PI / 180) / (512 * 30));
    expect(clusterAtScale(threshold - 0.01, 37)).toBe(true);
    expect(clusterAtScale(threshold + 0.01, 37)).toBe(false);
    expect(clusterAtScale(11, 37)).toBe(false);
  });
  it.each([[null, 37, false], [127, null, false], [NaN, 37, false], [127, 37, true]])("미등록 좌표를 지도에 넣지 않는다", (longitude, latitude, expected) => expect(hasCoordinates({ longitude, latitude } as Place)).toBe(expected));
  it("429 보호 시간을 보존한다", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "제한" }), { status: 429, headers: { "retry-after": "30" } })));
    await expect(transportGet("transport/bus/timetable")).rejects.toMatchObject({ status: 429, retryAfter: 30 });
  });
  it("조회 취소 signal을 전달한다", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response("{}")); vi.stubGlobal("fetch", fetcher);
    const controller = new AbortController(); await transportGet("transport/providers", controller.signal);
    expect(fetcher).toHaveBeenCalledWith("/api/transport/transport/providers", { cache: "no-store", signal: controller.signal });
  });
});
describe("수집 상태 표시", () => {
  it("공동 작업 성공을 개별 provider 성공과 구별한다", () => expect(statusLabel("shared_job_success")).toBe("공동 작업 성공"));
  it("배편 장시간 정상 실행을 weather의 10분 기준으로 오판하지 않는다", () => {
    const run = { runId: "1", status: "STARTED", jobName: "ferry_timetable_collection_job", startTime: 100, endTime: null };
    expect(runStalled(run, 3700 * 1000)).toBe(false);
    expect(runStalled(run, 15000 * 1000)).toBe(true);
  });
  it("GraphQL HTTP 200 오류를 정상으로 표시하지 않는다", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ errors: [{ message: "failed" }] }))));
    await expect(getDagsterOverview()).rejects.toThrow("Dagster 작업 목록");
  });
});
