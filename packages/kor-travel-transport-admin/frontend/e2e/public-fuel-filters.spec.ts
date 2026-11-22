import { expect, test, type Page, type Request, type Route } from "@playwright/test";

// 공개 유가(TRANSPORT_UI_MODE=fuel) 지역 이동·필터 서랍. 필터는 서버가 적용하므로 places 요청 query로 확인하고,
// 응답은 그 query를 흉내 낸 격리 응답이다. 스크린샷은 E2E_SCREENSHOT_DIR이 있으면 그곳에도 저장한다.
const generated = "2026-11-21T22:00:00Z";
const metrics = { station_count: 12, average_price: 1700, minimum_price: 1600, maximum_price: 1800, price_spread: 200,
  standard_deviation: 45, saving_50l: 5000, cheapest_station_count: 1, generated_at: generated, cheapest_station: { name: "최저가", address: "서울" } };
const catalog = { items: [
  { sido_value: "01", sido_name: "서울", sigungu: [{ sigungu_value: "0101", sigungu_name: "종로구", station_count: 20, bounds: [126.95, 37.56, 127.02, 37.6] }] },
  { sido_value: "15", sido_name: "충북", sigungu: [
    { sigungu_value: "1501", sigungu_name: "영동군", station_count: 30, bounds: [127.6, 36.0, 128.0, 36.3] },
    { sigungu_value: "1502", sigungu_name: "옥천군", station_count: 29, bounds: [127.5, 36.2, 127.8, 36.45] },
    { sigungu_value: "1503", sigungu_name: "청주시 상당구", station_count: 40, bounds: [127.45, 36.55, 127.65, 36.7] },
  ] },
] };

async function shot(page: Page, name: string, testInfo: { outputPath: (name: string) => string }) {
  await page.screenshot({ path: testInfo.outputPath(name), animations: "disabled" });
  if (process.env.E2E_SCREENSHOT_DIR) await page.screenshot({ path: `${process.env.E2E_SCREENSHOT_DIR}/${name}`, animations: "disabled" });
}

const placeRequests: URL[] = [];
test.beforeEach(async ({ page }) => {
  test.skip(process.env.E2E_PUBLIC_FUEL !== "true", "공개 유가(TRANSPORT_UI_MODE=fuel) 격리 UI 테스트");
  placeRequests.length = 0;
  await page.route((url) => /^https?:$/.test(url.protocol) && !["127.0.0.1", "localhost"].includes(url.hostname), (route) => route.abort());
  await page.route("**/api/public/fuel/places?*", (route: Route) => {
    const url = new URL(route.request().url());
    placeRequests.push(url);
    // 필터 개수만큼 주유소 수가 줄어든 서버 응답을 흉내 낸다.
    const active = ["self_only", "open_24h", "carwash", "maintenance", "cvs", "kpetro", "brands", "near_min"].filter(key => url.searchParams.has(key)).length;
    return route.fulfill({ json: {
      items: [], total: 0, truncated: false, clustered: false, available_sources: [],
      fuel_statistics: [{ ...metrics, product_code: "B027", station_count: 12 - active }],
      fuel_prices_stale: false, fuel_prices_last_refreshed_at: generated,
      fuel_viewport_sigungu: [{ sido_value: "15", sido_name: "충북", sigungu_value: "1502", sigungu_name: "옥천군", station_count: 12 - active }],
      fuel_viewport_sigungu_total: 1,
    } });
  });
  await page.route("**/api/public/fuel/area-catalog", (route: Route) => route.fulfill({ json: catalog }));
});

const summaryOf = (page: Page) => page.getByRole("region", { name: "현재 지도 범위 유가 통계" });
const lastPlaces = () => placeRequests.at(-1)!;
const waitPlaces = (page: Page, check: (url: URL) => boolean) => page.waitForRequest((request: Request) => {
  const url = new URL(request.url());
  return url.pathname.endsWith("/api/public/fuel/places") && check(url);
});
const noHorizontalScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);

for (const width of [320, 390, 1440]) {
  test(`${width}px 지역 이동: 시/도 → 구/군/시 → 확인하면 지도가 그 시군구로 옮겨진다`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: width < 1000 ? 844 : 900 });
    await page.goto("/");
    await expect(summaryOf(page)).toContainText("옥천군");
    await summaryOf(page).getByRole("button", { name: "지역" }).click();
    const dialog = page.getByRole("dialog", { name: "이동하세요…" });
    await expect(dialog).toBeVisible();
    // 지금 화면의 시군구(옥천군)가 선택된 채 열린다.
    await expect(dialog.getByRole("radio", { name: "충북" })).toBeChecked();
    await expect(dialog.getByRole("radio", { name: "옥천군" })).toBeChecked();
    await expect(dialog.getByRole("button", { name: "충북 옥천군 지역으로 이동" })).toBeVisible();
    for (const option of await dialog.locator(".fuel-region-option").all()) expect((await option.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    const box = (await dialog.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x + box.width).toBeLessThanOrEqual(width);
    await shot(page, `fuel-filters-region-picker-${width}.png`, testInfo);
    await dialog.getByRole("radio", { name: "서울" }).check();
    await expect(dialog.getByRole("button", { name: "구/군/시 선택" })).toBeDisabled();
    await dialog.getByRole("radio", { name: "종로구" }).check();
    const moved = waitPlaces(page, url => {
      const [west, south, east, north] = ["min_longitude", "min_latitude", "max_longitude", "max_latitude"].map(key => Number(url.searchParams.get(key)));
      return west <= 126.985 && east >= 126.985 && south <= 37.58 && north >= 37.58;
    });
    await dialog.getByRole("button", { name: "서울 종로구 지역으로 이동" }).click();
    await expect(dialog).toHaveCount(0);
    const request = new URL((await moved).url());
    expect(Number(request.searchParams.get("zoom"))).toBeGreaterThanOrEqual(10);
    expect(await noHorizontalScroll(page)).toBe(true);
  });

  test(`${width}px 필터 서랍: 각 필터가 서버 query로 적용되고 저장된다`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: width < 1000 ? 844 : 900 });
    await page.goto("/");
    await expect(summaryOf(page)).toContainText("12개 주유소");
    await summaryOf(page).getByRole("button", { name: "필터" }).click();
    const drawer = page.getByRole("dialog", { name: "필터" });
    await expect(drawer).toBeVisible();
    const box = (await drawer.boundingBox())!;
    expect(box.x + box.width).toBeLessThanOrEqual(width + 1);
    expect(box.height).toBeGreaterThanOrEqual((width < 1000 ? 844 : 900) - 2);
    await expect(drawer).not.toContainText(/믿음|직영|스마트|면세유|화물차|LIGHT|DARK|SYSTEM|테마/);
    await shot(page, `fuel-filters-drawer-${width}.png`, testInfo);
    // 유종 하나(휘발유) → 지도 최저가 범위 사용 가능
    await expect(drawer.getByRole("combobox", { name: /지도 최저가/ })).toBeDisabled();
    let next = waitPlaces(page, url => url.searchParams.get("product_codes") === "B027");
    await drawer.getByRole("radio", { name: "휘발유", exact: true }).check();
    await next;
    next = waitPlaces(page, url => url.searchParams.get("near_min") === "70");
    await drawer.getByRole("combobox", { name: /지도 최저가/ }).selectOption("70");
    await next;
    for (const [label, key] of [["'24시' 만", "open_24h"], ["'셀프주유' 만", "self_only"], ["'자동세차' 만", "carwash"], ["'경정비' 만", "maintenance"], ["'편의점' 만", "cvs"], ["'품질인증주유소' 만", "kpetro"]] as const) {
      const control = drawer.getByRole("switch", { name: label });
      expect((await control.locator("xpath=..").boundingBox())!.height).toBeGreaterThanOrEqual(44);
      next = waitPlaces(page, url => url.searchParams.get(key) === "true");
      await control.check();
      await next;
    }
    // 휘발유에서 LPG 충전 전용 상표는 비활성
    await expect(drawer.getByRole("checkbox", { name: /SK가스/ })).toBeDisabled();
    // 휘발유에서는 LPG 전용 상표(SK가스·E1)를 보내지 않는다: 11 − 알뜰 − 2 = 8개.
    next = waitPlaces(page, url => (url.searchParams.get("brands") ?? "").split(",").length === 8 && !url.searchParams.get("brands")!.includes("ALT"));
    await drawer.getByRole("checkbox", { name: /알뜰주유소/ }).uncheck();
    await next;
    await drawer.evaluate(node => { node.scrollTop = node.scrollHeight; });
    await shot(page, `fuel-filters-drawer-applied-${width}.png`, testInfo);
    // 필터 개수 배지·통계 반영, 새로고침 뒤에도 유지
    await page.keyboard.press("Escape");
    await expect(drawer).toHaveCount(0);
    await expect(summaryOf(page).getByRole("button", { name: "필터 8개 적용 중" })).toBeVisible();
    await expect(summaryOf(page)).toContainText("4개 주유소");
    await page.reload();
    await expect.poll(() => lastPlaces()?.searchParams.get("self_only")).toBe("true");
    expect(lastPlaces().searchParams.get("brands")).not.toContain("ALT");
    await summaryOf(page).getByRole("button", { name: "필터 8개 적용 중" }).click();
    next = waitPlaces(page, url => !["self_only", "open_24h", "carwash", "maintenance", "cvs", "kpetro", "brands", "near_min"].some(key => url.searchParams.has(key)));
    await page.getByRole("dialog", { name: "필터" }).getByRole("button", { name: "필터 초기화" }).click();
    await next;
    expect(await noHorizontalScroll(page)).toBe(true);
  });
}

test("필터 서랍은 키보드로 열고 닫으며 초점이 서랍 안에 머문다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const trigger = summaryOf(page).getByRole("button", { name: "필터" });
  await trigger.focus();
  await page.keyboard.press("Enter");
  const drawer = page.getByRole("dialog", { name: "필터" });
  await expect(drawer).toBeVisible();
  for (let i = 0; i < 40; i++) {
    await page.keyboard.press("Tab");
    expect(await drawer.evaluate(node => node.contains(document.activeElement))).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
});
