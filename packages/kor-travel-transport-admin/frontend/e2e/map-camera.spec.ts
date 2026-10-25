import { expect, test } from "@playwright/test";
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
  test("375px 좌표행·확대 버튼과 마커 위 출처 접근", async ({ page }, testInfo) => {
    const place = { id: 1, kind: "fuel_station", source: "opinet_browser", name: "조작부 겹침 시험", longitude: 127.8, latitude: 36.2, line_names: [], facilities: [], prices: [{ product_code: "B027", price: 1700, observed_at: "2026-10-25T01:00:00Z" }], updated_at: "2026-10-25T01:00:00Z" };
    await page.route("**/transport/features/places?**", (route) => route.fulfill({ json: { items: [place], total: 1, truncated: false } }));
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("/fuel");
    const canvas = page.locator(".maplibregl-map");
    await expect(page.locator(".kt-map-coordinates")).toContainText("center");
    await expect(page.locator(".kt-map-readout")).not.toContainText("조회 중");
    const stage = (await page.locator('[data-slot="map-stage"]').boundingBox())!;
    const zoom = page.locator(".maplibregl-ctrl-zoom-in");
    const zoomBox = (await zoom.boundingBox())!;
    const attribution = page.locator(".maplibregl-ctrl-attrib");
    const marker = page.locator(".transport-map-marker");
    await expect(marker).toBeVisible();
    const markerBox = (await marker.boundingBox())!, attributionBox = (await attribution.boundingBox())!;
    const offset = [markerBox.x + markerBox.width / 2 - attributionBox.x - attributionBox.width / 2, markerBox.y + markerBox.height / 2 - attributionBox.y - attributionBox.height / 2];
    const panResponse = page.waitForResponse((response) => response.url().includes("/features/places?") && response.status() === 200);
    await canvas.evaluate((element, offset) => (element as HTMLElement & { _maplibreMap: MapLibreMap })._maplibreMap.panBy(offset as [number, number], { duration: 0 }), offset);
    await panResponse;
    await expect(page.locator(".kt-map-readout")).not.toContainText("조회 중");
    await expect.poll(async () => {
      const a = (await attribution.boundingBox())!, m = (await marker.boundingBox())!;
      return Math.hypot(a.x + a.width / 2 - m.x - m.width / 2, a.y + a.height / 2 - m.y - m.height / 2);
    }).toBeLessThan(2);
    const attributionHit = await attribution.evaluate((element) => { const bounds = element.getBoundingClientRect(); return element.contains(document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2)); });
    await testInfo.attach("실 SDK 터치 치수와 출처 겹침", { body: JSON.stringify({ stage, zoom: zoomBox, attribution: await attribution.boundingBox(), marker: await marker.boundingBox(), attributionHit }), contentType: "application/json" });
    expect(stage.y).toBeLessThanOrEqual(240);
    expect(zoomBox.width).toBeGreaterThanOrEqual(44);
    expect(zoomBox.height).toBeGreaterThanOrEqual(44);
    expect(attributionHit).toBe(true);
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
