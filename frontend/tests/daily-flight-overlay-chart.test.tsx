import { fireEvent, render, screen, within } from "@testing-library/react";
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
    const { container } = render(
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
    expect(screen.getByText("00:00")).toBeInTheDocument();
    expect(screen.getByText("06:00")).toBeInTheDocument();
    expect(screen.getByText("12:00")).toBeInTheDocument();
    expect(screen.getByText("18:00")).toBeInTheDocument();
    expect(screen.getByText("24:00")).toBeInTheDocument();
    expect(screen.getByText("토요일")).toBeInTheDocument();
    expect(screen.getByText("일요일")).toBeInTheDocument();
    expect(screen.getByText("테스트 공휴일")).toBeInTheDocument();
    expect(container.querySelectorAll(".daily-line-special")).toHaveLength(3);
    expect(container.querySelector(".daily-line-holiday")).not.toBeNull();
  });

  test("expands the daily x axis four times", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <DailyFlightOverlayChart
        flightStatus={buildFlightStatus()}
        holidays={buildHolidays()}
        series={buildSeries()}
        scopeLabel="P1 주차장"
      />
    );

    expect(container.querySelector(".daily-overlay-chart")?.getAttribute("viewBox")).toBe("0 0 1180 320");

    await user.click(screen.getByTestId("daily-wide-axis-toggle"));

    expect(container.querySelector(".daily-overlay-chart")?.getAttribute("viewBox")).toBe("0 0 4720 320");
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

  test("offers native keyboard controls for flight markers outside the SVG image", async () => {
    const user = userEvent.setup();
    render(
      <DailyFlightOverlayChart
        flightStatus={buildFlightStatus()}
        holidays={buildHolidays()}
        series={buildSeries()}
        scopeLabel="P1 주차장"
      />
    );

    const button = screen.getByRole("button", { name: /10:00.*KE1101/ });
    button.focus();
    expect(button).toHaveFocus();
    await user.click(button);
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("daily-flight-highlight-label")).toHaveTextContent("KE1101");
  });
});
