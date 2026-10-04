import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AppShell } from "@/components/app-shell";
import { CurrentStatusView } from "@/components/pages/current-status-view";
import { DashboardProvider } from "@/lib/dashboard-context";
import {
  DASHBOARD_SELECTION_COOKIE_KEY,
  DASHBOARD_SELECTION_STORAGE_KEY,
} from "@/lib/dashboard-preferences";
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
  {
    code: "PUS",
    name_ko: "Gimhae",
    name_en: "Gimhae",
    source: "kac",
    parking_lots: [{ id: 5, source_lot_id: "pus-1", legacy_source_lot_id: null, name: "Passenger P1", terminal: null, category: null, is_active: true }],
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

const refreshedCurrentPayload: ParkingCurrentResponse = {
  ...currentPayload,
  generated_at: "2026-04-26T00:01:00.000Z",
  items: [
    {
      ...currentPayload.items[0],
      observed_at: "2026-04-26T00:01:00.000Z",
      collected_at: "2026-04-26T00:11:00.000Z",
      occupied_spaces: 136,
      available_spaces: 64,
    },
  ],
};

const timeSeriesPayload: ParkingTimeSeriesResponse = {
  generated_at: "2026-04-26T00:00:00.000Z",
  airport_code: "GMP",
  parking_lot_id: null,
  days: 7,
  interval_minutes: 30,
  items: [],
};

const holidaySummaryPayload: HolidaySummaryResponse = {
  generated_at: "2026-05-09T00:00:00.000Z",
  start_date: "2026-04-27",
  end_date: "2026-05-17",
  source: "sample_holiday_info",
  status: "sample",
  error_message: null,
  sentence: "5/5 (화) 어린이날 입니다.",
  items: [{ local_date: "2026-05-05", name: "어린이날", weekday: 1, weekday_name: "화" }],
};

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

function buildCollectorStatus(overrides: Partial<CollectorStatusResponse> = {}): CollectorStatusResponse {
  return {
    scheduler_enabled: true,
    collect_interval_seconds: 300,
    manual_collect_enabled: true,
    manual_collect_min_interval_seconds: 300,
    client_mode: "live",
    enabled_sources: ["kac_parking"],
    data_go_kr_service_key_configured: true,
    supported_airport_codes: ["GMP", "PUS"],
    latest_snapshot_observed_at: "2026-04-26T00:00:00.000Z",
    latest_snapshot_collected_at: "2026-04-26T00:10:00.000Z",
    earliest_snapshot_observed_at: "2026-04-19T00:00:00.000Z",
    manual_collect_available_at: "2026-04-26T00:15:00.000Z",
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

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
}));

// CurrentStatusView no longer owns the airport/parking-lot picker - AppShell does (T-035).
// Render them together so selection-change/persistence tests exercise the real composition.
function renderCurrentStatus(props: { autoRefreshIntervalMs?: number } = {}) {
  return render(
    <DashboardProvider apiBaseUrl="http://localhost:8000" autoRefreshIntervalMs={props.autoRefreshIntervalMs}>
      <AppShell>
        <CurrentStatusView />
      </AppShell>
    </DashboardProvider>
  );
}

describe("DashboardProvider + CurrentStatusView", () => {
  beforeEach(() => {
    localStorage.clear();
    document.cookie = `${DASHBOARD_SELECTION_COOKIE_KEY}=; Max-Age=0; Path=/`;
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

  test("restores the last selected airport and parking lot from localStorage", async () => {
    localStorage.setItem(
      DASHBOARD_SELECTION_STORAGE_KEY,
      JSON.stringify({ airportCode: "PUS", parkingLotId: 5 })
    );

    renderCurrentStatus();

    expect(await screen.findByDisplayValue("Gimhae")).toBeInTheDocument();
    expect(screen.getAllByRole("combobox")[1]).toHaveValue("5");
  });

  test("keeps a persistent aria-live region for the loading state instead of mounting one on demand", async () => {
    renderCurrentStatus();
    await screen.findByDisplayValue("Gimpo");

    // A screen reader is not guaranteed to announce a live region that is inserted
    // into the DOM already carrying its final content - the region must already
    // exist, then have its content change. Assert the announcer is present even
    // while nothing is loading (empty text), proving it isn't a mount/unmount node.
    const announcers = Array.from(document.querySelectorAll('[aria-live="polite"]'));
    expect(announcers.some((el) => el.className.includes("sr-only"))).toBe(true);
  });

  test("stores the selected airport when the user changes it", async () => {
    const user = userEvent.setup();
    renderCurrentStatus();

    await user.selectOptions(await screen.findByDisplayValue("Gimpo"), "PUS");

    await waitFor(() => {
      expect(localStorage.getItem(DASHBOARD_SELECTION_STORAGE_KEY)).toContain("\"airportCode\":\"PUS\"");
    });
  });

  test("offers no manual collect action even when the backend enables manual collection", async () => {
    // 공개 대시보드의 즉시 수집은 프록시가 항상 거부하는 죽은 경로였다(ADR-012, #61).
    renderCurrentStatus();

    await screen.findAllByText((_, element) => element?.textContent === "100/200대");
    expect(screen.queryByTestId("manual-collect-button")).toBeNull();
    expect(screen.queryByRole("button", { name: /수집/ })).toBeNull();
  });

  test("does not fetch analytics data when only the current-status view is mounted", async () => {
    renderCurrentStatus();

    await screen.findAllByText((_, element) => element?.textContent === "100/200대");
    expect(apiClient.getDashboardBootstrap).toHaveBeenCalled();
    expect(apiClient.getDashboardAnalytics).not.toHaveBeenCalled();
    expect(apiClient.getFlightStatus).not.toHaveBeenCalled();
  });

  test("refreshes dashboard data automatically when backend snapshots change", async () => {
    apiClient.getDashboardBootstrap
      .mockResolvedValueOnce({
        airports,
        current: currentPayload,
        collector: buildCollectorStatus(),
        holidays: holidaySummaryPayload,
      })
      .mockResolvedValue({
        airports,
        current: refreshedCurrentPayload,
        collector: buildCollectorStatus({
          latest_snapshot_observed_at: "2026-04-26T00:01:00.000Z",
          latest_snapshot_collected_at: "2026-04-26T00:11:00.000Z",
        }),
        holidays: holidaySummaryPayload,
      });
    apiClient.getCollectorStatus
      .mockResolvedValueOnce(buildCollectorStatus())
      .mockResolvedValueOnce(
        buildCollectorStatus({
          latest_snapshot_observed_at: "2026-04-26T00:01:00.000Z",
          latest_snapshot_collected_at: "2026-04-26T00:11:00.000Z",
        })
      )
      .mockResolvedValue(
        buildCollectorStatus({
          latest_snapshot_observed_at: "2026-04-26T00:01:00.000Z",
          latest_snapshot_collected_at: "2026-04-26T00:11:00.000Z",
        })
      );

    renderCurrentStatus({ autoRefreshIntervalMs: 20 });

    await screen.findAllByText((_, element) => element?.textContent === "100/200대");
    expect(apiClient.getDashboardBootstrap).toHaveBeenCalledTimes(1);

    await waitFor(() => {
      expect(apiClient.getDashboardBootstrap.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
    await waitFor(() => {
      expect(screen.getAllByText((_, element) => element?.textContent === "64/200대").length).toBeGreaterThan(0);
    });
  });

  test("skips full dashboard reloads while backend snapshots are unchanged", async () => {
    renderCurrentStatus({ autoRefreshIntervalMs: 20 });

    await screen.findAllByText((_, element) => element?.textContent === "100/200대");
    await new Promise((resolve) => setTimeout(resolve, 60));

    expect(apiClient.getCollectorStatus.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(apiClient.getDashboardBootstrap).toHaveBeenCalledTimes(1);
  });
});
