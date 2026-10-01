import { fireEvent, render, screen, within } from "@testing-library/react";

import { HistoryChart } from "@/components/history-chart";
import { formatDateTime } from "@/lib/format";
import type { HolidayItemSummary, ParkingTimeSeriesResponse } from "@/lib/types";

function buildSeries(): ParkingTimeSeriesResponse {
  const start = new Date("2026-04-23T15:00:00.000Z").getTime();

  return {
    generated_at: "2026-04-24T03:00:00.000Z",
    airport_code: "CJU",
    parking_lot_id: 1,
    days: 7,
    interval_minutes: 30,
    items: Array.from({ length: 25 }, (_, index) => ({
      bucket_at: new Date(start + index * 30 * 60 * 1000).toISOString(),
      available_spaces: 100 + index,
      occupied_spaces: 500 - index,
      total_spaces: 600,
      lot_observations: 1,
    })),
  };
}

function buildHolidays(): HolidayItemSummary[] {
  return [{ local_date: "2026-04-24", name: "테스트 공휴일", weekday: 4, weekday_name: "금" }];
}

function buildWeekendSeries(): ParkingTimeSeriesResponse {
  const start = new Date("2026-04-24T15:00:00.000Z").getTime();

  return {
    generated_at: "2026-04-26T03:00:00.000Z",
    airport_code: "CJU",
    parking_lot_id: 1,
    days: 7,
    interval_minutes: 30,
    items: Array.from({ length: 97 }, (_, index) => ({
      bucket_at: new Date(start + index * 30 * 60 * 1000).toISOString(),
      available_spaces: 140 + (index % 20),
      occupied_spaces: 460 - (index % 20),
      total_spaces: 600,
      lot_observations: 1,
    })),
  };
}

describe("HistoryChart", () => {
  test("breaks the line and area across missing observations", () => {
    const series = buildSeries();
    series.items = series.items.slice(0, 6).map((item, index) => index === 2 || index === 3
      ? { ...item, lot_observations: 0, available_spaces: 0, occupied_spaces: 0, total_spaces: 0 }
      : item);
    const { container } = render(<HistoryChart holidays={[]} series={series} scopeLabel="P1" />);

    expect(container.querySelectorAll(".history-line")).toHaveLength(2);
    expect(container.querySelectorAll(".history-area")).toHaveLength(2);
  });

  test("keeps isolated older observations visible as points", () => {
    const series = buildSeries();
    series.items = series.items.slice(0, 5).map((item, index) => index === 1 || index === 3
      ? item
      : { ...item, lot_observations: 0, available_spaces: 0, occupied_spaces: 0, total_spaces: 0 });
    const { container } = render(<HistoryChart holidays={[]} series={series} scopeLabel="P1" />);

    expect(container.querySelectorAll(".history-point.isolated")).toHaveLength(2);
  });

  test("renders 6 hour axis labels", () => {
    const { container } = render(
      <HistoryChart
        holidays={buildHolidays()}
        series={buildSeries()}
        scopeLabel={"P1 \uC8FC\uCC28\uC7A5"}
      />
    );

    const axisLabels = screen.getAllByTestId("history-axis-label");
    expect(axisLabels).toHaveLength(3);
    expect(screen.getByTestId("history-axis-shell")).toBeInTheDocument();
    expect(screen.getByText("\uAE30\uC900: P1 \uC8FC\uCC28\uC7A5")).toBeInTheDocument();
    expect(screen.getByText("00:00")).toBeInTheDocument();
    expect(screen.getByText("06:00")).toBeInTheDocument();
    expect(screen.getByText("12:00")).toBeInTheDocument();

    const linePath = container.querySelector(".history-line");
    expect(linePath?.getAttribute("d")).toContain("H");
    expect(linePath?.getAttribute("d")).toContain("V");

    const tooltip = screen.getByTestId("history-tooltip");
    expect(tooltip).toBeInTheDocument();
    expect(within(tooltip).getByText("124\uB300")).toBeInTheDocument();
    expect(
      within(tooltip).getByText(formatDateTime(buildSeries().items[24].bucket_at))
    ).toBeInTheDocument();
  });

  test("shows tooltip with time and available spaces on hover", () => {
    const series = buildSeries();

    render(
      <HistoryChart
        holidays={buildHolidays()}
        series={series}
        scopeLabel={"P1 \uC8FC\uCC28\uC7A5"}
      />
    );

    const interactionSurface = screen.getByTestId("history-chart-surface");
    Object.defineProperty(interactionSurface, "getBoundingClientRect", {
      configurable: true,
      value: () => ({
        x: 0,
        y: 0,
        top: 0,
        left: 0,
        right: 1080,
        bottom: 280,
        width: 1080,
        height: 280,
        toJSON: () => ({}),
      }),
    });

    fireEvent.mouseMove(interactionSurface, { clientX: 540 });

    const tooltip = screen.getByTestId("history-tooltip");
    expect(tooltip).toBeInTheDocument();
    expect(within(tooltip).getByText("112\uB300")).toBeInTheDocument();
    expect(within(tooltip).getByText(formatDateTime(series.items[12].bucket_at))).toBeInTheDocument();
  });

  test("does not move the touch cursor while horizontally dragging", () => {
    render(
      <HistoryChart
        holidays={buildHolidays()}
        series={buildSeries()}
        scopeLabel={"P1 \uC8FC\uCC28\uC7A5"}
      />
    );

    const interactionSurface = screen.getByTestId("history-chart-surface");
    Object.defineProperty(interactionSurface, "getBoundingClientRect", {
      configurable: true,
      value: () => ({
        x: 0,
        y: 0,
        top: 0,
        left: 0,
        right: 1080,
        bottom: 280,
        width: 1080,
        height: 280,
        toJSON: () => ({}),
      }),
    });

    fireEvent.touchStart(interactionSurface, { touches: [{ clientX: 100 }] });
    expect(within(screen.getByTestId("history-tooltip")).getByText("102\uB300")).toBeInTheDocument();

    fireEvent.touchMove(interactionSurface, { touches: [{ clientX: 640 }] });

    const tooltip = screen.getByTestId("history-tooltip");
    expect(within(tooltip).getByText("102\uB300")).toBeInTheDocument();
    expect(within(tooltip).queryByText("114\uB300")).not.toBeInTheDocument();
  });

  test("keeps flight markers out of the recent parking chart", () => {
    render(
      <HistoryChart
        holidays={buildHolidays()}
        series={buildSeries()}
        scopeLabel={"P1 \uC8FC\uCC28\uC7A5"}
      />
    );

    expect(screen.getAllByTestId("holiday-band")).toHaveLength(1);
    expect(screen.queryByTestId("flight-marker-summary")).not.toBeInTheDocument();
    expect(screen.queryByTestId("flight-marker-list")).not.toBeInTheDocument();
    expect(screen.queryByTestId("flight-highlight-label")).not.toBeInTheDocument();
  });

  test("marks Saturdays and Sundays in the recent parking chart", () => {
    render(
      <HistoryChart
        holidays={[]}
        series={buildWeekendSeries()}
        scopeLabel={"P1 \uC8FC\uCC28\uC7A5"}
      />
    );

    expect(screen.getAllByTestId("holiday-band")).toHaveLength(2);
    expect(screen.getByText("토요일")).toBeInTheDocument();
    expect(screen.getByText("일요일")).toBeInTheDocument();
  });
});
