// @vitest-environment jsdom
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { Place } from "@/lib/journey";

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
    ClusterLayer: ({ points, renderMarker }: { points: unknown[]; renderMarker: (point: unknown) => React.ReactNode }) => <>{points.map((point, index) => <React.Fragment key={index}>{renderMarker(point)}</React.Fragment>)}</>,
  };
});
vi.mock("./map-overlays", () => ({
  vworldApiKey: () => undefined, useVWorldBasemapHealth: () => ({}), ZoomButtons: () => null, CameraRequest: () => null, MarkerBadge: () => null, ClusterBubble: () => null, MapUnavailable: () => null, OverlapPopup: () => null,
  MapMarkerButton: ({ ariaLabel, onClick, children }: { ariaLabel: string; onClick: () => void; children: React.ReactNode }) => <button aria-label={ariaLabel} onClick={onClick}>{children}</button>,
}));
import { TransportMap } from "./transport-map";

const station: Place = { id: 1, kind: "rail_station", source: "kric_public_file", name: "시험역", longitude: 127.1, latitude: 37.3, line_names: ["시험선"], facilities: [], prices: [], updated_at: "2026-10-25T00:00:00Z" };
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true, ResizeObserver: class { observe() {} disconnect() {} } });
  vi.stubGlobal("fetch", vi.fn());
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  Object.assign(mapState, { longitude: 128.53, latitude: 37.6, zoom: 12.5 });
});
afterEach(() => vi.unstubAllGlobals());

test("외부 장소 지도는 자체 API를 호출하지 않고 목록 왕복에도 실제 카메라를 유지한다", async () => {
  const container = document.createElement("div"); document.body.append(container); const root = createRoot(container);
  try {
    await act(async () => root.render(<TransportMap places={[station]} />));
    const camera = () => container.querySelector('[data-testid="fixture-map"]')!;
    expect(camera().getAttribute("data-center")).toBe("128.53,37.6");
    Object.assign(mapState, { longitude: 129.1, latitude: 35.2, zoom: 14 });
    await act(async () => [...container.querySelectorAll("button")].find((node) => node.textContent === "지도 이동 모의")!.click());
    expect(camera().getAttribute("data-center")).toBe("129.1,35.2");
    await act(async () => container.querySelector<HTMLButtonElement>('[role="tab"][id]')?.focus());
    await act(async () => [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((node) => node.textContent?.includes("목록"))!.click());
    expect(container.querySelector('[data-testid="fixture-map"]')).toBeNull();
    await act(async () => [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((node) => node.textContent?.includes("지도"))!.click());
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
