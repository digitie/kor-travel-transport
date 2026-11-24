// @vitest-environment jsdom
import { act, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { Place } from "@/lib/journey";
import { publicFuelGet } from "@/lib/public-fuel";

const toastCalls = vi.hoisted(() => ({ success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() }));
vi.mock("sonner", () => ({ toast: toastCalls }));

const mapState = vi.hoisted(() => ({ longitude: 128.53, latitude: 37.6, zoom: 12.5 }));
vi.mock("maplibre-gl", () => ({ setWorkerUrl: vi.fn() }));
vi.mock("vworld-map-web", async () => {
  const React = await import("react");
  return {
    VWorldMapView: ({ children, onLoad, onMoveEnd, center, zoom }: { children: React.ReactNode; onLoad: (map: unknown) => void; onMoveEnd: (event: unknown) => void; center: number[]; zoom: number }) => {
      const map = React.useMemo(() => ({ getBounds: () => ({ getWest: () => 124, getSouth: () => 32, getEast: () => 132, getNorth: () => 39 }), getZoom: () => mapState.zoom, getCenter: () => ({ lng: mapState.longitude, lat: mapState.latitude }) }), []);
      React.useEffect(() => { onLoad(map); }, [map, onLoad]);
      return <div data-testid="fixture-map" data-center={center.join(",")} data-zoom={zoom}><button onClick={() => onMoveEnd({ target: map })}>지도 이동 모의</button>{children}</div>;
    },
    ClusterLayer: ({ points, renderMarker }: { points: { id: string }[]; renderMarker: (point: unknown) => React.ReactNode }) => <>{points.map((point) => <React.Fragment key={point.id}>{renderMarker(point)}</React.Fragment>)}</>,
  };
});
vi.mock("./map-overlays", () => ({
  vworldApiKey: () => undefined, useVWorldBasemapHealth: () => ({}), ZoomButtons: () => null, CameraRequest: ({ target }: { target?: unknown }) => <span data-camera-request={JSON.stringify(target)} />, MarkerBadge: () => null, ClusterBubble: () => null, MapUnavailable: () => null, OverlapPopup: () => null,
  MapMarkerButton: ({ ariaLabel, onClick, children, className }: { ariaLabel: string; onClick: () => void; children: React.ReactNode; className?: string }) => <button className={className} aria-label={ariaLabel} onClick={onClick}>{children}</button>,
}));
vi.mock("./filter-combobox", () => ({ FilterCombobox: ({ options, value, onChange, placeholder }: { options: {value:string;label:string}[]; value:string[]; onChange:(value:string[])=>void; placeholder:string }) => <select aria-label={placeholder} value={value[0] ?? ""} onChange={event=>onChange(event.target.value ? [event.target.value] : [])}><option value="">전체</option>{options.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select> }));
import { TransportMap } from "./transport-map";
import { layoutFuelRegionCards } from "@/lib/fuel-region-layout";
import { GeneralRailGuide } from "./general-rail-guide";

test("역 지도는 서버 HTML부터 공통 작업면과 지도·목록 탭을 제공한다", () => {
  const container = document.createElement("div");
  container.innerHTML = renderToStaticMarkup(<GeneralRailGuide />);
  const workspace = container.querySelector(
    'section[aria-label="철도 역 지도"] .map-workbench [data-slot="map-workspace"]',
  );
  expect(workspace).not.toBeNull();
  const tabs = Array.from(workspace?.querySelectorAll('[role="tab"]') ?? []);
  expect(tabs).toHaveLength(2);
  expect(tabs.some(tab => tab.textContent?.includes("지도"))).toBe(true);
  expect(tabs.some(tab => tab.textContent?.includes("목록"))).toBe(true);
});

test.each([[1120, 832], [351, 787]])("지역 카드 배치는 %sx%s에서 충돌과 범위 통계 영역을 피하며 부족한 공간을 알린다", (width, height) => {
  const cards = Array.from({ length: 12 }, () => ({ left: 110, top: 140, width: 130, height: 130 }));
  const reserved = { left: 8, top: 8, width: Math.min(384, width - 16), height: 90 };
  const offsets = layoutFuelRegionCards(cards, width, height, [reserved]);
  const placed = offsets.flatMap((offset, index) => offset.placed ? [{ ...cards[index], left: cards[index].left + offset.x, top: cards[index].top + offset.y }] : []);
  expect(placed.length).toBeGreaterThan(1);
  const overlap = (a: typeof reserved, b: typeof reserved) => a.left < b.left + b.width && a.left + a.width > b.left && a.top < b.top + b.height && a.top + a.height > b.top;
  for (const [index, rect] of placed.entries()) {
    expect(rect.left).toBeGreaterThanOrEqual(8); expect(rect.top).toBeGreaterThanOrEqual(8);
    expect(rect.left + rect.width).toBeLessThanOrEqual(width - 8);
    expect(rect.top + rect.height).toBeLessThanOrEqual(height - 8);
    expect(overlap(rect, reserved)).toBe(false);
    for (const other of placed.slice(index + 1)) expect(overlap(rect, other)).toBe(false);
  }
  expect(cards.every(card => card.left === 110 && card.top === 140)).toBe(true);
  if (width < 400) expect(offsets.some(offset => !offset.placed)).toBe(true);
  else expect(placed).toHaveLength(cards.length);
});

test("지역 카드는 별도 목록·토글 없이 지도 마커로만 전5유종과 미제공을 읽고 원좌표로 확대한다", async () => {
  Object.assign(mapState, { zoom: 7 });
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ items: [], total: 2, clustered: true, clusters: [], fuel_regions: [
    { region_key: "opinet:11", label: "서울특별시", product_code: "B027", average_price: 1700, station_count: 1, longitude: 127, latitude: 37.5 },
    { region_key: "opinet:41", label: "경기도", product_code: "D047", average_price: 1600, station_count: 1, longitude: 127.5, latitude: 37.7 },
  ] })));
  const container = document.createElement("div"); document.body.append(container); const root = createRoot(container);
  try {
    await act(async () => root.render(<TransportMap mode="fuel" />));
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 50)); });
    expect(container.querySelector(".kt-map-count")?.textContent).toBe("2건 표시");
    // 삭제한 "지역 카드 모두 보기 (n)" 토글과 그 목록은 다시 생기지 않는다.
    expect([...container.querySelectorAll("button")].some(button => button.textContent?.includes("지역 카드"))).toBe(false);
    expect(container.querySelector('[aria-label="모든 지역 유가"]')).toBeNull();
    expect(container.querySelector(".fuel-region-access")).toBeNull();
    const markers = [...container.querySelectorAll<HTMLButtonElement>("button.fuel-region-marker")];
    expect(markers).toHaveLength(2);
    for (const marker of markers) for (const label of ["휘발유", "경유", "고급유", "등유", "LPG", "미제공"]) expect(marker.getAttribute("aria-label")).toContain(label);
    const gyeonggi = markers.find(marker => marker.getAttribute("aria-label")?.startsWith("경기도"))!;
    gyeonggi.focus(); expect(document.activeElement).toBe(gyeonggi);
    await act(async () => gyeonggi.click());
    expect(JSON.parse(container.querySelector('[data-camera-request]')!.getAttribute("data-camera-request")!)).toMatchObject({ center: [127.5, 37.7], zoom: 8 });
  } finally { await act(async () => root.unmount()); container.remove(); }
});

test("공간이 모자라 접은 지역 카드도 키보드 탭 순서와 접근 이름을 유지한다", async () => {
  Object.assign(mapState, { zoom: 7 });
  const bounds = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function(this: HTMLElement) {
    return this.classList.contains("map-primary") ? new DOMRect(0, 0, 351, 190)
      : this.classList.contains("fuel-region-marker") ? new DOMRect(110, 140, 130, 130) : new DOMRect();
  });
  const width = vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockImplementation(function(this: HTMLElement) { return this.classList.contains("fuel-region-label") ? 130 : 0; });
  const height = vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockImplementation(function(this: HTMLElement) { return this.classList.contains("fuel-region-label") ? 130 : 0; });
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ items: [], total: 2, clustered: true, clusters: [], fuel_regions: [
    { region_key: "opinet:11", label: "서울특별시", product_code: "B027", average_price: 1700, station_count: 1, longitude: 127, latitude: 37.5 },
    { region_key: "opinet:41", label: "경기도", product_code: "D047", average_price: 1600, station_count: 1, longitude: 127.5, latitude: 37.7 },
  ] })));
  const container = document.createElement("div"); document.body.append(container); const root = createRoot(container);
  try {
    await act(async () => { root.render(<TransportMap mode="fuel" />); });
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 100)); });
    const markers = [...container.querySelectorAll<HTMLButtonElement>(".fuel-region-marker")];
    const overflowed = markers.filter(marker => marker.dataset.regionOverflow === "true");
    expect(overflowed.length).toBeGreaterThan(0);
    for (const marker of overflowed) {
      expect(marker.hasAttribute("aria-hidden")).toBe(false);
      expect(marker.tabIndex).not.toBe(-1);
      expect(marker.getAttribute("aria-label")).toContain("원/L");
      marker.focus(); expect(document.activeElement).toBe(marker);
    }
    expect(container.querySelector('[aria-label="모든 지역 유가"]')).toBeNull();
  } finally {
    await act(async () => root.unmount()); container.remove();
    bounds.mockRestore(); width.mockRestore(); height.mockRestore();
  }
});

const station: Place = { id: 1, kind: "rail_station", source: "kric_public_file", name: "시험역", longitude: 127.1, latitude: 37.3, line_names: ["시험선"], facilities: [], prices: [], updated_at: "2026-10-25T00:00:00Z" };

test("교통 지도는 일반 주차장 필터를 요청하고 좌표 없는 주차장은 목록에만 둔다", async () => {
  const parking: Place = { ...station, id: 12, kind: "public_parking_lot", source: "datagokr_parking_lots", name: "좌표없는 주차장", latitude: null, longitude: null, line_names: [], parking_capacity: 20 };
  vi.mocked(fetch).mockImplementation(async input => {
    const url = new URL(String(input), "http://test");
    const items = !url.searchParams.has("kind") || url.searchParams.get("kind") === "public_parking_lot" ? [parking] : [];
    return new Response(JSON.stringify({ items, total: items.length, truncated: false }));
  });
  const container = document.createElement("div"); document.body.append(container); const root = createRoot(container);
  try {
    await act(async () => root.render(<TransportMap mode="transport" />));
    const requests = () => vi.mocked(fetch).mock.calls.map(call => new URL(String(call[0]), "http://test"));
    expect(requests().some(url => url.searchParams.get("kinds")?.split(",").includes("public_parking_lot"))).toBe(true);
    expect(container.querySelector(".transport-map-marker.public_parking_lot")).toBeNull();
    await act(async () => [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find(button => button.textContent?.includes("목록"))!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
    expect(container.querySelector(".place-row")?.textContent).toContain(parking.name);
    expect(container.querySelector(".place-row")?.textContent).toContain("좌표 미등록");
    expect(requests().some(url => url.searchParams.get("kind") === "public_parking_lot" && url.searchParams.get("include_unlocated") === "true")).toBe(true);
  } finally { await act(async () => root.unmount()); container.remove(); }
});

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true, ResizeObserver: class { observe() {} unobserve() {} disconnect() {} } });
  vi.stubGlobal("fetch", vi.fn());
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  Object.assign(mapState, { longitude: 128.53, latitude: 37.6, zoom: 12.5 });
});
afterEach(() => vi.unstubAllGlobals());

test.each([7, 9])("줌%s 지역 카드 하나에 모든 유종을 함께 표시하고 평균 문구·누락 가격 대체를 넣지 않는다", async (zoom) => {
  Object.assign(mapState, { zoom });
  const regions = [
    ...["B027", "D047", "B034", "K015"].map((product_code, index) => ({region_key:"opinet:11",label:"서울특별시",product_code,average_price:1700+index*100,station_count:3,longitude:127+index*.01,latitude:37.5})),
    {region_key:"opinet:41",label:"경기도",product_code:"D047",average_price:1600,station_count:2,longitude:127.5,latitude:37.7},
  ];
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({items:[],total:5,clustered:true,clusters:[],fuel_regions:regions}), {status:200}));
  const container=document.createElement("div");document.body.append(container);const root=createRoot(container);
  try {
    await act(async()=>root.render(<TransportMap mode="fuel"/>));
    await act(async()=>{await new Promise(resolve=>setTimeout(resolve,50));});
    const cards=container.querySelectorAll(".fuel-region-marker");
    expect(cards).toHaveLength(2);
    const seoul=[...cards].find(card=>card.textContent?.includes("서울특별시"))!;
    for (const label of ["휘발유", "경유", "고급유", "등유", "LPG"]) expect(seoul.textContent).toContain(label);
    for (const price of ["1,700", "1,800", "1,900", "2,000"]) expect(seoul.textContent).toContain(price);
    expect(seoul.textContent).toContain("미제공");
    expect(seoul.textContent).not.toContain("평균");
    expect(seoul.getAttribute("aria-label")).toContain("경유 1800원/L");
    expect(seoul.getAttribute("aria-label")).not.toContain("평균");
    const gyeonggi=[...cards].find(card=>card.textContent?.includes("경기도"))!;
    expect(gyeonggi.textContent).toContain("1,600");expect(gyeonggi.textContent).not.toContain("1,700");
  } finally {await act(async()=>root.unmount());container.remove();}
});

test("지역은 유종 선택과 무관하게 함께 읽고 확대된 주유소에는 선택 유종 필터를 유지한다", async () => {
  Object.assign(mapState, {zoom:7});
  vi.mocked(fetch).mockImplementation(async()=>new Response(JSON.stringify({items:[],total:2,clustered:true,clusters:[],fuel_regions:[
    {region_key:"opinet:11",label:"서울특별시",product_code:"B027",average_price:1700,station_count:1,longitude:127,latitude:37.5},
    {region_key:"opinet:11",label:"서울특별시",product_code:"D047",average_price:1600,station_count:1,longitude:127,latitude:37.5},
  ]}),{status:200}));
  const container=document.createElement("div");document.body.append(container);const root=createRoot(container);
  const lastUrl=()=>new URL(String(vi.mocked(fetch).mock.calls.at(-1)?.[0]),"http://test");
  try {
    await act(async()=>root.render(<TransportMap mode="fuel"/>));
    await act(async()=>{const select=container.querySelector<HTMLSelectElement>('select[aria-label="전체 유종"]')!;select.value="D047";select.dispatchEvent(new Event("change",{bubbles:true}));});
    await act(async()=>{await new Promise(resolve=>setTimeout(resolve,50));});
    // 공개 gateway가 마지막 kind를 강제하므로 실제 지도 요청도 단일 kind여야 한다.
    expect(lastUrl().searchParams.get("kind")).toBe("fuel_station");
    expect(lastUrl().searchParams.has("kinds")).toBe(false);
    expect(lastUrl().searchParams.has("product_codes")).toBe(false);
    expect(container.querySelector(".fuel-region-marker")?.textContent).toContain("1,700");
    expect(container.querySelector(".fuel-region-marker")?.textContent).toContain("1,600");
    Object.assign(mapState,{zoom:12.5});
    await act(async()=>[...container.querySelectorAll("button")].find(button=>button.textContent==="지도 이동 모의")!.click());
    await act(async()=>{await new Promise(resolve=>setTimeout(resolve,450));});
    expect(lastUrl().searchParams.get("product_codes")).toBe("D047");
    expect(lastUrl().searchParams.get("kind")).toBe("fuel_station");
    expect(lastUrl().searchParams.has("kinds")).toBe(false);
    // 관리 유가 지도는 공개 화면 전용 시군구 목록·지도 중심 시군구를 묻지 않는다(응답 바이트 불변).
    for (const url of vi.mocked(fetch).mock.calls.map(([value]) => new URL(String(value), "http://test"))) {
      for (const key of ["include_viewport_sigungu", "center_longitude", "center_latitude"]) expect(url.searchParams.has(key)).toBe(false);
    }
  } finally {await act(async()=>root.unmount());container.remove();}
});

test("외부 장소 지도는 자체 API를 호출하지 않고 이동을 카메라 prop으로 되먹이지 않으며 목록 왕복에는 마지막 카메라로 다시 연다", async () => {
  const container = document.createElement("div"); document.body.append(container); const root = createRoot(container);
  try {
    await act(async () => root.render(<TransportMap places={[station]} />));
    expect(container.querySelector('[aria-label="선택 장소 상세"]')).toBeNull();
    const camera = () => container.querySelector('[data-testid="fixture-map"]')!;
    const readout = () => container.querySelector(".kt-map-coordinates")!.textContent;
    // mount 시점 카메라가 유지된다. 실제 카메라는 readout에만 반영한다(SDK가 prop 변화마다 ease를 다시 걸지 않게).
    expect(camera().getAttribute("data-center")).toBe("127.8,36.2");
    expect(camera().getAttribute("data-zoom")).toBe("7");
    expect(readout()).toBe("center 128.5300, 37.6000 · z 12.5");
    Object.assign(mapState, { longitude: 129.1, latitude: 35.2, zoom: 14 });
    await act(async () => [...container.querySelectorAll("button")].find((node) => node.textContent === "지도 이동 모의")!.click());
    expect(camera().getAttribute("data-center")).toBe("127.8,36.2");
    expect(camera().getAttribute("data-zoom")).toBe("7");
    expect(readout()).toBe("center 129.1000, 35.2000 · z 14.0");
    await act(async () => container.querySelector<HTMLButtonElement>('[role="tab"][id]')?.focus());
    await act(async () => [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((node) => node.textContent?.includes("목록"))!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
    expect(container.querySelector('[data-testid="fixture-map"]')).toBeNull();
    await act(async () => [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((node) => node.textContent?.includes("지도"))!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
    expect(camera().getAttribute("data-center")).toBe("129.1,35.2");
    expect(camera().getAttribute("data-zoom")).toBe("14");
    expect(fetch).not.toHaveBeenCalled();
  } finally { await act(async () => root.unmount()); container.remove(); }
});

test("장소 선택 없는 도로 detailKey도 공용 상세를 열고 Escape로 닫는다", async () => {
  const dismiss = vi.fn();
  function Highway() { const [opened, setOpened] = useState(true); return <TransportMap places={[]} selectedPlace={null} detailKey={opened ? "road:1" : undefined} detailTitle="시험 소통 구간" details={opened ? <p>속도 80 km/h</p> : undefined} onCloseDetails={() => { dismiss(); setOpened(false); }} />; }
  const container = document.createElement("div"); document.body.append(container); const root = createRoot(container);
  try {
    await act(async () => root.render(<Highway />));
    const detail = container.querySelector<HTMLElement>('[aria-label="선택 장소 상세"]')!;
    expect(detail.textContent).toContain("시험 소통 구간");
    expect(detail.textContent).toContain("80 km/h");
    await act(async () => detail.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
    expect(dismiss).toHaveBeenCalledOnce();
    expect(container.querySelector('[aria-label="선택 장소 상세"]')).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
  } finally { await act(async () => root.unmount()); container.remove(); }
});

test("목록 선택이 지도로 전환돼도 활성 상세에 초점을 두고 Escape 뒤 보이는 컨트롤로 복귀한다", async () => {
  function Route() {
    const [selected, setSelected] = useState<Place | null>(null);
    const [view, setView] = useState<"map" | "list">("list");
    return <TransportMap places={[station]} selectedPlace={selected} onSelectPlace={(place) => { setSelected(place); setView("map"); }} details={selected ? <p>선택 역 위치</p> : undefined} onCloseDetails={() => setSelected(null)} view={view} onViewChange={setView} />;
  }
  const container = document.createElement("div"); document.body.append(container); const root = createRoot(container);
  try {
    await act(async () => root.render(<Route />));
    const opener = container.querySelector<HTMLButtonElement>(".place-row")!;
    await act(async () => { opener.focus(); opener.click(); });
    const panel = () => container.querySelector<HTMLElement>('[data-view="map"] [aria-label="선택 장소 상세"]')!;
    await act(async () => { await vi.waitFor(() => expect(document.activeElement).toBe(panel())); });
    await act(async () => panel().dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
    await act(async () => { await vi.waitFor(() => expect(container.querySelector('[aria-label="선택 장소 상세"]')).toBeNull()); });
    await act(async () => { await vi.waitFor(() => expect(document.activeElement).toBe(container.querySelector('[role="tab"][aria-selected="true"]'))); });
  } finally { await act(async () => root.unmount()); container.remove(); }
});

test("별도 목록 건수는 좌표나 추가 지물과 합산하지 않고 지도 건수에는 영향을 주지 않는다", async () => {
  const container = document.createElement("div"); document.body.append(container); const root = createRoot(container);
  const places = [station, { ...station, id: 2, longitude: null, latitude: null }];
  const count = () => container.querySelector(".kt-map-count")!.textContent;
  try {
    await act(async () => root.render(<TransportMap places={places} view="list" listCount={6} listPlaces={false} listFeatureCount={5} />));
    expect(count()).toBe("6건 표시");
    await act(async () => root.render(<TransportMap places={places} view="list" listCount={0} listPlaces={false} listFeatureCount={5} />));
    expect(count()).toBe("0건 표시");
    await act(async () => root.render(<TransportMap places={places} view="map" listCount={6} mapFeatureCount={3} />));
    expect(count()).toBe("4건 표시");
    await act(async () => root.render(<TransportMap places={places} view="list" listFeatureCount={5} />));
    expect(count()).toBe("7건 표시");
    expect(fetch).not.toHaveBeenCalled();
  } finally { await act(async () => root.unmount()); container.remove(); }
});

test("숨긴 기본 장소는 목록 건수에 넣지 않고 추가 목록 지물만 센다", async () => {
  const container = document.createElement("div"); document.body.append(container); const root = createRoot(container);
  try {
    await act(async () => root.render(<TransportMap places={[station]} view="list" listPlaces={false} />));
    expect(container.querySelectorAll(".place-row")).toHaveLength(0);
    expect(container.querySelector(".kt-map-count")!.textContent).toBe("0건 표시");
    await act(async () => root.render(<TransportMap places={[station]} view="list" listPlaces={false} listFeatureCount={3} />));
    expect(container.querySelector(".kt-map-count")!.textContent).toBe("3건 표시");
  } finally { await act(async () => root.unmount()); container.remove(); }
});

test("지도 왕복은 목록 내부 검색 상태를 언마운트하지 않는다", async () => {
  function Search() { const [query, setQuery] = useState(""); return <input aria-label="목록 검색" value={query} onChange={(event) => setQuery(event.target.value)} />; }
  const container = document.createElement("div"); document.body.append(container); const root = createRoot(container);
  const tab = (name: string) => [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((node) => node.textContent?.includes(name))!;
  try {
    await act(async () => root.render(<TransportMap places={[station]} listPlaces={false} listContent={<Search />} />));
    await act(async () => tab("목록").click());
    const input = container.querySelector<HTMLInputElement>('[aria-label="목록 검색"]')!;
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "서울"); input.dispatchEvent(new Event("input", { bubbles: true })); });
    expect(input.value).toBe("서울");
    await act(async () => tab("지도").click());
    await act(async () => tab("목록").click());
    expect(container.querySelector<HTMLInputElement>('[aria-label="목록 검색"]')!.value).toBe("서울");
    expect(container.querySelector('[aria-label="목록 검색"]')).toBe(input);
    expect(fetch).not.toHaveBeenCalled();
  } finally { await act(async () => root.unmount()); container.remove(); }
});

test("숨긴 목록에는 선택 상세를 중복 마운트하지 않는다", async () => {
  const mounted = vi.fn(), unmounted = vi.fn();
  function Inspector() { useEffect(() => { mounted(); return () => { unmounted(); }; }, []); return <p data-testid="inspector-probe">선택 장소 정보</p>; }
  const container = document.createElement("div"); document.body.append(container); const root = createRoot(container);
  try {
    await act(async () => root.render(<TransportMap places={[station]} selectedPlace={station} details={<Inspector />} />));
    expect(mounted).toHaveBeenCalledTimes(1); expect(container.querySelectorAll('[data-testid="inspector-probe"]')).toHaveLength(1);
    await act(async () => [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((node) => node.textContent?.includes("목록"))!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
    expect(mounted).toHaveBeenCalledTimes(2); expect(unmounted).toHaveBeenCalledTimes(1);
    expect(container.querySelectorAll('[data-testid="inspector-probe"]')).toHaveLength(1);
  } finally { await act(async () => root.unmount()); container.remove(); }
});

test("주유소 지도 마커와 목록 모두 실제 상표 코드의 로고와 접근 이름을 사용한다", async () => {
  const fuel: Place = { ...station, id: 77, kind: "fuel_station", source: "opinet_browser", name: "시험 주유소", brand_code: "SOL", brand_name: "S-OIL", line_names: [] };
  const container = document.createElement("div"); document.body.append(container); const root = createRoot(container);
  try {
    await act(async () => root.render(<TransportMap places={[fuel]} mode="fuel" />));
    expect(container.querySelector('button[aria-label*="시험 주유소 S-OIL"] img')?.getAttribute("src")).toBe("/fuel-brands/soil.gif");
    await act(async () => [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((node) => node.textContent?.includes("목록"))!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
    expect(container.querySelector(".place-row img")?.getAttribute("alt")).toBe("S-OIL");
    expect(fetch).not.toHaveBeenCalled();
  } finally { await act(async () => root.unmount()); container.remove(); }
});


test("품질인증·전산보고는 마커 아이콘과 접근 이름에 함께 나온다", async () => {
  const fuel: Place = { ...station, id: 78, kind: "fuel_station", source: "opinet_browser", name: "인증 주유소", brand_code: "SOL", brand_name: "S-OIL", line_names: [], facilities: ["셀프"], is_kpetro: true, is_electronic: true };
  const container = document.createElement("div"); document.body.append(container); const root = createRoot(container);
  try {
    await act(async () => root.render(<TransportMap places={[fuel]} mode="fuel" />));
    const marker = container.querySelector<HTMLButtonElement>('button[aria-label*="인증 주유소"]')!;
    expect(marker.getAttribute("aria-label")).toContain("S-OIL 품질인증 전산보고");
    expect(marker.querySelectorAll(".fuel-cert-mark")).toHaveLength(2);
  } finally { await act(async () => root.unmount()); container.remove(); }
});

test("집계만 바뀐 같은 좌표 묶음은 DOM과 키보드 초점을 유지한다", async () => {
 let count=2;
 Object.assign(mapState,{zoom:7});
 vi.mocked(fetch).mockImplementation(async()=>new Response(JSON.stringify({items:[],total:count,clustered:true,clusters:[{longitude:127,latitude:37,count,kind_counts:{fuel_station:count}}]})));
 const host=document.createElement("div");document.body.append(host);const root=createRoot(host);
 try{
  await act(async()=>root.render(<TransportMap mode="fuel"/>));
  const cluster=()=>host.querySelector<HTMLButtonElement>(".map-cluster")!;
  expect(cluster()?.getAttribute("aria-label")).toBe("2개 장소 요약 묶음 확대");
  const original=cluster();original.focus();expect(document.activeElement).toBe(original);
  count=3;Object.assign(mapState,{zoom:8});
  await act(async()=>[...host.querySelectorAll("button")].find(button=>button.textContent==="지도 이동 모의")!.click());
  await act(async()=>{await new Promise(resolve=>setTimeout(resolve,450));});
  expect(cluster()?.getAttribute("aria-label")).toBe("3개 장소 요약 묶음 확대");
  expect(cluster()).toBe(original);expect(document.activeElement).toBe(original);
 }finally{await act(async()=>root.unmount());host.remove();}
});


test("서로 가까운 두 묶음도 집계와 순서가 바뀔 때 각 DOM과 초점을 보존한다", async () => {
 let updated=false;
 Object.assign(mapState,{zoom:7});
 vi.mocked(fetch).mockImplementation(async()=>{
  const first={longitude:126.9999999,latitude:37,count:updated?3:2,kind_counts:{fuel_station:updated?3:2}};
  const second={longitude:127.0000001,latitude:37,count:5,kind_counts:{fuel_station:5}};
  return new Response(JSON.stringify({items:[],total:updated?8:7,clustered:true,clusters:updated?[second,first]:[first,second]}));
 });
 const host=document.createElement("div");document.body.append(host);const root=createRoot(host);
 const cluster=(count:number)=>host.querySelector<HTMLButtonElement>(`.map-cluster[aria-label="${count}개 장소 요약 묶음 확대"]`)!;
 try{
  await act(async()=>root.render(<TransportMap mode="fuel"/>));
  const first=cluster(2),second=cluster(5);
  expect(first).not.toBeNull();expect(second).not.toBeNull();first.focus();
  expect(document.activeElement).toBe(first);
  updated=true;Object.assign(mapState,{zoom:8});
  await act(async()=>[...host.querySelectorAll("button")].find(button=>button.textContent==="지도 이동 모의")!.click());
  await act(async()=>{await new Promise(resolve=>setTimeout(resolve,450));});
  expect(cluster(3)).toBe(first);expect(cluster(5)).toBe(second);
  expect(host.querySelectorAll(".map-cluster")).toHaveLength(2);
  expect(document.activeElement).toBe(first);
 }finally{await act(async()=>root.unmount());host.remove();}
});

test("공개 지도는 모든 축척에서 유종을 요청에 반영하고 단일 유종 마커에서 이름을 뺀다", async () => {
  Object.assign(mapState, { zoom: 7 });
  const region = { region_key: "opinet:11", label: "서울", product_code: "C004", average_price: 1300, station_count: 1, longitude: 127, latitude: 37.5 };
  vi.mocked(fetch).mockImplementation(async () => Response.json({ items: [], total: 1, truncated: false, clustered: true, clusters: [], fuel_regions: [region] }));
  const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
  try {
    await act(async () => root.render(<TransportMap mode="fuel" mapOnly publicFuel={{ products: ["C004"], onProductsChange: vi.fn() }} />));
    expect(host.querySelector('[data-slot="map-filter-trigger"]')).toBeNull();
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("product_codes=C004"))).toBe(true);
    // 첫 이동 알림 전의 기본 범위는 실제 중심과 대칭이 아니라 중심을 묻지 않는다.
    const placesUrls = () => vi.mocked(fetch).mock.calls.map(([url]) => new URL(String(url), "http://test")).filter(url => url.pathname.includes("places"));
    expect(placesUrls()[0].searchParams.has("center_longitude")).toBe(false);
    // 지도가 범위를 알리면 지도 중심 시군구를 조회 범위(양자화된 범위)의 가운데로 묻는다.
    Object.assign(mapState, { zoom: 9.2 });
    await act(async () => [...host.querySelectorAll("button")].find(button => button.textContent === "지도 이동 모의")!.click());
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 450)); });
    const placesUrl = placesUrls().at(-1)!;
    expect(placesUrl.searchParams.get("min_longitude")).toBe("124.00");
    expect(placesUrl.searchParams.get("center_longitude")).toBe("128.00000");
    expect(placesUrl.searchParams.get("center_latitude")).toBe("35.50000");
    const middle = (low: string, high: string) => (Number(placesUrl.searchParams.get(low)) + Number(placesUrl.searchParams.get(high))) / 2;
    expect(Number(placesUrl.searchParams.get("center_longitude"))).toBeCloseTo(middle("min_longitude", "max_longitude"), 4);
    expect(Number(placesUrl.searchParams.get("center_latitude"))).toBeCloseTo(middle("min_latitude", "max_latitude"), 4);
    const marker = host.querySelector("button.fuel-region-marker");
    expect(marker?.textContent).toContain("1,300");
    expect(marker?.textContent).not.toContain("등유");
    expect(marker?.getAttribute("aria-label")).toContain("등유");
  } finally { await act(async () => root.unmount()); host.remove(); }
});

test("가격 아이콘 하나: 오래된 가격은 보이는 주유소 9곳이면 갱신·적용하고 10곳이면 이유와 함께 비활성", async () => {
  Object.assign(mapState, { zoom: 12.5 });
  toastCalls.success.mockClear();
  let count = 9, nextPrice = 1300;
  const stale = true;
  const products = ["C004"];
  const stations = () => Array.from({ length: count }, (_, i): Place => ({
    ...station, id: i + 70, kind: "fuel_station", source: "opinet_browser", name: `시험 ${i + 1} 주유소`,
    longitude: 127 + i * .01, latitude: 37, line_names: [],
    prices: [{ product_code: "C004", price: nextPrice, observed_at: "2026-11-21T00:00:00Z" }],
  }));
  const postRequests: unknown[] = [];
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input) === "/api/public/fuel/refresh") {
      postRequests.push(JSON.parse(String(init?.body)));
      if (postRequests.length === 1) {
        return Response.json({ results: Array.from({ length: 9 }, (_, i) => ({ station_id: i + 70, status: "cooldown" })) });
      }
      nextPrice = 1450;
      count = 10;
      return Response.json({ results: Array.from({ length: 9 }, (_, i) => ({ station_id: i + 70, status: "updated" })) });
    }
    return Response.json({ items: stations(), total: count, truncated: false, fuel_prices_stale: stale, fuel_prices_last_refreshed_at: "2026-11-21T00:00:00Z" });
  });
  const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
  const refreshButton = () => host.querySelector<HTMLButtonElement>(".public-fuel-price-button");
  try {
    await act(async () => root.render(<TransportMap mode="fuel" mapOnly publicFuel={{ products, onProductsChange: vi.fn(), refreshEnabled: true }} />));
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 360)); });
    expect(host.querySelector(".map-marker-price")?.textContent).toBe("1,300");
    // 지도 위 따로 있던 업데이트 단추는 없다(범위 요약의 가격 아이콘 하나).
    expect(host.querySelector('.public-fuel-map-refresh, button[aria-label="지도 범위 유가 업데이트"]')).toBeNull();
    expect(refreshButton()?.getAttribute("aria-label")).toBe("가격 오래됨 · 지도 범위 유가 업데이트");
    await act(async () => refreshButton()!.click());
    expect(toastCalls.info).toHaveBeenCalledWith("최근 갱신 요청이 있었습니다. 잠시 뒤 다시 시도해 주세요.");
    expect(toastCalls.success).not.toHaveBeenCalled();
    expect(host.querySelector(".map-marker-price")?.textContent).toBe("1,300");
    await act(async () => refreshButton()!.click());
    expect(postRequests).toEqual(Array.from({ length: 2 }, () => ({
      viewport: { min_longitude: 124, min_latitude: 32, max_longitude: 132, max_latitude: 39, product_codes: products },
    })));
    expect(toastCalls.success).toHaveBeenCalledWith("유가 업데이트 완료");
    expect(host.querySelector(".map-marker-price")?.textContent).toBe("1,450");
    // 10곳이면 서버 한도(9곳)를 넘어 누를 수 없고 이유를 알린다.
    expect(refreshButton()?.getAttribute("aria-disabled")).toBe("true");
    expect(refreshButton()?.getAttribute("aria-label")).toContain("지도에 보이는 주유소가 1~9곳일 때만");
    await act(async () => refreshButton()!.click());
    expect(postRequests).toHaveLength(2);
  } finally { await act(async () => root.unmount()); host.remove(); }
});

// 장소 지도 입장 제한(backend 429·504)과 한 번 자동 재조회(lib/place-retry.ts). 가짜 timer로 Retry-After 경계를 잰다.
const placesCalls = () => vi.mocked(fetch).mock.calls.map(call => String(call[0])).filter(url => url.includes("places"));
const countOf = (url: string) => placesCalls().filter(entry => entry === url).length;
const problem = (status: number, detail: string | null, retryAfter: string | null) => new Response(detail === null ? null : JSON.stringify({ detail }), {
  status, headers: { "content-type": "application/problem+json", ...(retryAfter === null ? {} : { "retry-after": retryAfter }) },
});
const BUSY = "장소 지도 조회가 혼잡합니다. 잠시 후 다시 시도하세요.";
const TIMEOUT = "장소 지도 조회 시간이 초과되었습니다. 지도 범위를 좁히거나 잠시 후 다시 시도하세요.";
const tick = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

async function withMapClock(run: (host: HTMLDivElement, root: ReturnType<typeof createRoot>, unmount: () => Promise<void>) => Promise<void>) {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
  // 재조회 jitter를 0으로 고정해 Retry-After 경계를 정확히 잰다.
  const random = vi.spyOn(Math, "random").mockReturnValue(0);
  const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
  let mounted = true;
  const unmount = async () => { if (mounted) { mounted = false; await act(async () => root.unmount()); } };
  try {
    await run(host, root, unmount);
  } finally {
    await unmount(); host.remove(); random.mockRestore(); vi.useRealTimers();
  }
}
const alerts = (host: HTMLElement) => [...host.querySelectorAll('[role="alert"]')].map(node => node.textContent ?? "").join("|");
// 다시 조회 버튼은 알림 밖(같은 실패 줄)에 있다. 버튼 이름이 바뀌어도 알림 전체가 다시 읽히지 않는다.
const retryButton = (host: HTMLElement) => [...host.querySelectorAll<HTMLButtonElement>('.map-failure > button')].find(button => button.textContent?.includes("다시 조회"));

test("일시 혼잡(429, Retry-After 1초)은 Retry-After 뒤 같은 조건으로 한 번만 다시 묻고 실패 안내 없이 결과를 그린다", async () => {
  vi.mocked(fetch).mockImplementation(async input => countOf(String(input)) === 1
    ? problem(429, BUSY, "1") : Response.json({ items: [station], total: 1, truncated: false }));
  await withMapClock(async (host, root) => {
    await act(async () => root.render(<TransportMap mode="transport" />));
    const initial = placesCalls()[0];
    await tick(300); // 지도 범위 알림(250ms 지연) → 실제 범위 요청이 429를 받는다.
    const real = placesCalls().at(-1)!;
    expect(real).not.toBe(initial);
    expect(countOf(real)).toBe(1);
    // 재조회를 기다리는 동안 실패 안내 없이 "다시 조회 중…"으로 둔다.
    expect(alerts(host)).not.toContain("조회 실패");
    expect(host.querySelector(".kt-map-count")?.textContent).toBe("다시 조회 중…");
    await tick(900);
    expect(countOf(real)).toBe(1); // Retry-After(1초)가 지나기 전에는 다시 묻지 않는다.
    await tick(200);
    expect(countOf(real)).toBe(2);
    expect(alerts(host)).not.toContain("조회 실패");
    expect(host.querySelector(".transport-map-marker.rail_station")).not.toBeNull();
    // 첫 기본 범위 요청은 실제 범위로 바뀌며 취소돼 다시 묻지 않는다.
    expect(countOf(initial)).toBe(1);
  });
});

test("backend 시한 초과(504, Retry-After 10초)는 되풀이하지 않고 서버 안내와 함께 10초 뒤에만 다시 조회를 허락한다", async () => {
  vi.mocked(fetch).mockImplementation(async () => problem(504, TIMEOUT, "10"));
  await withMapClock(async (host, root) => {
    await act(async () => root.render(<TransportMap mode="transport" />));
    await tick(300);
    await tick(5000);
    const urls = placesCalls();
    expect(new Set(urls).size).toBe(urls.length);
    expect(alerts(host)).toContain("조회 실패");
    expect(alerts(host)).toContain("지도 범위를 좁히거나");
    expect(retryButton(host)?.disabled).toBe(true);
    expect(retryButton(host)?.textContent).toBe("잠시 후 다시 조회");
    await tick(5500);
    expect(retryButton(host)?.disabled).toBe(false);
    expect(retryButton(host)?.textContent).toBe("다시 조회");
    const before = placesCalls().length;
    await act(async () => retryButton(host)!.click());
    expect(placesCalls().length).toBe(before + 1);
  });
});

test("Retry-After 없는 504(gateway 시한)는 자동으로 다시 묻지 않는다", async () => {
  vi.mocked(fetch).mockImplementation(async () => problem(504, null, null));
  await withMapClock(async (host, root) => {
    await act(async () => root.render(<TransportMap mode="transport" />));
    await tick(300);
    await tick(10_000);
    const urls = placesCalls();
    expect(urls.length).toBe(2);
    expect(new Set(urls).size).toBe(2);
    expect(alerts(host)).toContain("조회 실패");
    expect(retryButton(host)?.disabled).toBe(false);
  });
});

test("재조회를 기다리는 동안 지도 범위가 바뀌면 이전 범위는 다시 묻지 않고 새 범위만 묻는다", async () => {
  vi.mocked(fetch).mockImplementation(async input => countOf(String(input)) === 1
    ? problem(429, BUSY, "2") : Response.json({ items: [station], total: 1, truncated: false }));
  await withMapClock(async (host, root) => {
    await act(async () => root.render(<TransportMap mode="transport" />));
    await tick(300);
    const first = placesCalls().at(-1)!;
    Object.assign(mapState, { zoom: 14 });
    await act(async () => [...host.querySelectorAll("button")].find(button => button.textContent === "지도 이동 모의")!.click());
    await tick(300);
    const second = placesCalls().at(-1)!;
    expect(second).not.toBe(first);
    await tick(5000);
    expect(countOf(first)).toBe(1);
    expect(countOf(second)).toBe(2);
    expect(alerts(host)).not.toContain("조회 실패");
  });
});

test("재조회를 기다리는 동안 화면을 떠나면 더 묻지 않는다", async () => {
  vi.mocked(fetch).mockImplementation(async () => problem(429, BUSY, "2"));
  await withMapClock(async (_host, root, unmount) => {
    await act(async () => root.render(<TransportMap mode="transport" />));
    await tick(300);
    const before = placesCalls().length;
    await unmount();
    await tick(10_000);
    expect(placesCalls().length).toBe(before);
  });
});

test("목록 보기의 종류별 조회도 일시 혼잡을 한 번 다시 묻는다", async () => {
  vi.mocked(fetch).mockImplementation(async input => {
    const url = new URL(String(input), "http://test");
    if (url.searchParams.get("kind") === "rail_station") {
      return countOf(String(input)) === 1 ? problem(429, BUSY, "1") : Response.json({ items: [station], total: 1, truncated: false });
    }
    return Response.json({ items: [], total: 0, truncated: false });
  });
  await withMapClock(async (host, root) => {
    await act(async () => root.render(<TransportMap mode="transport" />));
    await tick(300);
    await act(async () => [...host.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find(button => button.textContent?.includes("목록"))!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
    await tick(2000);
    const rail = placesCalls().filter(url => new URL(url, "http://test").searchParams.get("kind") === "rail_station");
    expect(rail.length).toBe(2);
    expect(new Set(rail).size).toBe(1);
    expect(alerts(host)).not.toContain("조회 실패");
    expect(host.querySelector(".place-row")?.textContent).toContain(station.name);
  });
});

test("공개 유가 지도(publicFuelGet)도 혼잡을 한 번 다시 묻고, 시한 초과는 backend 안내를 보인다", async () => {
  const region = { region_key: "opinet:11", label: "서울", product_code: "B027", average_price: 1700, station_count: 1, longitude: 127, latitude: 37.5 };
  let mode: "busy" | "timeout" = "busy";
  vi.mocked(fetch).mockImplementation(async input => {
    const url = String(input);
    if (!url.startsWith("/api/public/fuel/places")) return Response.json({});
    if (mode === "timeout") return problem(504, TIMEOUT, "10");
    return countOf(url) === 1 ? problem(429, BUSY, "1")
      : Response.json({ items: [], total: 1, truncated: false, clustered: true, clusters: [], fuel_regions: [region] });
  });
  Object.assign(mapState, { zoom: 7 });
  // 공개 화면(components/public-fuel-map.tsx)처럼 공유 지도의 관리 경로 앞부분만 떼고 공개 reader로 묻는다.
  const loadFuel: typeof publicFuelGet = (path, signal) => publicFuelGet(path.replace(/^transport\//, ""), signal);
  await withMapClock(async (host, root) => {
    await act(async () => root.render(<TransportMap mode="fuel" mapOnly load={loadFuel} publicFuel={{ products: ["B027"], onProductsChange: vi.fn() }} />));
    await tick(300);
    const real = placesCalls().at(-1)!;
    expect(real.startsWith("/api/public/fuel/places")).toBe(true);
    await tick(1600);
    expect(countOf(real)).toBe(2);
    expect(alerts(host)).not.toContain("조회 실패");
    expect(host.querySelector("button.fuel-region-marker")?.textContent).toContain("1,700");
    mode = "timeout";
    Object.assign(mapState, { zoom: 8.5 });
    await act(async () => [...host.querySelectorAll("button")].find(button => button.textContent === "지도 이동 모의")!.click());
    await tick(300);
    await tick(3000);
    const timedOut = placesCalls().at(-1)!;
    expect(countOf(timedOut)).toBe(1);
    expect(alerts(host)).toContain("지도 범위를 좁히거나");
  });
});

// 유가 화면: 한 번의 조회 실패는 한 알림(role=alert)으로만 읽힌다. 범위 통계 칸은 글만 보인다.
const visibleAlerts = (host: HTMLElement) => [...host.querySelectorAll('[role="alert"]')]
  .filter(node => !node.closest('[hidden], [data-state="inactive"]')).map(node => node.textContent ?? "");
const loadFuel: typeof publicFuelGet = (path, signal) => publicFuelGet(path.replace(/^transport\//, ""), signal);
const fuelMap = (isPublic: boolean) => isPublic
  ? <TransportMap mode="fuel" mapOnly load={loadFuel} publicFuel={{ products: ["B027"], onProductsChange: vi.fn() }} />
  : <TransportMap mode="fuel" />;

test.each([["관리 /fuel", false], ["공개 유가 지도", true]])("%s 조회 실패는 범위 통계를 담은 알림 하나로만 알리고 버튼은 알림 밖에 둔다", async (_name, isPublic) => {
  vi.mocked(fetch).mockImplementation(async input => String(input).includes("places") ? problem(504, TIMEOUT, "10") : Response.json({}));
  Object.assign(mapState, { zoom: 12 });
  await withMapClock(async (host, root) => {
    await act(async () => root.render(fuelMap(isPublic)));
    await tick(300);
    await tick(100);
    const shown = visibleAlerts(host);
    expect(shown).toHaveLength(1);
    expect(shown[0]).toContain("주유소·범위 통계 조회 실패");
    expect(shown[0]).toContain("지도 범위를 좁히거나");
    expect(shown[0]).not.toContain("다시 조회");
    expect(host.querySelector('[role="alert"] button')).toBeNull();
    expect(retryButton(host)?.textContent).toBe("잠시 후 다시 조회");
    const summary = host.querySelector('[aria-label="현재 지도 범위 유가 통계"]')!;
    expect(summary.textContent).toContain("통계를 불러오지 못했습니다");
    expect(summary.querySelector('[role="alert"]')).toBeNull();
    // Retry-After가 지나 버튼 이름이 바뀌어도 알림 문구는 그대로다(다시 읽히지 않는다).
    const before = host.querySelector('[role="alert"]');
    await tick(10_000);
    expect(retryButton(host)?.textContent).toBe("다시 조회");
    expect(host.querySelector('[role="alert"]')).toBe(before);
    expect(visibleAlerts(host)).toEqual(shown);
  });
});

test("목록 보기 유가 실패는 묻지 않은 범위 통계를 말하지 않고, 교통 지도도 범위 통계 문구가 없다", async () => {
  vi.mocked(fetch).mockImplementation(async () => problem(504, TIMEOUT, "10"));
  await withMapClock(async (host, root) => {
    await act(async () => root.render(<TransportMap mode="fuel" />));
    await tick(300);
    await act(async () => [...host.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find(button => button.textContent?.includes("목록"))!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
    await tick(400);
    expect(visibleAlerts(host).join("|")).toContain("주유소 조회 실패");
    expect(visibleAlerts(host).join("|")).not.toContain("범위 통계");
  });
  await withMapClock(async (host, root) => {
    await act(async () => root.render(<TransportMap mode="transport" />));
    await tick(400);
    expect(visibleAlerts(host).join("|")).toContain("조회 실패");
    expect(visibleAlerts(host).join("|")).not.toContain("범위 통계");
  });
});

// 자동 재조회 대기(Retry-After): 새 요소 없이 기존 줄의 글을 "다시 조회 중…"으로 바꾼다.
const firstPlacesSucceeds = (retryAfter: string) => vi.mocked(fetch).mockImplementation(async input => {
  const url = String(input);
  if (!url.includes("places")) return Response.json({});
  // 첫 기본 범위 요청은 바로 성공시키고, 실제 범위 요청의 첫 응답만 혼잡으로 둔다.
  return url !== placesCalls()[0] && countOf(url) === 1 ? problem(429, BUSY, retryAfter) : Response.json({ items: [], total: 0, truncated: false });
});
const publicSummaryStatus = (host: HTMLElement) => host.querySelector('[aria-label="현재 지도 범위 유가 통계"] .public-fuel-summary-body [role="status"]')?.textContent ?? null;

test("공개 유가 지도는 재조회를 기다리는 동안 범위 요약 줄에서 '다시 조회 중…'을 알린다", async () => {
  firstPlacesSucceeds("2");
  Object.assign(mapState, { zoom: 12 });
  await withMapClock(async (host, root) => {
    await act(async () => root.render(fuelMap(true)));
    await tick(300);
    expect(publicSummaryStatus(host)).toBe("다시 조회 중…");
    expect(visibleAlerts(host)).toHaveLength(0);
    expect(host.querySelector(".map-retry-status")).toBeNull();
    await tick(2100);
    expect(publicSummaryStatus(host)).toBeNull();
    expect(visibleAlerts(host)).toHaveLength(0);
  });
});

test.each([["지도", false], ["목록", true]])("관리 화면은 %s 보기에서도 결과 줄(role=status)이 '다시 조회 중…'을 알린다", async (_name, list) => {
  vi.mocked(fetch).mockImplementation(async input => {
    const url = String(input);
    if (!url.includes("places")) return Response.json({});
    const listRequest = new URL(url, "http://test").searchParams.has("kind");
    if (list && !listRequest) return Response.json({ items: [], total: 0, truncated: false });
    return url !== placesCalls()[0] && countOf(url) === 1 ? problem(429, BUSY, "2") : Response.json({ items: [], total: 0, truncated: false });
  });
  await withMapClock(async (host, root) => {
    await act(async () => root.render(<TransportMap mode="transport" />));
    if (list) await act(async () => [...host.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find(button => button.textContent?.includes("목록"))!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
    await tick(300);
    const count = host.querySelector(".kt-map-count");
    expect(count?.textContent).toBe("다시 조회 중…");
    expect(count?.closest('[role="status"]')).not.toBeNull();
    await tick(2100);
    expect(host.querySelector(".kt-map-count")?.textContent).not.toContain("조회 중");
  });
});

test("재조회 뒤에도 실패하면 '다시 조회 중…'을 지우고 실패 알림 하나만 남긴다", async () => {
  vi.mocked(fetch).mockImplementation(async input => String(input).includes("places") ? problem(429, BUSY, "1") : Response.json({}));
  Object.assign(mapState, { zoom: 12 });
  await withMapClock(async (host, root) => {
    await act(async () => root.render(fuelMap(true)));
    await tick(300);
    expect(publicSummaryStatus(host)).toBe("다시 조회 중…");
    await tick(1200);
    expect(publicSummaryStatus(host)).toBeNull();
    expect(visibleAlerts(host)).toHaveLength(1);
    expect(visibleAlerts(host)[0]).toContain("혼잡합니다");
  });
});
