// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { Place } from "@/lib/journey";

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/journey", async (original) => ({ ...await original<typeof import("@/lib/journey")>(), transportGet: api.get }));
vi.mock("@/lib/journey-hooks", () => ({
  useSeoulToday: () => "2026-10-28",
  useNearbyPosition: () => ({ position: null, positionError: null, locating: false, locate: () => {} }),
}));
vi.mock("next/dynamic", () => ({ default: () => function MapFixture({ toolbar, feedback, details, places, selectedPlace, onSelectPlace, view, onViewChange, focusRevision, detailKey }: {
  toolbar?: ReactNode; feedback?: ReactNode; details?: ReactNode; places: Place[]; selectedPlace?: Place | null;
  onSelectPlace: (place: Place) => void; view: string; onViewChange: (view: "map" | "list") => void; focusRevision: number; detailKey?: string;
}) { return <div data-map-view={view} data-map-focus={focusRevision} data-detail-key={detailKey} data-selected-provider={selectedPlace?.provider_id}>
  {toolbar}{feedback}<button onClick={() => onViewChange("list")}>목록 보기 모형</button>
  {places.map((place) => <button key={place.id} data-guide-provider={place.provider_id} data-marker-id={place.id} onClick={() => onSelectPlace(place)}>{place.name} 지도 선택</button>)}{details}
</div>; } }));

import { GeneralRailGuide } from "./general-rail-guide";
import { GeneralRailJourney } from "./general-rail-journey";

const at = "2026-10-28T00:00:00Z";
const guideStations = [
  { provider_id: "GUIDE-SEOUL", station_name: "서울", station_code: "GUIDE-CODE-1", address: "서울 안내 주소", phone: "1588-0000", longitude: 126.97, latitude: 37.55 },
  { provider_id: "GUIDE-BUSAN", station_name: "부산", station_code: "GUIDE-CODE-2", address: "부산 안내 주소", phone: null, longitude: 129.04, latitude: 35.11 },
];
const cities = [{ code: "11", name: "서울" }, { code: "21", name: "부산" }];
function stationPage(city: string) { return { fetched_at: at, stale: false, city_code: city, items: city === "11"
  ? [{ station_id: "NAT-SEOUL-1", station_name: "서울" }, { station_id: "NAT-SEOUL-2", station_name: "서울" }]
  : [{ station_id: "NAT-BUSAN", station_name: "부산" }] }; }
function defaultGet(path: string) {
  const url = new URL(path, "http://fixture");
  if (url.pathname.endsWith("/catalog")) return Promise.resolve({ fetched_at: at, stale: false, cities, train_classes: [{ code: "00", name: "KTX" }] });
  if (url.pathname.endsWith("/guide")) {
    const category = url.searchParams.get("category_code") ?? "";
    return Promise.resolve({ fetched_at: at, stale: false, kind: "ktx", category_code: category, total: category ? 2 : 0,
      categories: [{ code: "ktx1", name: "경부선" }, { code: "ktx2", name: "다른 노선" }],
      items: category === "ktx2" ? [...guideStations].reverse() : category ? guideStations : [] });
  }
  if (url.pathname.endsWith("/stations")) return Promise.resolve(stationPage(url.searchParams.get("city_code")!));
  if (url.pathname.endsWith("/timetable")) return Promise.resolve({ fetched_at: at, stale: false, service_date: "2026-10-29", total: 0, truncated: false, items: [] });
  throw new Error("예상하지 않은 fixture 요청");
}
let root: Root, host: HTMLDivElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-10-28T00:00:00Z"));
  api.get.mockReset().mockImplementation(defaultGet);
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); });
async function change(element: HTMLInputElement | HTMLSelectElement, value: string) {
  await act(async () => {
    const prototype = element instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(element, value);
    element.dispatchEvent(new Event(element instanceof HTMLSelectElement || element.type === "date" ? "change" : "input", { bubbles: true }));
  });
}
function button(text: string, scope: ParentNode = host) { return [...scope.querySelectorAll<HTMLButtonElement>("button")].find((node) => node.textContent === text)!; }
async function click(element: HTMLElement) { expect(element).toBeTruthy(); await act(async () => element.click()); }
function group(label: string) { return [...host.querySelectorAll<HTMLFieldSetElement>("fieldset")].find((node) => node.querySelector("legend")?.textContent === label)!; }
async function chooseTago(label: string, city: string, name: string, node: string) {
  const field = group(label);
  await change(field.querySelector("select")!, city);
  await change(field.querySelector("input")!, name);
  await click(button(name + node, field));
}
async function guideChoice(provider = "GUIDE-SEOUL") {
  const category = host.querySelector<HTMLSelectElement>('select[id$="-category"]')!;
  if (!category.value) await change(category, "ktx1");
  await click(host.querySelector<HTMLElement>(`[data-guide-provider="${provider}"]`)!);
}
const timetableCalls = () => api.get.mock.calls.filter(([path]) => String(path).includes("/timetable?"));

test("안내의 provider 참조로 지정 의도를 전달하며 노선 목록 재정렬에도 지도 표시 ID를 유지한다", async () => {
  const onStationIntent = vi.fn();
  await act(async () => root.render(<GeneralRailGuide onStationIntent={onStationIntent} />));
  await guideChoice();
  const marker = () => host.querySelector('[data-guide-provider="GUIDE-SEOUL"]')!;
  const markerId = marker().getAttribute("data-marker-id");
  expect(host.querySelector('[data-map-view]')?.getAttribute("data-detail-key")).toBe(JSON.stringify(["korail_public_guide", "GUIDE-SEOUL"]));
  await click(button("출발로 지정"));
  expect(onStationIntent).toHaveBeenLastCalledWith({ role: "departure", station: { provider: "korail_public_guide", provider_id: "GUIDE-SEOUL", name: "서울" } });
  await change(host.querySelector('select[id$="-category"]')!, "ktx2");
  expect(marker().getAttribute("data-marker-id")).toBe(markerId);
  expect(button("도착으로 지정")).toBeUndefined(); // 노선 변경의 기존 상세 닫기 동작.
  await guideChoice();
  await click(button("도착으로 지정"));
  expect(onStationIntent).toHaveBeenLastCalledWith({ role: "arrival", station: { provider: "korail_public_guide", provider_id: "GUIDE-SEOUL", name: "서울" } });
  expect(timetableCalls()).toHaveLength(0);
});

test("출발 지정은 이름 hint만 넘기며 반대역·날짜·차종·지도 필터와 보기 상태를 유지한다", async () => {
  await act(async () => root.render(<GeneralRailJourney />));
  await chooseTago("도착역", "21", "부산", "NAT-BUSAN");
  await change(host.querySelector('select[id$="-grade"]')!, "00");
  await change(host.querySelector('input[type="date"]')!, "2026-10-29");
  await guideChoice();
  await change(host.querySelector('input[id$="-query"]')!, "서울");
  await click(button("목록 보기 모형"));
  const focus = host.querySelector('[data-map-view]')!.getAttribute("data-map-focus");
  await click(button("출발로 지정"));
  const from = group("출발역"), to = group("도착역");
  expect(from.querySelector("input")!.value).toBe("서울");
  expect(from.querySelector("select")!.value).toBe("");
  expect(document.activeElement).toBe(from.querySelector("select"));
  expect(from.textContent).not.toContain("조건에 맞는 역이 없습니다");
  expect(to.textContent).toContain("NAT-BUSAN");
  expect(host.querySelector<HTMLSelectElement>('select[id$="-grade"]')!.value).toBe("00");
  expect(host.querySelector<HTMLInputElement>('input[type="date"]')!.value).toBe("2026-10-29");
  expect(host.querySelector('[data-map-view]')!.getAttribute("data-map-view")).toBe("list");
  expect(host.querySelector('[data-map-view]')!.getAttribute("data-map-focus")).toBe(focus);
  expect(host.querySelector<HTMLSelectElement>('select[id$="-category"]')!.value).toBe("ktx1");
  expect(button("예정 운행편 조회").disabled).toBe(true);
  await change(from.querySelector("select")!, "11");
  expect(document.activeElement).toBe(from.querySelector("input"));
  expect(from.querySelectorAll('.station-results button[aria-pressed="true"]')).toHaveLength(0);
  expect(from.querySelectorAll(".station-results button")).toHaveLength(2);
  expect(button("예정 운행편 조회").disabled).toBe(true); // 이름이 같아도 자동 확정하지 않음.
  await click(button("서울NAT-SEOUL-2", from));
  expect(button("예정 운행편 조회").disabled).toBe(false);
  await click(button("예정 운행편 조회"));
  const url = new URL(timetableCalls()[0][0], "http://fixture");
  expect(Object.fromEntries(url.searchParams)).toEqual({ departure_station_id: "NAT-SEOUL-2", arrival_station_id: "NAT-BUSAN", date: "2026-10-29", train_grade_code: "00" });
});

test("같은 역의 도착 지정도 재진입하며 진행 중 옛 시간표를 취소하고 기존 출발을 보존한다", async () => {
  let resolveOld!: (value: unknown) => void;
  api.get.mockImplementation((path: string) => path.includes("/timetable?") ? new Promise((resolve) => { resolveOld = resolve; }) : defaultGet(path));
  await act(async () => root.render(<GeneralRailJourney />));
  await chooseTago("출발역", "11", "서울", "NAT-SEOUL-1");
  await chooseTago("도착역", "21", "부산", "NAT-BUSAN");
  await click(button("예정 운행편 조회"));
  const oldSignal = timetableCalls()[0][1] as AbortSignal;
  await guideChoice("GUIDE-BUSAN");
  await click(button("도착으로 지정"));
  expect(oldSignal.aborted).toBe(true);
  expect(group("출발역").textContent).toContain("NAT-SEOUL-1");
  expect(group("도착역").querySelectorAll('.station-results button[aria-pressed="true"]')).toHaveLength(0);
  expect(document.activeElement).toBe(group("도착역").querySelector("input"));
  expect(button("예정 운행편 조회").disabled).toBe(true); // 후보가 하나여도 수동 확인.
  await act(async () => resolveOld({ fetched_at: at, stale: false, service_date: "2026-10-28", total: 1, truncated: false,
    items: [{ train_number: "OLD-TRAIN", departure_planned_time: "2026-10-28T10:00:00+09:00" }] }));
  expect(host.textContent).not.toContain("OLD-TRAIN");
  await click(button("부산NAT-BUSAN", group("도착역")));
  await change(group("도착역").querySelector("input")!, "다른 검색");
  await click(button("도착으로 지정"));
  expect(group("도착역").querySelector("input")!.value).toBe("부산");
  expect(group("도착역").querySelector("select")!.value).toBe("21");
  expect(button("예정 운행편 조회").disabled).toBe(true);
});

test("지역 전환의 늦은 목록은 후보를 덮지 않고 loading/error를 빈 결과로 표시하지 않는다", async () => {
  let resolveSeoul!: (value: unknown) => void, rejectBusan!: (reason: Error) => void;
  api.get.mockImplementation((path: string) => path.includes("/stations?city_code=11") ? new Promise((resolve) => { resolveSeoul = resolve; })
    : path.includes("/stations?city_code=21") ? new Promise((_resolve, reject) => { rejectBusan = reject; }) : defaultGet(path));
  await act(async () => root.render(<GeneralRailJourney />));
  await guideChoice(); await click(button("출발로 지정"));
  const from = group("출발역");
  await change(from.querySelector("select")!, "11");
  const old = api.get.mock.calls.find(([path]) => path.includes("/stations?city_code=11"))![1] as AbortSignal;
  await change(from.querySelector("select")!, "21");
  expect(old.aborted).toBe(true);
  expect(from.textContent).toContain("조회 중");
  expect(from.textContent).not.toContain("조건에 맞는 역이 없습니다");
  await act(async () => resolveSeoul(stationPage("11")));
  expect(from.querySelectorAll(".station-results button")).toHaveLength(0);
  await act(async () => rejectBusan(new Error("fixture 목록 접근 실패")));
  expect(from.querySelector('[role="alert"]')?.textContent).toBe("fixture 목록 접근 실패");
  expect(from.textContent).not.toContain("조건에 맞는 역이 없습니다");
  expect(button("예정 운행편 조회").disabled).toBe(true);
});

test("이전 출발 지역의 늦은 응답이 새 도착 지정의 초점을 빼앗지 않는다", async () => {
  let resolveDeparture!: (value: unknown) => void;
  api.get.mockImplementation((path: string) => path.includes("/stations?city_code=11")
    ? new Promise((resolve) => { resolveDeparture = resolve; }) : defaultGet(path));
  await act(async () => root.render(<GeneralRailJourney />));
  await guideChoice(); await click(button("출발로 지정"));
  await change(group("출발역").querySelector("select")!, "11");
  await guideChoice("GUIDE-BUSAN"); await click(button("도착으로 지정"));
  const arrivalCity = group("도착역").querySelector("select");
  expect(document.activeElement).toBe(arrivalCity);
  await act(async () => resolveDeparture(stationPage("11")));
  expect(document.activeElement).toBe(arrivalCity);
  expect(group("출발역").querySelector("input")!.value).toBe("서울");
  expect(group("도착역").querySelector("input")!.value).toBe("부산");
});
