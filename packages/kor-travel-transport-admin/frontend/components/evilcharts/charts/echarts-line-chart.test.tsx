// @vitest-environment jsdom
import { act, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { expect, test, vi } from "vitest";
import { EChartsLineChart } from "./echarts-line-chart";
vi.mock("echarts/core", async importOriginal => {
  const actual = await importOriginal<typeof import("echarts/core")>();
  return { ...actual, init: () => ({ setOption: vi.fn(), on: vi.fn(), resize: vi.fn(), dispose: vi.fn(), dispatchAction: vi.fn(), getWidth: () => 600, getHeight: () => 300, getOption: () => ({}), containPixel: () => true, convertFromPixel: () => [0, 0], getZr: () => ({ on: vi.fn(), off: vi.fn(), add: vi.fn(), remove: vi.fn() }) }) };
});
vi.mock("motion/react", () => ({ useReducedMotion: () => true, domAnimation: {}, LazyMotion: ({ children }: { children: import("react").ReactNode }) => children, m: { div: ({ children, className }: { children: import("react").ReactNode; className: string }) => <div className={className}>{children}</div> } }));
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const data = [{ day: "월", price: 1500 }, { day: "화", price: 1600 }];
const config = { price: { label: "엄격모드유가", colors: { light: ["#0052a4"] } } };
const view = (onSelectionChange: (key: string | null) => void) => <StrictMode><EChartsLineChart data={data} config={config} xDataKey="day" animation={false} onSelectionChange={onSelectionChange}><EChartsLineChart.Line dataKey="price" isClickable /><EChartsLineChart.Legend isClickable /></EChartsLineChart></StrictMode>;

test("StrictMode에서도 선택 callback은 클릭마다 한 번이고 최신 callback을 사용한다", async () => {
  const container = document.createElement("div"), root = createRoot(container), first = vi.fn(), next = vi.fn();
  try {
    await act(async () => root.render(view(first)));
    await act(async () => container.querySelector("button")!.click());
    expect(first.mock.calls).toEqual([["price"]]);
    await act(async () => root.render(view(next)));
    await act(async () => container.querySelector("button")!.click());
    expect(first.mock.calls).toEqual([["price"]]); expect(next.mock.calls).toEqual([[null]]);
  } finally { await act(async () => root.unmount()); }
});

test("같은 batch의 연속 두 클릭도 중간 선택을 잃거나 callback을 중복하지 않는다", async () => {
  const container = document.createElement("div"), root = createRoot(container), change = vi.fn();
  try {
    await act(async () => root.render(view(change)));
    await act(async () => { container.querySelector("button")!.click(); container.querySelector("button")!.click(); });
    expect(change.mock.calls).toEqual([["price"], [null]]);
  } finally { await act(async () => root.unmount()); }
});
