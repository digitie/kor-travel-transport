// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// MapLibre는 WebGL이 필요하다. 지도 셸의 동작만 보도록 생성자·카메라·마커·팝업을 대역으로 바꾼다.
type Handler = (event?: unknown) => void;
const state = vi.hoisted(() => ({
  throwOnCreate: false,
  instances: [] as Array<{ easeTo: ReturnType<typeof vi.fn>; handlers: Map<string, Handler[]> }>,
  popups: [] as Array<{ element: HTMLElement }>,
}));
vi.mock("maplibre-gl/dist/maplibre-gl.css", () => ({}));
vi.mock("maplibre-gl", () => {
  class FakeMap {
    easeTo = vi.fn();
    handlers = new Map<string, Handler[]>();
    constructor() {
      if (state.throwOnCreate) throw new Error("Failed to initialize WebGL");
      state.instances.push(this);
    }
    on(type: string, handler: Handler) { this.handlers.set(type, [...(this.handlers.get(type) ?? []), handler]); return this; }
    off() { return this; }
    addControl() { return this; }
    removeControl() { return this; }
    remove() {}
    resize() {}
    setStyle() {}
    getZoom() { return 7; }
    getMaxZoom() { return 19; }
  }
  class FakeMarker {
    element: HTMLElement;
    constructor({ element }: { element: HTMLElement }) { this.element = element; }
    setLngLat() { return this; }
    addTo() { document.body.append(this.element); return this; }
    getElement() { return this.element; }
    remove() { this.element.remove(); }
  }
  class FakePopup {
    element = document.createElement("div");
    constructor() { state.popups.push(this); }
    setLngLat() { return this; }
    setDOMContent(node: HTMLElement) { this.element.append(node); return this; }
    addTo() { document.body.append(this.element); return this; }
    getElement() { return this.element; }
    on() { return this; }
    off() { return this; }
    remove() { this.element.remove(); }
  }
  class Control {}
  return { Map: FakeMap, NavigationControl: Control, ScaleControl: Control, Marker: FakeMarker, Popup: FakePopup };
});

import { DomMarker, MapPopup, VWorldMapView, type CameraTarget } from "./vworld-map";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  state.throwOnCreate = false; state.instances.length = 0; state.popups.length = 0;
  host = document.createElement("div"); document.body.append(host);
  root = createRoot(host);
});
afterEach(() => { act(() => root.unmount()); host.remove(); document.body.replaceChildren(); });

function render(cameraTarget?: CameraTarget, children?: React.ReactNode) {
  act(() => root.render(<VWorldMapView apiKey="" center={[127.8, 36.2]} zoom={7} cameraTarget={cameraTarget}
    fallback={<p>지도를 표시하지 못합니다. 목록 보기에서 장소를 선택해 주세요.</p>}>{children}</VWorldMapView>));
}
function emit(type: string, event?: unknown) {
  act(() => { for (const handler of state.instances[0].handlers.get(type) ?? []) handler(event); });
}

describe("지도 카메라 요청", () => {
  it("같은 위치라도 새 요청이면 다시 이동한다(손으로 옮긴 뒤 같은 묶음·장소를 다시 누른 경우)", () => {
    render({ center: [127, 37], zoom: 11, id: "rail_station:3:1" });
    const map = state.instances[0];
    render({ center: [127, 37], zoom: 11, id: "rail_station:3:2" });
    expect(map.easeTo).toHaveBeenCalledTimes(1);
    expect(map.easeTo).toHaveBeenLastCalledWith({ center: [127, 37], zoom: 11 });
  });
  it("같은 요청의 재렌더는 사용자가 옮긴 화면을 되돌리지 않는다", () => {
    render({ center: [127, 37], zoom: 11, id: "a" });
    render({ center: [127, 37], zoom: 11, id: "a" });
    expect(state.instances[0].easeTo).not.toHaveBeenCalled();
  });
});

describe("지도 초기화 실패", () => {
  it("WebGL이 없어 생성자가 던지면 페이지를 깨지 않고 대체 안내를 보인다", () => {
    state.throwOnCreate = true;
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(() => render()).not.toThrow();
    expect(host.textContent).toContain("목록 보기에서 장소를 선택해 주세요");
    expect(host.querySelector("[data-testid=vworld-map-container]")).toBeNull();
    warn.mockRestore();
  });
});

describe("지도 오류 로그", () => {
  it("메시지와 URL 양쪽에서 VWorld 키를 가린다", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    render();
    emit("error", { error: { message: "Could not load https://api.vworld.kr/req/wmts/1.0.0/SECRET-KEY/Base/7/1/2.png: 401", url: "https://example.test/req/wmts/1.0.0/SECRET-KEY/Base/7/1/2.png" } });
    const logged = JSON.stringify(warn.mock.calls);
    expect(logged).not.toContain("SECRET-KEY");
    expect(logged).toContain("/req/wmts/1.0.0/***/Base");
    warn.mockRestore();
  });
});

describe("마커와 팝업 접근성", () => {
  it("선택 상태를 aria-pressed로 알리고 누른 마커 요소를 넘긴다", () => {
    const onClick = vi.fn();
    render(undefined, <>
      <DomMarker lngLat={[127, 37]} ariaLabel="철도역 서울역 상세 보기" pressed passThrough zIndex={4} onClick={onClick}><span /></DomMarker>
      <DomMarker lngLat={[127.1, 37]} ariaLabel="묶음" onClick={onClick}><span /></DomMarker>
    </>);
    emit("load");
    const selected = document.querySelector<HTMLElement>("[aria-label='철도역 서울역 상세 보기']")!;
    expect(selected.getAttribute("aria-pressed")).toBe("true");
    expect(document.querySelector("[aria-label='묶음']")!.hasAttribute("aria-pressed")).toBe(false);
    // 선택 마커는 묶음 위(z 4)에 그리되 바깥 MapLibre 요소에서 포인터를 통과시킨다.
    expect(selected.parentElement!.style.zIndex).toBe("4");
    expect(selected.parentElement!.style.pointerEvents).toBe("none");
    act(() => selected.click());
    expect(onClick).toHaveBeenCalledWith(selected);
  });
  it("Escape로 팝업을 닫는다", () => {
    const onClose = vi.fn();
    render(undefined, <MapPopup lngLat={[127, 37]} onClose={onClose}><button type="button">시험항</button></MapPopup>);
    emit("load");
    const button = state.popups[0].element.querySelector("button")!;
    act(() => { button.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
