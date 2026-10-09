// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// MapLibre는 WebGL이 필요하다. 라이브러리(vworld-map-web) 위에 얹은 교통 지도 부품의 동작만 보도록
// maplibre-gl 생성자·카메라·마커·팝업을 대역으로 바꾼다(vitest.config가 라이브러리를 inline해 대역이 닿는다).
type Handler = (event?: unknown) => void;
const state = vi.hoisted(() => ({
  throwOnCreate: false,
  instances: [] as Array<{ easeTo: ReturnType<typeof vi.fn>; jumpTo: ReturnType<typeof vi.fn>; handlers: Map<string, Handler[]> }>,
  popups: [] as Array<{ element: HTMLElement }>,
}));
vi.mock("maplibre-gl/dist/maplibre-gl.css", () => ({}));
vi.mock("maplibre-gl", () => {
  class FakeMap {
    easeTo = vi.fn();
    jumpTo = vi.fn();
    handlers = new Map<string, Handler[]>();
    container = document.createElement("div");
    constructor() {
      if (state.throwOnCreate) throw new Error("Failed to initialize WebGL with https://api.vworld.kr/req/wmts/1.0.0/SECRET-KEY/Base/7/1/2.png");
      state.instances.push(this);
    }
    on(type: string, handler: Handler) { this.handlers.set(type, [...(this.handlers.get(type) ?? []), handler]); return this; }
    off() { return this; }
    addControl() { return this; }
    removeControl() { return this; }
    getContainer() { return this.container; }
    remove() {}
    resize() {}
    setStyle() {}
    setMinZoom() {}
    setMaxZoom() {}
    setMaxBounds() {}
    setTransformRequest() {}
    isMoving() { return false; }
    getZoom() { return 7; }
    getMaxZoom() { return 19; }
  }
  class FakeMarker {
    element: HTMLElement;
    constructor({ element }: { element?: HTMLElement }) { this.element = element ?? document.createElement("div"); this.element.classList.add("maplibregl-marker"); }
    setLngLat() { return this; }
    setOffset() { return this; }
    addTo() { document.body.append(this.element); return this; }
    getElement() { return this.element; }
    remove() { this.element.remove(); }
  }
  class FakePopup {
    element = document.createElement("div");
    constructor() { this.element.className = "maplibregl-popup"; state.popups.push(this); }
    setLngLat() { return this; }
    setMaxWidth() { return this; }
    setOffset() { return this; }
    setDOMContent(node: HTMLElement) { this.element.append(node); return this; }
    addTo() { document.body.append(this.element); return this; }
    getElement() { return this.element; }
    on() { return this; }
    off() { return this; }
    remove() { this.element.remove(); }
  }
  class Control {}
  return { Map: FakeMap, NavigationControl: Control, ScaleControl: Control, GeolocateControl: Control, Marker: FakeMarker, Popup: FakePopup, addProtocol: () => {} };
});

import { VWorldMapView } from "vworld-map-web";
import { CameraRequest, MapMarkerButton, MapUnavailable, OverlapPopup, useVWorldBasemapHealth, vworldApiKey, type CameraTarget } from "./map-overlays";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  state.throwOnCreate = false; state.instances.length = 0; state.popups.length = 0;
  host = document.createElement("div"); document.body.append(host);
  root = createRoot(host);
});
afterEach(() => { act(() => root.unmount()); host.remove(); document.body.replaceChildren(); });

function render(children?: React.ReactNode, apiKey = "test-key") {
  act(() => root.render(<VWorldMapView apiKey={apiKey} center={[127.8, 36.2]} zoom={7} navigation={false} geolocate={false} scale={false}
    fallback={(info) => <MapUnavailable info={info} />}>{children}</VWorldMapView>));
}
function emit(type: string, event?: unknown) {
  act(() => { for (const handler of state.instances[0].handlers.get(type) ?? []) handler(event); });
}

describe("지도 카메라 요청", () => {
  const camera = (id: string): CameraTarget => ({ center: [127, 37], zoom: 11, id });
  it("지도 준비 뒤 첫 요청은 바로 옮기고, 같은 위치라도 새 요청이면 다시 이동한다", () => {
    render(<CameraRequest target={camera("rail_station:3:1")} />);
    emit("load");
    const map = state.instances[0];
    expect(map.jumpTo).toHaveBeenCalledWith({ center: [127, 37], zoom: 11 });
    render(<CameraRequest target={camera("rail_station:3:2")} />);
    expect(map.easeTo).toHaveBeenCalledTimes(1);
    expect(map.easeTo).toHaveBeenLastCalledWith({ center: [127, 37], zoom: 11 });
  });
  it("같은 요청의 재렌더는 사용자가 옮긴 화면을 되돌리지 않는다", () => {
    render(<CameraRequest target={camera("a")} />);
    emit("load");
    render(<CameraRequest target={camera("a")} />);
    expect(state.instances[0].easeTo).not.toHaveBeenCalled();
    expect(state.instances[0].jumpTo).toHaveBeenCalledTimes(1);
  });
});

describe("지도 초기화 실패", () => {
  it("WebGL이 없어 생성자가 던지면 페이지를 깨지 않고 대체 안내를 보이며 키를 가려 남긴다", () => {
    state.throwOnCreate = true;
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(() => render()).not.toThrow();
    expect(host.textContent).toContain("이 브라우저에서 지도를 표시하지 못합니다");
    expect(host.querySelector("[data-testid=vworld-map-container]")).toBeNull();
    const logged = JSON.stringify(warn.mock.calls);
    expect(logged).not.toContain("SECRET-KEY");
    expect(logged).toContain("/req/wmts/1.0.0/***/Base");
    warn.mockRestore();
  });
  it.each(["", "  ", "CHANGE_ME", "replace-with-vworld-browser-key", undefined])("키가 %j이면 지도를 만들지 않고 목록 보기로 안내한다", (key) => {
    render(undefined, vworldApiKey(key));
    expect(state.instances).toHaveLength(0);
    expect(host.textContent).toContain("VWorld 지도 키가 없어");
  });
});

function HealthProbe({ onReady }: { onReady: (health: ReturnType<typeof useVWorldBasemapHealth>) => void }) {
  const health = useVWorldBasemapHealth();
  onReady(health);
  return <p data-failed={String(health.basemapFailed)} />;
}

describe("VWorld 배경지도 상태", () => {
  const tile = (path: string) => `vworld://api.vworld.kr/req/wmts/1.0.0/SECRET-KEY/Base/${path}.png?fallback=x&mapId=1`;
  const tileError = (path: string) => ({ type: "error", error: Object.assign(new Error("Failed to fetch"), { url: `https://api.vworld.kr/req/wmts/1.0.0/SECRET-KEY/Base/${path}.png` }) });
  let health!: ReturnType<typeof useVWorldBasemapHealth>;
  const failed = () => host.querySelector("p")!.dataset.failed;
  beforeEach(() => act(() => root.render(<HealthProbe onReady={(value) => { health = value; }} />)));

  it("타일 하나가 실패해도(서비스 영역 밖·일시 오류) 화면 안내를 띄우지 않고, 키를 가린 요약 한 줄만 남긴다", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    for (const path of ["7/49/108", "7/49/109", "7/50/108"]) health.transformRequest(tile(path), "Tile" as never);
    act(() => health.onError(tileError("7/49/108") as never));
    expect(warn).not.toHaveBeenCalled();
    act(() => health.onIdle());
    expect(failed()).toBe("false");
    expect(warn).toHaveBeenCalledTimes(1);
    const logged = JSON.stringify(warn.mock.calls);
    expect(logged).toContain("1/3");
    expect(logged).not.toContain("SECRET-KEY");
    expect(logged).toContain("/req/wmts/1.0.0/***/Base/7/49/108.png");
    warn.mockRestore();
  });
  it("한 번의 그리기에서 요청한 VWorld 타일이 모두 실패하면 배경지도 실패로 보고, 성공하면 거둔다", () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    for (const path of ["7/49/108", "7/49/109"]) { health.transformRequest(tile(path), "Tile" as never); act(() => health.onError(tileError(path) as never)); }
    act(() => health.onIdle());
    expect(failed()).toBe("true");
    health.transformRequest(tile("8/98/217"), "Tile" as never);
    act(() => health.onIdle());
    expect(failed()).toBe("false");
    vi.restoreAllMocks();
  });
  it("타일이 아닌 지도 오류는 메시지와 URL 양쪽에서 VWorld 키를 가려 남긴다", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    act(() => health.onError({ type: "error", error: { message: "Style failed at https://api.vworld.kr/req/wmts/1.0.0/SECRET-KEY/Base/x" } } as never));
    const logged = JSON.stringify(warn.mock.calls);
    expect(logged).not.toContain("SECRET-KEY");
    expect(logged).toContain("/req/wmts/1.0.0/***/Base");
    warn.mockRestore();
  });
});

describe("마커와 팝업 접근성", () => {
  it("선택 상태를 마커 요소의 aria-pressed로 알리고, 포인터를 통과시키며, 누른 마커 요소를 넘긴다", () => {
    const onClick = vi.fn();
    render(<>
      <MapMarkerButton lngLat={[127, 37]} ariaLabel="철도역 서울역 상세 보기" interactionId="rail_station:1" className="transport-map-marker rail_station" pressed passThrough zIndex={4} onClick={onClick}><span /></MapMarkerButton>
      <MapMarkerButton lngLat={[127.1, 37]} ariaLabel="묶음" interactionId="cluster:1" className="map-cluster" isCluster onClick={onClick}><span /></MapMarkerButton>
    </>);
    emit("load");
    const selected = document.querySelector<HTMLElement>("[aria-label='철도역 서울역 상세 보기']")!;
    expect(selected.classList.contains("maplibregl-marker")).toBe(true);
    expect(selected.getAttribute("role")).toBe("button");
    expect(selected.getAttribute("aria-pressed")).toBe("true");
    expect(document.querySelector("[aria-label='묶음']")!.hasAttribute("aria-pressed")).toBe(false);
    expect(selected.style.zIndex).toBe("4");
    expect(selected.style.pointerEvents).toBe("none");
    act(() => selected.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
    expect(onClick).toHaveBeenCalledWith(selected);
  });
  it("Escape로 팝업을 닫는다(목록 버튼에 포커스가 있어도)", () => {
    const onClose = vi.fn();
    render(<OverlapPopup lngLat={[127, 37]} onClose={onClose}><button type="button">시험항</button></OverlapPopup>);
    emit("load");
    const button = state.popups[0].element.querySelector("button")!;
    act(() => { button.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
    expect(onClose).toHaveBeenCalledTimes(1);
    act(() => { document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
