import { expect, test, type Locator, type Page } from "@playwright/test";

const observedAt = "2026-10-25T01:00:00Z";
const station = { id: 71, kind: "rail_station", source: "kric_public_file", name: "시험역", subtitle: "시험 운영기관", provider_id: "S1", line_names: ["시험선"], address: "시험 주소", phone: "031-000-0000", latitude: 37.3, longitude: 127.1, prices: [], facilities: ["엘리베이터"], updated_at: observedAt };
const airport = { ...station, kind: "airport", provider_id: "GMP", name: "시험공항", line_names: [] };
const ports = Array.from({ length: 6 }, (_, index) => ({ ...station, id: index + 1, kind: "ferry_port", provider_id: `P${index + 1}`, name: `시험항구${index + 1}`, line_names: [] }));
const fuel = { ...station, kind: "fuel_station", source: "opinet_browser", name: "시험주유소", prices: [{ product_code: "B027", price: 1705, observed_at: observedAt }] };
const metrics = { product_code: "B027", station_count: 10, average_price: 1700, minimum_price: 1600, maximum_price: 1800, price_spread: 200, standard_deviation: 50, saving_50l: 5000, cheapest_station_count: 1, cheapest_station: { name: "시험주유소", address: "시험 주소" }, generated_at: observedAt };

async function fixture(page: Page) {
  await page.context().addCookies([{ name: "kor_travel_transport_admin_session", value: "isolated-e2e", url: process.env.E2E_BASE_URL ?? "http://127.0.0.1:12351", httpOnly: true, sameSite: "Strict" }]);
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url()); let body: unknown = { items: [] };
    if (url.pathname.endsWith("/features/places")) {
      const kind = url.searchParams.get("kind");
      const items = kind === "airport" ? [airport] : kind === "rail_station" ? [station] : kind === "ferry_port" ? ports : kind === "fuel_station" || url.searchParams.get("kinds") === "fuel_station" ? [fuel] : kind ? [] : [station, airport, ports[0]];
      body = { items, total: items.length, truncated: false, fuel_statistics: [metrics], fuel_prices_stale: true, fuel_prices_last_refreshed_at: observedAt };
    } else if (url.pathname.endsWith("/rail/general/guide")) body = { fetched_at: observedAt, stale: false, kind: "ktx", category_code: "A", total: 1, categories: [{ code: "A", name: "시험노선" }], items: [{ provider_id: "S1", station_name: station.name, address: station.address, phone: station.phone, latitude: station.latitude, longitude: station.longitude }] };
    else if (url.pathname.endsWith("/rail/general/catalog")) body = { fetched_at: observedAt, cities: [{ code: "11", name: "서울" }], train_classes: [{ code: "0A", name: "KTX" }] };
    else if (url.pathname.endsWith("/bus/terminals")) body = { items: [{ id: 1, terminal_id: "T1", terminal_name: "시험터미널", city_name: "시험도시", latitude: 37.3, longitude: 127.1, updated_at: observedAt }], next_offset: null };
    else if (url.pathname.endsWith("/highways/roads")) body = { items: [{ road_id: "001", name: "시험도로", road_number: "1" }], stale: false, fetched_at: observedAt };
    else if (url.pathname.endsWith("/highways/road-traffic")) body = { items: [{ link_id: "L1", section_name: "시험 소통 구간", speed_kmh: 80, length_m: 1000, path: [[127, 37], [127.1, 37.1]] }], road_id: "001", road_name: "시험도로", direction: "1", fetched_at: observedAt, stale: false, source_url: "https://www.its.go.kr/map/traffic" };
    else if (url.pathname.endsWith("/parking/current")) body = { items: [{ parking_lot_id: 1, parking_lot_name: "시험주차장", available_spaces: 52, total_spaces: 100, observed_at: new Date().toISOString() }] };
    else if (url.pathname.endsWith("/flights/status")) body = { status: "success", items: [{ flight_number: "FUTURE101", direction: "arrival", origin_airport: "PUS", destination_airport: "GMP", scheduled_at: new Date(Date.now() + 3600000).toISOString(), estimated_at: null }] };
    else if (url.pathname.endsWith("/parking/outlook")) body = { generated_at: observedAt, items: [] };
    else if (url.pathname.endsWith("/ports/timetables")) body = { service_date: url.searchParams.get("date"), items: [], missing_port_ids: url.searchParams.get("port_ids")?.split(",") ?? [] };
    await route.fulfill({ json: body });
  });
}

async function clipping(locator: Locator) {
  return locator.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const visible = { left: 0, top: 0, right: innerWidth, bottom: innerHeight };
    for (let parent = element.parentElement; parent; parent = parent.parentElement) {
      const style = getComputedStyle(parent), bounds = parent.getBoundingClientRect();
      if (/auto|scroll|hidden|clip/.test(style.overflowY)) { visible.top = Math.max(visible.top, bounds.top); visible.bottom = Math.min(visible.bottom, bounds.bottom); }
      if (/auto|scroll|hidden|clip/.test(style.overflowX)) { visible.left = Math.max(visible.left, bounds.left); visible.right = Math.min(visible.right, bounds.right); }
    }
    return { fullyVisible: rect.top >= visible.top - 1 && rect.bottom <= visible.bottom + 1 && rect.left >= visible.left - 1 && rect.right <= visible.right + 1, top: rect.top, bottom: rect.bottom, clipTop: visible.top, clipBottom: visible.bottom };
  });
}

test.beforeEach(async ({ page }) => {
  test.skip(process.env.E2E_MAP_WORKSPACE !== "true", "격리 지도 작업면 UI 테스트");
  await fixture(page);
});

const routes = ["/map", "/fuel", "/highways", "/rail", "/rail/metro", "/bus/express", "/bus/intercity", "/flights", "/ferry"];
for (const width of [320, 375, 1440]) for (const path of routes) test(`${path} ${width}px 남은 높이와 지도·목록 작업면`, async ({ page }, testInfo) => {
  const height = width === 320 ? 568 : width === 375 ? 812 : 900;
  await page.setViewportSize({ width, height });
  await page.goto(path);
  if (path === "/flights") {
    await expect(page.getByText("52", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("FUTURE101", { exact: false })).toBeVisible();
    await expect(page.locator('[data-slot="map-workspace"]')).toHaveCount(0);
    await page.getByRole("button", { name: "공항 지도", exact: true }).click();
  }
  const stage = page.locator('[data-slot="map-stage"]:visible');
  await expect(stage).toBeVisible();
  const bounds = (await stage.boundingBox())!;
  await testInfo.attach("작업면 치수", { body: JSON.stringify({ path, width, height, stage: bounds }), contentType: "application/json" });
  expect(bounds.height).toBeGreaterThan(180);
  if (width === 375) expect(bounds.y).toBeLessThanOrEqual(240);
  if (width === 1440) expect(height - bounds.y - bounds.height).toBeLessThanOrEqual(24);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  if (width < 640) await expect(page.locator('[data-slot="map-filter-trigger"]')).toHaveAttribute("aria-expanded", "false");
  if (path === "/fuel") {
    const summary = page.getByRole("region", { name: "현재 지도 범위 유가 통계" });
    await expect(summary).toContainText("1,700");
    for (const node of [summary.locator("header"), summary.locator("dl"), summary.getByRole("status"), page.locator(".map-feedback").getByRole("alert")]) {
      const bounds = await clipping(node);
      expect(bounds, JSON.stringify({ text: await node.textContent(), ...bounds })).toMatchObject({ fullyVisible: true });
    }
  }
  await page.screenshot({ path: `test-results/workspace-${testInfo.project.name}-${path.replaceAll("/", "-")}-${width}.png`, fullPage: false, animations: "disabled" });
  await page.getByRole("tab", { name: "목록", exact: true }).click();
  await expect(page.locator('[data-slot="map-stage"][data-view="list"]')).toBeVisible();
  await page.getByRole("tab", { name: "지도", exact: true }).click();
  await expect(page.locator('[data-slot="map-stage"][data-view="map"]')).toBeVisible();
});

for (const width of [414, 768]) for (const path of routes) test(`${path} ${width}px 중간 폭 치수와 대표 상세 닫기`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 });
  await page.goto(path);
  if (path === "/flights") await page.getByRole("button", { name: "공항 지도", exact: true }).click();
  const stage = page.locator('[data-slot="map-stage"]:visible');
  await expect(stage).toBeVisible();
  const bounds = (await stage.boundingBox())!;
  expect(bounds.height).toBeGreaterThan(300);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await testInfo.attach("작업면 치수", { body: JSON.stringify({ path, width, stage: bounds }), contentType: "application/json" });
  if (path === "/fuel" || path === "/rail") {
    await page.getByRole("tab", { name: "목록", exact: true }).click();
    const opener = page.locator(".map-place-list").getByRole("button", { name: path === "/fuel" ? /시험주유소/ : /시험역/ }).first();
    await opener.click();
    const close = page.getByRole("button", { name: "상세 닫기", exact: true });
    await expect(close).toBeVisible();
    expect(await clipping(close)).toMatchObject({ fullyVisible: true });
    await close.click();
    await expect(page.getByRole("complementary", { name: "선택 장소 상세" })).toHaveCount(0);
    await expect(opener).toBeFocused();
  }
});

test.describe("터치 지도 접근", () => {
  test.use({ hasTouch: true });
  for (const width of [320, 375]) test(`유가 ${width}px 터치 컨트롤과 필수 정보`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 320 ? 568 : 812 });
    await page.goto("/fuel");
    const summary = page.getByRole("region", { name: "현재 지도 범위 유가 통계" });
    await expect(summary).toContainText("1,700");
    if (width === 375) expect((await page.locator('[data-slot="map-stage"]:visible').boundingBox())!.y).toBeLessThanOrEqual(240);
    for (const node of [summary.locator("header"), summary.locator("dl"), summary.getByRole("status"), page.locator(".map-feedback").getByRole("alert")]) expect(await clipping(node)).toMatchObject({ fullyVisible: true });
    for (const control of [page.locator('[data-slot="map-filter-trigger"]'), page.locator('[data-slot="map-workspace-expand"]'), page.getByRole("tab", { name: "지도", exact: true }), summary.getByRole("button", { name: "지도 범위 유가 통계 안내" })]) expect((await control.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });

  for (const variant of ["landscape", "text200"]) test(`유가 ${variant} 명시 확장으로 필수 정보·상세 접근`, async ({ page }, testInfo) => {
    await page.setViewportSize(variant === "landscape" ? { width: 812, height: 375 } : { width: 320, height: 568 });
    await page.goto("/fuel");
    const summary = page.getByRole("region", { name: "현재 지도 범위 유가 통계" });
    await expect(summary).toContainText("1,700");
    if (variant === "text200") await page.addStyleTag({ content: "html { font-size: 200% !important; }" });
    const expand = page.getByRole("button", { name: "지도 크게 보기", exact: true });
    expect(await clipping(expand)).toMatchObject({ fullyVisible: true });
    await expand.click();
    const workspace = page.locator('[data-slot="map-workspace"]');
    await expect(workspace).toHaveAttribute("data-expanded", "true");
    await expect(page.getByRole("heading", { name: "유가 지도", exact: true })).not.toBeVisible();
    const essentials = [summary.locator("header"), summary.locator("dl"), summary.getByRole("status"), page.locator(".map-feedback").getByRole("alert")];
    for (const node of essentials) expect(await clipping(node), await node.textContent() ?? "").toMatchObject({ fullyVisible: true });
    await page.getByRole("tab", { name: "목록", exact: true }).click();
    await page.locator(".map-place-list").getByRole("button", { name: /시험주유소/ }).click();
    await page.getByRole("tab", { name: "지도", exact: true }).click();
    await expect(summary.getByRole("button", { name: "현재 지도 범위", exact: true })).toHaveAttribute("aria-expanded", "false");
    await expect(summary.locator("dl")).not.toBeVisible();
    for (const node of [summary.getByRole("button", { name: "현재 지도 범위", exact: true }), page.locator(".map-feedback").getByRole("alert"), page.getByRole("button", { name: "상세 닫기", exact: true })]) expect(await clipping(node), await node.textContent() ?? "").toMatchObject({ fullyVisible: true });
    const detail = page.getByRole("complementary", { name: "선택 장소 상세" });
    await expect(detail.getByRole("status")).toContainText("26.10.25 10:00 KST");
    expect(await clipping(detail.getByRole("status"))).toMatchObject({ fullyVisible: true });
    const price = detail.locator(".price-grid dd");
    await price.scrollIntoViewIfNeeded();
    expect(await clipping(price)).toMatchObject({ fullyVisible: true });
    expect(await clipping(page.getByRole("button", { name: "상세 닫기", exact: true }))).toMatchObject({ fullyVisible: true });
    await testInfo.attach("확장 작업면 치수", { body: JSON.stringify({ variant, stage: await page.locator('[data-slot="map-stage"]:visible').boundingBox(), summary: await summary.boundingBox() }), contentType: "application/json" });
    await page.screenshot({ path: `test-results/workspace-${testInfo.project.name}-${variant}-expanded.png`, animations: "disabled" });
    await detail.focus();
    await page.keyboard.press("Escape");
    await expect(detail).toHaveCount(0);
    await expect(summary.locator("dl")).toBeVisible();
    for (const node of essentials) expect(await clipping(node), await node.textContent() ?? "").toMatchObject({ fullyVisible: true });
    await expect(workspace).toHaveAttribute("data-expanded", "true");
    await page.getByRole("button", { name: "원래 화면으로", exact: true }).focus();
    await page.keyboard.press("Escape");
    await expect(workspace).toHaveAttribute("data-expanded", "false");
    await expect(page.getByRole("heading", { name: "유가 지도", exact: true })).toBeVisible();
    await expect(expand).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
});

test("고속도로 장소 없는 구간 상세는 목록에서 열고 닫아도 조회 조건을 유지한다", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/highways");
  await page.getByRole("tab", { name: "목록", exact: true }).click();
  await page.locator(".map-place-list").getByRole("button", { name: /시험 소통 구간/ }).click();
  await expect(page.getByRole("tab", { name: "지도", exact: true })).toHaveAttribute("aria-selected", "true");
  const detail = page.getByRole("complementary", { name: "선택 장소 상세" });
  await expect(detail).toContainText("시험 소통 구간");
  await expect(detail).toContainText("80 km/h");
  await expect(detail).toBeFocused();
  expect(await clipping(page.getByRole("button", { name: "상세 닫기", exact: true }))).toMatchObject({ fullyVisible: true });
  await page.keyboard.press("Escape");
  await expect(detail).toHaveCount(0);
  await page.getByRole("tab", { name: "목록", exact: true }).click();
  await expect(page.locator(".map-place-list").getByRole("button", { name: /시험 소통 구간/ })).toBeVisible();
});

test("공항 선택으로 연 상세를 모바일에서 닫으면 숨은 select 대신 보이는 필터로 복귀한다", async ({ page }) => {
  const secondAirport = { ...airport, id: 72, provider_id: "CJU", name: "두번째공항" };
  await page.route("**/transport/features/places?**", (route) => route.fulfill({ json: { items: [airport, secondAirport] } }));
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/flights");
  await expect(page.getByLabel("공항", { exact: true })).toHaveValue(String(airport.id));
  await page.getByRole("button", { name: "공항 지도", exact: true }).click();
  const detail = page.getByRole("complementary", { name: "선택 장소 상세" });
  await expect(detail).toBeFocused();
  const select = page.getByLabel("공항", { exact: true });
  await select.focus();
  await select.selectOption(String(secondAirport.id));
  await expect(detail).toContainText("두번째공항");
  await expect(detail).toBeFocused();
  await page.setViewportSize({ width: 375, height: 812 });
  const trigger = page.locator('[data-slot="map-filter-trigger"]');
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await expect(select).not.toBeVisible();
  await page.keyboard.press("Escape");
  await expect(detail).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("출처 팝업을 연 채 모바일로 바꾸면 숨은 필터에 팝업과 초점을 남기지 않는다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/fuel");
  await expect(page.getByRole("region", { name: "현재 지도 범위 유가 통계" })).toContainText("1,700");
  const source = page.getByLabel("데이터 출처", { exact: true });
  await source.click();
  await expect(page.getByRole("listbox")).toBeVisible();
  await page.setViewportSize({ width: 375, height: 812 });
  const trigger = page.locator('[data-slot="map-filter-trigger"]');
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("listbox")).not.toBeVisible();
  await expect(trigger).toBeFocused();
  await trigger.click();
  await source.click();
  await expect(page.getByRole("listbox")).toBeVisible();
});

for (const [path, hash] of [["/rail", "#general-rail-timetable"], ["/rail/metro", "#station-timetable"], ["/bus/express", "#bus-departures"], ["/ferry", "#ferry-comparison"]]) test(`${path} 확장 지도에서도 시간표·비교와 native anchor 왕복`, async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(path);
  const filter = page.locator('[data-slot="map-filter-trigger"]');
  if (path === "/rail/metro") {
    await filter.click();
    await page.getByLabel("노선", { exact: true }).selectOption({ label: "시험선 · 시험 운영기관" });
    await page.getByRole("tab", { name: "목록", exact: true }).click();
    await page.locator(".map-place-list").getByRole("button", { name: /시험역/ }).click();
    await page.getByRole("tab", { name: "지도", exact: true }).click();
  }
  await page.getByRole("button", { name: "지도 크게 보기", exact: true }).click();
  if (await filter.getAttribute("aria-expanded") === "false") await filter.click();
  const stage = page.locator('[data-slot="map-stage"]:visible');
  const height = (await stage.boundingBox())!.height;
  await page.locator(`.kt-map-filter-panel-body a[href="${hash}"]`).click();
  const target = page.locator(hash);
  await expect(target).toBeInViewport();
  expect(await page.evaluate(() => location.hash)).toBe(hash);
  expect(await page.locator("main").evaluate((node) => node.scrollTop)).toBeGreaterThan(100);
  expect((await stage.boundingBox())!.height).toBeCloseTo(height, 1);
  await target.getByRole("link", { name: "지도 작업면으로", exact: true }).click();
  await expect(stage).toBeInViewport();
  expect((await stage.boundingBox())!.height).toBeCloseTo(height, 1);
  await expect(page.locator('[data-slot="map-workspace"]')).toHaveAttribute("data-expanded", "true");
});

test("배편 목록은 5곳 선택과 지도 왕복을 보존하고 여섯째 선택은 막는다", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/ferry");
  await page.getByRole("tab", { name: "목록", exact: true }).click();
  const choices = page.getByRole("checkbox");
  await expect(choices).toHaveCount(6);
  for (let index = 0; index < 5; index++) await choices.nth(index).check();
  await expect(choices.nth(5)).toBeDisabled();
  await expect(page.getByRole("complementary", { name: "선택 장소 상세" })).toHaveCount(0);
  await page.getByRole("tab", { name: "지도", exact: true }).click();
  await page.getByRole("tab", { name: "목록", exact: true }).click();
  for (let index = 0; index < 5; index++) await expect(choices.nth(index)).toBeChecked();
  await choices.nth(0).uncheck();
  await expect(choices.nth(5)).toBeEnabled();
});
