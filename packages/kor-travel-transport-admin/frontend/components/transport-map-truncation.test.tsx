// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("maplibre-gl", () => ({ setWorkerUrl: vi.fn() }));
vi.mock("vworld-map-web", () => ({
  VWorldMapView: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  ClusterLayer: () => null,
}));
vi.mock("./map-overlays", () => ({
  CameraRequest: () => null, ClusterBubble: () => null, MapMarkerButton: () => null,
  MapUnavailable: () => null, MarkerBadge: () => null, OverlapPopup: () => null,
  ZoomButtons: () => null, vworldApiKey: () => "",
  useVWorldBasemapHealth: () => ({ basemapFailed: false }),
}));
vi.mock("@/lib/journey", async (original) => ({
  ...await original<typeof import("@/lib/journey")>(), transportGet: mocks.get,
}));
import { TransportMap } from "./transport-map";

let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  container = document.createElement("div"); document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount()); container.remove(); vi.unstubAllGlobals();
});

for (const mode of ["fuel", "transport"] as const) describe(`${mode} 목록 상한`, () => {
  for (const partial of [false, true]) it(`${partial ? "일부" : "완전"} 응답은 목록에서만 해당 상태를 알린다`, async () => {
    const kind = mode === "fuel" ? "fuel_station" : "rail_station";
    mocks.get.mockImplementation(async (path: string) => {
      const params = new URL(path, "https://fixture.invalid").searchParams;
      const includes = params.has("kinds") || params.get("kind") === kind;
      const items = includes ? [{ id: 1, kind, source: "fixture", name: "시험 장소",
        longitude: 127, latitude: 37, line_names: [], prices: [], facilities: [], updated_at: "2026-10-24T00:00:00Z" }] : [];
      return { items, total: items.length + (includes && partial ? 1 : 0),
        truncated: includes && partial, available_sources: ["fixture"] };
    });
    await act(async () => { root.render(<TransportMap mode={mode} />); });
    const notice = () => container.querySelector<HTMLButtonElement>('button[aria-label="목록 일부 표시 안내"]');
    expect(notice()).toBeNull(); // 지도 응답의 truncated를 안내로 오인하지 않는다.
    const list = [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
      .find((button) => button.textContent === "목록")!;
    expect(list).toBeDefined();
    await act(async () => { list.click(); });
    expect(container.querySelectorAll(".place-row")).toHaveLength(1);
    expect(mocks.get).toHaveBeenCalledTimes(mode === "fuel" ? 2 : 7); // 안내가 새 API를 호출하지 않는다.
    expect(container.querySelectorAll(".kt-map-count")).toHaveLength(1);
    expect(container.querySelector(".kt-map-count")?.textContent).toBe("1건 표시");
    if (partial) {
      expect(notice()).not.toBeNull();
      expect(document.body.textContent).not.toContain("일부 결과만 조회했습니다.");
      await act(async () => { notice()!.click(); });
      expect(document.body.textContent).toContain("일부 결과만 조회했습니다.");
      expect(document.body.textContent).toContain(mode === "fuel" ? "주유소 최대 300건" : "철도역 최대 150건");
      expect(document.body.textContent).not.toContain("항구 최대");
    } else {
      expect(notice()).toBeNull();
      expect(document.body.textContent).not.toContain("일부 결과만 조회했습니다.");
    }
  });
});
