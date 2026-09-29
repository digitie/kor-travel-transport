import { afterEach, describe, expect, it, vi } from "vitest";
import { clusterAtScale, dateTime, hasCoordinates, hasFuelPrice, money, seoulDate, serviceTime, transportGet, type Place } from "./journey";
import { getDagsterOverview, runStalled, statusLabel } from "./dagster";

afterEach(() => vi.unstubAllGlobals());
describe("여행 정보 표시 계약", () => {
  it.each([null, 0, -1, NaN, Infinity])("미제공 또는 잘못된 유가 %s는 판매 가격이 아니다", (price) => {
    expect(hasFuelPrice({ product_code: "B034", price, observed_at: "2026-09-29T00:00:00Z" })).toBe(false);
  });
  it("양수 유가만 판매 가격으로 표시한다", () => expect(hasFuelPrice({ product_code: "B034", price: 2000, observed_at: "2026-09-29T00:00:00Z" })).toBe(true));
  it.each(["235960", "23:59:60", "20260927235960"])("잘못된 초 %s는 정상 시각으로 표시하지 않는다", (value) => expect(serviceTime(value)).toBe("시각 확인 필요"));
  it.each([["0900", "09:00"], ["093000", "09:30"], ["202609270930", "09:30"], ["20260927093000", "09:30"], ["9:30", "09:30"], ["24:05", "익일 00:05"], ["29:59", "익일 05:59"], ["30:00", "시각 확인 필요"], ["12:60", "시각 확인 필요"], ["unknown", "시각 확인 필요"], [null, "시각 미제공"]])("시각 %s", (value, expected) => expect(serviceTime(value)).toBe(expected));
  it.each([[0, "0원"], [12000, "12,000원"], ["12,000원", "12,000원"], [null, "요금 미제공"], ["", "요금 미제공"], ["미정", "요금 확인 필요"], [-1, "요금 확인 필요"]])("요금 %s", (value, expected) => expect(money(value)).toBe(expected));
  it("한국 자정/월말/연말 기준을 사용한다", () => {
    expect(seoulDate(0, Date.parse("2026-09-26T15:00:00Z"))).toBe("2026-09-27");
    expect(seoulDate(9, Date.parse("2026-12-28T00:00:00Z"))).toBe("2027-01-06");
    expect(dateTime("bad-date")).toBe("확인되지 않음");
  });
  it("날짜를 포함하는 야간 도착에서 익일을 보존한다", () => {
    expect(serviceTime("202609280130", "202609272330")).toBe("익일 01:30");
    expect(serviceTime("202609290130", "2026-09-27")).toBe("2일 뒤 01:30");
    expect(serviceTime("2405", "2026-09-27")).toBe("익일 00:05");
  });
  it("광역 축척에서는 밀도가 낮아도 묶음을 유지한다", () => expect(clusterAtScale(10.99, 37, 2)).toBe(true));
  it("동네 축척의 드문 장소는 개별 표시한다", () => expect(clusterAtScale(11, 37, 6, 320, 380)).toBe(false));
  it("같은 장소 수라도 작은 화면에서는 묶는다", () => {
    expect(clusterAtScale(12, 37, 15, 320, 380)).toBe(true);
    expect(clusterAtScale(12, 37, 15, 1000, 600)).toBe(false);
  });
  it("최대 확대에서도 과밀한 장소를 한꺼번에 펼치지 않는다", () => expect(clusterAtScale(20, 37, 100, 1000, 600)).toBe(true));
  it.each([NaN, Infinity, -Infinity])("잘못된 축척 %s는 보수적으로 묶는다", (zoom) => expect(clusterAtScale(zoom, 37)).toBe(true));
  it.each([[null, 37, false], [127, null, false], [NaN, 37, false], [127, 37, true]])("미등록 좌표를 지도에 넣지 않는다", (longitude, latitude, expected) => expect(hasCoordinates({ longitude, latitude } as Place)).toBe(expected));
  it.each([[37.424805, 126.423637], [181, 37], [-181, 37], [127, -91], [Infinity, 37], [127, -Infinity]])("범위 밖 좌표 %s/%s를 지도와 카메라에 넣지 않는다", (longitude, latitude) => expect(hasCoordinates({ longitude, latitude } as Place)).toBe(false));
  it.each([[180, 90], [-180, -90], [0, 0]])("유효한 좌표 경계 %s/%s는 유지한다", (longitude, latitude) => expect(hasCoordinates({ longitude, latitude } as Place)).toBe(true));
  it("429 보호 시간을 보존한다", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "제한" }), { status: 429, headers: { "retry-after": "30" } })));
    await expect(transportGet("transport/bus/timetable")).rejects.toMatchObject({ status: 429, retryAfter: 30 });
  });
  it("영문/구조화된 서버 오류는 안내 문구로 바꾼다", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: [{ msg: "invalid" }] }), { status: 422 })));
    await expect(transportGet("transport/providers")).rejects.toThrow("검색 조건을 다시 확인");
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
    expect(runStalled({ ...run, jobName: "kric_timetable_collection_job" }, 3700 * 1000)).toBe(false);
  });
  it("GraphQL HTTP 200 오류를 정상으로 표시하지 않는다", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ errors: [{ message: "failed" }] }))));
    await expect(getDagsterOverview()).rejects.toThrow("Dagster 작업 목록");
  });
});
