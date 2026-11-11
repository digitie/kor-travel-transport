// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { Place } from "@/lib/journey";
import type { RailStation } from "@/lib/general-rail";

type PickerProps = {id:string;label:string;stations:RailStation[];value:RailStation|null;onChange:(station:RailStation|null)=>void;searchRequest?:{revision:number;text:string}};

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

vi.mock("./general-rail-station-detail",()=>({GeneralRailStationDetail:()=>null}));
vi.mock("./rail-station-picker",()=>({RailStationPicker:({id,label,stations,value,onChange,searchRequest}:PickerProps)=><fieldset><legend>{label}</legend><input id={id} aria-label={`${label} 검색`} value={searchRequest?.text??""} readOnly/><select aria-label={`${label} 후보`} value={value?.station_id??""} onChange={event=>onChange(stations.find(station=>station.station_id===event.target.value)??null)}><option value="">선택</option>{stations.map(station=><option key={station.station_id} value={station.station_id}>{station.station_name} · {station.city_name}</option>)}</select></fieldset>}));

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
const originalScrollIntoView=Object.getOwnPropertyDescriptor(HTMLElement.prototype,"scrollIntoView");
let root: Root, host: HTMLDivElement;
beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype,"scrollIntoView",{configurable:true,value:vi.fn()});
  vi.stubGlobal("ResizeObserver",class{observe(){}unobserve(){}disconnect(){}});
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-10-28T00:00:00Z"));
  api.get.mockReset().mockImplementation(defaultGet);
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks();vi.unstubAllGlobals();if(originalScrollIntoView)Object.defineProperty(HTMLElement.prototype,"scrollIntoView",originalScrollIntoView);else Reflect.deleteProperty(HTMLElement.prototype,"scrollIntoView"); });
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



async function selectGrade(label:string){
 const trigger=host.querySelector<HTMLElement>('[role="combobox"][aria-label="열차 종류"]')!;expect(trigger).toBeTruthy();
 await act(async()=>trigger.dispatchEvent(new KeyboardEvent("keydown",{key:"Enter",bubbles:true,cancelable:true})));
 const option=[...document.querySelectorAll<HTMLElement>('[role="option"]')].find(node=>node.textContent?.trim()===label)!;expect(option).toBeTruthy();
 await act(async()=>option.dispatchEvent(new KeyboardEvent("keydown",{key:"Enter",bubbles:true,cancelable:true})));
}

async function pick(role:string,id:string){await change(group(role).querySelector("select")!,id);}
async function openGuide(){await click(button("지도에서 역 선택"));await guideChoice();}

test("지도 지정은 검색어만 전달하고 반대역·날짜·차종을 보존하며 실제 후보 선택 뒤 조회한다",async()=>{
  await act(async()=>root.render(<GeneralRailJourney/>));
  await pick("도착역","NAT-BUSAN");
  await selectGrade("KTX");
  await change(host.querySelector('input[type="date"]')!,"2026-10-29");
  await openGuide();await click(button("출발로 지정"));
  expect(group("출발역").querySelector("input")!.value).toBe("서울");
  expect(group("출발역").querySelector("select")!.value).toBe("");
  expect(group("도착역").querySelector("select")!.value).toBe("NAT-BUSAN");
  expect(button("예정 시간표 조회").disabled).toBe(true);
  expect(timetableCalls()).toHaveLength(0);
  await pick("출발역","NAT-SEOUL-2");await click(button("예정 시간표 조회"));
  expect(Object.fromEntries(new URL(timetableCalls()[0][0],"http://fixture").searchParams)).toEqual({departure_station_id:"NAT-SEOUL-2",arrival_station_id:"NAT-BUSAN",date:"2026-10-29",train_grade_code:"00"});
});

test("지도 재지정은 진행 중 응답을 취소하며 옛 조건으로 돌아와도 자동 재조회하지 않는다",async()=>{
  let resolveOld!:(value:unknown)=>void;
  api.get.mockImplementation((path:string)=>path.includes("/timetable?")?new Promise(resolve=>{resolveOld=resolve;}):defaultGet(path));
  await act(async()=>root.render(<GeneralRailJourney/>));
  await pick("출발역","NAT-SEOUL-1");await pick("도착역","NAT-BUSAN");await click(button("예정 시간표 조회"));
  const signal=timetableCalls()[0][1] as AbortSignal;
  await openGuide();await guideChoice("GUIDE-BUSAN");await click(button("도착으로 지정"));
  expect(signal.aborted).toBe(true);
  expect(group("출발역").querySelector("select")!.value).toBe("NAT-SEOUL-1");
  expect(group("도착역").querySelector("select")!.value).toBe("");
  await act(async()=>resolveOld({fetched_at:at,stale:false,service_date:"2026-10-28",total:1,truncated:false,items:[{train_number:"OLD-TRAIN",departure_planned_time:"2026-10-28T10:00:00+09:00"}]}));
  await pick("도착역","NAT-BUSAN");
  expect(host.textContent).not.toContain("OLD-TRAIN");expect(timetableCalls()).toHaveLength(1);
  expect(button("예정 시간표 조회").disabled).toBe(false);
});

test("딥링크 이름이 유일해도 실제 시간표 코드를 자동 확정하지 않는다",async()=>{
  await act(async()=>root.render(<GeneralRailJourney initialDepartureName="부산" initialStationIntent={{role:"arrival",station:{provider:"korail_public_guide",provider_id:"GUIDE-BUSAN",name:"부산"}}}/>));
  expect(group("도착역").querySelector("input")!.value).toBe("부산");
  expect(group("도착역").querySelector("select")!.value).toBe("");
  expect(timetableCalls()).toHaveLength(0);
  expect(button("예정 시간표 조회").disabled).toBe(true);
});
