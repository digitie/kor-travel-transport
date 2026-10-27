import { act, cleanup, render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import type { MockInstance } from "vitest";

import { useAnalyticsData } from "@/hooks/use-analytics-data";
import { buildApiClient } from "@/lib/api";
import { useDashboard } from "@/lib/dashboard-context";
import type { DashboardAnalyticsResponse, FlightStatusResponse } from "@/lib/types";

vi.mock("@/lib/dashboard-context", () => ({ useDashboard: vi.fn() }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function flights(airport = "GMP", number = "KE1101"): FlightStatusResponse {
  return {
    generated_at: "2026-10-27T04:00:00Z", airport_code: airport, local_date: "2026-10-27",
    source: "fixture", status: "success", error_message: null,
    items: [{ airport_code: airport, flight_number: number, direction: "departure", airline: "대한항공",
      scheduled_at: "2026-10-27T04:00:00Z", estimated_at: null, marker_at: "2026-10-27T04:00:00Z",
      origin_airport: airport, destination_airport: "CJU", status: "출발", line_type: "국내" }],
  };
}

const analytics: DashboardAnalyticsResponse = {
  threshold_events: [],
  threshold_insights: { generated_at: "2026-10-27T04:00:00Z", airport_code: "GMP", parking_lot_id: 1,
    days: 21, interval_minutes: 10, weekday_items: [], history_items: [] },
  weekday_hour_patterns: [],
  holiday_patterns: { generated_at: "2026-10-27T04:00:00Z", airport_code: "GMP", parking_lot_id: 1,
    source: "fixture", status: "success", error_message: null, items: [] },
  time_series: { generated_at: "2026-10-27T04:00:00Z", airport_code: "GMP", parking_lot_id: 1,
    days: 7, interval_minutes: 10, items: [] },
};

function Probe({ enabled = true }: { enabled?: boolean }) {
  const state = useAnalyticsData(6_000, enabled);
  return <output data-testid="state">{JSON.stringify(state)}</output>;
}

function state() {
  return JSON.parse(screen.getByTestId("state").textContent ?? "{}");
}

async function settle() { await act(async () => { await Promise.resolve(); }); }
async function advance(ms: number) { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); }

describe("분석 화면의 항공편 대기·최종 응답", () => {
  let pending: ReturnType<typeof deferred<FlightStatusResponse>>;
  let dashboard: ReturnType<typeof useDashboard>;
  let flightRequest: MockInstance<ReturnType<typeof buildApiClient>["getFlightStatus"]>;
  let analyticsRequest: MockInstance<ReturnType<typeof buildApiClient>["getDashboardAnalytics"]>;

  beforeEach(() => {
    vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-27T04:00:00Z"));
    pending = deferred<FlightStatusResponse>();
    const api = buildApiClient("/api/transport", "");
    flightRequest = vi.spyOn(api, "getFlightStatus").mockReturnValue(pending.promise);
    analyticsRequest = vi.spyOn(api, "getDashboardAnalytics").mockResolvedValue(analytics);
    dashboard = { api, airports: [], selectedAirportCode: "GMP", selectedParkingLotId: 1,
      selectedAirport: null, selectedAirportLots: [], selectedParkingLotName: null, scopeItems: [],
      holidaySummary: null, collectorStatus: null, dataVersion: 0, loading: false, error: null,
      onAirportChange: vi.fn(), onParkingLotChange: vi.fn(), onRefresh: vi.fn() };
    vi.mocked(useDashboard).mockReturnValue(dashboard);
  });

  afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

  test("6초에 주차 분석을 먼저 표시하고 같은 요청의 14.767초 성공을 반영한다", async () => {
    render(<Probe />); await settle(); await advance(6_000);
    expect(state().loading).toBe(false); expect(state().flightStatus.items).toHaveLength(0);
    await advance(8_767);
    await act(async () => pending.resolve(flights()));
    expect(state().flightStatus.status).toBe("success");
    expect(state().flightStatus.items[0].flight_number).toBe("KE1101");
    expect(flightRequest).toHaveBeenCalledTimes(1);
  });

  test("6초는 확정 실패가 아니라 계속 조회 중인 안내다", async () => {
    render(<Probe />); await advance(6_000);
    expect(state().flightStatus.status).toBe("loading");
    expect(state().flightStatus.error_message).toMatch(/계속 조회 중/);
  });

  test("8.981초 성공을 13초 분석 완료 시 옛 대기값으로 덮지 않는다", async () => {
    const delayed = deferred<DashboardAnalyticsResponse>(); analyticsRequest.mockReturnValue(delayed.promise);
    render(<Probe />); await advance(8_981);
    await act(async () => pending.resolve(flights()));
    await advance(4_019); await act(async () => delayed.resolve(analytics));
    expect(state().loading).toBe(false); expect(state().flightStatus.status).toBe("success");
    expect(state().flightStatus.items).toHaveLength(1);
  });

  test("빠른 항공편과 13초 분석은 6초 실패로 버리지 않는다", async () => {
    const delayed = deferred<DashboardAnalyticsResponse>(); analyticsRequest.mockReturnValue(delayed.promise);
    pending.resolve(flights()); render(<Probe />); await advance(13_000);
    await act(async () => delayed.resolve(analytics));
    expect(state().error).toBeNull(); expect(state().loading).toBe(false);
    expect(state().flightStatus.status).toBe("success");
  });

  test("최종 30초에는 요청을 중단하고 그 뒤 성공은 반영하지 않는다", async () => {
    render(<Probe />); await advance(29_999);
    const signal = flightRequest.mock.calls[0]?.[1]; expect(signal?.aborted).toBe(false);
    await advance(1); expect(signal?.aborted).toBe(true);
    expect(state().flightStatus.status).toBe("client_error");
    expect(state().flightStatus.error_message).toMatch(/시간.*초과/);
    await act(async () => pending.resolve(flights()));
    expect(state().flightStatus.status).toBe("client_error"); expect(flightRequest).toHaveBeenCalledTimes(1);
  });

  test("실제 취소 거절이 먼저 발생해도 최종 기한 안내를 유지한다", async () => {
    flightRequest.mockImplementation((_airport, signal) => new Promise((_resolve, reject) => {
      signal?.addEventListener("abort", () => reject(new DOMException("취소", "AbortError")));
    }));
    render(<Probe />); await advance(30_000);
    expect(state().flightStatus.status).toBe("client_error");
    expect(state().flightStatus.error_message).toMatch(/시간.*초과/);
    expect(vi.getTimerCount()).toBe(0); expect(flightRequest).toHaveBeenCalledTimes(1);
  });

  test("서버 거절은 실제 오류로 표시하고 성공 0편과 구별한다", async () => {
    pending.reject(new Error("제공기관 거절")); render(<Probe />); await settle();
    expect(state().flightStatus.status).toBe("client_error");
    expect(state().flightStatus.error_message).toBe("제공기관 거절"); expect(state().error).toBeNull();
  });

  test("유효한 0편 성공을 대기나 오류로 바꾸지 않는다", async () => {
    pending.resolve({ ...flights(), items: [] }); render(<Probe />); await settle();
    expect(state().flightStatus.status).toBe("success"); expect(state().flightStatus.items).toEqual([]);
    expect(state().flightStatus.error_message).toBeNull(); expect(vi.getTimerCount()).toBe(0);
  });

  test("제공기관 오류 응답은 정상 0편으로 바꾸지 않는다", async () => {
    pending.resolve({ ...flights(), status: "upstream_error", error_message: "제공기관 조회 실패", items: [] });
    render(<Probe />); await settle();
    expect(state().flightStatus.status).toBe("upstream_error");
    expect(state().flightStatus.error_message).toBe("제공기관 조회 실패");
  });

  test("분석 자체의 오류를 나중 항공편 성공으로 숨기지 않는다", async () => {
    analyticsRequest.mockRejectedValue(new Error("분석 요청 실패")); render(<Probe />); await settle();
    await act(async () => pending.resolve(flights()));
    expect(state().error).toBe("분석 요청 실패"); expect(state().loading).toBe(false);
  });

  test.each(["airport", "lot", "refresh"])("%s 변경 후 이전 늦은 응답이 새 값을 덮지 않는다", async (change) => {
    const newer = deferred<FlightStatusResponse>(); flightRequest.mockReturnValueOnce(pending.promise).mockReturnValueOnce(newer.promise);
    const view = render(<Probe />); await advance(6_000);
    const oldSignal = flightRequest.mock.calls[0]?.[1];
    dashboard = { ...dashboard, ...(change === "airport" ? { selectedAirportCode: "CJU" }
      : change === "lot" ? { selectedParkingLotId: 2 } : { dataVersion: 1 }) };
    vi.mocked(useDashboard).mockReturnValue(dashboard); view.rerender(<Probe />); await settle();
    expect(oldSignal?.aborted).toBe(true);
    await act(async () => newer.resolve(flights(dashboard.selectedAirportCode, "NEW")));
    await act(async () => pending.resolve(flights("GMP", "OLD")));
    expect(state().flightStatus.items[0].flight_number).toBe("NEW"); expect(flightRequest).toHaveBeenCalledTimes(2);
  });

  test("비활성화는 요청을 취소하고 이전 응답을 반영하지 않는다", async () => {
    const view = render(<Probe />); await advance(6_000); view.rerender(<Probe enabled={false} />);
    expect(flightRequest.mock.calls[0]?.[1]?.aborted).toBe(true);
    await act(async () => pending.resolve(flights()));
    expect(state().flightStatus.status).not.toBe("success"); expect(vi.getTimerCount()).toBe(0);
  });

  test("처음부터 비활성이면 조회하지 않는다", () => {
    render(<Probe enabled={false} />); expect(flightRequest).not.toHaveBeenCalled();
    expect(analyticsRequest).not.toHaveBeenCalled(); expect(vi.getTimerCount()).toBe(0);
  });

  test("unmount는 요청과 두 대기 타이머를 정리한다", async () => {
    const view = render(<Probe />); await settle(); const signal = flightRequest.mock.calls[0]?.[1];
    view.unmount(); expect(signal?.aborted).toBe(true); expect(vi.getTimerCount()).toBe(0);
    await act(async () => pending.resolve(flights())); expect(vi.getTimerCount()).toBe(0);
  });

  test("StrictMode의 폐기된 효과는 취소하고 살아 있는 효과만 갱신한다", async () => {
    const view = render(<StrictMode><Probe /></StrictMode>); await settle();
    expect(flightRequest).toHaveBeenCalledTimes(2);
    expect(flightRequest.mock.calls[0]?.[1]?.aborted).toBe(true);
    expect(flightRequest.mock.calls[1]?.[1]?.aborted).toBe(false);
    await advance(6_000); await act(async () => pending.resolve(flights()));
    expect(state().flightStatus.status).toBe("success"); view.unmount(); expect(vi.getTimerCount()).toBe(0);
  });
});
