vi.mock("@/components/parking-availability-charts", () => ({ ParkingAvailabilityCharts: () => null }));
vi.mock("@/components/evilcharts/parking-line-canvas", () => ({ ParkingLineCanvas: () => <div data-testid="parking-line-canvas-probe" /> }));
vi.mock("@/components/parking-pattern-heatmap", async (original) => ({ ...await original<typeof import("@/components/parking-pattern-heatmap")>(), ParkingPatternHeatmap: () => null }));
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AnalyticsView } from "@/components/pages/analytics-view";
import { CurrentStatusView } from "@/components/pages/current-status-view";
import { DashboardProvider, useDashboard } from "@/lib/dashboard-context";
import { DASHBOARD_SELECTION_COOKIE_KEY } from "@/lib/dashboard-preferences";
import type {
  Airport,
  CollectorStatusResponse,
  DashboardAnalyticsResponse,
  HolidayPatternResponse,
  HolidaySummaryResponse,
  ParkingCurrentResponse,
  ParkingTimeSeriesResponse,
  ThresholdInsightsResponse,
} from "@/lib/types";

const airports: Airport[] = [
  {
    code: "GMP",
    name_ko: "Gimpo",
    name_en: "Gimpo",
    source: "kac",
    parking_lots: [{ id: 1, source_lot_id: "gmp-1", legacy_source_lot_id: null, name: "Domestic P1", terminal: null, category: null, is_active: true }],
  },
];

const currentPayload: ParkingCurrentResponse = {
  generated_at: "2026-04-26T00:00:00.000Z",
  items: [
    {
      airport_code: "GMP",
      airport_name: "Gimpo",
      parking_lot_id: 1,
      parking_lot_name: "Domestic P1",
      terminal: null,
      category: null,
      observed_at: "2026-04-26T00:00:00.000Z",
      collected_at: "2026-04-26T00:10:00.000Z",
      occupied_spaces: 100,
      total_spaces: 200,
      available_spaces: 100,
      congestion_label: null,
      congestion_ratio: 50,
      status_level: "stable",
    },
  ],
};

const holidaySummaryPayload: HolidaySummaryResponse = {
  generated_at: "2026-05-09T00:00:00.000Z",
  start_date: "2026-04-27",
  end_date: "2026-05-17",
  source: "sample_holiday_info",
  status: "sample",
  error_message: null,
  sentence: "5/5 (화) 어린이날 입니다.",
  items: [],
};

function buildCollectorStatus(overrides: Partial<CollectorStatusResponse> = {}): CollectorStatusResponse {
  return {
    scheduler_enabled: true,
    collect_interval_seconds: 300,
    manual_collect_enabled: false,
    manual_collect_min_interval_seconds: 300,
    client_mode: "live",
    enabled_sources: ["kac_parking"],
    data_go_kr_service_key_configured: true,
    supported_airport_codes: ["GMP"],
    latest_snapshot_observed_at: "2026-04-26T00:00:00.000Z",
    latest_snapshot_collected_at: "2026-04-26T00:10:00.000Z",
    earliest_snapshot_observed_at: "2026-04-19T00:00:00.000Z",
    manual_collect_available_at: null,
    manual_collect_blocked: false,
    upstream_rate_limited: false,
    upstream_rate_limited_until: null,
    last_run: null,
    recent_runs: [],
    ...overrides,
    effective_collect_interval_seconds: overrides.effective_collect_interval_seconds ?? 180,
    scheduler_safety_buffer_seconds: overrides.scheduler_safety_buffer_seconds ?? 120,
  };
}

const holidayPatternPayload: HolidayPatternResponse = {
  generated_at: "2026-05-09T00:00:00.000Z",
  airport_code: "GMP",
  parking_lot_id: null,
  source: "sample_holiday_info",
  status: "sample",
  error_message: null,
  items: [],
};

const thresholdInsightsPayload: ThresholdInsightsResponse = {
  generated_at: "2026-04-26T00:00:00.000Z",
  airport_code: "GMP",
  parking_lot_id: null,
  days: 21,
  interval_minutes: 10,
  weekday_items: [],
  history_items: [],
};

const timeSeriesPayload: ParkingTimeSeriesResponse = {
  generated_at: "2026-04-26T00:00:00.000Z",
  airport_code: "GMP",
  parking_lot_id: null,
  days: 7,
  interval_minutes: 30,
  items: [],
};

const dashboardAnalyticsPayload: DashboardAnalyticsResponse = {
  threshold_events: [],
  threshold_insights: thresholdInsightsPayload,
  weekday_hour_patterns: [],
  holiday_patterns: holidayPatternPayload,
  time_series: timeSeriesPayload,
};

const apiClient = {
  getDashboardBootstrap: vi.fn(async () => ({
    airports,
    current: currentPayload,
    collector: buildCollectorStatus(),
    holidays: holidaySummaryPayload,
  })),
  getDashboardAnalytics: vi.fn(async (): Promise<DashboardAnalyticsResponse> => dashboardAnalyticsPayload),
  getFlightStatus: vi.fn(async () => ({
    generated_at: "2026-04-26T00:00:00.000Z",
    airport_code: "GMP",
    local_date: "2026-04-26",
    source: "sample_flight_status",
    status: "sample",
    error_message: null,
    items: [],
  })),
  getCollectorStatus: vi.fn(async () => buildCollectorStatus()),
};

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {
    constructor(
      message: string,
      readonly status: number
    ) {
      super(message);
      this.name = "ApiError";
    }
  },
  buildApiClient: () => apiClient,
}));

function renderAnalytics() {
  return render(
    <DashboardProvider apiBaseUrl="http://localhost:8000">
      <AnalyticsView />
    </DashboardProvider>
  );
}

describe("AnalyticsView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    document.cookie = `${DASHBOARD_SELECTION_COOKIE_KEY}=; Max-Age=0; Path=/`;
    apiClient.getCollectorStatus.mockResolvedValue(buildCollectorStatus());
    apiClient.getDashboardBootstrap.mockResolvedValue({
      airports,
      current: currentPayload,
      collector: buildCollectorStatus(),
      holidays: holidaySummaryPayload,
    });
    apiClient.getDashboardAnalytics.mockResolvedValue(dashboardAnalyticsPayload);
  });

  test("일별 엔진은 첫 탭 방문 때 열고 다시 숨겨도 날짜 선택을 유지한다", async () => {
    apiClient.getDashboardAnalytics.mockResolvedValue({ ...dashboardAnalyticsPayload, time_series: {
      ...timeSeriesPayload, items: [{ bucket_at: "2026-11-03T08:00:00Z", available_spaces: 0, occupied_spaces: 100, total_spaces: 100, lot_observations: 1 }],
    } });
    const user = userEvent.setup(); renderAnalytics();
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    expect(screen.queryByTestId("daily-date-toggles")).not.toBeInTheDocument();
    const daily = screen.getByRole("tab", { name: "일별 흐름" });
    await user.click(daily); expect(daily).toHaveFocus();
    const date = screen.getByRole("button", { name: "11/3 (화)" });
    await act(async () => date.focus()); await user.keyboard("{Enter}"); expect(date).toHaveAttribute("aria-pressed", "false");
    await user.click(screen.getByRole("tab", { name: "요일별 패턴" }));
    await user.click(daily); expect(daily).toHaveFocus();
    expect(screen.getByRole("button", { name: "11/3 (화)" })).toHaveAttribute("aria-pressed", "false");
    expect(apiClient.getDashboardAnalytics).toHaveBeenCalledTimes(1);
  });

  test("일별 자료를 기다리다 떠났다면 응답이 와도 숨은 차트를 처음 열지 않는다", async () => {
    let complete!: (value: DashboardAnalyticsResponse) => void;
    apiClient.getDashboardAnalytics.mockReturnValueOnce(new Promise((resolve) => { complete = resolve; }));
    const user = userEvent.setup(); renderAnalytics();
    await waitFor(() => expect(apiClient.getDashboardAnalytics).toHaveBeenCalled());
    await user.click(screen.getByRole("tab", { name: "일별 흐름" }));
    await user.click(screen.getByRole("tab", { name: "요일별 패턴" }));
    complete({ ...dashboardAnalyticsPayload, time_series: { ...timeSeriesPayload, items: [
      { bucket_at: "2026-11-03T08:00:00Z", available_spaces: 0, occupied_spaces: 100, total_spaces: 100, lot_observations: 1 },
    ] } });
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    expect(screen.queryByTestId("daily-date-toggles")).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "일별 흐름" }));
    expect(screen.getByRole("button", { name: "11/3 (화)" })).toBeInTheDocument();
  });

  test("inactive 패널은 native hidden으로 레이아웃과 키보드 경로에서 제외한다", async () => {
    const user = userEvent.setup(); renderAnalytics();
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    const panels = screen.getAllByRole("tabpanel", { hidden: true });
    function panelFor(name: string) {
      const id = screen.getByRole("tab", { name }).id;
      return panels.find((panel) => panel.getAttribute("aria-labelledby") === id)!;
    }
    expect(panelFor("요일별 패턴")).not.toHaveAttribute("hidden");
    for (const name of ["공휴일 패턴", "임계치", "일별 흐름"]) expect(panelFor(name)).toHaveAttribute("hidden");
    const threshold = screen.getByRole("tab", { name: "임계치" });
    await user.click(threshold); expect(threshold).toHaveFocus();
    expect(panelFor("임계치")).not.toHaveAttribute("hidden");
    expect(panelFor("요일별 패턴")).toHaveAttribute("hidden");
  });

  test.each(["airport", "lot"])("%s 범위 변경 뒤 새 일별 자료는 숨은 탭에서 처음 열지 않는다", async (change) => {
    const filled = { ...dashboardAnalyticsPayload, time_series: { ...timeSeriesPayload, items: [
      { bucket_at: "2026-11-03T08:00:00Z", available_spaces: 0, occupied_spaces: 100, total_spaces: 100, lot_observations: 1 },
    ] } };
    let complete!: (value: DashboardAnalyticsResponse) => void;
    apiClient.getDashboardBootstrap.mockResolvedValue({ airports: [...airports, { ...airports[0], code: "CJU", name_ko: "Jeju" }], current: currentPayload, collector: buildCollectorStatus(), holidays: holidaySummaryPayload });
    apiClient.getDashboardAnalytics.mockResolvedValueOnce(filled).mockReturnValueOnce(new Promise((resolve) => { complete = resolve; }));
    function ScopeHarness() {
      const { onAirportChange, onParkingLotChange } = useDashboard();
      return <><button type="button" onClick={() => change === "airport" ? onAirportChange("CJU") : onParkingLotChange(1)}>범위 변경</button><AnalyticsView /></>;
    }
    const user = userEvent.setup(); render(<DashboardProvider apiBaseUrl="http://localhost:8000" initialSelection={{ airportCode: "GMP", parkingLotId: null }}><ScopeHarness /></DashboardProvider>);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    await user.click(screen.getByRole("tab", { name: "일별 흐름" }));
    expect(screen.getByTestId("daily-date-toggles")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "요일별 패턴" }));
    await user.click(screen.getByRole("button", { name: "범위 변경" }));
    await waitFor(() => expect(apiClient.getDashboardAnalytics).toHaveBeenCalledTimes(2));
    const airport = change === "airport" ? "CJU" : "GMP";
    const lot = change === "lot" ? 1 : null;
    await act(async () => complete({ ...filled,
      threshold_insights: { ...filled.threshold_insights, airport_code: airport, parking_lot_id: lot },
      holiday_patterns: { ...filled.holiday_patterns, airport_code: airport, parking_lot_id: lot },
      time_series: { ...filled.time_series, airport_code: airport, parking_lot_id: lot },
    }));
    expect(screen.queryByTestId("daily-date-toggles")).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "일별 흐름" }));
    expect(screen.getByTestId("daily-date-toggles")).toBeInTheDocument();
  });

  test("빈 일별 응답에서 떠난 뒤 60초 후 첫 관측이 와도 숨은 차트를 열지 않는다", async () => {
    vi.useFakeTimers();
    try {
      apiClient.getDashboardAnalytics.mockResolvedValueOnce(dashboardAnalyticsPayload).mockResolvedValue({ ...dashboardAnalyticsPayload, time_series: { ...timeSeriesPayload, items: [
        { bucket_at: "2026-11-03T08:00:00Z", available_spaces: 0, occupied_spaces: 100, total_spaces: 100, lot_observations: 1 },
      ] } });
      renderAnalytics();
      await act(async () => { await Promise.resolve(); });
      await act(async () => { fireEvent.mouseDown(screen.getByRole("tab", { name: "일별 흐름" }), { button: 0, ctrlKey: false }); });
      await act(async () => { fireEvent.mouseDown(screen.getByRole("tab", { name: "요일별 패턴" }), { button: 0, ctrlKey: false }); });
      await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
      expect(apiClient.getDashboardAnalytics).toHaveBeenCalledTimes(2);
      expect(screen.queryByTestId("daily-date-toggles")).not.toBeInTheDocument();
      await act(async () => { fireEvent.mouseDown(screen.getByRole("tab", { name: "일별 흐름" }), { button: 0, ctrlKey: false }); });
      expect(screen.getByTestId("daily-date-toggles")).toBeInTheDocument();
    } finally { cleanup(); vi.useRealTimers(); }
  });

  test("withholds empty results until the initial analytics request completes", async () => {
    let resolveAnalytics!: (payload: DashboardAnalyticsResponse) => void;
    apiClient.getDashboardAnalytics.mockImplementationOnce(() => new Promise((resolve) => { resolveAnalytics = resolve; }));
    const user = userEvent.setup();
    renderAnalytics();
    await waitFor(() => expect(apiClient.getDashboardAnalytics).toHaveBeenCalled());

    for (const name of ["요일별 패턴", "공휴일 패턴", "임계치", "일별 흐름"]) {
      await user.click(screen.getByRole("tab", { name }));
      expect(screen.getByRole("status")).toHaveTextContent("분석 자료를 불러오는 중입니다.");
      expect(screen.queryAllByText(/데이터가 없습니다|충분한 기록이 없습니다|이벤트가 없습니다|달성 기록이 없습니다/)).toHaveLength(0);
    }

    resolveAnalytics(dashboardAnalyticsPayload);
    expect(await screen.findByText("표시할 날짜별 시계열 데이터가 없습니다.")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  test("fetches the analytics bundle once mounted", async () => {
    renderAnalytics();

    await waitFor(() => {
      expect(apiClient.getDashboardAnalytics).toHaveBeenCalledWith("GMP", null, expect.any(AbortSignal));
    });
    expect(apiClient.getFlightStatus).toHaveBeenCalledWith("GMP", expect.any(AbortSignal));
  });

  test("renders the four sub-tabs and switches between them", async () => {
    const user = userEvent.setup();
    renderAnalytics();

    await screen.findByRole("tab", { name: "요일별 패턴" });
    expect(screen.getByRole("tab", { name: "요일별 패턴" })).toHaveAttribute("aria-selected", "true");

    await user.click(screen.getByRole("tab", { name: "공휴일 패턴" }));
    expect(screen.getByRole("tab", { name: "공휴일 패턴" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("표시할 공휴일/토/일요일 패턴 데이터가 없습니다.")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "임계치" }));
    expect(await screen.findByText("임계치 이벤트")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "일별 흐름" }));
    expect(await screen.findByText("표시할 날짜별 시계열 데이터가 없습니다.")).toBeInTheDocument();
  });

  test("does not re-fetch dashboard bootstrap data itself (only the analytics bundle)", async () => {
    renderAnalytics();

    await waitFor(() => {
      expect(apiClient.getDashboardAnalytics).toHaveBeenCalled();
    });
    // AnalyticsView still needs the shared selection/bootstrap from DashboardProvider.
    expect(apiClient.getDashboardBootstrap).toHaveBeenCalledTimes(1);
  });

  test("shows an error alert when the analytics fetch fails", async () => {
    apiClient.getDashboardAnalytics.mockRejectedValueOnce(new Error("분석 데이터를 불러오지 못했습니다."));
    renderAnalytics();

    expect(await screen.findByRole("alert")).toHaveTextContent("분석 데이터를 불러오지 못했습니다.");
  });

  test("does not fetch analytics twice for a single parking-lot selection change", async () => {
    function Harness() {
      const { onParkingLotChange } = useDashboard();
      return (
        <>
          <button type="button" onClick={() => onParkingLotChange(1)}>
            select lot
          </button>
          <AnalyticsView />
        </>
      );
    }

    const user = userEvent.setup();
    render(
      <DashboardProvider apiBaseUrl="http://localhost:8000">
        <Harness />
      </DashboardProvider>
    );

    await waitFor(() => {
      expect(apiClient.getDashboardAnalytics).toHaveBeenCalledWith("GMP", null, expect.any(AbortSignal));
    });
    apiClient.getDashboardAnalytics.mockClear();

    await user.click(screen.getByRole("button", { name: "select lot" }));

    await waitFor(() => {
      expect(apiClient.getDashboardAnalytics).toHaveBeenCalledWith("GMP", 1, expect.any(AbortSignal));
    });
    expect(apiClient.getDashboardAnalytics).toHaveBeenCalledTimes(1);
  });
});

describe("route isolation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiClient.getCollectorStatus.mockResolvedValue(buildCollectorStatus());
    apiClient.getDashboardBootstrap.mockResolvedValue({
      airports,
      current: currentPayload,
      collector: buildCollectorStatus(),
      holidays: holidaySummaryPayload,
    });
    apiClient.getDashboardAnalytics.mockResolvedValue(dashboardAnalyticsPayload);
  });

  test("the current-status view alone never triggers the analytics fetch", async () => {
    render(
      <DashboardProvider apiBaseUrl="http://localhost:8000">
        <CurrentStatusView />
      </DashboardProvider>
    );

    await screen.findAllByText((_, element) => element?.textContent === "100/200대");
    expect(apiClient.getDashboardAnalytics).not.toHaveBeenCalled();
  });
});
