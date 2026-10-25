import { expect, test } from "@playwright/test";

for (const width of [375, 1440]) test(`공통 지도 필터·좌표·상세 오버레이 ${width}px`, async ({ page }) => {
  test.setTimeout(90_000);
  test.skip(!process.env.E2E_TRANSPORT_UI_PASSWORD, "로그인 암호 필요");
  await page.setViewportSize({ width, height: 1000 });
  await page.goto("/login");
  await page.getByLabel("비밀번호").fill(process.env.E2E_TRANSPORT_UI_PASSWORD!);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/$/, { timeout: 30_000 });
  const place = { id: 9401, kind: "rest_area", source: "krex_rest_area", name: "공통 UI 시험휴게소", latitude: 36.2, longitude: 127.8, line_names: [], facilities: [], prices: [], updated_at: new Date().toISOString() };
  await page.route("**/transport/features/places?**", (route) => {
    const query = new URL(route.request().url()).searchParams;
    const items = query.has("kinds") || query.get("kind") === "rest_area" ? [place] : [];
    return route.fulfill({ json: { items, total: items.length, truncated: false, available_sources: [place.source] } });
  });
  await page.goto("/map");
  const filter = page.locator("[data-slot=map-filter-bar]");
  const query = page.getByLabel("장소 검색", { exact: true });
  const source = page.getByRole("combobox", { name: "데이터 출처" });
  await expect(query).toBeVisible();
  const sizes = await filter.evaluate((element) => {
    const field = element.querySelector<HTMLInputElement>('input[type="search"]')!;
    const combo = element.querySelector<HTMLElement>(".kt-map-combobox")!;
    const kind = element.querySelector<HTMLElement>(".kt-map-kinds > button")!;
    return [field, combo, kind].map((node) => ({ height: node.getBoundingClientRect().height, top: node.getBoundingClientRect().top, width: node.getBoundingClientRect().width }));
  });
  expect(sizes.map((item) => item.height)).toEqual([30, 30, 30]);
  if (width === 1440) {
    expect(sizes[0].width).toBe(176);
    expect(sizes[1].width).toBe(176);
    expect(Math.max(...sizes.map((item) => item.top)) - Math.min(...sizes.map((item) => item.top))).toBeLessThan(2);
  }
  await expect(page.locator(".kt-map-coordinates")).toHaveText(/center -?\d+\.\d{4}, -?\d+\.\d{4} · z \d+\.\d/, { timeout: 30_000 });
  await expect(page.locator(".kt-map-count")).toHaveText(/\d+건 표시/);
  await source.fill("고속도로");
  await page.getByRole("option", { name: "한국도로공사 고속도로 정보", exact: true }).click();
  await page.keyboard.press("Escape");
  await expect(page.locator(".kt-map-combobox")).toHaveCSS("height", "30px");
  await page.getByRole("tab", { name: "목록", exact: true }).click();
  await page.locator(".map-place-list").getByRole("button", { name: /공통 UI 시험휴게소/ }).click();
  const detail = page.getByRole("complementary", { name: "선택 장소 상세" });
  await expect(detail).toBeVisible();
  await expect(detail).toHaveCSS("position", "absolute");
  const stage = await page.locator(".kt-map-stage:visible").boundingBox();
  const overlay = await detail.boundingBox();
  expect(overlay!.x).toBeGreaterThanOrEqual(stage!.x);
  expect(overlay!.x + overlay!.width).toBeLessThanOrEqual(stage!.x + stage!.width + 1);
  await page.screenshot({ path: `test-results/transport-shared-overlay-${width}.png`, fullPage: true });
  await detail.focus();
  await page.keyboard.press("Escape");
  await expect(detail).toHaveCount(0);
  await expect(query).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/shared-map-ui-${width}.png`, fullPage: true });
});
