import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ParkingLinesProbe } from "./parking-lines-probe";
import { HistoryChart } from "@/components/history-chart";
import { DailyFlightOverlayChart } from "@/components/daily-flight-overlay-chart";
import type { ParkingTimeSeriesResponse } from "@/lib/types";
vi.mock("next/dynamic", () => ({ default: () => ParkingLinesProbe }));
const series: ParkingTimeSeriesResponse = {
  generated_at: "2026-11-12T16:00:00Z", airport_code: "CJU", parking_lot_id: 1, days: 7, interval_minutes: 30,
  items: [0, null, 12].map((value, index) => ({ bucket_at: new Date(Date.parse("2026-11-12T15:00:00Z") + index * 1800000).toISOString(), available_spaces: value ?? 0, occupied_spaces: 0, total_spaces: 20, lot_observations: value === null ? 0 : 1 })),
};
test("shared history table mounts only on expansion and keeps zero, missing, observation count and keyboard time choice", async () => {
  const user = userEvent.setup();render(<HistoryChart series={series} holidays={[]} scopeLabel="시험" />);
  expect(screen.queryByRole("table")).toBeNull();
  const summary=screen.getByText("관측 수치와 특별일 보기");await user.click(summary);
  const table=await screen.findByRole("table",{name:"실제 주차 관측 수치"});const rows=within(table).getAllByRole("row");
  expect(rows).toHaveLength(4);expect(within(rows[1]).getByRole("cell",{name:"0"})).toBeInTheDocument();
  expect(within(rows[2]).getByRole("cell",{name:"관측 없음"})).toBeInTheDocument();expect(within(rows[2]).getByRole("cell",{name:"0"})).toBeInTheDocument();
  const slider=screen.getByRole("slider",{name:"주차 관측 시점"});fireEvent.change(slider,{target:{value:"0"}});expect(slider).toHaveAttribute("aria-valuetext",expect.stringContaining("0대"));fireEvent.change(slider,{target:{value:"1"}});expect(slider).toHaveAttribute("aria-valuetext",expect.stringContaining("주차 정보 없음"));
  await user.click(summary);await waitFor(()=>expect(screen.queryByRole("table")).toBeNull());
});
test("shared daily table keeps all rows including an explicit missing bucket and unmounts on collapse", async () => {
  const user=userEvent.setup();render(<DailyFlightOverlayChart series={series} holidays={[]} flightStatus={null} scopeLabel="시험" />);
  expect(screen.queryByRole("table")).toBeNull();const summary=screen.getByText("날짜별 관측 수치 보기");await user.click(summary);
  const table=await screen.findByRole("table");expect(table).toHaveAccessibleName(expect.stringContaining("11/13"));const rows=within(table).getAllByRole("row");
  expect(rows).toHaveLength(4);expect(within(rows[1]).getByRole("cell",{name:"0"})).toBeInTheDocument();expect(within(rows[2]).getByRole("cell",{name:"관측 없음"})).toBeInTheDocument();expect(within(rows[3]).getByRole("cell",{name:"12"})).toBeInTheDocument();
  await user.click(summary);await waitFor(()=>expect(screen.queryByRole("table")).toBeNull());
});
