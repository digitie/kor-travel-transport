// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { BusJourney } from "./bus-journey";
import { FlightJourney } from "./flight-journey";
import { seoulDate } from "@/lib/journey";

const calendar = vi.hoisted(() => ({ today: "" }));
vi.mock("@/lib/journey-hooks", () => ({
  useSeoulToday: () => calendar.today,
  useNearbyPosition: () => ({ position: null, positionError: "", locating: false, locate: () => {} }),
}));
vi.mock("next/dynamic", () => ({ default: () => function MapFixture({ toolbar, feedback, listContent, listCount, details }: { details?: ReactNode; toolbar?: ReactNode; feedback?: ReactNode; listContent?: ReactNode; listCount?: number }) {
  return <div data-testid="map" data-list-count={listCount} data-has-detail={Boolean(details)}>{toolbar}{feedback}{listContent}</div>;
} }));
vi.mock("./journey-controls", () => ({ PlaceDetails: () => null }));
const terminals = [
  { id: 1, terminal_id: "SEO", terminal_name: "서울", city_name: "서울", latitude: null, longitude: null, updated_at: "2026-11-11T00:00:00Z" },
  { id: 2, terminal_id: "BUS", terminal_name: "부산", city_name: "부산", latitude: null, longitude: null, updated_at: "2026-11-11T00:00:00Z" },
];
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
function deferred<T>() { let resolve!: (value: T) => void; return { promise: new Promise<T>(done => { resolve = done; }), resolve: (value: T) => resolve(value) }; }
let root: Root, host: HTMLDivElement;
let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date("2026-11-11T14:59:00Z"));
  calendar.today = seoulDate();
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  fetchMock = vi.fn(async () => json({ items: terminals, next_offset: null })); vi.stubGlobal("fetch", fetchMock);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.useRealTimers(); vi.unstubAllGlobals(); });
async function input(selector: string, value: string) {
  const node = host.querySelector<HTMLInputElement>(selector)!;
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(node, value); node.dispatchEvent(new Event("input", { bubbles: true })); });
}
async function click(label: string, within: Element = host) {
  const node = [...within.querySelectorAll<HTMLButtonElement>("button")].find(item => item.textContent?.trim() === label)!;
  expect(node, label).toBeDefined(); await act(async () => node.click());
}
async function chooseRoute(type: "express" | "intercity" = "express") {
  await act(async () => root.render(<BusJourney type={type} />));
  await input('[id="bus-출발 터미널"]', "서울");
  await click("서울서울 · SEO", host.querySelectorAll(".terminal-search")[0]);
  await click("부산부산 · BUS", host.querySelectorAll(".terminal-search")[1]);
}
function timetable(name: string) { return { service_date: calendar.today, fetched_at: "2026-11-11T14:00:00Z", items: [{ departure_planned_time: "235900", arrival_planned_time: "275900", departure_terminal_name: "서울", arrival_terminal_name: name, grade_name: "우등", adult_fare: 20000 }] }; }

test("터미널 필터의 실제 표시 행 수를 같은 검색 모델에서 계산한다", async () => {
  await act(async () => root.render(<BusJourney type="express" />));
  expect(host.querySelector('[data-testid="map"]')?.getAttribute("data-list-count")).toBe("0");
  expect(host.querySelector('[data-testid="map"]')?.getAttribute("data-has-detail")).toBe("false");
  await input('[id="bus-출발 터미널"]', "서울");
  expect(host.querySelectorAll(".station-results button")).toHaveLength(1);
  expect(host.querySelector('[data-testid="map"]')?.getAttribute("data-list-count")).toBe("1");
  await input('[id="bus-도착 터미널"]', "부산");
  expect(host.querySelectorAll(".station-results button")).toHaveLength(2);
  expect(host.querySelector('[data-testid="map"]')?.getAttribute("data-list-count")).toBe("2");
});

test("운행일 변경은 진행 요청을 취소하고 늦은 옛 시간표가 새 날짜를 덮지 않는다", async () => {
  const old = deferred<Response>(); let signal: AbortSignal | undefined;
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url.includes("bus/timetable")) { signal = init?.signal as AbortSignal; return old.promise; }
    return json({ items: terminals, next_offset: null });
  });
  await chooseRoute(); await click("운행편 조회");
  expect(host.textContent).toContain("운행편 확인 중…");
  await input("#bus-service-date", "2026-11-12");
  expect(signal?.aborted).toBe(true);
  expect(host.textContent).not.toContain("운행편 확인 중…");
  await act(async () => old.resolve(json(timetable("옛 날짜 응답"))));
  expect(host.textContent).not.toContain("옛 날짜 응답");
  expect(host.textContent).toContain("출발·도착지를 선택하고 운행편을 조회하세요.");
});

test("시외버스 한국 날짜가 넘어가면 기존 날짜의 결과를 즉시 숨긴다", async () => {
  fetchMock.mockImplementation(async (url: string) => url.includes("bus/timetable") ? json(timetable("어제 운행편")) : json({ items: terminals, next_offset: null }));
  await chooseRoute("intercity"); await click("운행편 조회");
  expect(host.textContent).toContain("어제 운행편");
  vi.setSystemTime(new Date("2026-11-11T15:01:00Z")); calendar.today = seoulDate();
  await act(async () => root.render(<BusJourney type="intercity" />));
  expect(host.textContent).not.toContain("어제 운행편");
  expect(host.querySelector<HTMLInputElement>("#bus-service-date")?.value).toBe("2026-11-12");
});

test("공항 주차 HTTP 실패는 요청 정체를 유지해 무한 로딩으로 보이지 않는다", async () => {
  const airport = { id: 1, kind: "airport", provider_id: "GMP", source: "fixture", name: "김포", latitude: null, longitude: null, prices: [], line_names: [], facilities: [], updated_at: "2026-11-11T00:00:00Z" };
  fetchMock.mockImplementation(async (url: string) => {
    if (url.includes("features/places")) return json({ items: [airport] });
    if (url.includes("parking/current")) return json({ detail: "현재 주차 조회 실패" }, 503);
    if (url.includes("flights/status")) return json({ status: "success", items: [], error_message: null });
    return json({ items: [], generated_at: "2026-11-11T00:00:00Z" });
  });
  await act(async () => root.render(<FlightJourney />));
  expect(host.textContent).toContain("주차 현황을 불러오지 못했습니다.");
  expect(host.textContent).not.toContain("주차 현황을 확인하는 중입니다…");
});
