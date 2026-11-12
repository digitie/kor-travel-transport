import * as echarts from "echarts/core";
import { PieChart } from "echarts/charts";
import { CalendarComponent, TooltipComponent } from "echarts/components";
import { render, screen } from "@testing-library/react";
import { ParkingPie } from "@/components/parking-pie";
import { ParkingHeatmapCanvas } from "@/components/parking-pattern-heatmap-canvas";
import { groupParkingLots, heatCellDescription, parkingCounts, parkingHeatCells, type ParkingChartLot } from "@/lib/parking-chart-model";

type PieOptions = { series: { data: { value: number }[]; radius: string[] }[]; tooltip: { formatter: (p: { seriesId: string; seriesName: string; name: string; value: number }) => string; triggerOn: string } };
type HeatOptions = { series: { data: number[][] }[]; tooltip: { formatter: (p: { dataIndex: number }) => string } };
type PieProps = { chartOptions: PieOptions; data: { name: string; value: number }[] };
type HeatProps = { chartOptions: HeatOptions; onDataSelect: (index: number) => void };
const captured = vi.hoisted(() => ({ pie: null as PieProps | null, heat: null as HeatProps | null }));
vi.mock("@/components/evilcharts/charts/echarts-pie-chart", () => ({ EChartsPieChart: Object.assign((props: PieProps) => { captured.pie = props; return <div data-testid="pie" />; }, { Pie: () => null }) }));
vi.mock("@/components/evilcharts/charts/echarts-heatmap-chart", () => ({ EChartsHeatmapChart: Object.assign((props: HeatProps) => { captured.heat = props; return <div data-testid="heat" />; }, { Cell: () => null }) }));

const lot = (id: number, name = `장기 주차타워 P${id}`, terminal = "T1"): ParkingChartLot => ({ parking_lot_id: id, parking_lot_name: name, terminal, total_spaces: 100, available_spaces: 20, occupied_spaces: 80, observed_at: "2026-11-13T01:00:00Z" });
test("P1/P2만 터미널별 동심원으로 묶고 같은 이름의 별개 시설은 합치지 않는다", () => {
  expect(groupParkingLots([lot(1), lot(2), lot(3, "장기 주차타워 P3", "T2"), lot(4, "국내선"), lot(5, "국내선")]).map((g) => g.length)).toEqual([2, 1, 1, 1]);
  expect(groupParkingLots([{ ...lot(1), airport_code: "ICN" }, { ...lot(2), airport_code: "GMP" }])).toHaveLength(2);
});
test("0 잔여는 실제 만차이고 결측·불일치는 파이 0으로 만들지 않는다", () => {
  expect(parkingCounts({ ...lot(1), available_spaces: 0, occupied_spaces: 100 })).toEqual({ total: 100, available: 0, occupied: 100 });
  for (const bad of [{ total_spaces: 0 }, { available_spaces: -1 }, { available_spaces: 101 }, { available_spaces: Number.NaN }, { occupied_spaces: 0 }]) expect(parkingCounts({ ...lot(1), ...bad })).toBeNull();
});
test("동심원 각 원은 독립된 전체·잔여·사용 수치를 유지하고 tooltip은 이름을 escape한다", () => {
  render(<ParkingPie lots={[lot(1), { ...lot(2, "<img>P2"), total_spaces: 200, available_spaces: 0, occupied_spaces: 200 }]} />);
  const options = captured.pie!.chartOptions;
  expect(captured.pie!.data).toEqual([{ name: "available", value: 20 }, { name: "occupied", value: 80 }]);
  expect(options.series.map((s) => s.data.map((d) => d.value))).toEqual([[20, 80], [0, 200]]);
  expect(options.series[0].radius).not.toEqual(options.series[1].radius);
  expect(options.tooltip.formatter({ seriesId: "lot-2", seriesName: "<img>P2", name: "잔여", value: 0 })).toContain("&lt;img&gt;P2");
  expect(options.tooltip.triggerOn).toBe("mousemove|click");
});
test("행렬은 null을 빈칸으로 보존하고 0과 소수점 평균·최저·최고·표본을 정확히 전달한다", () => {
  const rows = [{ key: "mon", label: "월요일", hourly_buckets: [
    { hour: 0, average_available_spaces: 0, min_available_spaces: 0, max_available_spaces: 0, observations: 2 },
    { hour: 1, average_available_spaces: null, min_available_spaces: null, max_available_spaces: null, observations: 0 },
    { hour: 2, average_available_spaces: 0.125, min_available_spaces: 0, max_available_spaces: 1, observations: 8 },
  ] }];
  const cells = parkingHeatCells(rows);
  expect(cells.map((c) => c.hour)).toEqual([0, 2]);
  expect(heatCellDescription(cells[1])).toContain("평균 0.125면 · 최저 0면 · 최고 1면 · 관측 8개");
  const onSelect = vi.fn();
  render(<ParkingHeatmapCanvas rows={rows} cells={cells} onSelect={onSelect} />);
  expect(screen.getByTestId("heat")).toBeTruthy();
  expect(captured.heat!.chartOptions.series[0].data).toEqual([[0, 0, 0], [2, 0, 0.125]]);
  expect(captured.heat!.chartOptions.tooltip.formatter({ dataIndex: 1 })).toContain("0.125");
  captured.heat!.onDataSelect(1);
  expect(onSelect).toHaveBeenCalledWith(1);
});


test("실제 ECharts SVG 엔진이 동심원과 시간대 행렬 옵션을 렌더링한다", () => {
  echarts.use([PieChart, CalendarComponent, TooltipComponent]);
  render(<ParkingPie lots={[lot(1), lot(2)]} />);
  const pie = echarts.init(null, undefined, { renderer: "svg", ssr: true, width: 320, height: 240 });
  try {
    pie.setOption({ ...captured.pie!.chartOptions, animation: false, tooltip: { show: false } });
    expect(pie.renderToSVGString()).toContain("<path");
  } finally { pie.dispose(); }
  const rows = [{ key: "holiday", label: "공휴일", hourly_buckets: [{ hour: 12, average_available_spaces: 0.125, min_available_spaces: 0, max_available_spaces: 1, observations: 8 }] }];
  render(<ParkingHeatmapCanvas rows={rows} cells={parkingHeatCells(rows)} onSelect={() => {}} />);
  const heat = echarts.init(null, undefined, { renderer: "svg", ssr: true, width: 680, height: 280 });
  try {
    heat.setOption({ ...captured.heat!.chartOptions, animation: false, tooltip: { show: false } });
    expect(heat.renderToSVGString()).toContain("공휴일");
  } finally { heat.dispose(); }
});
