import { expect, test, type Page, type Request, type Route } from "@playwright/test";

// 공개 유가(TRANSPORT_UI_MODE=fuel) 작은 결함 묶음(소유자 목록 4a~4e)을 격리 응답으로 검사한다.
// 4a favicon, 4b 지역 이동 기본 선택(칩이 없으면 지도 중심), 4c 대화상자 제목 "지역 이동",
// 4d 필터 브랜드 "기타" 이름 한 번, 4e 지역 이동 직후 이전 zoom의 시/도 카드가 가장자리에 몰리지 않음.
// 스크린샷은 E2E_SCREENSHOT_DIR이 있으면 그곳에도 저장한다(ui- 접두어).
const generated = "2026-11-21T22:00:00Z";
const metrics = { station_count: 12, average_price: 1700, minimum_price: 1600, maximum_price: 1800, price_spread: 200,
  standard_deviation: 45, saving_50l: 5000, cheapest_station_count: 1, generated_at: generated, cheapest_station: { name: "최저가", address: "서울" } };
// 목록 첫 항목이 강원이다(예전에는 칩이 없으면 강원이 미리 골라졌다).
const catalog = { items: [
  { sido_value: "강원특별자치도", sido_name: "강원", sigungu: [{ sigungu_value: "강릉시", sigungu_name: "강릉시", station_count: 87, bounds: [128.8, 37.61, 129.04, 37.9] }] },
  { sido_value: "서울특별시", sido_name: "서울", sigungu: [
    { sigungu_value: "종로구", sigungu_name: "종로구", station_count: 20, bounds: [126.95, 37.57, 127.02, 37.6] },
    { sigungu_value: "중구", sigungu_name: "중구", station_count: 12, bounds: [126.96, 37.54, 127.02, 37.57] },
  ] },
  { sido_value: "경기도", sido_name: "경기", sigungu: [{ sigungu_value: "고양시 덕양구", sigungu_name: "고양시 덕양구", station_count: 60, bounds: [126.8, 37.58, 126.95, 37.72] }] },
] };
const sidoCards = [
  ["opinet:11", "서울", 126.98, 37.57], ["opinet:26", "부산", 129.07, 35.18], ["opinet:41", "경기", 127.2, 37.4],
  ["opinet:42", "강원", 128.2, 37.8], ["opinet:46", "전남", 126.9, 34.8], ["opinet:47", "경북", 128.7, 36.4],
].map(([region_key, label, longitude, latitude]) => ({ scope: "sido", region_key, label, product_code: "B027", average_price: 1700, station_count: 10, longitude, latitude }));

async function shot(page: Page, name: string, testInfo: { outputPath: (name: string) => string }) {
  await page.screenshot({ path: testInfo.outputPath(name), animations: "disabled" });
  if (process.env.E2E_SCREENSHOT_DIR) await page.screenshot({ path: `${process.env.E2E_SCREENSHOT_DIR}/${name}`, animations: "disabled" });
}
const summaryOf = (page: Page) => page.getByRole("region", { name: "현재 지도 범위 유가 통계" });
const regionDialog = (page: Page) => page.getByRole("dialog", { name: "지역 이동" });
const zoomOf = (request: Request) => Number(new URL(request.url()).searchParams.get("zoom"));
const isPlaces = (request: Request) => new URL(request.url()).pathname.endsWith("/api/public/fuel/places");
const fuelPayload = (extra: Record<string, unknown> = {}) => ({
  items: [], total: 0, truncated: false, clustered: false, available_sources: [],
  fuel_statistics: [{ ...metrics, product_code: "B027" }], fuel_prices_stale: false, fuel_prices_last_refreshed_at: generated, ...extra,
});

test.beforeEach(async ({ page }) => {
  test.skip(process.env.E2E_PUBLIC_FUEL !== "true", "공개 유가(TRANSPORT_UI_MODE=fuel) 격리 UI 테스트");
  await page.route((url) => /^https?:$/.test(url.protocol) && !["127.0.0.1", "localhost"].includes(url.hostname), (route) => route.abort());
  await page.route("**/api/public/fuel/area-catalog", (route: Route) => route.fulfill({ json: catalog }));
});

test("4a fuel-web은 /favicon.ico로 주유기 아이콘을 내고 페이지가 그것을 아이콘으로 건다", async ({ page, request }, testInfo) => {
  await page.route("**/api/public/fuel/places?*", (route: Route) => route.fulfill({ json: fuelPayload() }));
  const response = await request.get("/favicon.ico");
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toBe("image/x-icon");
  const body = await response.body();
  expect([...body.subarray(0, 6)]).toEqual([0, 0, 1, 0, 3, 0]);
  const notFound: string[] = [];
  page.on("response", item => { if (item.status() === 404) notFound.push(new URL(item.url()).pathname); });
  await page.goto("/");
  await expect(summaryOf(page)).toBeVisible();
  await expect(page.locator('link[rel="icon"]').first()).toHaveAttribute("href", /\/favicon\.ico/);
  // 페이지와 함께 나간 요청 중 /favicon.ico 404가 없다.
  await page.waitForTimeout(500);
  expect(notFound).not.toContain("/favicon.ico");
  // 받은 바이트가 브라우저에서 이미지로 해석되는지 16·32·48·128px로 그려 보고 저장한다
  // (headless Chromium은 image/x-icon 주소로 직접 이동하면 내려받기로 처리해 중단한다).
  const source = `data:image/x-icon;base64,${body.toString("base64")}`;
  await page.setViewportSize({ width: 360, height: 180 });
  await page.goto("about:blank");
  await page.setContent(`<body style="margin:0;padding:24px;display:flex;gap:24px;align-items:center;background:#fff">${
    [16, 32, 48, 128].map(size => `<img src="${source}" width="${size}" height="${size}">`).join("")}</body>`);
  await expect.poll(() => page.evaluate(() => [...document.images].every(image => image.complete && image.naturalWidth >= 16))).toBe(true);
  await shot(page, "ui-4a-favicon-after.png", testInfo);
});

for (const state of ["failed", "pending"] as const) {
  test(`4b·4c places ${state === "failed" ? "실패" : "대기"}로 지역 칩이 없으면 대화상자는 '지역 이동' 제목으로 지도 중심의 시/도·구/군/시를 고른 채 열린다`, async ({ page }, testInfo) => {
    await page.route("**/api/public/fuel/places?*", (route: Route) => state === "failed"
      ? route.fulfill({ status: 503, json: { detail: "unavailable" } })
      : new Promise<void>(() => { /* 응답하지 않는다(대기) */ }));
    await page.setViewportSize({ width: 390, height: 844 });
    // 지도 중심을 서울 종로구 안(126.99, 37.585)으로 둔다. 목록 첫 항목(강원)이 아니라 종로구가 골라져야 한다.
    await page.goto("/?longitude=126.99&latitude=37.585");
    await expect(summaryOf(page)).toBeVisible();
    await expect(summaryOf(page).locator(".fuel-sigungu-chips")).toHaveCount(0);
    await summaryOf(page).getByRole("button", { name: "지역 이동" }).click();
    const dialog = regionDialog(page);
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("heading", { name: "지역 이동" })).toBeVisible();
    await expect(dialog).not.toContainText("이동하세요");
    await expect(dialog.getByRole("radio", { name: "서울" })).toBeChecked();
    await expect(dialog.getByRole("radio", { name: "종로구" })).toBeChecked();
    await expect(dialog.getByRole("radio", { name: "강원" })).not.toBeChecked();
    await expect(dialog.getByRole("button", { name: "서울 종로구 지역으로 이동" })).toBeEnabled();
    await dialog.evaluate(node => Promise.all(node.getAnimations({ subtree: true }).map(animation => animation.finished)));
    await shot(page, `ui-4b-picker-preselect-center-${state}-after.png`, testInfo);
  });
}

test("4b 지역 칩이 있으면 그 칩(서버 지도 중심 시군구)을 고른 채 연다", async ({ page }, testInfo) => {
  await page.route("**/api/public/fuel/places?*", (route: Route) => {
    const url = new URL(route.request().url());
    return route.fulfill({ json: fuelPayload({
      fuel_viewport_sigungu: [{ sido_value: "서울특별시", sido_name: "서울", sigungu_value: "종로구", sigungu_name: "종로구", station_count: 9 }],
      fuel_viewport_sigungu_total: 1,
      ...(url.searchParams.has("center_longitude") ? { fuel_center_sigungu: { sido_value: "경기도", sido_name: "경기", sigungu_value: "고양시 덕양구", sigungu_name: "고양시 덕양구", method: "nearest_station", distance_m: 300 } } : {}),
    }) });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/?longitude=126.99&latitude=37.585");
  await expect(summaryOf(page).locator(".fuel-sigungu-chips .fuel-sigungu-chip:not(.fuel-sigungu-clear)")).toHaveText("경기 고양시 덕양구");
  await summaryOf(page).getByRole("button", { name: "지역 이동" }).click();
  const dialog = regionDialog(page);
  await expect(dialog.getByRole("radio", { name: "경기" })).toBeChecked();
  await expect(dialog.getByRole("radio", { name: "고양시 덕양구" })).toBeChecked();
  await dialog.evaluate(node => Promise.all(node.getAnimations({ subtree: true }).map(animation => animation.finished)));
  await shot(page, "ui-4b-picker-preselect-chip-after.png", testInfo);
});

test("4d 필터 브랜드의 '기타'(로고 없음)는 이름이 한 번만 나온다", async ({ page }, testInfo) => {
  await page.route("**/api/public/fuel/places?*", (route: Route) => route.fulfill({ json: fuelPayload() }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await summaryOf(page).getByRole("button", { name: /^유종·필터/ }).click();
  const menu = page.getByRole("dialog", { name: "유종·필터" });
  const etc = menu.locator(".fuel-filter-brand").filter({ has: page.getByRole("checkbox", { name: "기타", exact: true }) });
  await expect(etc).toHaveCount(1);
  await etc.scrollIntoViewIfNeeded();
  expect((await etc.innerText()).trim()).toBe("기타");
  expect(await etc.evaluate(node => node.textContent)).toBe("기타");
  await expect(menu.getByText("기타", { exact: true })).toHaveCount(1);
  // 아이콘은 꾸밈이다: title 툴팁·숨김 이름이 없다. 다른 브랜드 행도 이름이 한 번이다.
  await expect(etc.locator("[title], .sr-only")).toHaveCount(0);
  for (const row of await menu.locator(".fuel-filter-brand").all()) {
    const name = (await row.locator(".fuel-filter-brand-mark + span").innerText()).split(" · ")[0].trim();
    expect((await row.evaluate(node => node.textContent ?? "")).split(name).length - 1, name).toBe(1);
  }
  await page.waitForTimeout(200);
  await menu.screenshot({ path: testInfo.outputPath("ui-4d-etc-row-after.png") });
  if (process.env.E2E_SCREENSHOT_DIR) await menu.screenshot({ path: `${process.env.E2E_SCREENSHOT_DIR}/ui-4d-etc-row-after.png` });
});

test("4e 지역 이동 직후 새 응답 전에는 이전 zoom의 시/도 카드를 그리지 않는다(가장자리에 몰리지 않음)", async ({ page }, testInfo) => {
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/public/fuel/places?*", async (route: Route) => {
    const zoom = zoomOf(route.request());
    if (zoom < 8) return route.fulfill({ json: fuelPayload({ clustered: true, clusters: [], fuel_regions: sidoCards, total: 60 }) });
    await held;
    return route.fulfill({ json: fuelPayload() });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const markers = page.locator(".fuel-region-marker");
  await expect(markers).toHaveCount(sidoCards.length, { timeout: 20_000 });
  await expect(markers.locator(".fuel-region-label").first()).toBeVisible();
  await shot(page, "ui-4e-region-move-0-sido-cards.png", testInfo);
  await summaryOf(page).getByRole("button", { name: "지역 이동" }).click();
  const dialog = regionDialog(page);
  await dialog.getByRole("radio", { name: "서울" }).check();
  await dialog.getByRole("radio", { name: "종로구" }).check();
  const detailed = page.waitForRequest(request => isPlaces(request) && zoomOf(request) >= 10);
  await dialog.getByRole("button", { name: "서울 종로구 지역으로 이동" }).click();
  await expect(dialog).toHaveCount(0);
  // 새 범위 요청이 나간 뒤(이동 끝) 응답이 오기 전: 옛 시/도 카드가 하나도 없다.
  await detailed;
  await expect(markers).toHaveCount(0);
  // 응답을 기다리는 동안 잠깐이라도 다시 나타나지 않는다.
  const reappeared = await page.evaluate(() => new Promise<boolean>(resolve => {
    let seen = false; const started = performance.now();
    const tick = () => {
      if (document.querySelector(".fuel-region-marker")) seen = true;
      if (performance.now() - started > 800) resolve(seen); else requestAnimationFrame(tick);
    };
    tick();
  }));
  expect(reappeared).toBe(false);
  await shot(page, "ui-4e-region-move-1-pending-after.png", testInfo);
  release();
  await expect(markers).toHaveCount(0);
  await shot(page, "ui-4e-region-move-2-settled-after.png", testInfo);
});
