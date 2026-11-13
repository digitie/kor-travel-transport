import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { HistoryView } from "@/components/pages/history-view";
import { DashboardProvider } from "@/lib/dashboard-context";
import type {
  Airport,
  CollectorStatusResponse,
  HolidaySummaryResponse,
  ParkingCurrentResponse,
  ParkingTimeSeriesResponse,
} from "@/lib/types";

// 날짜/API/초점 계약을 검증하는 view 시험이다. 실제 브라우저 전용 Canvas는
// 별도 차트 시험과 브라우저 fixture에서 검증하며 jsdom 전역 API를 위조하지 않는다.
vi.mock("@/components/evilcharts/parking-line-canvas", () => ({
  ParkingLineCanvas: () => null,
}));

const airports: Airport[] = [
  {
    code: "GMP",
    name_ko: "Gimpo",
    name_en: "Gimpo",
    source: "kac",
    parking_lots: [],
  },
];

const currentPayload: ParkingCurrentResponse = { generated_at: "2026-04-26T00:00:00.000Z", items: [] };

const holidaySummaryPayload: HolidaySummaryResponse = {
  generated_at: "2026-05-09T00:00:00.000Z",
  start_date: "2026-04-27",
  end_date: "2026-05-17",
  source: "sample_holiday_info",
  status: "sample",
  error_message: null,
  sentence: "",
  items: [],
};

function buildCollectorStatus(): CollectorStatusResponse {
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
    effective_collect_interval_seconds: 180,
    scheduler_safety_buffer_seconds: 120,
  };
}

function buildTimeSeries(overrides: Partial<ParkingTimeSeriesResponse> = {}): ParkingTimeSeriesResponse {
  return {
    generated_at: "2026-04-26T00:00:00.000Z",
    airport_code: "GMP",
    parking_lot_id: null,
    days: 7,
    interval_minutes: 10,
    future_hours: 0,
    items: [
      { bucket_at: "2026-04-25T00:00:00.000Z", available_spaces: 30, occupied_spaces: 70, total_spaces: 100, lot_observations: 1 },
      { bucket_at: "2026-04-26T00:00:00.000Z", available_spaces: 50, occupied_spaces: 50, total_spaces: 100, lot_observations: 1 },
    ],
    ...overrides,
  };
}

const apiClient = {
  getDashboardBootstrap: vi.fn(async () => ({
    airports,
    current: currentPayload,
    collector: buildCollectorStatus(),
    holidays: holidaySummaryPayload,
  })),
  getCollectorStatus: vi.fn(async () => buildCollectorStatus()),
  getTimeSeries: vi.fn(async () => buildTimeSeries()),
};

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  buildApiClient: () => apiClient,
}));

function renderHistory() {
  return render(
    <DashboardProvider apiBaseUrl="http://localhost:8000">
      <HistoryView />
    </DashboardProvider>
  );
}

describe("HistoryView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiClient.getDashboardBootstrap.mockResolvedValue({
      airports,
      current: currentPayload,
      collector: buildCollectorStatus(),
      holidays: holidaySummaryPayload,
    });
    apiClient.getCollectorStatus.mockResolvedValue(buildCollectorStatus());
    apiClient.getTimeSeries.mockResolvedValue(buildTimeSeries());
  });

  test("fetches the default relative 7-day window on mount", async () => {
    renderHistory();

    await waitFor(() => {
      expect(apiClient.getTimeSeries).toHaveBeenCalledWith("GMP", { parkingLotId: null, days: 7 });
    });
  });

  test("shows the min/average/max summary once data loads", async () => {
    renderHistory();

    const minLabel = await screen.findByText("최소 잔여 주차면");
    const averageLabel = screen.getByText("평균 잔여 주차면");
    const maxLabel = screen.getByText("최대 잔여 주차면");
    expect(minLabel.nextElementSibling).toHaveTextContent("30대");
    expect(averageLabel.nextElementSibling).toHaveTextContent("40대");
    expect(maxLabel.nextElementSibling).toHaveTextContent("50대");
  });

  test("shows an error alert when the fetch fails", async () => {
    apiClient.getTimeSeries.mockRejectedValueOnce(new Error("과거 자료를 불러오지 못했습니다."));
    renderHistory();

    expect(await screen.findByRole("alert")).toHaveTextContent("과거 자료를 불러오지 못했습니다.");
  });

  test("selecting a calendar date range fetches an explicit start/end date instead of days", async () => {
    const user = userEvent.setup();
    renderHistory();

    await waitFor(() => {
      expect(apiClient.getTimeSeries).toHaveBeenCalledWith("GMP", { parkingLotId: null, days: 7 });
    });
    apiClient.getTimeSeries.mockClear();

    await user.click(screen.getByRole("button", { name: "날짜 범위 선택" }));
    await screen.findByRole("dialog");
    // Query by the data-day attribute (always present on every day cell) rather than
    // aria-label/text, since those are locale-formatted (Korean here) and would make this
    // test brittle to locale changes.
    const dayButtons = screen.getAllByRole("button").filter((button) => button.hasAttribute("data-day"));
    const selectableDayButtons = dayButtons.filter((button) => !(button as HTMLButtonElement).disabled);
    const firstButton = selectableDayButtons[0];
    const lastButton = selectableDayButtons[selectableDayButtons.length - 1];
    const expectedStartDate = toDateKeyFromDayAttribute(firstButton.getAttribute("data-day"));
    const expectedEndDate = toDateKeyFromDayAttribute(lastButton.getAttribute("data-day"));

    await user.click(firstButton);
    // react-day-picker remounts the day grid on selection change - re-query rather than
    // reuse the pre-click node reference, which is now detached from the live DOM.
    const lastButtonAfterFirstClick = screen
      .getAllByRole("button")
      .find((button) => button.getAttribute("data-day") === lastButton.getAttribute("data-day"));
    if (!lastButtonAfterFirstClick) {
      throw new Error("Expected the end-of-range day button to still be present after selecting the start date.");
    }
    await user.click(lastButtonAfterFirstClick);

    await waitFor(() => {
      expect(apiClient.getTimeSeries).toHaveBeenCalledWith("GMP", {
        parkingLotId: null,
        startDate: expectedStartDate,
        endDate: expectedEndDate,
        intervalMinutes: expect.any(Number),
      });
    });
    const resetButton = await screen.findByRole("button", { name: /최근 7일 보기/ });
    expect(resetButton).toBeInTheDocument();

    await user.click(resetButton);
    // The reset button unmounts itself once the range is cleared - focus must land
    // somewhere sensible (the picker trigger) rather than fall through to <body>.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "날짜 범위 선택" })).toHaveFocus();
    });
  });
});

/** Assert that the actual clicked calendar-day keys reach the API. */
function toDateKeyFromDayAttribute(label: string | null): string {
  if (!label || !/^\d{4}-\d{2}-\d{2}$/.test(label)) {
    throw new Error(`Unexpected data-day format: ${label}`);
  }
  return label;
}
