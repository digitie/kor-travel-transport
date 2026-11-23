import { expect, test, type Page, type Request, type Route } from "@playwright/test";

// 공개 유가(TRANSPORT_UI_MODE=fuel) 소유자 요청 2026-11-23 묶음(격리 응답):
// 1) "오래됨"·"업데이트"를 유종·필터 옆 아이콘 하나로(오래됨=빨간 ClockAlert·누르면 업데이트, 최신·불가=포커스 가능한 비활성+툴팁 이유·시각)
// 2) 장소 정보 영역을 낮게, 사용자가 고른 지역 칩은 파랑, 통계 대화상자·지역 이동 대화상자의 "해제"
// 3) PC에서는 주유소 상세를 지도 오른쪽 위에, 여러 유종이면 유종마다 시군구 등급 안내(한 번의 요청 product_grades)
// 업데이트 버튼을 누를 수 있는 경우는 서버가 갱신 경로를 설정했을 때만이다(E2E_FUEL_REFRESH=true: 하네스가 FUEL_REFRESH_* 를 준다).
// 스크린샷은 E2E_SCREENSHOT_DIR이 있으면 그곳에도 저장한다(ui2- 접두어).
const generated = "2026-11-21T22:00:00Z";
const CENTER = { longitude: 126.978, latitude: 37.5665 };
const metrics = { station_count: 29, average_price: 1883, minimum_price: 1819, maximum_price: 1998, price_spread: 179,
  standard_deviation: 40, saving_50l: 3200, cheapest_station_count: 1, generated_at: generated, cheapest_station: { name: "최저", address: "서울" } };
const catalog = { items: [
  { sido_value: "강원", sido_name: "강원", sigungu: [{ sigungu_value: "강릉시", sigungu_name: "강릉시", station_count: 87, bounds: [128.8, 37.61, 129.04, 37.9] }] },
  { sido_value: "서울", sido_name: "서울", sigungu: [
    { sigungu_value: "종로구", sigungu_name: "종로구", station_count: 20, bounds: [126.95, 37.57, 127.02, 37.6] },
    { sigungu_value: "중구", sigungu_name: "중구", station_count: 12, bounds: [126.96, 37.54, 127.02, 37.57] },
  ] },
] };
const CENTER_CHIP = { sido_value: "서울", sido_name: "서울", sigungu_value: "중구", sigungu_name: "중구", method: "nearest_station", distance_m: 200 };
const station = { id: 7, kind: "fuel_station", source: "opinet_browser", name: "중구시험주유소", brand_code: "SKE", brand_name: "SK에너지",
  latitude: CENTER.latitude, longitude: CENTER.longitude, address: "서울 중구", phone: null, line_names: [], facilities: [],
  prices: [{ product_code: "B027", price: 1819, observed_at: generated }, { product_code: "D047", price: 1760, observed_at: generated }],
  updated_at: generated };
const comparison = (scope: string, label: string, grade: string | null, gradeLabel: string | null, difference: number, price = 1819) => ({
  scope, label, station_count: scope === "sigungu" ? 29 : 500, minimum_price: 1700, average_price: price - difference, maximum_price: 2000,
  price, difference, percentile: 40, grade, grade_label: gradeLabel, sufficient: grade !== null });
const distribution = (product: string) => ({
  product_code: product, generated_at: generated, update_pending: false, minimum_sample: 3,
  sido_value: "서울", sigungu_value: "중구", sido_name: "서울", sigungu_name: "중구",
  grade_rule: [{ grade: "A+", label: "제일싸요", percentile_below: 10 }], filters_applied: [],
  sigungu: { scope: "sigungu", label: "서울 중구", station_count: 29, minimum_price: 1700, average_price: 1883, maximum_price: 2000,
    sufficient: true, bin_width: 50, histogram: [{ start: 1700, end: 1750, count: 3 }, { start: 1750, end: 1800, count: 10 }, { start: 1800, end: 2000, count: 16 }],
    quantiles: [0, 50, 100].map(percent => ({ percent, price: 1700 + percent * 3 })) },
  sido: { scope: "sido", label: "서울", station_count: 500, minimum_price: 1650, average_price: 1870, maximum_price: 2300 },
  nationwide: { scope: "nationwide", label: "전국", station_count: 10900, minimum_price: 1600, average_price: 1854, maximum_price: 2549 },
  station: { station_id: 7, name: station.name, price: product === "D047" ? 1760 : 1819, sells_product: true, products: ["B027", "D047"],
    comparisons: [comparison("sigungu", "서울 중구", "A", "저렴해요", -64), comparison("sido", "서울", "B", "평범해요", -51), comparison("nationwide", "전국", "B+", "조금 싸요", -35)],
    product_grades: [
      { ...comparison("sigungu", "서울 중구", "A", "저렴해요", -64), product_code: "B027" },
      { ...comparison("sigungu", "서울 중구", "C+", "조금 비싸요", 40, 1760), product_code: "D047" },
    ].sort((left, right) => Number(left.product_code !== product) - Number(right.product_code !== product)) },
});

async function shot(page: Page, name: string, testInfo: { outputPath: (name: string) => string }) {
  await page.screenshot({ path: testInfo.outputPath(name), animations: "disabled" });
  if (process.env.E2E_SCREENSHOT_DIR) await page.screenshot({ path: `${process.env.E2E_SCREENSHOT_DIR}/${name}`, animations: "disabled" });
}
const summaryOf = (page: Page) => page.getByRole("region", { name: "현재 지도 범위 유가 통계" });
const priceButton = (page: Page) => summaryOf(page).locator(".public-fuel-price-button");
const chip = (page: Page) => summaryOf(page).locator(".fuel-sigungu-chips .fuel-sigungu-chip:not(.fuel-sigungu-clear)");
const noHorizontalScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);
const isDistribution = (request: Request) => new URL(request.url()).pathname.endsWith("/api/public/fuel/price-distribution");

type Options = { stale?: boolean; stations?: boolean };
async function mockFuel(page: Page, { stale = false, stations = false }: Options = {}) {
  const refreshes: unknown[] = [];
  await page.route("**/api/public/fuel/places?*", (route: Route) => {
    const url = new URL(route.request().url());
    const detailed = Number(url.searchParams.get("zoom")) >= 10;
    return route.fulfill({ json: {
      items: stations && detailed ? [station] : [], total: stations && detailed ? 1 : 0, truncated: false, clustered: false, available_sources: [],
      fuel_statistics: [{ ...metrics, product_code: "B027" }, { ...metrics, product_code: "D047", average_price: 1760, minimum_price: 1700 }],
      fuel_prices_stale: stale, fuel_prices_last_refreshed_at: generated,
      fuel_viewport_sigungu: [{ sido_value: "서울", sido_name: "서울", sigungu_value: "중구", sigungu_name: "중구", station_count: 1 }],
      fuel_viewport_sigungu_total: 1,
      ...(url.searchParams.has("center_longitude") ? { fuel_center_sigungu: CENTER_CHIP } : {}),
    } });
  });
  await page.route("**/api/public/fuel/area-catalog", (route: Route) => route.fulfill({ json: catalog }));
  await page.route("**/api/public/fuel/price-distribution?*", (route: Route) =>
    route.fulfill({ json: distribution(new URL(route.request().url()).searchParams.get("product_code") ?? "B027") }));
  await page.route("**/api/public/fuel/stations/*/price-history?*", (route: Route) => route.fulfill({ json: {
    station_id: 7, source: "opinet_browser", window: { from_at: "2026-10-23T00:00:00Z", to_at: generated }, items: [], latest_prices: [], next_cursor: null,
  } }));
  await page.route("**/api/public/fuel/refresh", (route: Route) => {
    refreshes.push(route.request().postDataJSON());
    return route.fulfill({ json: { results: [{ station_id: 7, status: "updated" }] } });
  });
  return refreshes;
}

test.beforeEach(async ({ page }) => {
  test.skip(process.env.E2E_PUBLIC_FUEL !== "true", "공개 유가(TRANSPORT_UI_MODE=fuel) 격리 UI 테스트");
  await page.route((url) => /^https?:$/.test(url.protocol) && !["127.0.0.1", "localhost"].includes(url.hostname), (route) => route.abort());
});

const at = (width: number) => ({ width, height: width < 1000 ? 844 : 900 });
const STATION_VIEW = `/?longitude=${CENTER.longitude}&latitude=${CENTER.latitude}`;

for (const width of [320, 390, 1440]) {
  test(`${width}px 가격 아이콘 하나: 오래됨은 빨간 시계로 유종·필터 옆에서 눌러 업데이트한다`, async ({ page }, testInfo) => {
    const refreshes = await mockFuel(page, { stale: true, stations: true });
    await page.setViewportSize(at(width));
    await page.goto(STATION_VIEW);
    const summary = summaryOf(page);
    await expect(summary).toContainText("1,883");
    // 따로 있던 "오래됨" 글자·"업데이트" 버튼·지도 위 업데이트 버튼은 없다.
    await expect(summary.getByText("오래됨", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "업데이트", exact: true })).toHaveCount(0);
    await expect(page.locator(".public-fuel-map-refresh")).toHaveCount(0);
    const button = priceButton(page);
    await expect(button).toHaveCount(1);
    await expect(button).toHaveAttribute("data-stale", "true");
    const color = await button.evaluate(node => getComputedStyle(node).color);
    const [red, green] = color.match(/[\d.]+/g)!.map(Number);
    expect(red, `빨간 아이콘 ${color}`).toBeGreaterThan(green + 60);
    // 유종·필터와 같은 줄 오른쪽에 붙어 있다.
    const [buttonBox, filterBox, summaryBox] = [(await button.boundingBox())!, (await summary.locator(".public-fuel-filter-trigger").boundingBox())!, (await summary.boundingBox())!];
    expect(Math.abs((buttonBox.y + buttonBox.height / 2) - (filterBox.y + filterBox.height / 2))).toBeLessThanOrEqual(2);
    expect(buttonBox.x).toBeGreaterThanOrEqual(filterBox.x + filterBox.width);
    expect(buttonBox.x - (filterBox.x + filterBox.width)).toBeLessThanOrEqual(12);
    expect(buttonBox.x + buttonBox.width).toBeLessThanOrEqual(summaryBox.x + summaryBox.width);
    expect(buttonBox.width).toBeGreaterThanOrEqual(44); expect(buttonBox.height).toBeGreaterThanOrEqual(44);
    expect(await noHorizontalScroll(page)).toBe(true);
    if (process.env.E2E_FUEL_REFRESH === "true") {
      await expect(button).toHaveAccessibleName("가격 오래됨 · 지도 범위 유가 업데이트");
      await button.hover();
      await expect(page.getByRole("tooltip")).toContainText("마지막 가격 갱신 26.11.22 07:00 KST");
      await shot(page, `ui2-price-stale-${width}.png`, testInfo);
      await button.click();
      await expect.poll(() => refreshes.length).toBe(1);
      expect(refreshes[0]).toMatchObject({ viewport: { product_codes: [] } });
    } else {
      await expect(button).toHaveAttribute("aria-disabled", "true");
      await shot(page, `ui2-price-stale-${width}.png`, testInfo);
    }
  });

  test(`${width}px 가격이 최신이면 회색 시계의 비활성 단추: 포커스·툴팁으로 이유와 갱신 시각을 알린다`, async ({ page }, testInfo) => {
    const refreshes = await mockFuel(page, { stale: false, stations: true });
    await page.setViewportSize(at(width));
    await page.goto(STATION_VIEW);
    const button = priceButton(page);
    await expect(button).toHaveAttribute("aria-disabled", "true");
    await expect(button).not.toHaveAttribute("data-stale");
    await expect(button).toHaveAccessibleName("가격 최신 · 업데이트할 수 없음: 가격이 최신이라 업데이트할 필요가 없습니다");
    const color = await button.evaluate(node => getComputedStyle(node).color);
    const [red, green, blue] = color.match(/[\d.]+/g)!.map(Number);
    expect(Math.max(red, green, blue) - Math.min(red, green, blue), `회색 ${color}`).toBeLessThanOrEqual(40);
    // 키보드로 닿는다(native disabled가 아님). 포커스하면 툴팁에 이유와 마지막 가격 갱신 시각.
    await button.focus();
    await expect(button).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("tooltip")).toContainText("가격이 최신이라 업데이트할 필요가 없습니다");
    await expect(page.getByRole("tooltip")).toContainText("마지막 가격 갱신 26.11.22 07:00 KST");
    expect(refreshes).toHaveLength(0);
    await shot(page, `ui2-price-fresh-tip-${width}.png`, testInfo);
    // 마우스로 눌러도 업데이트하지 않는다.
    await button.click();
    expect(refreshes).toHaveLength(0);
  });

  test(`${width}px 장소 정보 영역은 낮고, 고른 지역 칩은 파랑이며 통계·지역 이동 대화상자의 '해제'로 자동 지역으로 돌아간다`, async ({ page }, testInfo) => {
    await mockFuel(page);
    await page.setViewportSize(at(width));
    await page.goto(STATION_VIEW);
    const summary = summaryOf(page);
    await expect(chip(page)).toHaveText("서울 중구");
    await expect(summary.locator(".fuel-sigungu-chips")).toHaveAttribute("aria-label", "지도 중심 지역 가격 통계");
    // 유종마다 한 줄(이름·평균·최저). 320px에서도 두 줄을 넘지 않는다.
    for (const row of await summary.locator(".public-fuel-summary-product").all()) {
      expect((await row.boundingBox())!.height).toBeLessThanOrEqual(width <= 320 ? 46 : 24);
    }
    const summaryHeight = (await summary.boundingBox())!.height;
    expect(summaryHeight, `요약 높이 ${summaryHeight}`).toBeLessThanOrEqual(width <= 320 ? 230 : 190);
    const autoBackground = await chip(page).evaluate(node => getComputedStyle(node).backgroundColor);
    await shot(page, `ui2-summary-auto-chip-${width}.png`, testInfo);
    // 지역 이동: 고른 지역이 없으면 해제가 없다.
    const opener = summary.getByRole("button", { name: "지역 이동" });
    await opener.click();
    const picker = page.getByRole("dialog", { name: "지역 이동" });
    await expect(picker.getByRole("button", { name: /해제/ })).toHaveCount(0);
    await picker.getByRole("radio", { name: "종로구" }).check();
    await picker.getByRole("button", { name: "서울 종로구 지역으로 이동" }).click();
    await expect(picker).toHaveCount(0);
    // 고른 지역 칩은 파랑(채움·테두리)으로 자동 칩과 다르다.
    await expect(chip(page)).toHaveText("서울 종로구");
    await expect(chip(page)).toHaveAttribute("data-basis", "selected");
    const [selectedBackground, selectedColor, selectedBorder] = await chip(page).evaluate(node => {
      const style = getComputedStyle(node);
      return [style.backgroundColor, style.color, style.borderTopColor];
    });
    expect(selectedBackground).not.toBe(autoBackground);
    const [red, green, blue] = selectedColor.match(/[\d.]+/g)!.map(Number);
    expect(blue, `파란 글자 ${selectedColor}`).toBeGreaterThan(red + 40);
    expect(selectedBorder).toBe(selectedColor);
    await shot(page, `ui2-summary-selected-chip-${width}.png`, testInfo);
    // 통계 대화상자의 해제: 선택을 풀고 닫힌다(자동 지도 중심 칩으로).
    await chip(page).click();
    const stats = page.getByRole("dialog", { name: /서울 종로구/ });
    const release = stats.getByRole("button", { name: /해제/ });
    await expect(release).toHaveText("해제");
    await shot(page, `ui2-stats-dialog-release-${width}.png`, testInfo);
    await release.click();
    await expect(stats).toHaveCount(0);
    await expect(chip(page)).toHaveText("서울 중구");
    await expect(summary.locator(".fuel-sigungu-chips")).toHaveAttribute("aria-label", "지도 중심 지역 가격 통계");
    // 지역 이동 대화상자의 해제: 고른 지역이 있을 때만 확인 버튼 바로 옆.
    await opener.click();
    await picker.getByRole("radio", { name: "종로구" }).check();
    await picker.getByRole("button", { name: "서울 종로구 지역으로 이동" }).click();
    await expect(chip(page)).toHaveText("서울 종로구");
    await opener.click();
    const pickerRelease = picker.getByRole("button", { name: /해제/ });
    await expect(pickerRelease).toBeVisible();
    const confirm = picker.getByRole("button", { name: "서울 종로구 지역으로 이동" });
    const [releaseBox, confirmBox] = [(await pickerRelease.boundingBox())!, (await confirm.boundingBox())!];
    expect(await picker.locator(".fuel-region-actions > button").evaluateAll(nodes => nodes.map(node => node.textContent))).toEqual(["취소", "해제", "서울 종로구"]);
    if (Math.abs(releaseBox.y - confirmBox.y) <= 2) expect(confirmBox.x - (releaseBox.x + releaseBox.width)).toBeLessThanOrEqual(12);
    await picker.evaluate(node => Promise.all(node.getAnimations({ subtree: true }).map(animation => animation.finished)));
    await shot(page, `ui2-picker-release-${width}.png`, testInfo);
    await pickerRelease.click();
    await expect(picker).toHaveCount(0);
    await expect(chip(page)).toHaveText("서울 중구");
    await expect(chip(page)).toHaveAttribute("data-basis", "center");
    expect(await noHorizontalScroll(page)).toBe(true);
  });

  test(`${width}px 주유소 상세: ${width >= 1024 ? "PC는 지도 오른쪽 위" : "모바일은 요약 아래"}, 유종마다 가격과 시군구 등급 안내(요청 한 번)`, async ({ page }, testInfo) => {
    await mockFuel(page, { stations: true });
    await page.setViewportSize(at(width));
    const distributionRequests: string[] = [];
    page.on("request", request => { if (isDistribution(request)) distributionRequests.push(request.url()); });
    await page.goto(STATION_VIEW);
    const marker = page.getByRole("button", { name: /중구시험주유소.*상세 보기/ });
    await expect(marker).toBeVisible({ timeout: 20_000 });
    await marker.click();
    const detail = page.getByRole("complementary", { name: "선택 장소 상세" });
    await expect(detail).toBeVisible();
    const prices = detail.locator(".public-fuel-current-prices");
    await expect(prices.locator("> div")).toHaveCount(2);
    await expect(prices.locator("> div").nth(0)).toContainText("휘발유");
    await expect(prices.locator("> div").nth(0).locator(".fuel-product-grade")).toContainText("A 저렴해요");
    await expect(prices.locator("> div").nth(1)).toContainText("경유");
    await expect(prices.locator("> div").nth(1).locator(".fuel-product-grade")).toContainText("C+ 조금 비싸요");
    // 지금 유종(휘발유)은 시군구·시도·전국 상세 등급을 그대로 보인다.
    const grades = detail.getByRole("region", { name: "휘발유 가격 비교" });
    await expect(grades.locator(".fuel-grade[data-scope]")).toHaveCount(3);
    // 유종별 등급 때문에 요청을 늘리지 않는다: 가격 분포는 주유소당 한 번.
    expect(distributionRequests.filter(url => url.includes("station_id=7"))).toHaveLength(1);
    const [detailBox, summaryBox] = [(await detail.boundingBox())!, (await summaryOf(page).boundingBox())!];
    if (width >= 1024) {
      // 오른쪽 위: 맨 위에서 시작하고(요약 아래가 아니다) 화면 오른쪽에 붙는다(확대 단추 자리만 비운다).
      expect(detailBox.y).toBeLessThanOrEqual(summaryBox.y + 2);
      expect(detailBox.x + detailBox.width).toBeGreaterThanOrEqual(width - 80);
      expect(detailBox.x).toBeGreaterThan(summaryBox.x + summaryBox.width);
      expect(detailBox.y + detailBox.height).toBeLessThanOrEqual(900);
    } else {
      // 모바일은 지금처럼 요약 아래.
      expect(detailBox.y).toBeGreaterThanOrEqual(summaryBox.y + summaryBox.height - 1);
    }
    expect(await noHorizontalScroll(page)).toBe(true);
    await shot(page, `ui2-station-detail-${width}.png`, testInfo);
  });
}

test("390px 필터를 켠 동안 오래된 가격 아이콘은 비활성이고 이유를 알린다", async ({ page }, testInfo) => {
  await page.addInitScript(() => localStorage.setItem("transport.public-fuel.filters", JSON.stringify({ self_only: true })));
  const refreshes = await mockFuel(page, { stale: true, stations: true });
  await page.setViewportSize(at(390));
  await page.goto(STATION_VIEW);
  const button = priceButton(page);
  await expect(button).toHaveAttribute("data-stale", "true");
  await expect(button).toHaveAttribute("aria-disabled", "true");
  const expected = process.env.E2E_FUEL_REFRESH === "true" ? "필터를 켠 동안은 지도 범위 업데이트를 할 수 없습니다" : "이 화면에서는 유가 업데이트를 쓸 수 없습니다";
  await expect(button).toHaveAccessibleName(new RegExp(`가격 오래됨 · 업데이트할 수 없음: ${expected}`));
  await button.click();
  await expect(page.getByRole("tooltip")).toContainText(expected);
  await expect(page.getByRole("tooltip")).toContainText("마지막 가격 갱신");
  expect(refreshes).toHaveLength(0);
  await shot(page, "ui2-price-stale-filters-390.png", testInfo);
});
