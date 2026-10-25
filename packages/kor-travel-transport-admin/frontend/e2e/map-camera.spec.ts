import { expect, test } from "@playwright/test";
import type { Map as MapLibreMap } from "maplibre-gl";

// 공개 키·운영 타일 없이 실제 SDK/MapLibre 엔진의 재마운트를 검증한다.
// QA dev 서버에는 운영 키 대신 NEXT_PUBLIC_VWORLD_API_KEY=transport-layout-local-fixture를 준다.
test.beforeEach(async ({ page }) => {
  test.skip(process.env.E2E_MAP_SDK !== "true", "격리 SDK 지도·타일 fixture 필요");
  await page.context().addCookies([{ name: "kor_travel_transport_admin_session", value: "isolated-e2e", url: process.env.E2E_BASE_URL ?? "http://127.0.0.1:12352", httpOnly: true, sameSite: "Strict" }]);
  await page.route("**/api/transport/**", (route) => route.fulfill({ json: { items: [], total: 0, truncated: false } }));
  await page.route("https://api.vworld.kr/**", (route) => route.fulfill({ contentType: "image/png", headers: { "access-control-allow-origin": "*" }, body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/zHcAAAAASUVORK5CYII=", "base64") }));
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
  await page.locator(".maplibregl-map").evaluate((element) => (element as HTMLElement & { _maplibreMap: MapLibreMap })._maplibreMap.jumpTo({ center: [128.5316, 37.6031], zoom: 12.5 }));
  await expect.poll(async () => (await readCamera())?.longitude).toBeCloseTo(128.5316, 4);
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
