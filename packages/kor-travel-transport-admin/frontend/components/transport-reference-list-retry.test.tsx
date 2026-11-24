// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { TransportReferenceList } from "./transport-reference-list";

// 역·항구 기준정보 목록(limit=5000)도 장소 지도 입장 제한(backend 429·504)을 받는다. 자동 재조회와 Retry-After 뒤 새로고침을 검사한다.
vi.mock("@/lib/journey-hooks", () => ({ useSeoulToday: () => "2026-11-11" }));
vi.mock("next/dynamic", () => ({ default: () => function MapFixture({ toolbar, feedback, listContent }: { toolbar?: ReactNode; feedback?: ReactNode; listContent?: ReactNode }) {
  return <div data-testid="map">{toolbar}{feedback}{listContent}</div>;
} }));
vi.mock("./journey-controls", () => ({ PlaceDetails: () => null, MultiSearch: () => null, FerryDepartures: () => null }));
vi.mock("./rail-timetables", () => ({ RailTimetables: () => null }));

const station = { id: 1, kind: "rail_station", source: "fixture", name: "시험역", provider_id: "S1", longitude: 127.1, latitude: 37.3, line_names: ["시험선"], facilities: [], prices: [], updated_at: "2026-11-11T00:00:00Z" };
const problem = (status: number, detail: string, retryAfter: string) => new Response(JSON.stringify({ detail }), { status, headers: { "retry-after": retryAfter } });
let root: Root, host: HTMLDivElement, fetchMock: ReturnType<typeof vi.fn>;
let failures: Response[];
const catalogCalls = () => fetchMock.mock.calls.filter(([url]) => String(url).includes("features/places")).length;
const advance = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
const refreshButton = () => [...host.querySelectorAll<HTMLButtonElement>("button")].find(button => button.textContent?.includes("새로고침"));

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout"] }); vi.setSystemTime(new Date("2026-11-11T03:00:00Z"));
  vi.spyOn(Math, "random").mockReturnValue(0);
  failures = [];
  fetchMock = vi.fn(async (url: string) => url.includes("features/places")
    ? failures.shift() ?? new Response(JSON.stringify({ items: [station] }))
    : new Response(JSON.stringify({ items: [] })));
  vi.stubGlobal("fetch", fetchMock);
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.useRealTimers(); vi.unstubAllGlobals(); });

test("일시 혼잡(429)은 Retry-After 뒤 한 번 자동으로 다시 묻고 실패를 보이지 않는다", async () => {
  failures = [problem(429, "장소 지도 조회가 혼잡합니다. 잠시 후 다시 시도하세요.", "2")];
  await act(async () => root.render(<TransportReferenceList kind="rail_station" />));
  expect(catalogCalls()).toBe(1);
  await advance(1999);
  expect(catalogCalls()).toBe(1);
  await advance(1);
  expect(catalogCalls()).toBe(2);
  expect(host.textContent).not.toContain("기준정보를 불러오지 못했습니다");
  expect(host.textContent).toContain("저장된 역 1곳");
});

test("두 번 연속 혼잡이면 서버 안내를 보이고 Retry-After가 지나야 새로고침할 수 있다", async () => {
  failures = [problem(429, "장소 지도 조회가 혼잡합니다. 잠시 후 다시 시도하세요.", "2"), problem(429, "장소 지도 조회가 혼잡합니다. 잠시 후 다시 시도하세요.", "2")];
  await act(async () => root.render(<TransportReferenceList kind="rail_station" />));
  await advance(2000);
  expect(catalogCalls()).toBe(2);
  expect(host.textContent).toContain("기준정보를 불러오지 못했습니다. 장소 지도 조회가 혼잡합니다.");
  expect(refreshButton()?.disabled).toBe(true);
  await advance(2000);
  expect(refreshButton()?.disabled).toBe(false);
  await act(async () => refreshButton()!.click());
  expect(catalogCalls()).toBe(3);
  expect(host.textContent).not.toContain("기준정보를 불러오지 못했습니다");
  expect(host.textContent).toContain("저장된 역 1곳");
});
