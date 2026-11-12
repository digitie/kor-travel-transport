// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { GeneralRailStationIntent } from "./general-rail-guide";

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/journey", async original => ({ ...await original<typeof import("@/lib/journey")>(), transportGet: api.get }));
vi.mock("@/lib/journey-hooks", () => ({ useSeoulToday: () => "2026-11-12" }));
vi.mock("./general-rail-guide", () => ({ GeneralRailGuide: ({ onStationIntent }: { onStationIntent: (intent: GeneralRailStationIntent) => void }) =>
  <button onClick={() => onStationIntent({ role: "departure", station: { provider: "korail_public_guide", provider_id: "guide-seoul", name: "서울" } })}>서울 출발로 재지정</button> }));

import { GeneralRailJourney } from "./general-rail-journey";

let host: HTMLDivElement, root: Root, releaseCatalog: (value: unknown) => void;
const originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollIntoView");
const catalog = { fetched_at: "2026-11-12T00:00:00Z", stale: false, cities: [{ code: "11", name: "서울" }], train_classes: [] };
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: vi.fn() });
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  api.get.mockReset().mockImplementation((path: string) => {
    if (path.includes("/catalog")) return new Promise(resolve => { releaseCatalog = resolve; });
    if (path.includes("/stations")) return Promise.resolve({ fetched_at: catalog.fetched_at, stale: false, items: [{ station_id: "NAT-SEOUL", station_name: "서울" }] });
    throw new Error("예상하지 않은 요청");
  });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); vi.restoreAllMocks();
  if (originalScroll) Object.defineProperty(HTMLElement.prototype, "scrollIntoView", originalScroll);
  else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
});
function picker(role: string) {
  const label = [...host.querySelectorAll("label")].find(node => node.textContent === role)!;
  return document.getElementById(label.htmlFor) as HTMLInputElement;
}
async function ready() { await act(async () => releaseCatalog(catalog)); }
function lookupButton() { return [...host.querySelectorAll<HTMLButtonElement>("button")].find(node => node.textContent === "예정 시간표 조회")!; }

for (const compact of [false, true]) test("늦은 역 목록과 재마운트가 수동 검색어의 상세 초점을 빼앗지 않는다 compact=" + compact, async () => {
  for (const key of ["list", "map"]) {
    await act(async () => root.render(<aside key={key} aria-label="선택 장소 상세" tabIndex={-1}><GeneralRailJourney initialDepartureName="서울" compact={compact} /></aside>));
    const detail = host.querySelector("aside")!;
    await act(async () => detail.focus());
    expect(picker("출발역").disabled).toBe(true);
    await ready();
    expect(picker("출발역").disabled).toBe(false);
    expect(picker("출발역").value).toBe("서울");
    expect(document.activeElement).toBe(detail);
    expect(lookupButton().disabled).toBe(true);
  }
  expect(api.get.mock.calls.some(([path]) => String(path).includes("/timetable?"))).toBe(false);
});

for (const role of ["departure", "arrival"] as const) test("명시적인 " + role + " 지정은 늦게 준비된 실제 입력칸으로 초점을 안내한다", async () => {
  await act(async () => root.render(<GeneralRailJourney initialStationIntent={{ role, station: { provider: "korail_public_guide", provider_id: "guide-seoul", name: "서울" } }} />));
  await ready();
  const target = picker(role === "departure" ? "출발역" : "도착역");
  expect(document.activeElement).toBe(target); expect(target.value).toBe("서울");
  expect(picker(role === "departure" ? "도착역" : "출발역").value).toBe("");
  expect(lookupButton().disabled).toBe(true);
});

test("같은 역을 다시 지정해도 새 요청은 실제 출발역 입력칸에 초점을 준다", async () => {
  await act(async () => root.render(<GeneralRailJourney initialDepartureName="서울" />)); await ready();
  const toggle = [...host.querySelectorAll<HTMLButtonElement>("button")].find(node => node.textContent === "지도에서 역 선택")!;
  await act(async () => toggle.click());
  const choose = [...host.querySelectorAll<HTMLButtonElement>("button")].find(node => node.textContent === "서울 출발로 재지정")!;
  for (let index = 0; index < 2; index++) {
    await act(async () => { toggle.focus(); choose.click(); });
    expect(document.activeElement).toBe(picker("출발역"));
    expect(picker("출발역").value).toBe("서울"); expect(lookupButton().disabled).toBe(true);
  }
});
