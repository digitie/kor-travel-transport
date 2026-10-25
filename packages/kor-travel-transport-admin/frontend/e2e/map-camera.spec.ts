import { expect, test, type Locator } from "@playwright/test";
import type { Map as MapLibreMap } from "maplibre-gl";

// 공개 키·운영 타일 없이 실제 SDK/MapLibre 엔진의 재마운트를 검증한다.
// QA dev 서버에는 운영 키 대신 NEXT_PUBLIC_VWORLD_API_KEY=transport-layout-local-fixture를 준다.
test.beforeEach(async ({ page }) => {
  test.skip(process.env.E2E_MAP_SDK !== "true", "격리 SDK 지도·타일 fixture 필요");
  await page.context().addCookies([{ name: "kor_travel_transport_admin_session", value: "isolated-e2e", url: process.env.E2E_BASE_URL ?? "http://127.0.0.1:12352", httpOnly: true, sameSite: "Strict" }]);
  await page.route("**/api/transport/**", (route) => route.fulfill({ json: { items: [], total: 0, truncated: false } }));
  const tile = await page.evaluate(() => { const canvas = document.createElement("canvas"); canvas.width = 256; canvas.height = 256; return canvas.toDataURL("image/png").split(",")[1]; });
  await page.route("https://api.vworld.kr/**", (route) => route.fulfill({ contentType: "image/png", headers: { "access-control-allow-origin": "*" }, body: Buffer.from(tile, "base64") }));
});

test.describe("실제 SDK 터치 조작부", () => {
  test.use({ hasTouch: true });
  for (const variant of ["320", "375", "text200"]) test(`조회 중 표시의 높이와 실제 카메라 유지 ${variant}`, async ({ page }, testInfo) => {
    const width = variant === "375" ? 375 : 320;
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    await page.route("**/transport/features/places?**", async (route) => { if (new URL(route.request().url()).searchParams.get("zoom") === "12") await gate; await route.fulfill({ json: { items: [], total: 0, truncated: false } }); });
    await page.setViewportSize({ width, height: width === 375 ? 812 : 568 });
    await page.goto("/map");
    const canvas = page.locator(".maplibregl-map");
    await expect(page.locator(".kt-map-coordinates")).toContainText("center");
    if (variant === "text200") {
      await page.addStyleTag({ content: "html { font-size: 200% !important; }" });
      await page.getByRole("button", { name: "지도 크게 보기", exact: true }).click();
    }
    await expect.poll(() => canvas.evaluate((element) => { const map = (element as HTMLElement & { _maplibreMap: MapLibreMap })._maplibreMap; return map.loaded() && !map.isMoving(); })).toBe(true);
    await expect(page.locator(".kt-map-readout")).toContainText("0건 표시");
    const stage = page.locator('[data-slot="map-stage"][data-view="map"]');
    const before = (await stage.boundingBox())!;
    const viewportResponse = page.waitForResponse((response) => new URL(response.url()).searchParams.get("zoom") === "12");
    await canvas.evaluate((element) => (element as HTMLElement & { _maplibreMap: MapLibreMap })._maplibreMap.jumpTo({ center: [128.5316, 37.6031], zoom: 12.5 }));
    try {
      await expect(page.locator(".kt-map-readout")).toContainText("조회 중…");
      await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
      const pending = (await stage.boundingBox())!;
      expect(pending.y).toBeCloseTo(before.y, 1); expect(pending.height).toBeCloseTo(before.height, 1);
      const camera = await canvas.evaluate((element) => { const map = (element as HTMLElement & { _maplibreMap: MapLibreMap })._maplibreMap; return { longitude: map.getCenter().lng, latitude: map.getCenter().lat, zoom: map.getZoom() }; });
      expect(camera.longitude).toBeCloseTo(128.5316, 4); expect(camera.latitude).toBeCloseTo(37.6031, 4); expect(camera.zoom).toBeCloseTo(12.5, 2);
      await testInfo.attach("조회 중 작업면·카메라", { body: JSON.stringify({ before, pending, camera }), contentType: "application/json" });
    } finally { release(); }
    await viewportResponse;
    await expect(page.locator(".kt-map-readout")).toContainText("0건 표시");
    const after = (await stage.boundingBox())!;
    expect(after.y).toBeCloseTo(before.y, 1); expect(after.height).toBeCloseTo(before.height, 1);
    await expect.poll(() => canvas.evaluate((element) => (element as HTMLElement & { _maplibreMap: MapLibreMap })._maplibreMap.getCenter().lat)).toBeCloseTo(37.6031, 4);
  });

  test("375px 좌표행·확대 버튼과 마커 위 출처 접근", async ({ page }, testInfo) => {
    await page.route("**/transport/features/places?**", (route) => route.fulfill({ json: { items: [], total: 659, truncated: false, clustered: true, clusters: [{ longitude: 127.8, latitude: 36.2, count: 659, kind_counts: { fuel_station: 659 } }] } }));
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("/fuel");
    const canvas = page.locator(".maplibregl-map");
    await expect(page.locator(".kt-map-coordinates")).toContainText("center");
    await expect(page.locator(".kt-map-readout")).not.toContainText("조회 중");
    const stage = (await page.locator('[data-slot="map-stage"][data-view="map"]').boundingBox())!;
    const zoom = page.locator(".maplibregl-ctrl-zoom-in");
    const zoomBox = (await zoom.boundingBox())!;
    const attribution = page.locator(".maplibregl-ctrl-attrib");
    const marker = page.locator(".map-cluster");
    await expect(marker).toBeVisible();
    const overlap = async (target: Locator) => {
      const m = (await marker.boundingBox())!, a = (await target.boundingBox())!;
      const offset = [m.x + m.width / 2 - a.x - a.width / 2, m.y + m.height / 2 - a.y - a.height / 2];
      const response = page.waitForResponse((response) => response.url().includes("/features/places?") && response.status() === 200);
      await canvas.evaluate((element, offset) => (element as HTMLElement & { _maplibreMap: MapLibreMap })._maplibreMap.panBy(offset as [number, number], { duration: 0 }), offset);
      await response;
      await expect(page.locator(".kt-map-readout")).not.toContainText("조회 중");
      await expect.poll(async () => { const a = (await target.boundingBox())!, m = (await marker.boundingBox())!; return Math.hypot(a.x + a.width / 2 - m.x - m.width / 2, a.y + a.height / 2 - m.y - m.height / 2); }).toBeLessThan(2);
      return target.evaluate((element) => { const bounds = element.getBoundingClientRect(); return element.contains(document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2)); });
    };
    const attributionHit = await overlap(attribution);
    const attributionOverlap = await marker.boundingBox();
    const zoomHit = await overlap(zoom);
    const corners = await page.locator(".maplibregl-ctrl-top-right, .maplibregl-ctrl-bottom-right").evaluateAll((elements) => elements.map((element) => getComputedStyle(element).zIndex));
    const markerZ = await marker.evaluate((element) => getComputedStyle(element).zIndex);
    await testInfo.attach("실 SDK 터치 치수와 조작부 겹침", { body: JSON.stringify({ stage, zoom: zoomBox, attribution: await attribution.boundingBox(), attributionOverlap, marker: await marker.boundingBox(), markerZ, corners, attributionHit, zoomHit }), contentType: "application/json" });
    expect(stage.y).toBeLessThanOrEqual(240);
    expect(zoomBox.width).toBeGreaterThanOrEqual(44);
    expect(zoomBox.height).toBeGreaterThanOrEqual(44);
    expect(markerZ).toBe("3");
    expect(corners).toEqual(["6", "6"]);
    expect(attributionHit).toBe(true);
    expect(zoomHit).toBe(true);
    const zoomBefore = await canvas.evaluate((element) => (element as HTMLElement & { _maplibreMap: MapLibreMap })._maplibreMap.getZoom());
    await zoom.click();
    await expect.poll(() => canvas.evaluate((element) => (element as HTMLElement & { _maplibreMap: MapLibreMap })._maplibreMap.getZoom())).toBeCloseTo(zoomBefore + 1, 2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/workspace-sdk-${testInfo.project.name}-375-touch-controls.png`, animations: "disabled" });
  });
});

for (const width of [375, 1440]) for (const path of ["/map", "/rail/metro"]) test(`${path} ${width}px 실제 SDK 카메라는 목록 왕복 뒤 유지된다`, async ({ page }) => {
  await page.setViewportSize({ width, height: width === 375 ? 812 : 900 });
  await page.goto(path);
  const readCamera = () => page.locator(".maplibregl-map").evaluate((element) => {
    const map = (element as HTMLElement & { _maplibreMap?: MapLibreMap })._maplibreMap;
    const center = map?.getCenter();
    return map && center ? { longitude: center.lng, latitude: center.lat, zoom: map.getZoom() } : null;
  });
  await expect.poll(readCamera).not.toBeNull();
  await expect(page.locator(".kt-map-coordinates")).toContainText("center");
  await expect.poll(() => page.locator(".maplibregl-map").evaluate((element) => (element as HTMLElement & { _maplibreMap: MapLibreMap })._maplibreMap.loaded())).toBe(true);
  await page.locator(".maplibregl-map").evaluate((element) => (element as HTMLElement & { _maplibreMap: MapLibreMap })._maplibreMap.jumpTo({ center: [128.5316, 37.6031], zoom: 12.5 }));
  await expect.poll(async () => (await readCamera())?.longitude).toBeCloseTo(128.5316, 4);
  await expect.poll(async () => (await readCamera())?.latitude).toBeCloseTo(37.6031, 4);
  await expect.poll(() => page.locator(".maplibregl-map").evaluate((element) => (element as HTMLElement & { _maplibreMap: MapLibreMap })._maplibreMap.isMoving())).toBe(false);
  const before = (await readCamera())!;
  await page.getByRole("tab", { name: "목록", exact: true }).click();
  await page.getByRole("tab", { name: "지도", exact: true }).click();
  await expect.poll(readCamera).not.toBeNull();
  const after = (await readCamera())!;
  expect(after.longitude).toBeCloseTo(before.longitude, 4);
  expect(after.latitude).toBeCloseTo(before.latitude, 4);
  expect(after.zoom).toBeCloseTo(before.zoom, 2);
  await expect(page.locator(".kt-map-coordinates")).toContainText("center 128.5316, 37.6031 · z 12.5");
  if (width === 375) {
    await page.locator(".maplibregl-map").evaluate((element) => { (window as Window & { transportFixtureMap?: MapLibreMap }).transportFixtureMap = (element as HTMLElement & { _maplibreMap: MapLibreMap })._maplibreMap; });
    await page.getByRole("button", { name: "지도 크게 보기", exact: true }).click();
    await expect(page.locator('[data-slot="map-workspace"]')).toHaveAttribute("data-expanded", "true");
    expect(await page.locator(".maplibregl-map").evaluate((element) => (element as HTMLElement & { _maplibreMap: MapLibreMap })._maplibreMap === (window as Window & { transportFixtureMap?: MapLibreMap }).transportFixtureMap)).toBe(true);
    await expect.poll(async () => (await readCamera())?.longitude).toBeCloseTo(before.longitude, 4);
    await page.getByRole("button", { name: "원래 화면으로", exact: true }).click();
    await expect.poll(async () => (await readCamera())?.latitude).toBeCloseTo(before.latitude, 4);
    expect((await readCamera())!.zoom).toBeCloseTo(before.zoom, 2);
  }
});
