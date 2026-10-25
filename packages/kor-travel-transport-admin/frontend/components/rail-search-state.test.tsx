// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { Place } from "@/lib/journey";

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/journey", async (original) => ({ ...await original<typeof import("@/lib/journey")>(), transportGet: api.get }));
vi.mock("@/lib/journey-hooks", () => ({ useNearbyPosition: () => ({ position: null, positionError: null, locate: () => {}, locating: false }) }));
vi.mock("next/dynamic", () => ({ default: () => function MapFixture({ toolbar, feedback, listContent, places }: { toolbar?: ReactNode; feedback?: ReactNode; listContent?: ReactNode; places: Place[] }) { return <div>{toolbar}<section data-testid="result-flow">{feedback}{listContent}{places.map((place) => <button key={place.id}>{place.name}</button>)}</section></div>; } }));
import { MetroJourney } from "./metro-journey";
import { GeneralRailGuide } from "./general-rail-guide";

beforeEach(() => { Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); api.get.mockReset(); });
afterEach(() => vi.unstubAllGlobals());
const at = "2026-10-25T01:00:00Z";
const station = { id: 1, provider_id: "S1", kind: "rail_station", source: "kric_public_file", name: "시험역", subtitle: "시험기관", line_names: ["시험선"], prices: [], facilities: [], longitude: 127.1, latitude: 37.3, updated_at: at };

for (const scenario of [
  { name: "도시철도", Component: MetroJourney, retry: "새로고침", loading: "불러오는 중", response: { items: [station] } },
  { name: "일반철도", Component: GeneralRailGuide, retry: "다시 조회", loading: "조회 중", response: { fetched_at: at, stale: false, kind: "ktx", category_code: "", categories: [], total: 1, items: [{ provider_id: "S1", station_name: "시험역", longitude: 127.1, latitude: 37.3 }] } },
]) test(`${scenario.name}는 로딩·실패를 빈 검색 결과로 보이지 않고 성공 뒤 안내를 복원한다`, async () => {
  let rejectInitial!: (error: Error) => void, resolveRetry!: (value: unknown) => void;
  api.get.mockReturnValueOnce(new Promise((_resolve, reject) => { rejectInitial = reject; })).mockReturnValueOnce(new Promise((resolve) => { resolveRetry = resolve; }));
  const container = document.createElement("div"); document.body.append(container); const root = createRoot(container);
  const result = () => container.querySelector<HTMLElement>('[data-testid="result-flow"]')!;
  const search = (value: string) => { const input = container.querySelector<HTMLInputElement>('input[type="search"]')!; Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); };
  try {
    const Component = scenario.Component;
    await act(async () => root.render(<Component />));
    await act(async () => search("없는역명"));
    expect(result().textContent).toContain(scenario.loading); expect(result().textContent).not.toContain("조건에 맞는 역이 없습니다");
    await act(async () => rejectInitial(new Error("역 fixture 조회 실패")));
    expect(result().querySelector('[role="alert"]')).not.toBeNull(); expect(result().textContent).not.toContain("조건에 맞는 역이 없습니다");
    await act(async () => [...container.querySelectorAll("button")].find((node) => node.textContent === scenario.retry)!.click());
    expect(result().querySelector('[role="alert"]')).toBeNull(); expect(result().textContent).toContain(scenario.loading); expect(result().textContent).not.toContain("조건에 맞는 역이 없습니다");
    await act(async () => resolveRetry(scenario.response));
    expect(result().textContent).toContain("조건에 맞는 역이 없습니다");
    await act(async () => search("시험역"));
    expect(result().textContent).not.toContain("조건에 맞는 역이 없습니다"); expect(result().querySelector("button")?.textContent).toBe("시험역");
  } finally { await act(async () => root.unmount()); container.remove(); }
});
