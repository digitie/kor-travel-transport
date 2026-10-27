// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/journey", async (original) => ({ ...await original<typeof import("@/lib/journey")>(), transportGet: api.get }));
vi.mock("next/link", () => ({ default: ({ href, children, className }: { href: string; children: ReactNode; className?: string }) => <a href={href} className={className}>{children}</a> }));
import { HighwayStatistics } from "./highway-statistics";

const observed = () => new Date(Date.now() - 60_000).toISOString();
const row = (identity: string, routeNo: string, routeName: string, speed: number) => ({ identity_key: identity, route_no: routeNo, route_name: routeName, speed, observed_at: observed() });

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  api.get.mockReset();
  api.get.mockImplementation(async (path: string) => {
    if (path.startsWith("transport/statistics")) return { traffic: [{ route_no: "0010" }, { route_no: "1000" }, { route_no: null }] };
    if (path.includes("route_no=1000")) return { items: [row("1000-a", "1000", "수도권제1순환선", 30), row("1000-b", "1000", "수도권제1순환선", 50)], generated_at: observed() };
    return { items: [row("0010-a", "0010", "경부선", 90), row("0010-b", "0010", "경부선", 70)], generated_at: observed() };
  });
});
afterEach(() => vi.unstubAllGlobals());

test("전체 노선은 1,000행 표본으로 표기하고 노선을 고르면 그 노선 전체를 다시 조회한다", async () => {
  const container = document.createElement("div"); document.body.append(container); const root = createRoot(container);
  try {
    await act(async () => root.render(<HighwayStatistics />));
    const paths = () => api.get.mock.calls.map(([path]) => String(path));
    expect(paths()).toContain("transport/highways/traffic?days=1&limit=1000");
    expect(paths()).toContain("transport/statistics?days=1");
    // 표본에 없고 1일 통계에만 있는 노선도 고를 수 있다.
    const select = container.querySelector<HTMLSelectElement>("select")!;
    expect([...select.options].map((option) => option.value)).toEqual(["", "0010", "1000"]);
    expect(container.textContent).toContain("최근 관측 1,000행 표본");
    expect(container.textContent).toContain("표본 구간 2곳");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!.call(select, "1000");
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(paths()).toContain("transport/highways/traffic?days=1&limit=1000&route_no=1000");
    expect(container.textContent).toContain("선택 노선의 최근 관측");
    expect(container.textContent).toContain("수도권제1순환선");
  } finally { await act(async () => root.unmount()); container.remove(); }
});
