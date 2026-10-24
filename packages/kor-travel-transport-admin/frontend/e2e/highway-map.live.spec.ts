import { expect, test } from "@playwright/test";

const password = process.env.E2E_TRANSPORT_UI_PASSWORD;
const api = process.env.E2E_TRANSPORT_HIGHWAY_API_URL;
for (const width of [375, 1440]) test(`실제 ITS 소통 경로 지도·상세·접근성 ${width}px`, async ({ page, request }) => {
  test.setTimeout(100_000);
  test.skip(!password || !api, "명시적인 실제 ITS 로컬 API와 로그인 설정 필요");
  await page.setViewportSize({ width, height: 1000 });
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  let firstLinkCenter: [number, number] | null = null;
  // 지도 소통은 실제 로컬 API→SDK→ITS 응답을 전달한다. 운영 DB의 다른 영역은 조회하지 않는다.
  for (const path of ["roads", "road-traffic"]) await page.route(`**/api/transport/transport/highways/${path}${path === "roads" ? "" : "?**"}`, async (route) => {
    const url = new URL(route.request().url());
    const response = await request.get(`${api}/v1/transport/highways/${path}${url.search}`, { timeout: 30_000 });
    if (path === "road-traffic" && response.ok()) {
      const body = await response.json() as { items: { path: [number, number][] }[] };
      const points = body.items[0]?.path;
      firstLinkCenter = points?.[Math.floor(points.length / 2)] ?? null;
    }
    await route.fulfill({ response });
  });
  for (const path of ["traffic", "incidents"]) await page.route(`**/transport/highways/${path}?**`, (route) => route.fulfill({ json: { items: [] } }));
  await page.goto("/login"); await page.getByLabel("비밀번호").fill(password!);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto("/highways");
  await expect(page.getByRole("combobox", { name: "고속도로", exact: true }).locator("option")).not.toHaveCount(1);
  await page.getByRole("combobox", { name: "고속도로", exact: true }).selectOption("0010");
  const list = page.getByLabel("선택 도로 소통 구간").filter({ visible: true });
  await expect(list.getByRole("button").first()).toBeVisible({ timeout: 40_000 });
  const stage = page.locator(".embedded-map .map-primary").first();
  const box = await stage.boundingBox();
  expect(box!.height).toBeGreaterThan(500);
  if (width === 375) expect(box!.y).toBeLessThan(650);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect.poll(() => page.locator(".maplibregl-map").evaluate((element) => {
    const map = (element as HTMLElement & { _maplibreMap?: { getLayer: (id: string) => unknown; queryRenderedFeatures: (options: { layers: string[] }) => unknown[] } })._maplibreMap;
    return map?.getLayer("its-selected-road-lines") ? map.queryRenderedFeatures({ layers: ["its-selected-road-lines"] }).length : 0;
  }), { timeout: 20_000 }).toBeGreaterThan(0);
  const row = list.getByRole("button").first();
  await row.focus(); await row.press("Enter");
  const detail = page.getByRole("complementary", { name: "선택 장소 상세" });
  await expect(detail).toBeFocused();
  await expect(detail.getByRole("link", { name: "ITS 원문 지도" })).toHaveAttribute("href", "https://www.its.go.kr/map/traffic");
  await expect(detail).toHaveCSS("position", "absolute");
  await page.keyboard.press("Escape"); await expect(detail).toHaveCount(0); await expect(row).toBeFocused();
  await page.getByRole("tab", { name: "목록", exact: true }).click();
  await expect(page.getByLabel("선택 도로 소통 구간").filter({ visible: true })).toHaveCount(1);
  await page.getByLabel("선택 도로 소통 구간").filter({ visible: true }).getByRole("button").first().click();
  await expect(page.getByRole("tab", { name: "지도", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(detail).toBeVisible(); await page.keyboard.press("Escape");
  await expect.poll(() => page.locator(".maplibregl-map").evaluate((element, expected) => {
    const map = (element as HTMLElement & { _maplibreMap?: { getCenter: () => { lng: number; lat: number }; getZoom: () => number } })._maplibreMap;
    const center = map?.getCenter();
    return Boolean(center && expected && Math.abs(center.lng - expected[0]) < .001 && Math.abs(center.lat - expected[1]) < .001 && map!.getZoom() >= 10.9);
  }, firstLinkCenter)).toBe(true);
  await page.locator(".maplibregl-map").evaluate((element) => {
    (element as HTMLElement & { _maplibreMap?: { jumpTo: (camera: { center: [number, number]; zoom: number }) => void } })._maplibreMap?.jumpTo({ center: [129, 35], zoom: 8 });
  });
  await list.getByRole("button").first().click();
  await expect.poll(() => page.locator(".maplibregl-map").evaluate((element, expected) => {
    const center = (element as HTMLElement & { _maplibreMap?: { getCenter: () => { lng: number; lat: number } } })._maplibreMap?.getCenter();
    return Boolean(center && expected && Math.abs(center.lng - expected[0]) < .001 && Math.abs(center.lat - expected[1]) < .001);
  }, firstLinkCenter)).toBe(true);
  await expect(detail).toBeFocused(); await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "도로 지도 출처와 범위 안내" }).click();
  await expect(page.getByText("전국 완전성은 보장하지 않으며", { exact: false })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.screenshot({ path: `test-results/highway-live-${width}.png`, fullPage: true });
  expect(pageErrors).toEqual([]);
});
