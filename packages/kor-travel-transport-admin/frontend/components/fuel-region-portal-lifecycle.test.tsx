// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const fixture = vi.hoisted(() => ({ ready: new Set<string>(), get: vi.fn(), layout: vi.fn() }));
vi.mock("maplibre-gl", () => ({ setWorkerUrl: vi.fn() }));
vi.mock("vworld-map-web", () => ({ VWorldMapView: ({ children }: { children: ReactNode }) => <div>{children}</div>, ClusterLayer: () => null }));
vi.mock("./map-overlays", () => ({
  CameraRequest: () => null, ClusterBubble: () => null, MapUnavailable: () => null,
  MarkerBadge: () => null, OverlapPopup: () => null, ZoomButtons: () => null,
  useVWorldBasemapHealth: () => ({ basemapFailed: false }),
  // A retained native marker host can exist before/after its React portal children.
  MapMarkerButton: ({ interactionId, className, children }: { interactionId: string; className: string; children: ReactNode }) =>
    <div className={className} data-marker-id={interactionId}>{fixture.ready.has(interactionId) ? children : null}</div>,
}));
vi.mock("@/lib/journey", async original => ({ ...await original<typeof import("@/lib/journey")>(), transportGet: fixture.get }));
vi.mock("@/lib/fuel-region-layout", () => ({ layoutFuelRegionCards: fixture.layout }));
import { TransportMap } from "./transport-map";

let root: Root, container: HTMLDivElement;
let nextFrame: number, frames: Map<number, FrameRequestCallback>;
const flushFrames = () => { const batch = [...frames.values()]; frames.clear(); batch.forEach(callback => callback(0)); };
const host = (id: string) => container.querySelector<HTMLElement>(`[data-marker-id="region:${id}"]`)!;
const render = async () => { await act(async () => root.render(<TransportMap mode="fuel" mapOnly />)); };

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal("matchMedia", vi.fn((media: string) => ({ media, matches: false, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })));
  nextFrame = 0; frames = new Map();
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { frames.set(++nextFrame, callback); return nextFrame; });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    const primary = this.classList.contains("map-primary");
    const marker = this.classList.contains("fuel-region-marker");
    const left = marker ? this.dataset.markerId === "region:A" ? 80 : 380 : 0;
    const top = marker ? 100 : 0;
    return { x: left, y: top, left, top, right: left + (primary ? 600 : 0), bottom: top + (primary ? 400 : 0), width: primary ? 600 : 0, height: primary ? 400 : 0, toJSON: () => ({}) };
  });
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockImplementation(function (this: HTMLElement) { return this.classList.contains("fuel-region-label") ? 148 : 0; });
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockImplementation(function (this: HTMLElement) { return this.classList.contains("fuel-region-label") ? 140 : 0; });
  fixture.ready.clear(); fixture.ready.add("region:B"); fixture.get.mockReset(); fixture.layout.mockReset();
  fixture.layout.mockImplementation((cards: unknown[]) => cards.map((_, index) => ({ x: (index + 1) * 30, y: (index + 1) * 20, placed: true })));
  fixture.get.mockResolvedValue({ items: [], total: 2, truncated: false, clustered: true, kind_totals: { fuel_station: 2 }, clusters: [], available_sources: [],
    fuel_regions: ["A", "B"].map(region_key => ({ region_key, label: region_key, product_code: "B027", average_price: 1700, station_count: 1, longitude: 127, latitude: 37 })) });
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("defers incomplete portal hosts without phantom cards and keeps ready hosts paired through label remove/re-add", async () => {
  await render();
  expect(host("A")).not.toBeNull(); expect(host("A").querySelector(".fuel-region-label")).toBeNull();
  expect(() => flushFrames()).not.toThrow();
  expect(fixture.layout.mock.lastCall?.[0]).toHaveLength(1);
  expect(host("A").style.getPropertyValue("--region-offset-x")).toBe("");
  expect(host("B").style.getPropertyValue("--region-offset-x")).toBe("30px");

  // The actual MutationObserver schedules the hook again when portal content arrives.
  fixture.ready.add("region:A"); await render(); expect(frames.size).toBeGreaterThan(0); flushFrames();
  expect(fixture.layout.mock.lastCall?.[0]).toHaveLength(2);
  expect(host("A").style.getPropertyValue("--region-offset-x")).toBe("30px");
  expect(host("B").style.getPropertyValue("--region-offset-x")).toBe("60px");

  fixture.ready.delete("region:A"); await render(); expect(frames.size).toBeGreaterThan(0);
  expect(() => flushFrames()).not.toThrow();
  expect(fixture.layout.mock.lastCall?.[0]).toHaveLength(1);
  expect(host("B").style.getPropertyValue("--region-offset-x")).toBe("30px");
  expect(fixture.layout.mock.lastCall?.[0].every((card: { width: number; height: number }) => card.width === 148 && card.height === 140)).toBe(true);

  fixture.ready.add("region:A"); await render(); flushFrames();
  expect(host("A").style.getPropertyValue("--region-offset-x")).toBe("30px");
  expect(host("B").style.getPropertyValue("--region-offset-x")).toBe("60px");
  expect(fixture.get).toHaveBeenCalledTimes(1);
});
