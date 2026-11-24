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


test("지금 이후만은 UTC/KST 정상 DTO의 이후 편을 유지하고 해제하면 지난 편도 보인다", async () => {
  vi.setSystemTime(new Date("2026-11-12T03:00:00Z")); calendar.today = seoulDate();
  const airport = { id: 1, kind: "airport", provider_id: "GMP", source: "fixture", name: "김포", latitude: null, longitude: null, prices: [], line_names: [], facilities: [], updated_at: "2026-11-12T00:00:00Z" };
  const flight = (flight_number: string, scheduled_at: string) => ({ flight_number, scheduled_at, estimated_at: null, direction: "departure", airline: "시험 항공", origin_airport: "GMP", destination_airport: "CJU", status: "예정" });
  fetchMock.mockImplementation(async (url: string) => {
    if (url.includes("features/places")) return json({ items: [airport] });
    if (url.includes("flights/status")) return json({ status: "success", items: [flight("FUTURE", "2026-11-12T12:30:00+09:00"), flight("PAST", "2026-11-12T02:30:00Z")], error_message: null });
    return json({ items: [], generated_at: "2026-11-12T03:00:00Z" });
  });
  await act(async () => root.render(<FlightJourney />));
  const rows = () => [...host.querySelectorAll(".departure-row")].map((row) => row.textContent);
  expect(rows()).toHaveLength(1); expect(rows()[0]).toContain("FUTURE");
  const checkbox = host.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
  expect(checkbox.checked).toBe(true);
  await act(async () => checkbox.click());
  expect(rows()).toHaveLength(2); expect(rows().join()).toContain("PAST");
  await act(async () => checkbox.click());
  expect(rows()).toHaveLength(1); expect(rows()[0]).toContain("FUTURE");
});


// 공항 목록은 장소 지도 입장 제한(backend 429·504)을 받을 수 있다. 전체 새로고침 없이 회복해야 한다.
const catalogAirport = { id: 1, kind: "airport", provider_id: "GMP", source: "fixture", name: "김포", latitude: null, longitude: null, prices: [], line_names: [], facilities: [], updated_at: "2026-11-11T00:00:00Z" };
const problemJson = (status: number, detail: string, retryAfter: string) => new Response(JSON.stringify({ detail }), { status, headers: { "retry-after": retryAfter } });
const catalogCalls = () => fetchMock.mock.calls.filter(([url]) => String(url).includes("features/places")).length;
async function withCatalogClock(run: () => Promise<void>) {
  vi.useRealTimers();
  vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout"] }); vi.setSystemTime(new Date("2026-11-11T14:59:00Z"));
  const random = vi.spyOn(Math, "random").mockReturnValue(0);
  try { await run(); } finally { random.mockRestore(); }
}
const advance = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
function catalogResponses(failures: Response[]) {
  fetchMock.mockImplementation(async (url: string) => {
    if (url.includes("features/places")) return failures.shift() ?? json({ items: [catalogAirport] });
    if (url.includes("flights/status")) return json({ status: "success", items: [], error_message: null });
    return json({ items: [], generated_at: "2026-11-11T00:00:00Z" });
  });
}

test("공항 목록의 일시 혼잡(429)은 Retry-After 뒤 한 번 자동으로 다시 묻고 실패를 보이지 않는다", async () => {
  await withCatalogClock(async () => {
    catalogResponses([problemJson(429, "장소 지도 조회가 혼잡합니다. 잠시 후 다시 시도하세요.", "1")]);
    await act(async () => root.render(<FlightJourney />));
    expect(catalogCalls()).toBe(1);
    expect(host.textContent).not.toContain("공항 목록을 불러오지 못했습니다");
    await advance(1000);
    expect(catalogCalls()).toBe(2);
    expect(host.textContent).not.toContain("공항 목록을 불러오지 못했습니다");
    expect(host.querySelector<HTMLSelectElement>("select")?.selectedOptions[0]?.textContent).toBe("김포");
  });
});

test("공항 목록이 시한 초과(504)로 실패하면 서버 안내를 보이고 Retry-After 뒤 버튼으로 다시 조회한다", async () => {
  await withCatalogClock(async () => {
    catalogResponses([problemJson(504, "장소 지도 조회 시간이 초과되었습니다. 지도 범위를 좁히거나 잠시 후 다시 시도하세요.", "10")]);
    await act(async () => root.render(<FlightJourney />));
    await advance(2000);
    // Retry-After 10초는 자동으로 되풀이하지 않는다.
    expect(catalogCalls()).toBe(1);
    expect(host.textContent).toContain("공항 목록을 불러오지 못했습니다. 장소 지도 조회 시간이 초과되었습니다.");
    const retry = () => [...host.querySelectorAll<HTMLButtonElement>("button")].find(button => button.textContent?.includes("다시 조회") && button.closest('[data-slot="alert"], [role="alert"]'));
    expect(retry()?.disabled).toBe(true);
    // 기존 "주차·항공편 새로고침"도 Retry-After 전에는 공항 목록을 다시 묻지 않는다.
    await click("주차·항공편 새로고침");
    expect(catalogCalls()).toBe(1);
    await advance(8000);
    expect(retry()?.disabled).toBe(false);
    await act(async () => retry()!.click());
    expect(catalogCalls()).toBe(2);
    expect(host.textContent).not.toContain("공항 목록을 불러오지 못했습니다");
    expect(host.querySelector<HTMLSelectElement>("select")?.selectedOptions[0]?.textContent).toBe("김포");
  });
});

test("공항 목록 실패 뒤 기존 새로고침 버튼도 공항 목록을 다시 묻는다", async () => {
  await withCatalogClock(async () => {
    catalogResponses([json({ detail: "server error" }, 500)]);
    await act(async () => root.render(<FlightJourney />));
    expect(host.textContent).toContain("공항 목록을 불러오지 못했습니다.");
    await click("주차·항공편 새로고침");
    await advance(0);
    expect(catalogCalls()).toBe(2);
    expect(host.textContent).not.toContain("공항 목록을 불러오지 못했습니다");
  });
});
