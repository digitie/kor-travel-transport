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
  const detailOpener = page.locator(".map-place-list").getByRole("button", { name: /공통 UI 시험휴게소/ });
  await detailOpener.click();
  const detail = page.getByRole("complementary", { name: "선택 장소 상세" });
  await expect(detail).toBeVisible();
  const overlays = page.locator(".kt-map-stage:visible .kt-map-stage-overlays");
  await expect(overlays).toHaveCSS("position", "absolute");
  await expect(detail.getByRole("heading", { name: place.name, exact: true })).toBeVisible();
  const stage = await page.locator(".kt-map-stage:visible").boundingBox();
  const overlay = await detail.boundingBox();
  expect(overlay!.x).toBeGreaterThanOrEqual(stage!.x);
  expect(overlay!.x + overlay!.width).toBeLessThanOrEqual(stage!.x + stage!.width + 1);
  expect(overlay!.height).toBeGreaterThan(0);
  expect(overlay!.y).toBeGreaterThanOrEqual(stage!.y);
  expect(overlay!.y + overlay!.height).toBeLessThanOrEqual(stage!.y + stage!.height + 1);
  const readable = await detail.evaluate((element) => {
    const heading = element.querySelector("h2")!;
    const text = document.createRange();
    text.selectNodeContents(heading);
    const label = text.getBoundingClientRect();
    const panel = element.getBoundingClientRect();
    return { scrollWidth: element.scrollWidth, clientWidth: element.clientWidth,
      label: { left: label.left, right: label.right, top: label.top, bottom: label.bottom, height: label.height },
      panel: { left: panel.left, right: panel.right, top: panel.top, bottom: panel.bottom } };
  });
  expect(readable.scrollWidth).toBeLessThanOrEqual(readable.clientWidth + 1);
  expect(readable.label.height).toBeGreaterThan(0);
  expect(readable.label.left).toBeGreaterThanOrEqual(readable.panel.left);
  expect(readable.label.right).toBeLessThanOrEqual(readable.panel.right + 1);
  expect(readable.label.top).toBeGreaterThanOrEqual(readable.panel.top);
  expect(readable.label.bottom).toBeLessThanOrEqual(readable.panel.bottom + 1);
  for (const button of await detail.locator(".kt-map-detail-header > button, .info-button").all()) {
    await expect(button).toHaveCSS("width", "32px");
    await expect(button).toHaveCSS("height", "32px");
    await expect(button.locator("svg")).toHaveCSS("width", "16px");
    await expect(button.locator("svg")).toHaveCSS("height", "16px");
  }
  const collapse = detail.getByRole("button", { name: "상세 접기", exact: true });
  await collapse.focus();
  await page.keyboard.press("Enter");
  await expect(detail.locator(".kt-map-detail-body")).toBeHidden();
  await page.keyboard.press("Space");
  await expect(detail.locator(".kt-map-detail-body")).toBeVisible();
  const info = detail.locator(".info-button").first();
  await info.click();
  const infoClose = page.getByRole("button", { name: "안내 닫기", exact: true });
  await expect(infoClose).toHaveCSS("width", "32px");
  await expect(infoClose).toHaveCSS("height", "32px");
  await expect(infoClose.locator("svg")).toHaveCSS("width", "16px");
  await expect(infoClose.locator("svg")).toHaveCSS("height", "16px");
  await infoClose.click();
  await page.screenshot({ path: `test-results/transport-shared-overlay-${width}.png`, fullPage: true });
  await detail.focus();
  await page.keyboard.press("Escape");
  await expect(detail).toHaveCount(0);
  await expect(detailOpener).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/shared-map-ui-${width}.png`, fullPage: true });
});


for (const width of [375, 1440]) test(`임베디드 공공주차 상세 버튼 ${width}px`, async ({ page }) => {
  test.setTimeout(90_000);
  test.skip(!process.env.E2E_TRANSPORT_UI_PASSWORD, "로그인 암호 필요");
  await page.setViewportSize({ width, height: 1000 });
  await page.goto("/login");
  await page.getByLabel("비밀번호").fill(process.env.E2E_TRANSPORT_UI_PASSWORD!);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/$/, { timeout: 30_000 });
  const stamp = new Date().toISOString();
  const item = { id: 9412, source: "datagokr_parking_lots", provider_id: "fixture",
    name: "임베디드 시험 공영주차장", longitude: 127.8, latitude: 36.2,
    road_address: "시험 주소", capacity: 25, collected_at: stamp, is_current: true,
    opening_hours: { weekday_open: null, weekday_close: null, saturday_open: null,
      saturday_close: null, holiday_open: null, holiday_close: null } };
  await page.route("**/transport/transport/parking-lots**", route => route.fulfill({ json:
    new URL(route.request().url()).pathname.endsWith("/9412") ? item : {
      generated_at: stamp, collection: { source: item.source, last_success_at: stamp,
        failed: false, stale: false, last_attempt_failed: false },
      items: [item], has_more: false, next_cursor: null,
    },
  }));
  await page.goto("/parking-lots");
  await page.getByRole("tab", { name: "목록", exact: true }).click();
  await page.locator(".public-parking-list .place-row").filter({ hasText: item.name }).click();
  const detail = page.locator(".embedded-map [data-slot=map-detail-overlay]:visible");
  await expect(detail).toHaveCount(1);
  await expect(detail.getByRole("heading", { name: item.name, exact: true })).toBeVisible();
  for (const button of await detail.locator(".kt-map-detail-header > button").all()) {
    await expect(button).toHaveCSS("width", "32px");
    await expect(button).toHaveCSS("height", "32px");
    await expect(button.locator("svg")).toHaveCSS("width", "16px");
    await expect(button.locator("svg")).toHaveCSS("height", "16px");
  }
  await detail.getByRole("button", { name: "상세 접기", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(detail.locator(".kt-map-detail-body")).toBeHidden();
  await page.keyboard.press("Space");
  await expect(detail.locator(".kt-map-detail-body")).toBeVisible();
  await detail.getByRole("button", { name: "상세 닫기", exact: true }).click();
  await expect(detail).toHaveCount(0);
});
