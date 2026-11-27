// @vitest-environment jsdom
import { act, type ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const state = vi.hoisted(() => ({ props: {} as Record<string, unknown>, picker: {} as Record<string, unknown>, get: vi.fn() }));
vi.mock("./transport-map", () => ({ TransportMap: (props: Record<string, unknown>) => { state.props = props; return <div data-map="fuel" />; } }));
vi.mock("@/components/map-overlays", () => ({ CameraRequest: () => null, FitBoundsRequest: () => null, UserLocationMarker: () => null }));
vi.mock("@/lib/public-fuel", () => ({ publicFuelGet: state.get }));
// 지도 화면은 주소의 유종(`product`)을 Next 라우터로 읽는다. 시험에서는 지금 주소를 그대로 돌려준다.
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(window.location.search) }));
vi.mock("@/components/public-fuel-controls", () => ({ FuelRegionPicker: (props: Record<string, unknown>) => { state.picker = props; return null; } }));
import { PublicFuelMap } from "./public-fuel-map";
let root: Root, host: HTMLDivElement;
beforeEach(() => { vi.useFakeTimers(); vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true); host = document.createElement("div"); document.body.append(host); root = createRoot(host); state.get.mockReset(); });
afterEach(async () => { await act(async () => root.unmount()); host.remove(); window.history.replaceState(null, "", "/"); localStorage.removeItem("transport.public-fuel.products"); localStorage.removeItem("transport.public-fuel.filters"); vi.useRealTimers(); vi.unstubAllGlobals(); });
// layers = <><CameraRequest target /><UserLocationMarker position /><FitBoundsRequest target /></>
const layerProps = () => (state.props.layers as ReactElement<{ children: ReactElement<{ target?: unknown; position?: unknown }>[] }>).props.children.map(child => child.props);
const cameraTarget = () => layerProps()[0].target;
const userPosition = () => layerProps()[1].position;
async function render() { await act(async () => root.render(<PublicFuelMap />)); }
it("loads map and history through the public reader without admin path prefixes", async () => {
  await render();
  const load = state.props.load as (path: string, signal?: AbortSignal) => Promise<unknown>;
  const signal = new AbortController().signal;
  await load("transport/features/places?zoom=10", signal);
  await load("transport/fuel/stations/12/price-history?cursor=abc", signal);
  expect(state.get.mock.calls).toEqual([["features/places?zoom=10", signal], ["fuel/stations/12/price-history?cursor=abc", signal]]);
  expect(state.props.mode).toBe("fuel");
});
it("only requests location after a click and moves to a valid result", async () => {
  const get = vi.fn(); Object.defineProperty(navigator, "geolocation", { configurable: true, value: { getCurrentPosition: get } });
  await render();
  expect(get).not.toHaveBeenCalled();
  const button = host.querySelector("button")!;
  expect(button.textContent).toBe("");
  expect(button.getAttribute("aria-label")).toBe("내 위치 주변 유가 보기");
  await act(async () => button.click());
  expect(button.getAttribute("aria-busy")).toBe("true");
  expect(button.textContent).toBe("");
  await act(async () => button.click());
  expect(get).toHaveBeenCalledTimes(1);
  expect(get.mock.calls[0][2]).toMatchObject({ enableHighAccuracy: false, maximumAge: 60_000 });
  await act(async () => get.mock.calls[0][0]({ coords: { longitude: 127, latitude: 37 } }));
  expect(button.hasAttribute("aria-busy")).toBe(false);
  expect(cameraTarget()).toMatchObject({ center: [127, 37], zoom: 14 });
  expect(userPosition()).toEqual([127, 37]);
  expect(state.props.mapOnly).toBe(true);
  expect(state.props.view).toBeUndefined();
  expect(state.props.onViewChange).toBeUndefined();
  expect(host.querySelector('[role="status"]')).toBeNull();
});
type Get = ReturnType<typeof vi.fn>;
const succeed = (get: Get, call: number, longitude = 127, latitude = 37) => act(async () => (get.mock.calls[call] as [PositionCallback])[0]({ coords: { longitude, latitude } } as GeolocationPosition));
const failWith = (get: Get, call: number, code: number) => act(async () => (get.mock.calls[call] as [PositionCallback, PositionErrorCallback])[1]({ code } as GeolocationPositionError));
const status = () => host.querySelector('[role="status"]')?.textContent ?? "";
const retry = () => [...host.querySelectorAll("button")].find(button => button.textContent === "다시 시도");
function mockGeolocation(extra: Partial<Geolocation> = {}) {
  const get = vi.fn();
  Object.defineProperty(navigator, "geolocation", { configurable: true, value: { getCurrentPosition: get, ...extra } });
  return get;
}
it("asks for a cached low-accuracy position first, then retries with high accuracy after a timeout", async () => {
  const get = mockGeolocation();
  await render(); await act(async () => host.querySelector("button")!.click());
  expect(get.mock.calls[0][2]).toEqual({ enableHighAccuracy: false, maximumAge: 60_000, timeout: 10_000 });
  await failWith(get, 0, 3);
  expect(get).toHaveBeenCalledTimes(2);
  expect(get.mock.calls[1][2]).toMatchObject({ enableHighAccuracy: true, timeout: 15_000 });
  expect(host.querySelector("button")!.getAttribute("aria-busy")).toBe("true");
  await succeed(get, 1, 126.98, 37.57);
  expect(cameraTarget()).toMatchObject({ center: [126.98, 37.57], zoom: 14 });
  expect(userPosition()).toEqual([126.98, 37.57]);
  expect(host.querySelector('[role="status"]')).toBeNull();
});
it("denial stops at once, keeps the viewport and explains how to allow location without a useless retry", async () => {
  const get = mockGeolocation();
  await render(); await act(async () => host.querySelector("button")!.click());
  await failWith(get, 0, 1);
  expect(get).toHaveBeenCalledTimes(1);
  expect(cameraTarget()).toBeUndefined();
  expect(userPosition()).toBeUndefined();
  expect(host.querySelector('[role="status"]')?.className).not.toContain("sr-only");
  expect(status()).toContain("위치 권한이 거부되었습니다");
  expect(retry()).toBeUndefined();
  expect(host.querySelector("button")!.hasAttribute("aria-busy")).toBe(false);
});
it.each([
  { code: 2, message: "현재 위치를 확인할 수 없습니다" },
  { code: 3, message: "위치 확인 시간이 초과되었습니다" },
])("reports error $code after both attempts and retries from the status", async ({ code, message }) => {
  const get = mockGeolocation();
  await render(); await act(async () => host.querySelector("button")!.click());
  await failWith(get, 0, code);
  await failWith(get, 1, code);
  expect(status()).toContain(message);
  expect(host.querySelector("button")!.hasAttribute("aria-busy")).toBe(false);
  await act(async () => retry()!.click());
  expect(get).toHaveBeenCalledTimes(3);
  expect(host.querySelector('[role="status"]')).toBeNull();
  await succeed(get, 2);
  expect(userPosition()).toEqual([127, 37]);
});
it("rejects a position outside Korea with its own message", async () => {
  const get = mockGeolocation();
  await render(); await act(async () => host.querySelector("button")!.click());
  await succeed(get, 0, -122.4, 37.7);
  expect(cameraTarget()).toBeUndefined();
  expect(status()).toContain("국내 위치에서만");
});
it("explains unsupported and insecure contexts without calling the provider", async () => {
  Object.defineProperty(navigator, "geolocation", { configurable: true, value: undefined });
  await render(); await act(async () => host.querySelector("button")!.click());
  expect(status()).toContain("이 브라우저에서는 위치를 사용할 수 없습니다");
  const get = mockGeolocation();
  vi.stubGlobal("isSecureContext", false);
  await act(async () => host.querySelector("button")!.click());
  expect(get).not.toHaveBeenCalled();
  expect(status()).toContain("HTTPS");
});
it("bounds an unresponsive provider, still applies a late fix, and lets a new click supersede it", async () => {
  const get = mockGeolocation();
  await render(); await act(async () => host.querySelector("button")!.click());
  // 권한 창을 보는 동안에는 단계 timeout이 돌지 않는다. 앱 쪽 안전 상한만 30초 뒤에 끝낸다.
  await act(async () => vi.advanceTimersByTime(29_000));
  expect(host.querySelector("button")!.getAttribute("aria-busy")).toBe("true");
  await act(async () => vi.advanceTimersByTime(1_000));
  expect(host.querySelector("button")!.hasAttribute("aria-busy")).toBe(false);
  expect(status()).toContain("위치 확인 시간이 초과되었습니다");
  await succeed(get, 0);
  expect(cameraTarget()).toMatchObject({ center: [127, 37] });
  expect(host.querySelector('[role="status"]')).toBeNull();
  // 새 요청을 보내면 이전 요청의 늦은 응답은 무시한다.
  await act(async () => host.querySelector("button")!.click());
  const before = cameraTarget();
  await act(async () => vi.advanceTimersByTime(30_000));
  await act(async () => host.querySelector("button")!.click());
  await succeed(get, 1, 128, 36);
  expect(cameraTarget()).toBe(before);
  await succeed(get, 2, 129, 35.5);
  expect(cameraTarget()).toMatchObject({ center: [129, 35.5] });
});
it("keeps tracking through transient watch errors and stops only when permission is revoked", async () => {
  const watch = vi.fn(() => 3); const clear = vi.fn();
  const get = mockGeolocation({ watchPosition: watch, clearWatch: clear });
  await render(); await act(async () => host.querySelector("button")!.click());
  await succeed(get, 0);
  const onWatchError = (watch.mock.calls[0] as unknown as [PositionCallback, PositionErrorCallback])[1];
  await act(async () => onWatchError({ code: 2 } as GeolocationPositionError));
  await act(async () => onWatchError({ code: 3 } as GeolocationPositionError));
  expect(userPosition()).toEqual([127, 37]);
  expect(clear).not.toHaveBeenCalled();
  await act(async () => onWatchError({ code: 1 } as GeolocationPositionError));
  expect(userPosition()).toBeUndefined();
  expect(clear).toHaveBeenCalledWith(3);
});

it("restores and saves the public product selection, including all products", async () => {
  const key = "transport.public-fuel.products";
  localStorage.setItem(key, JSON.stringify(["C004", "invalid", "C004"]));
  await render();
  const controls = () => state.props.publicFuel as { products: string[]; onProductsChange: (value: string[]) => void };
  expect(controls().products).toEqual(["C004"]);
  await act(async () => controls().onProductsChange(["B027", "D047"]));
  expect(controls().products).toEqual(["B027", "D047"]);
  expect(JSON.parse(localStorage.getItem(key)!)).toEqual(["B027", "D047"]);
  await act(async () => controls().onProductsChange([]));
  expect(controls().products).toEqual([]);
  expect(JSON.parse(localStorage.getItem(key)!)).toEqual([]);
});

it("shows my location as a point and follows later position updates without moving the camera", async () => {
  const get = vi.fn(); const watch = vi.fn(() => 7); const clear = vi.fn();
  Object.defineProperty(navigator, "geolocation", { configurable: true, value: { getCurrentPosition: get, watchPosition: watch, clearWatch: clear } });
  await render();
  await act(async () => host.querySelector("button")!.click());
  await act(async () => get.mock.calls[0][0]({ coords: { longitude: 128.7, latitude: 36.5 } }));
  expect(userPosition()).toEqual([128.7, 36.5]);
  expect(watch).toHaveBeenCalledTimes(1);
  const camera = cameraTarget();
  await act(async () => (watch.mock.calls[0] as unknown as [(position: { coords: { longitude: number; latitude: number } }) => void])[0]({ coords: { longitude: 128.71, latitude: 36.51 } }));
  expect(userPosition()).toEqual([128.71, 36.51]);
  expect(cameraTarget()).toBe(camera);
  await act(async () => root.unmount());
  expect(clear).toHaveBeenCalledWith(7);
  root = createRoot(host);
});

it("saves filters and passes them with the products to the single top selector; no separate filter drawer", async () => {
  await render();
  type Controls = { filters: { self_only: boolean; brands: string[] }; filterQuery: string; onFiltersChange: (value: unknown) => void; onOpenFilters?: unknown };
  const controls = () => state.props.publicFuel as Controls;
  expect(controls().onOpenFilters).toBeUndefined();
  expect(controls().filterQuery).toBe("");
  await act(async () => controls().onFiltersChange({ ...controls().filters, self_only: true, brands: ["SKE"] }));
  expect(controls().filters.self_only).toBe(true);
  expect(controls().filterQuery).toBe("brands=SKE&self_only=true");
  expect(JSON.parse(localStorage.getItem("transport.public-fuel.filters")!)).toMatchObject({ self_only: true, brands: ["SKE"] });
  // 다시 열어도(새로 mount) 저장한 필터를 읽는다.
  await act(async () => root.unmount()); root = createRoot(host);
  await render();
  expect(controls().filterQuery).toBe("brands=SKE&self_only=true");
});

it("keeps only the region chosen in the region picker and clears it on request", async () => {
  await render();
  type Controls = { selectedRegion?: unknown; onClearRegion: () => void; onOpenRegion: (current?: unknown, opener?: HTMLElement | null) => void };
  const controls = () => state.props.publicFuel as Controls;
  expect(controls().selectedRegion).toBeUndefined();
  await act(async () => controls().onOpenRegion({ sido_value: "15", sigungu_value: "1502" }, null));
  expect(state.picker.open).toBe(true);
  expect(state.picker.current).toEqual({ sido_value: "15", sigungu_value: "1502" });
  const region = { sido_value: "01", sigungu_value: "0101", label: "서울 종로구" };
  await act(async () => (state.picker.onConfirm as (bounds: number[], value: unknown) => void)([126.9, 37.5, 127, 37.6], region));
  expect(controls().selectedRegion).toEqual(region);
  expect(layerProps()[2].target).toMatchObject({ bounds: [126.9, 37.5, 127, 37.6] });
  await act(async () => controls().onClearRegion());
  expect(controls().selectedRegion).toBeUndefined();
});

it("opens with the fuel from the link (?product=) without overwriting the saved selection, then saves a user choice and drops the link fuel", async () => {
  const key = "transport.public-fuel.products";
  localStorage.setItem(key, JSON.stringify(["B027", "D047"]));
  window.history.replaceState(null, "", "/?longitude=127.1&latitude=37.5&product=K015");
  await render();
  const controls = () => state.props.publicFuel as { products: string[]; onProductsChange: (value: string[]) => void; filterQuery?: string };
  expect(controls().products).toEqual(["K015"]);
  // 지도의 통계 단추도 그 유종으로 연다.
  expect(host.querySelector('a[aria-label="지역별 유가 통계"]')?.getAttribute("href")).toBe("/statistics?product=K015&from=map");
  // 링크로 연 유종은 저장하지 않는다.
  expect(JSON.parse(localStorage.getItem(key)!)).toEqual(["B027", "D047"]);
  await act(async () => controls().onProductsChange(["D047"]));
  expect(controls().products).toEqual(["D047"]);
  expect(JSON.parse(localStorage.getItem(key)!)).toEqual(["D047"]);
  // 주소의 유종은 지워 뒤로 가기·새로고침이 링크 유종으로 되돌리지 않게 한다(좌표는 그대로).
  expect(window.location.search).toBe("?longitude=127.1&latitude=37.5");
  await act(async () => root.unmount()); root = createRoot(host);
  await render();
  expect(controls().products).toEqual(["D047"]);
});
it("ignores an unknown link fuel and keeps the saved selection", async () => {
  localStorage.setItem("transport.public-fuel.products", JSON.stringify(["C004"]));
  window.history.replaceState(null, "", "/?product=X999");
  await render();
  expect((state.props.publicFuel as { products: string[] }).products).toEqual(["C004"]);
});
it("uses the link fuel even when the browser blocks storage, and a later choice still wins", async () => {
  window.history.replaceState(null, "", "/?product=D047");
  const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
  try {
    await render();
    const controls = () => state.props.publicFuel as { products: string[]; onProductsChange: (value: string[]) => void };
    expect(controls().products).toEqual(["D047"]);
    await act(async () => controls().onProductsChange([]));
    expect(controls().products).toEqual([]);
    expect(window.location.search).toBe("");
  } finally { setItem.mockRestore(); }
});
