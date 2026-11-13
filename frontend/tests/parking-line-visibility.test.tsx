import { act, cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { ParkingLineCanvas } from "@/components/evilcharts/parking-line-canvas";

vi.mock("@/components/evilcharts/charts/echarts-line-chart", () => ({
  EChartsLineChart: Object.assign(({ children, chartOptions }: { children: ReactNode; chartOptions: unknown }) => <div data-testid="visible-engine" data-options={JSON.stringify(chartOptions)}>{children}</div>, { Line: () => null }),
}));

const observers: ControlledResizeObserver[] = [];
class ControlledResizeObserver implements ResizeObserver {
  target: Element | null = null;
  disconnected = false;
  constructor(readonly callback: ResizeObserverCallback) { observers.push(this); }
  observe(target: Element) { this.target = target; }
  unobserve() { this.target = null; }
  disconnect() { this.disconnected = true; }
}
function measure(node: HTMLElement, width: number, height: number) {
  Object.defineProperties(node, { clientWidth: { configurable: true, value: width }, clientHeight: { configurable: true, value: height } });
  act(() => { for (const observer of observers) if (!observer.disconnected && observer.target === node) observer.callback([], observer); });
}
const options = { xAxis: { min: 0, max: 1440 }, series: [{ data: [[0, 0], [30, null]] }] };

beforeEach(() => {
  observers.length = 0;
  vi.stubGlobal("ResizeObserver", ControlledResizeObserver);
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test("크기0인 숨은 컨테이너에서는 실제 엔진을 마운트하지 않는다", () => {
  render(<ParkingLineCanvas options={options} height={320} label="시계열" />);
  const host = screen.getByRole("img", { name: "시계열" });
  measure(host, 0, 320); expect(screen.queryByTestId("visible-engine")).not.toBeInTheDocument();
  measure(host, 1180, 0); expect(screen.queryByTestId("visible-engine")).not.toBeInTheDocument();
  measure(host, 1180, 320); expect(screen.getByTestId("visible-engine")).toBeInTheDocument();
});

test("숨김 뒤 새 options가 와도 엔진은 보류하고 복귀 때 최신 축과 관측0을 복구한다", () => {
  const view = render(<ParkingLineCanvas options={options} height={320} label="시계열" />);
  const host = screen.getByRole("img"); measure(host, 1180, 320);
  expect(screen.getByTestId("visible-engine")).toHaveAttribute("data-options", JSON.stringify(options));
  measure(host, 0, 0); expect(screen.queryByTestId("visible-engine")).not.toBeInTheDocument();
  const latest = { ...options, series: [{ data: [[0, 0], [60, 12]] }] };
  view.rerender(<ParkingLineCanvas options={latest} height={320} label="시계열" />);
  expect(screen.queryByTestId("visible-engine")).not.toBeInTheDocument();
  measure(host, 1180, 320);
  expect(screen.getByTestId("visible-engine")).toHaveAttribute("data-options", JSON.stringify(latest));
});

test("컨테이너 교체와 unmount는 이전 크기 관측자를 정리한다", () => {
  const view = render(<ParkingLineCanvas key="first" options={options} height={280} label="이력" />);
  const first = screen.getByRole("img"); measure(first, 1200, 280);
  const previous = observers.filter((observer) => observer.target === first);
  expect(previous.length).toBeGreaterThan(0);
  view.rerender(<ParkingLineCanvas key="next" options={options} height={280} label="이력" />);
  expect(previous.every((observer) => observer.disconnected)).toBe(true);
  const next = screen.getByRole("img"); expect(next).not.toBe(first); measure(next, 1200, 280);
  const current = observers.filter((observer) => observer.target === next);
  expect(current.length).toBeGreaterThan(0); view.unmount();
  expect(current.every((observer) => observer.disconnected)).toBe(true);
});
