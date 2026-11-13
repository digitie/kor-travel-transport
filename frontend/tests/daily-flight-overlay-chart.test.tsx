import { ParkingLinesProbe, lineOptions } from "./parking-lines-probe";
vi.mock("next/dynamic", () => ({ default: () => ParkingLinesProbe }));
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DailyFlightOverlayChart } from "@/components/daily-flight-overlay-chart";
import type { FlightStatusResponse, HolidayItemSummary, ParkingTimeSeriesResponse } from "@/lib/types";

const LOCAL_DATES = [
  "2026-04-18",
  "2026-04-19",
  "2026-04-20",
  "2026-04-21",
  "2026-04-22",
  "2026-04-23",
  "2026-04-24",
];

function kstIso(localDate: string, hour: number, minute = 0): string {
  const [year, month, day] = localDate.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day, hour - 9, minute)).toISOString();
}

function buildSeries(): ParkingTimeSeriesResponse {
  return {
    generated_at: "2026-04-24T03:00:00.000Z",
    airport_code: "CJU",
    parking_lot_id: 1,
    days: 7,
    interval_minutes: 30,
    items: LOCAL_DATES.flatMap((localDate, dateIndex) => [
      {
        bucket_at: kstIso(localDate, 0),
        available_spaces: 100 + dateIndex * 10,
        occupied_spaces: 500,
        total_spaces: 600,
        lot_observations: 1,
      },
      {
        bucket_at: kstIso(localDate, 12),
        available_spaces: 70 + dateIndex * 10,
        occupied_spaces: 530,
        total_spaces: 600,
        lot_observations: 1,
      },
      {
        bucket_at: kstIso(localDate, 23, 30),
        available_spaces: 120 + dateIndex * 10,
        occupied_spaces: 480,
        total_spaces: 600,
        lot_observations: 1,
      },
    ]),
  };
}

function buildFlightStatus(): FlightStatusResponse {
  return {
    generated_at: "2026-04-24T03:00:00.000Z",
    airport_code: "CJU",
    local_date: "2026-04-24",
    source: "sample_flight_status",
    status: "sample",
    error_message: null,
    items: [
      {
        airport_code: "CJU",
        direction: "departure",
        flight_number: "KE1101",
        airline: "대한항공",
        scheduled_at: kstIso("2026-04-24", 10, 0),
        estimated_at: null,
        marker_at: kstIso("2026-04-24", 10, 0),
        origin_airport: "제주",
        destination_airport: "김포",
        status: "출발",
        line_type: "국내",
      },
      {
        airport_code: "CJU",
        direction: "arrival",
        flight_number: "OZ8922",
        airline: "아시아나항공",
        scheduled_at: kstIso("2026-04-24", 15, 30),
        estimated_at: null,
        marker_at: kstIso("2026-04-24", 15, 30),
        origin_airport: "김포",
        destination_airport: "제주",
        status: "도착",
        line_type: "국내",
      },
    ],
  };
}

function buildHolidays(): HolidayItemSummary[] {
  return [{ local_date: "2026-04-24", name: "테스트 공휴일", weekday: 5, weekday_name: "토" }];
}

describe("DailyFlightOverlayChart", () => {
  test("shows the full KST date airline and status in the visible flight tooltip", () => {
    const flightStatus = buildFlightStatus();
    flightStatus.items = [{ ...flightStatus.items[0], marker_at: "2026-04-23T18:00:00Z", airline: "대한항공", status: "지연" }];
    render(<DailyFlightOverlayChart flightStatus={flightStatus} holidays={[]} series={buildSeries()} scopeLabel="시험" />);
    const marker = screen.getByTestId("daily-flight-marker");
    fireEvent.mouseEnter(marker);
    const hovered = screen.getByTestId("daily-flight-highlight-label");
    expect(hovered).toBeVisible();
    expect(hovered).toHaveTextContent("04.24 03:00");
    expect(within(hovered).getByText(/대한항공/)).toBeVisible();
    expect(within(hovered).getByText(/지연/)).toBeVisible();
    fireEvent.mouseLeave(marker);
    expect(screen.queryByTestId("daily-flight-highlight-label")).toBeNull();
    fireEvent.click(marker);
    const selected = screen.getByTestId("daily-flight-highlight-label");
    expect(selected).toBeVisible();
    expect(selected).toHaveTextContent("04.24 03:00");
    expect(within(selected).getByText(/대한항공/)).toBeVisible();
    expect(within(selected).getByText(/지연/)).toBeVisible();
  });
  test("explicit missing daily buckets remain gaps while observed zero is retained", () => {
    const series = buildSeries();
    series.items[0] = { ...series.items[0], available_spaces: 0 };
    series.items[1] = { ...series.items[1], available_spaces: 0, lot_observations: 0 };
    render(<DailyFlightOverlayChart flightStatus={null} holidays={[]} series={series} scopeLabel="P1" />);
    const options = lineOptions<{ series: { data: [number, number | null][]; connectNulls: boolean }[] }>();
    expect(options.series[0].data).toEqual([[0, 0], [720, null], [1410, series.items[2].available_spaces]]);
    expect(options.series[0].connectNulls).toBe(false);
    expect(screen.getByText("날짜별 관측 수치 보기")).toBeInTheDocument();
  });
  test("flight position uses marker_at in KST rather than scheduled or estimated time", () => {
    const flightStatus = buildFlightStatus();
    flightStatus.items = [{ ...flightStatus.items[0], marker_at: "2026-04-23T18:00:00Z", scheduled_at: "2026-04-24T01:00:00Z", estimated_at: "2026-04-24T02:00:00Z" }];
    render(<DailyFlightOverlayChart flightStatus={flightStatus} holidays={[]} series={buildSeries()} scopeLabel="P1" />);
    const options = lineOptions<{ graphic: { children: { shape: { x1: number } }[] }[] }>();
    expect(options.graphic[0].children[0].shape.x1).toBe(42 + 3 / 24 * (1180 - 84));
    expect(within(screen.getByRole("group", { name: "비행편 선택" })).getByRole("button", { name: /03:00.*KE1101/ })).toBeInTheDocument();
  });
  test("계속 조회 중인 항공편을 확정 0편이나 오류로 표시하지 않고 늦은 성공을 그린다", () => {
    const props = { holidays: buildHolidays(), series: buildSeries(), scopeLabel: "P1 주차장" };
    const view = render(<DailyFlightOverlayChart {...props} flightStatus={{ ...buildFlightStatus(),
      status: "loading", error_message: "비행편 정보를 계속 조회 중입니다.", items: [] }} />);
    expect(screen.getByRole("status")).toHaveTextContent("계속 조회 중");
    expect(screen.getByRole("status")).not.toHaveClass("flight-marker-error");
    expect(screen.queryByText(/비행편 출발 0편/)).not.toBeInTheDocument();
    view.rerender(<DailyFlightOverlayChart {...props} flightStatus={{ ...buildFlightStatus(), status: "success" }} />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("daily-flight-marker-button")).toHaveLength(buildFlightStatus().items.length);
  });
  test("renders seven daily lines, fixed day axis, flight markers, and holiday styling", () => {
    render(
      <DailyFlightOverlayChart
        flightStatus={buildFlightStatus()}
        holidays={buildHolidays()}
        series={buildSeries()}
        scopeLabel="P1 주차장"
      />
    );

    expect(screen.getByTestId("daily-flight-overlay-chart")).toBeInTheDocument();
    expect(screen.getAllByTestId("daily-overlay-line")).toHaveLength(7);
    expect(screen.getAllByTestId("daily-flight-marker")).toHaveLength(2);
    expect(screen.getAllByTestId("daily-flight-marker-button")).toHaveLength(2);
    const options = lineOptions<{ xAxis: { min: number; max: number; interval: number }; series: { markPoint: { data: unknown[] }; lineStyle: { type: string } }[] }>();
    expect(options.xAxis).toMatchObject({ min: 0, max: 1440, interval: 360 });
    expect(options.series.filter((line) => line.markPoint.data.length)).toHaveLength(3);
    expect(options.series.filter((line) => line.lineStyle.type === "dashed")).toHaveLength(3);
    expect(screen.getByText("토요일")).toBeInTheDocument();
    expect(screen.getByText("일요일")).toBeInTheDocument();
    expect(screen.getByText("테스트 공휴일")).toBeInTheDocument();
  });

  test("expands the daily x axis four times", async () => {
    const user = userEvent.setup();
    render(
      <DailyFlightOverlayChart
        flightStatus={buildFlightStatus()}
        holidays={buildHolidays()}
        series={buildSeries()}
        scopeLabel="P1 주차장"
      />
    );

    expect(screen.getByTestId("daily-flight-overlay-chart").querySelector(".daily-overlay-chart-stage")).toHaveStyle({ width: "1180px" });

    await user.click(screen.getByTestId("daily-wide-axis-toggle"));

    expect(screen.getByTestId("daily-flight-overlay-chart").querySelector(".daily-overlay-chart-stage")).toHaveStyle({ width: "4720px" });
  });

  test("hides and shows a selected date line", async () => {
    const user = userEvent.setup();

    render(
      <DailyFlightOverlayChart
        flightStatus={buildFlightStatus()}
        holidays={buildHolidays()}
        series={buildSeries()}
        scopeLabel="P1 주차장"
      />
    );

    const dateToggles = screen.getByTestId("daily-date-toggles");
    const targetDate = within(dateToggles).getByRole("button", { name: /4\/24/ });

    await user.click(targetDate);
    expect(screen.getAllByTestId("daily-overlay-line")).toHaveLength(6);
    expect(targetDate).toHaveAttribute("aria-pressed", "false");

    await user.click(targetDate);
    expect(screen.getAllByTestId("daily-overlay-line")).toHaveLength(7);
    expect(targetDate).toHaveAttribute("aria-pressed", "true");
  });

  test("toggles departure and arrival markers independently", async () => {
    const user = userEvent.setup();

    render(
      <DailyFlightOverlayChart
        flightStatus={buildFlightStatus()}
        holidays={buildHolidays()}
        series={buildSeries()}
        scopeLabel="P1 주차장"
      />
    );

    expect(screen.getAllByTestId("daily-flight-marker")).toHaveLength(2);

    await user.click(screen.getByLabelText("출발편"));
    expect(screen.getAllByTestId("daily-flight-marker")).toHaveLength(1);
    expect(screen.getByText(/출발 0편 \/ 도착 1편/)).toBeInTheDocument();

    await user.click(screen.getByLabelText("도착편"));
    expect(screen.queryAllByTestId("daily-flight-marker")).toHaveLength(0);
    expect(screen.getByText(/출발 0편 \/ 도착 0편/)).toBeInTheDocument();
  });

  test("highlights a flight marker when it is hovered or clicked", () => {
    render(
      <DailyFlightOverlayChart
        flightStatus={buildFlightStatus()}
        holidays={buildHolidays()}
        series={buildSeries()}
        scopeLabel="P1 주차장"
      />
    );

    const marker = screen.getAllByTestId("daily-flight-marker")[0];
    fireEvent.mouseEnter(marker);
    expect(screen.getByTestId("daily-flight-highlight-label")).toHaveTextContent("KE1101");

    fireEvent.mouseLeave(marker);
    expect(screen.queryByTestId("daily-flight-highlight-label")).not.toBeInTheDocument();

    fireEvent.click(marker);
    expect(screen.getByTestId("daily-flight-highlight-label")).toHaveTextContent("KE1101");
  });

  test("offers native keyboard controls for flight markers outside the canvas image", async () => {
    const user = userEvent.setup();
    render(
      <DailyFlightOverlayChart
        flightStatus={buildFlightStatus()}
        holidays={buildHolidays()}
        series={buildSeries()}
        scopeLabel="P1 주차장"
      />
    );

    const button = within(screen.getByRole("group", { name: "비행편 선택" })).getByRole("button", { name: /10:00.*KE1101/ });
    act(() => button.focus());
    expect(button).toHaveFocus();
    await user.click(button);
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("daily-flight-highlight-label")).toHaveTextContent("KE1101");
  });
});
