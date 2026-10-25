import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AnalyticsView } from "@/components/pages/analytics-view";
import { CurrentStatusView } from "@/components/pages/current-status-view";
import { DashboardProvider, useDashboard } from "@/lib/dashboard-context";
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
    apiClient.getCollectorStatus.mockResolvedValue(buildCollectorStatus());
    apiClient.getDashboardBootstrap.mockResolvedValue({
      airports,
      current: currentPayload,
      collector: buildCollectorStatus(),
      holidays: holidaySummaryPayload,
    });
    apiClient.getDashboardAnalytics.mockResolvedValue(dashboardAnalyticsPayload);
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
      expect(apiClient.getDashboardAnalytics).toHaveBeenCalledWith("GMP", null);
    });
    expect(apiClient.getFlightStatus).toHaveBeenCalledWith("GMP");
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
      expect(apiClient.getDashboardAnalytics).toHaveBeenCalledWith("GMP", null);
    });
    apiClient.getDashboardAnalytics.mockClear();

    await user.click(screen.getByRole("button", { name: "select lot" }));

    await waitFor(() => {
      expect(apiClient.getDashboardAnalytics).toHaveBeenCalledWith("GMP", 1);
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
