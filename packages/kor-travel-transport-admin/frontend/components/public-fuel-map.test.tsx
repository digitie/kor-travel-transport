// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const state = vi.hoisted(() => ({ props: {} as Record<string, unknown>, get: vi.fn() }));
vi.mock("./transport-map", () => ({ TransportMap: (props: Record<string, unknown>) => { state.props = props; return <div data-map="fuel" />; } }));
vi.mock("@/lib/public-fuel", () => ({ publicFuelGet: state.get }));
import { PublicFuelMap } from "./public-fuel-map";
let root: Root, host: HTMLDivElement;
beforeEach(() => { vi.useFakeTimers(); vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true); host = document.createElement("div"); document.body.append(host); root = createRoot(host); state.get.mockReset(); });
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.useRealTimers(); vi.unstubAllGlobals(); });
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
  await render(); expect(get).not.toHaveBeenCalled();
  await act(async () => host.querySelector("button")!.click());
  await act(async () => get.mock.calls[0][0]({ coords: { longitude: 127, latitude: 37 } }));
  expect(state.props.requestedLocation).toMatchObject({ longitude: 127, latitude: 37 });
  expect(host.textContent).toContain("내 위치 주변의 유가");
});
it("denial keeps the viewport and gives visible fallback feedback", async () => {
  const get = vi.fn(); Object.defineProperty(navigator, "geolocation", { configurable: true, value: { getCurrentPosition: get } });
  await render(); await act(async () => host.querySelector("button")!.click());
  await act(async () => get.mock.calls[0][1]({ code: 1 }));
  expect(state.props.requestedLocation).toBeUndefined();
  expect(host.querySelector('[role="status"]')?.className).not.toContain("sr-only");
  expect(host.textContent).toContain("현재 지도 범위를 표시");
});
it("bounds an unresponsive location provider and ignores a late result", async () => {
  const get = vi.fn(); Object.defineProperty(navigator, "geolocation", { configurable: true, value: { getCurrentPosition: get } });
  await render(); await act(async () => host.querySelector("button")!.click());
  await act(async () => vi.advanceTimersByTime(6500));
  expect(host.querySelector("button")!.disabled).toBe(false);
  await act(async () => get.mock.calls[0][0]({ coords: { longitude: 127, latitude: 37 } }));
  expect(state.props.requestedLocation).toBeUndefined();
});
