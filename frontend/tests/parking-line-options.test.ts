import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GraphicComponent, GridComponent, MarkAreaComponent, MarkLineComponent, MarkPointComponent, TooltipComponent } from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
import { historyLineOptions, dailyLineOptions } from "@/components/evilcharts/parking-line-options";

echarts.use([LineChart, GraphicComponent, GridComponent, MarkAreaComponent, MarkLineComponent, MarkPointComponent, TooltipComponent, SVGRenderer]);
const points = [null, 0, null, 12, null].map((available, index) => ({ bucket_at: `2026-04-24T00:0${index}:00Z`, available_spaces: available ?? 0, occupied_spaces: 0, total_spaces: 20, lot_observations: available === null ? 0 : 1, x: 18 + index * 311, y: 20 }));
test("history options retain isolated actual zero, null gaps, exact bounds, holiday band, and active point", () => {
  const option = historyLineOptions({ points, width: 1280, bands: [{ x: 18, width: 622, name: "공휴일", day_type: "holiday" }], activeIndex: 2 });
  const line = option.series[0];
  expect(line.data).toEqual([[18, null], [329, 0], [640, null], [951, 12], [1262, null]]);
  expect(line.symbolSize([], { dataIndex: 1 })).toBe(8);
  expect(line.symbolSize([], { dataIndex: 3 })).toBe(8);
  expect(line.symbolSize([], { dataIndex: 2 })).toBe(0);
  expect(line.markPoint.data.map((point) => point.coord)).toEqual([[951, 12]]);
  expect(option.xAxis).toMatchObject({ min: 18, max: 1262 });
  expect(line.markArea.data[0]).toMatchObject([{ name: "공휴일", xAxis: 18 }, { xAxis: 640 }]);
});
test("daily lines preserve nulls and stable date colors; flight callbacks remain independent", () => {
  const onHover = vi.fn(), onSelect = vi.fn();
  const option = dailyLineOptions({ allDates: ["2026-04-23", "2026-04-24"], lines: [{ localDate: "2026-04-24", label: "4/24", specialDayType: "holiday", specialDayName: "공휴일", points: [{ minuteOfDay: 0, availableSpaces: 0 }, { minuteOfDay: 30, availableSpaces: null }, { minuteOfDay: 60, availableSpaces: 12 }] }], width: 1180, maxValue: 20, flights: [{ key: "flight", x: 100, y: 40, label: "KE1101", direction: "departure" }], activeFlightKey: null, onHover, onSelect });
  expect(option.series[0].data).toEqual([[0, 0], [30, null], [60, 12]]);
  expect(option.series[0].connectNulls).toBe(false);
  expect(option.series[0].lineStyle).toMatchObject({ type: "dashed", color: "var(--color-chart-series-1)" });
  expect(option.xAxis.axisLabel.formatter(1440)).toBe("24:00");
  expect(option.graphic[0].children.map((child) => child.z)).toEqual([10, 11]);
  option.graphic[0].onmouseover(); option.graphic[0].onclick(); option.graphic[0].onmouseout();
  expect(onHover.mock.calls).toEqual([["flight"], [null]]); expect(onSelect).toHaveBeenCalledWith("flight");
});
test("real ECharts renders the discontinuous history series and holidays without invented future x bounds", () => {
  const chart = echarts.init(null, undefined, { renderer: "svg", ssr: true, width: 1280, height: 280 });
  const option = historyLineOptions({ points, width: 1280, bands: [{ x: 18, width: 622, name: "공휴일", day_type: "holiday" }], activeIndex: 1 });
  try {
    chart.setOption(option);
    const actual = chart.getOption() as { series: { data: unknown[]; connectNulls: boolean }[]; xAxis: { min: number; max: number }[] };
    expect(actual.series[0].data).toEqual(option.series[0].data);
    expect(actual.series[0].connectNulls).toBe(false);
    expect(actual.xAxis[0]).toMatchObject({ min: 18, max: 1262 });
    expect(chart.renderToSVGString()).toContain("<svg");
    expect(chart.renderToSVGString()).toContain("공휴일");
  } finally { chart.dispose(); }
});
