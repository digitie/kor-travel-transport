// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test, vi } from "vitest";
import FuelPriceChart from "./fuel-price-chart";
const capture = vi.hoisted(() => ({ options: {} as Record<string, unknown> }));
vi.mock("./evilcharts/charts/echarts-line-chart", () => ({ EChartsLineChart: ({ chartOptions }: { chartOptions: Record<string, unknown> }) => { capture.options = chartOptions; return <div data-official-chart="true" />; } }));
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
test("공식 EvilCharts에 실제 시간축·최저최고 whisker·안전한 수치 툴팁을 전달한다", async () => {
  const container = document.createElement("div"), root = createRoot(container);
  try {
    await act(async () => root.render(<FuelPriceChart label="검증 차트" series={[{ product: "B027", points: [
      { time: "2026-11-01", average: 1700.35, minimum: 1600.25, maximum: 1900.85, generated_at: "2026-11-01T01:00:00Z", cheapest: { name: '<img src=x onerror="evil()">', longitude: 127, latitude: 37 } },
      { time: "2026-11-04", average: 1701.25, minimum: null, maximum: null },
    ] }]} />));
    await act(async () => { await vi.waitFor(() => expect(capture.options.series).toBeDefined()); });
    expect(container.querySelector('[data-official-chart="true"]')).not.toBeNull();
    expect(capture.options.xAxis).toMatchObject({ type: "time", axisLabel: { hideOverlap: true } });
    const charts = capture.options.series as { id: string; type: string; data: unknown[]; renderItem?: (params: unknown, api: unknown) => { children: unknown[] } }[];
    expect(charts[0].data).toHaveLength(3); // 관측 두 점과 실제 날짜 공백 null.
    expect(charts[1].type).toBe("custom"); expect(charts[1].data).toHaveLength(1);
    const whisker = charts[1].renderItem!({}, { value: (index: number) => [1, 2, 3][index], coord: (pair: number[]) => pair });
    expect(whisker.children).toHaveLength(3);
    const tooltip = capture.options.tooltip as { triggerOn: string; formatter: (params: unknown) => string };
    expect(tooltip.triggerOn).toContain("click");
    const html = tooltip.formatter([{ seriesId: "B027:average", value: (charts[0].data[0]) }]);
    for (const value of ["2026-11-01 00:00", "1,700.35", "1,600.25", "1,900.85", "2026-11-01 10:00", "/fuel?longitude=127&amp;latitude=37"]) expect(html).toContain(value);
    expect(html).not.toContain("<img"); expect(html).toContain("&lt;img");
    const chart = container.querySelector(".fuel-chart-keyboard")!;
    await act(async () => chart.dispatchEvent(new KeyboardEvent("keydown", { key: "End", bubbles: true })));
    expect(container.querySelector('[role="status"]')?.textContent).toContain("미제공");
  } finally { await act(async () => root.unmount()); }
});
