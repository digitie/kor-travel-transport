import { expect, test, type Page, type Route } from "@playwright/test";

// 공개 유가(TRANSPORT_UI_MODE=fuel) 시군구 가격 분포: 범위 요약의 지역 칩(고른 곳 하나, 고르기 전에는 화면 대표 시군구 하나)
// → 대화상자(토글), 주유소 상세 등급·핀.
// 유가 BFF는 page.route가 대신하고 외부 지도 타일은 막는다. 스크린샷은 E2E_SCREENSHOT_DIR이 있으면 그곳에도 저장한다.
const generated = "2026-11-21T22:00:00Z";
const SEOUL = { latitude: 37.5665, longitude: 126.978 };
const metrics = { station_count: 29, average_price: 1883, minimum_price: 1819, maximum_price: 1998, price_spread: 179,
  standard_deviation: 40, saving_50l: 3200, cheapest_station_count: 1, generated_at: generated,
  cheapest_station: { name: "옥천최저주유소", address: "충북 옥천군" } };
const regions = [
  ["15", "충북", "1501", "옥천군", 29], ["15", "충북", "1502", "보은군", 18], ["15", "충북", "1503", "영동군", 22],
  ["16", "충남", "1601", "금산군", 15], ["16", "대전", "1602", "동구", 40], ["16", "대전", "1603", "중구", 33],
  ["11", "서울", "1101", "중구", 25], ["15", "충북", "1504", "청주시 상당구", 31],
].map(([sido_value, sido_name, sigungu_value, sigungu_name, station_count]) => ({ sido_value, sido_name, sigungu_value, sigungu_name, station_count }));
const station = { id: 7, kind: "fuel_station", source: "opinet_browser", name: "옥천시험주유소", brand_code: "SKE", brand_name: "SK에너지",
  latitude: SEOUL.latitude, longitude: SEOUL.longitude, address: "충북 옥천군 옥천읍", phone: null, line_names: [], facilities: [],
  prices: [{ product_code: "B027", price: 1819, observed_at: generated }, { product_code: "D047", price: 1714, observed_at: generated }],
  updated_at: generated };
const quantiles = [1819, 1826, 1838, 1850, 1861, 1872, 1880, 1886, 1893, 1925, 1990].map((price, index) => ({ percent: index * 10, price }));
const histogram = [1, 1, 1, 1, 2, 1, 4, 6, 10, 1, 1].map((count, index) => ({ start: 1800 + index * 20, end: 1820 + index * 20, count }));
const distribution = (product: string, withStation: boolean, smallSample = false) => ({
  product_code: product, generated_at: generated, update_pending: false, minimum_sample: 3,
  sido_value: "15", sigungu_value: "1501", sido_name: "충북", sigungu_name: "옥천군",
  grade_rule: [{ grade: "A+", label: "제일싸요", percentile_below: 10 }],
  sigungu: { scope: "sigungu", label: "충북 옥천군", station_count: smallSample ? 2 : 29, minimum_price: 1819, average_price: 1883,
    maximum_price: 1998, sufficient: !smallSample, bin_width: 20, histogram, quantiles },
  sido: { scope: "sido", label: "충북", station_count: 480, minimum_price: 1700, average_price: 1870, maximum_price: 2300 },
  nationwide: { scope: "nationwide", label: "전국", station_count: 10900, minimum_price: 1765, average_price: 1854, maximum_price: 2549 },
  station: withStation ? { station_id: 7, name: station.name, price: 1819, sells_product: true, products: ["B027", "D047"], comparisons: [
    { scope: "sigungu", label: "충북 옥천군", station_count: 29, minimum_price: 1819, average_price: 1883, maximum_price: 1998, price: 1819, difference: -64, percentile: 1.7, grade: "A+", grade_label: "제일싸요", sufficient: true },
    { scope: "sido", label: "충북", station_count: 480, minimum_price: 1700, average_price: 1870, maximum_price: 2300, price: 1819, difference: -51, percentile: 46, grade: "B", grade_label: "평범해요", sufficient: true },
    { scope: "nationwide", label: "전국", station_count: 10900, minimum_price: 1765, average_price: 1854, maximum_price: 2549, price: 1819, difference: -35, percentile: 31, grade: "B+", grade_label: "조금 싸요", sufficient: true },
  ] } : null,
});

async function shot(page: Page, name: string, testInfo: { outputPath: (name: string) => string }) {
  await page.screenshot({ path: testInfo.outputPath(name), animations: "disabled" });
  if (process.env.E2E_SCREENSHOT_DIR) await page.screenshot({ path: `${process.env.E2E_SCREENSHOT_DIR}/${name}`, animations: "disabled" });
}

test.beforeEach(async ({ page }) => {
  test.skip(process.env.E2E_PUBLIC_FUEL !== "true", "공개 유가(TRANSPORT_UI_MODE=fuel) 격리 UI 테스트");
  await page.route((url) => /^https?:$/.test(url.protocol) && !["127.0.0.1", "localhost"].includes(url.hostname), (route) => route.abort());
  await page.route("**/api/public/fuel/places?*", (route: Route) => {
    const url = new URL(route.request().url());
    expect(url.searchParams.get("include_viewport_sigungu")).toBe("true");
    const zoom = Number(url.searchParams.get("zoom"));
    return route.fulfill({ json: {
      items: zoom >= 10 ? [station] : [], total: zoom >= 10 ? 1 : 0, truncated: false, clustered: false, available_sources: [],
      fuel_statistics: [{ ...metrics, product_code: "B027" }, { ...metrics, product_code: "D047", average_price: 1760, minimum_price: 1714 }],
      fuel_prices_stale: false, fuel_prices_last_refreshed_at: generated,
      fuel_viewport_sigungu: regions, fuel_viewport_sigungu_total: 14,
    } });
  });
  await page.route("**/api/public/fuel/price-distribution?*", (route: Route) => {
    const url = new URL(route.request().url());
    const product = url.searchParams.get("product_code") ?? "B027";
    return route.fulfill({ json: distribution(product, url.searchParams.has("station_id"), url.searchParams.get("sigungu_value") === "1502") });
  });
  await page.route("**/api/public/fuel/stations/*/price-history?*", (route: Route) => route.fulfill({ json: {
    station_id: 7, source: "opinet_browser", window: { from_at: "2026-10-23T00:00:00Z", to_at: generated }, items: [], latest_prices: [], next_cursor: null,
  } }));
});

const summaryOf = (page: Page) => page.getByRole("region", { name: "현재 지도 범위 유가 통계" });
const noHorizontalScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);

for (const width of [320, 390, 1440]) {
  test(`${width}px 지역 칩 하나 → 통계 대화상자 · 분포(%) · 전국 대비`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: width < 1000 ? 844 : 900 });
    await page.goto("/");
    const chips = summaryOf(page).getByRole("group", { name: "지도 대표 지역 가격 통계" });
    await expect(chips).toBeVisible();
    // 화면에 시군구 8곳(전체 14곳)이 있어도 칩은 주유소가 가장 많은 첫 곳 하나뿐이고 더 보기(+N)도 없다.
    await expect(chips.getByRole("button")).toHaveCount(1);
    await expect(chips.getByRole("button", { name: /더 보기/ })).toHaveCount(0);
    for (const other of ["보은군", "영동군", "금산군", "중구", "청주시"]) await expect(chips).not.toContainText(other);
    const chip = chips.getByRole("button", { name: /^충북 옥천군 휘발유 가격 통계 · 지도 안 29개 주유소$/ });
    expect((await chip.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    expect(await noHorizontalScroll(page)).toBe(true);
    await shot(page, `fuel-stats-chips-${width}.png`, testInfo);
    await chip.click();
    const dialog = page.getByRole("dialog", { name: "충북 옥천군 29개 휘발유 값 통계" });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("최저 1,819원, 평균 1,883원, 최고 1,998원");
    await expect(dialog.locator("time")).toContainText("2026년 11월 22일 일요일 오전 7시 기준");
    const chart = dialog.getByRole("img", { name: /옥천군 휘발유 가격 분포 그래프/ });
    await expect(chart).toBeVisible();
    await expect(chart.locator("canvas")).toHaveCount(1);
    const dialogBox = (await dialog.boundingBox())!;
    expect(dialogBox.x).toBeGreaterThanOrEqual(0);
    expect(dialogBox.x + dialogBox.width).toBeLessThanOrEqual(width);
    // 그래프 위를 누르면 툴팁(가격 구간 + 개수 또는 가격 곡선 값)이 뜬다.
    const chartBox = (await chart.boundingBox())!;
    await page.mouse.click(chartBox.x + chartBox.width * .55, chartBox.y + chartBox.height - 34);
    // ECharts 툴팁은 차트 컨테이너 안에 붙는다(범례 문구와 섞이지 않게 차트 안만 본다).
    await expect(dialog.locator(".fuel-distribution-chart div").filter({ hasText: /^(\d{1,3}(,\d{3})*원~ \d+개|낮은 가격부터 \d+% · [\d,]+원)$/ }).first()).toBeVisible();
    await shot(page, `fuel-stats-dialog-${width}.png`, testInfo);
    // 분포(%)
    const percent = dialog.getByRole("checkbox", { name: "분포(%)" });
    await percent.check();
    await expect(dialog.getByRole("list", { name: "그래프 범례" })).toContainText("값 분포(%)");
    await dialog.getByText("가격 구간 표").click();
    await expect(dialog.getByRole("table", { name: "충북 옥천군 휘발유 가격 구간별 주유소" })).toContainText("34.5%");
    // 전국 대비
    const compare = dialog.getByRole("checkbox", { name: "전국 대비" });
    await compare.check();
    const legend = dialog.getByRole("list", { name: "그래프 범례" });
    for (const text of ["전국 최저(1,765원)", "전국 평균(1,854원)", "전국 최고(2,549원)"]) await expect(legend).toContainText(text);
    await expect(dialog).toContainText("전국 최저 1,765원, 평균 1,854원, 최고 2,549원.");
    await dialog.evaluate(node => { node.scrollTop = 0; });
    await shot(page, `fuel-stats-dialog-national-percent-${width}.png`, testInfo);
    // 키보드: Escape로 닫으면 칩으로 초점이 돌아온다.
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(chip).toBeFocused();
    expect(await noHorizontalScroll(page)).toBe(true);
  });
}

test("390px 작은 시군구는 그래프 대신 안내 문구", async ({ page }, testInfo) => {
  // 이 화면에서는 보은군(표본 2곳)이 주유소 수 1순위라 칩으로 보인다. 나중에 등록한 route가 먼저 처리된다.
  await page.route("**/api/public/fuel/places?*", (route: Route) => route.fulfill({ json: {
    items: [], total: 0, truncated: false, clustered: false, available_sources: [],
    fuel_statistics: [{ ...metrics, product_code: "B027" }], fuel_prices_stale: false, fuel_prices_last_refreshed_at: generated,
    fuel_viewport_sigungu: [regions[1], regions[0]], fuel_viewport_sigungu_total: 2,
  } }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await summaryOf(page).getByRole("button", { name: /^충북 보은군 휘발유 가격 통계/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("주유소가 2곳뿐이라 분포 그래프를 그리지 않습니다");
  await expect(dialog.getByRole("img")).toHaveCount(0);
  await shot(page, "fuel-stats-small-sample-390.png", testInfo);
});

// 소유자 지시(2026-11-22): 공개 유가 화면에는 테마 선택 기능이 없다. 앱은 지금처럼 한 가지(밝은) 색 구성을 유지하고,
// OS가 어두운 모드여도 선택기·저장 키 없이 같은 화면을 그린다.
test("공개 유가 화면에는 테마 선택기가 없고 OS 다크 모드에서도 대화상자가 읽힌다", async ({ page }, testInfo) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(summaryOf(page)).toBeVisible();
  const themeControl = /테마|화면 모드|라이트|다크|light|dark|system/i;
  for (const role of ["button", "radio", "switch", "combobox", "menuitemradio", "tab"] as const) {
    await expect(page.getByRole(role, { name: themeControl })).toHaveCount(0);
  }
  expect(await page.evaluate(() => Object.keys(localStorage).filter(key => /theme/i.test(key)))).toEqual([]);
  await summaryOf(page).getByRole("button", { name: /^충북 옥천군 휘발유 가격 통계/ }).click();
  const dialog = page.getByRole("dialog", { name: /옥천군/ });
  await expect(dialog.getByRole("img")).toBeVisible();
  const [text, background] = await dialog.evaluate(node => [getComputedStyle(node.querySelector("h2")!).color, getComputedStyle(node).backgroundColor]);
  expect(text).not.toBe(background);
  await shot(page, "fuel-stats-dialog-os-dark-390.png", testInfo);
});

test.describe("주유소 상세", () => {
  test.use({ permissions: ["geolocation"], geolocation: SEOUL });
  for (const width of [320, 390, 1440]) {
    test(`${width}px 주유소 상세는 시군구·시도·전국 등급과 평균 대비 차이, 핀이 꽂힌 분포를 보인다`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: width < 1000 ? 844 : 900 });
      await page.goto("/");
      await page.getByRole("button", { name: "내 위치 주변 유가 보기" }).click();
      const marker = page.getByRole("button", { name: /옥천시험주유소.*상세 보기/ });
      await expect(marker).toBeVisible({ timeout: 20_000 });
      await marker.click();
      const position = page.getByRole("region", { name: "주변 대비 가격" });
      await expect(position).toBeVisible();
      const grades = position.getByRole("region", { name: "휘발유 가격 비교" });
      await expect(grades).toContainText("1,819");
      await expect(grades).toContainText("제일싸요");
      await expect(grades).toContainText("평범해요");
      await expect(grades).toContainText("조금 싸요");
      await expect(grades).toContainText("평균 −64원");
      await expect(grades).toContainText("옥천군 29곳 중 A+ 제일싸요");
      await position.scrollIntoViewIfNeeded();
      await shot(page, `fuel-stats-station-grades-${width}.png`, testInfo);
      await position.getByRole("button", { name: "옥천군 가격 분포" }).click();
      const dialog = page.getByRole("dialog", { name: /옥천군 29개 휘발유 값 통계/ });
      await expect(dialog.getByRole("img", { name: /가격 분포 그래프/ })).toBeVisible();
      await expect(dialog.getByRole("list", { name: "그래프 범례" })).toContainText("이 주유소 1,819원");
      await expect(dialog.getByRole("combobox", { name: "유종" }).locator("option")).toHaveText(["휘발유", "경유"]);
      await dialog.getByRole("checkbox", { name: "전국 대비" }).check();
      expect(await noHorizontalScroll(page)).toBe(true);
      await shot(page, `fuel-stats-station-dialog-${width}.png`, testInfo);
    });
  }
});
