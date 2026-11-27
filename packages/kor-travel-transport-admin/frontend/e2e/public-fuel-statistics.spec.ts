import { expect, test, type Page, type Route } from "@playwright/test";

// 공개 유가 지역별 통계(/statistics, TRANSPORT_UI_MODE=fuel 서버)를 격리 응답으로 검사한다. 유가 BFF는 page.route가 대신한다.
const generated = "2026-11-27T00:31:44Z";
const item = (scope_key: string, label: string, product_code = "B027") => ({ scope_key, label, product_code, generated_at: generated,
  station_count: 10200, average_price: 1853.72, minimum_price: 1736, maximum_price: 2549, price_spread: 813, standard_deviation: 40, saving_50l: 5000,
  cheapest_station_count: 1, cheapest_station: { name: "최저가 시험주유소(아주 긴 이름의 고속도로 휴게소 주유소)", address: "서울특별시 중구 세종대로 110 시험빌딩 1층", longitude: 126.978, latitude: 37.5665 } });
const statistics = (items: unknown[]) => ({ generated_at: generated, update_pending: false, items, history: [] });
const SIGUNGU = [item('["서울특별시","강남구"]', "서울 강남구"), item('["서울특별시","중구"]', "서울 중구"), item('["부산광역시","해운대구"]', "부산 해운대구")];

function trend(search: URLSearchParams) {
  const bucket = search.get("bucket") === "auto" ? "week" : "day";
  const from = search.get("from") ?? "2025-06-02";
  const step = bucket === "week" ? 7 : 1;
  const count = Math.min(400, Math.floor((Date.parse("2026-11-27") - Date.parse(from)) / 86_400_000 / step) + 1);
  return { label: "전국", bucket, from_day: from, to_day: "2026-11-27", generated_at: generated, update_pending: false,
    points: Array.from({ length: count }, (_, index) => {
      const day = new Date(Date.parse(from) + index * step * 86_400_000).toISOString().slice(0, 10);
      return { product_code: search.get("product_code"), day, first_day: day, last_day: day, day_count: step, generated_at: generated,
        average_price: 1800 + Math.round(30 * Math.sin(index / 9)), minimum_price: 1700, maximum_price: 1950, station_count: 10000 };
    }) };
}

async function routeFuel(page: Page, history: (route: Route, search: URLSearchParams) => Promise<void> = (route, search) => route.fulfill({ json: trend(search) })) {
  const requests: URLSearchParams[] = [];
  await page.route((url) => /^https?:$/.test(url.protocol) && !["127.0.0.1", "localhost"].includes(url.hostname), (route) => route.abort());
  await page.route("**/api/public/fuel/statistics?*", (route) => {
    const search = new URL(route.request().url()).searchParams;
    const scope = search.get("scope");
    const product = search.get("product_code") ?? "B027";
    const items = scope === "sigungu" ? SIGUNGU : scope === "sido" ? [item('["서울특별시"]', "서울"), item('["경기도"]', "경기")]
      : scope === "highway" ? [item('["0010"]', "경부선")] : scope === "highways" ? (product === "B034" ? [] : [item("all", "고속도로 전체")]) : [item("all", "전국")];
    return route.fulfill({ json: statistics(items.map(row => ({ ...row, product_code: product }))) });
  });
  await page.route("**/api/public/fuel/statistics/history?*", (route) => {
    const search = new URL(route.request().url()).searchParams; requests.push(search);
    return history(route, search);
  });
  return requests;
}

const noHorizontalScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);

test.beforeEach(async () => {
  test.skip(process.env.E2E_PUBLIC_FUEL !== "true", "공개 유가(TRANSPORT_UI_MODE=fuel) 격리 UI 테스트");
});

for (const width of [390, 1440]) {
  test(`${width}px 현재 가격·최저가 주유소·기간별 추이를 넘침 없이 보인다`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: width < 1000 ? 844 : 900 });
    const requests = await routeFuel(page);
    await page.goto("/statistics");
    await expect(page.getByRole("heading", { level: 1, name: "지역별 유가 통계" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "전국 · 휘발유 현재 가격" })).toBeVisible();
    await expect(page.getByLabel("현재 유가")).toContainText("1,853.72");
    await expect(page.getByRole("link", { name: "지도에서 보기" })).toHaveAttribute("href", "/?longitude=126.978&latitude=37.5665");
    await expect(page.locator("time")).toHaveText("2026.11.27 09:31 KST");
    await expect(page.getByRole("group", { name: /전국 휘발유 최근 30일 평균·최저·최고 가격/ })).toBeVisible();
    expect(requests[0].get("from")).toBe("2026-10-29");
    expect(await noHorizontalScroll(page)).toBe(true);
    // 터치 목표: 분절 선택과 지역 선택은 44px 이상.
    for (const box of await page.locator(".public-fuel-segmented label").evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().height))) expect(box).toBeGreaterThanOrEqual(44);
    await page.screenshot({ path: testInfo.outputPath(`public-fuel-statistics-${width}.png`), fullPage: true, animations: "disabled" });

    // 1년·전체: 장기 추이 API(일·auto). 점이 많으면 점선 범례.
    await page.getByRole("radio", { name: "1년" }).check();
    await expect(page.getByRole("heading", { name: "최근 1년 휘발유 평균 가격 추이" })).toBeVisible();
    await expect.poll(() => requests.at(-1)?.get("from")).toBe("2025-11-28");
    await expect(page.getByText("실선: 평균 · 같은 색 점선")).toBeVisible();
    await page.getByRole("radio", { name: "전체" }).check();
    await expect.poll(() => requests.at(-1)?.get("bucket")).toBe("auto");
    await expect(page.getByText(/주 단위\(월요일 시작\)/)).toBeVisible();
    await expect(page).toHaveURL(/period=all/);
    await page.locator(".public-fuel-stats-table summary").click();
    await expect(page.getByRole("table", { name: "기간별 평균·최저·최고 가격" })).toBeVisible();
    expect(await noHorizontalScroll(page)).toBe(true);
  });

  test(`${width}px 시군구는 시도·시군구 두 단계로 고르고 URL로 다시 연다`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: width < 1000 ? 844 : 900 });
    const requests = await routeFuel(page);
    await page.goto("/statistics");
    await page.getByRole("radio", { name: "시군구" }).check();
    await expect(page.getByLabel("시도 선택")).toHaveValue("서울특별시");
    await expect(page.getByRole("heading", { name: "서울 강남구 · 휘발유 현재 가격" })).toBeVisible();
    await page.getByLabel("시도 선택").selectOption("부산광역시");
    await expect(page.getByLabel("시군구 선택")).toHaveValue('["부산광역시","해운대구"]');
    await expect(page.getByRole("heading", { name: "부산 해운대구 · 휘발유 현재 가격" })).toBeVisible();
    await page.getByRole("radio", { name: "경유" }).check();
    await expect(page.getByRole("heading", { name: "부산 해운대구 · 경유 현재 가격" })).toBeVisible();
    await expect.poll(() => requests.at(-1)?.get("scope_key")).toBe('["부산광역시","해운대구"]');
    expect(await noHorizontalScroll(page)).toBe(true);
    const selects = await page.locator(".public-fuel-stats-region select").evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().width));
    for (const selectWidth of selects) expect(selectWidth).toBeGreaterThan(120);
    await page.screenshot({ path: testInfo.outputPath(`public-fuel-statistics-sigungu-${width}.png`), fullPage: true, animations: "disabled" });
    await page.reload();
    await expect(page.getByRole("heading", { name: "부산 해운대구 · 경유 현재 가격" })).toBeVisible();
  });
}

for (const width of [390, 1440]) {
  test(`${width}px 혼잡(429 Retry-After)은 남은 초 동안 다시 조회를 막고 지나면 다시 읽는다`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: width < 1000 ? 844 : 900 });
    let busy = true;
    await routeFuel(page, (route, search) => busy
      ? route.fulfill({ status: 429, headers: { "retry-after": "8", "content-type": "application/problem+json" }, json: { detail: "유가 추이 조회가 혼잡합니다. 잠시 후 다시 시도하세요." } })
      : route.fulfill({ json: trend(search) }));
    await page.goto("/statistics");
    const alert = page.locator(".public-fuel-stats-alert");
    await expect(alert).toContainText("유가 추이 조회가 혼잡합니다");
    const retry = alert.getByRole("button", { name: /추이 다시 조회/ });
    await expect(retry).toBeDisabled();
    await expect(retry).toContainText("초 후");
    // 현재 가격은 추이 실패와 따로 보인다.
    await expect(page.getByLabel("현재 유가")).toContainText("1,853.72");
    expect(await noHorizontalScroll(page)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`public-fuel-statistics-busy-${width}.png`), animations: "disabled" });
    busy = false;
    await expect(retry).toBeEnabled({ timeout: 12_000 });
    await retry.click();
    await expect(page.getByRole("group", { name: /최근 30일 평균·최저·최고 가격/ })).toBeVisible();
  });
}

test("고속도로에 없는 유종은 빈 상태로 안내한다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await routeFuel(page);
  await page.goto("/statistics?scope=highway&product=B034");
  await expect(page.getByText("이 범위에는 고급유 통계가 없습니다")).toBeVisible();
  await expect(page.getByLabel("노선 선택")).toHaveValue("all");
});

test("공개 지도에서 지역별 통계로 가고 다시 지도로 돌아온다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await routeFuel(page);
  await page.route("**/api/public/fuel/places?*", (route) => route.fulfill({ json: {
    items: [], total: 0, truncated: false, clustered: false, available_sources: [], fuel_statistics: [],
    fuel_prices_stale: false, fuel_prices_last_refreshed_at: generated } }));
  await page.goto("/");
  const link = page.getByRole("link", { name: "지역별 유가 통계" });
  await expect(link).toBeVisible();
  const box = (await link.boundingBox())!;
  expect(box.width).toBeGreaterThanOrEqual(44); expect(box.height).toBeGreaterThanOrEqual(44);
  await link.click();
  await expect(page).toHaveURL(/\/statistics$/);
  await expect(page.getByRole("heading", { level: 1, name: "지역별 유가 통계" })).toBeVisible();
  await page.getByRole("link", { name: "유가 지도" }).click();
  await expect(page.getByRole("button", { name: "내 위치 주변 유가 보기" })).toBeVisible();
});
