import { expect, test, type Page, type Route } from "@playwright/test";
import { isolatePublicFuel } from "./public-fuel-isolation";

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
  await isolatePublicFuel(page);
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
    await expect(page.getByRole("link", { name: "지도에서 보기" })).toHaveAttribute("href", "/?longitude=126.978&latitude=37.5665&product=B027");
    await expect(page.locator("time")).toHaveText("2026.11.27 09:31");
    await expect(page.getByRole("group", { name: /전국 휘발유 최근 30일 평균·최저·최고 가격/ })).toBeVisible();
    expect(requests[0].get("from")).toBe("2026-10-29");
    expect(await noHorizontalScroll(page)).toBe(true);
    // 터치 목표: 분절 선택과 지역 선택은 44px 이상.
    for (const box of await page.locator(".public-fuel-segmented label").evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().height))) expect(box).toBeGreaterThanOrEqual(44);
    await page.screenshot({ path: testInfo.outputPath(`public-fuel-statistics-${width}.png`), fullPage: true, animations: "disabled" });

    // 1년·전체: 장기 추이 API(일·auto). 점이 많으면 점선 범례.
    await page.getByRole("radio", { name: "1년" }).check();
    await expect(page.getByRole("heading", { name: "최근 1년 휘발유 평균 가격 변화" })).toBeVisible();
    await expect.poll(() => requests.at(-1)?.get("from")).toBe("2025-11-28");
    await expect(page.getByText("선: 평균 (원/L)")).toBeVisible();
    await page.getByLabel("그래프에 그날의 최저·최고도 함께 보기").check();
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

test("고속도로에 없는 유종(고급유)은 휘발유로 바꾸고 알린다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await routeFuel(page);
  await page.goto("/statistics?scope=highway&product=B034");
  await expect(page.getByText("고속도로 휴게소에는 고급유 가격이 없어 휘발유(으)로 바꿨습니다")).toBeVisible();
  await expect(page.getByRole("heading", { name: "고속도로 전체 · 휘발유 현재 가격" })).toBeVisible();
  await expect(page.getByRole("radio", { name: "휘발유" })).toBeChecked();
  await expect(page.getByLabel("노선 선택")).toHaveValue("all");
  await expect(page).not.toHaveURL(/product=/);
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

test("뒤로 가기로 돌아와도 고른 조건이 남고, 지도에서 왔으면 '유가 지도'가 지도를 그대로 돌려준다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await routeFuel(page);
  await page.route("**/api/public/fuel/places?*", (route) => route.fulfill({ json: {
    items: [], total: 0, truncated: false, clustered: false, available_sources: [], fuel_statistics: [],
    fuel_prices_stale: false, fuel_prices_last_refreshed_at: generated } }));
  await page.goto("/statistics");
  await page.getByRole("radio", { name: "경유" }).check();
  await page.getByRole("radio", { name: "시도" }).check();
  await expect(page.getByRole("heading", { name: "서울 · 경유 현재 가격" })).toBeVisible();
  await expect(page).toHaveURL(/scope=sido/);
  await page.getByRole("link", { name: "유가 지도" }).click();
  await expect(page.getByRole("button", { name: "내 위치 주변 유가 보기" })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("heading", { name: "서울 · 경유 현재 가격" })).toBeVisible();
  await expect(page).toHaveURL(/product=D047/);
  // 지도 → 통계 → "유가 지도"는 새 지도를 쌓지 않고 뒤로 간다.
  await page.goto("/");
  await page.getByRole("link", { name: "지역별 유가 통계" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "지역별 유가 통계" })).toBeVisible();
  const before = await page.evaluate(() => history.length);
  await page.getByRole("link", { name: "유가 지도" }).click();
  await expect(page).toHaveURL(/\/$/);
  expect(await page.evaluate(() => history.length)).toBe(before);
});

test("최저가 주유소 '지도에서 보기'는 그 주유소 둘레를 확대해 연다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await routeFuel(page);
  const zooms: string[] = [];
  await page.route("**/api/public/fuel/places?*", (route) => {
    zooms.push(new URL(route.request().url()).searchParams.get("zoom") ?? "");
    return route.fulfill({ json: { items: [], total: 0, truncated: false, clustered: false, available_sources: [], fuel_statistics: [],
      fuel_prices_stale: false, fuel_prices_last_refreshed_at: generated } });
  });
  await page.goto("/statistics");
  await page.getByRole("link", { name: "지도에서 보기" }).click();
  await expect(page).toHaveURL(/longitude=126.978/);
  await expect.poll(() => zooms.at(-1)).toBe("15");
});

test("통계에서 고른 유종으로 지도를 연다 — 저장한 유종 선택은 그대로 두고, 지도에서 유종을 고르면 그 선택을 따른다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await routeFuel(page);
  const products: string[] = [];
  await page.route("**/api/public/fuel/places?*", (route) => {
    products.push(new URL(route.request().url()).searchParams.get("product_codes") ?? "");
    return route.fulfill({ json: { items: [], total: 0, truncated: false, clustered: false, available_sources: [], fuel_statistics: [],
      fuel_prices_stale: false, fuel_prices_last_refreshed_at: generated } });
  });
  // 이 브라우저에는 휘발유를 저장해 두었다.
  await page.addInitScript(() => { if (!localStorage.getItem("transport.public-fuel.products")) localStorage.setItem("transport.public-fuel.products", JSON.stringify(["B027"])); });
  await page.goto("/statistics?product=K015");
  await expect(page.getByRole("heading", { name: "전국 · LPG 현재 가격" })).toBeVisible();
  await page.getByRole("link", { name: "지도에서 보기" }).click();
  await expect(page).toHaveURL(/longitude=126.978.*product=K015/);
  const combo = page.getByRole("region", { name: "현재 지도 범위 유가 통계" }).getByRole("button", { name: /^유종·필터/ });
  await expect(combo).toHaveAccessibleName("유종·필터: LPG (통계 링크로 연 유종)");
  await expect.poll(() => products.at(-1)).toBe("K015");
  expect(await page.evaluate(() => localStorage.getItem("transport.public-fuel.products"))).toBe(JSON.stringify(["B027"]));
  // 지도의 통계 단추도 그 유종으로 연다.
  await expect(page.getByRole("link", { name: "지역별 유가 통계" })).toHaveAttribute("href", "/statistics?product=K015&from=map");
  // 유종·필터를 열면 링크 유종이라는 것과 저장한 유종(휘발유)을 알린다.
  await combo.click();
  await expect(page.getByRole("dialog", { name: "유종·필터" })).toContainText("통계 화면에서 고른 LPG(으)로 열었습니다. 저장한 유종(휘발유)은 그대로");
  // 지도에서 고르면 저장하고 주소의 유종은 지운다(좌표는 남는다). 새로고침해도 고른 유종이다.
  await page.getByRole("dialog", { name: "유종·필터" }).getByRole("checkbox", { name: "경유", exact: true }).check();
  await page.keyboard.press("Escape");
  await expect(page).not.toHaveURL(/product=/);
  await expect(page).toHaveURL(/longitude=126.978/);
  await page.reload();
  await expect(combo).toHaveAccessibleName(/^유종·필터: .*경유/);
  // 통계에서 지도를 새로 여는 "유가 지도"(지도에서 오지 않은 화면)도 보던 유종으로 연다.
  await page.goto("/statistics?product=D047");
  await page.getByRole("link", { name: "유가 지도" }).click();
  await expect(page).toHaveURL(/\/\?product=D047$/);
  await expect(combo).toHaveAccessibleName("유종·필터: 경유 (통계 링크로 연 유종)");
  // "저장한 유종으로 보기"는 저장 값을 바꾸지 않고 저장한 선택으로 돌아가며 주소의 유종을 지운다.
  await combo.click();
  await page.getByRole("dialog", { name: "유종·필터" }).getByRole("button", { name: "저장한 유종으로 보기" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("dialog", { name: "유종·필터" })).toHaveCount(0);
  await expect(combo).toBeFocused();
  await expect(combo).toHaveAccessibleName(/^유종·필터: .*경유/);
  await expect(combo).not.toHaveAccessibleName(/통계 링크/);
  // 기본 휘발유만 본 통계 화면의 "유가 지도"는 유종을 싣지 않는다(저장한 선택 그대로).
  await page.goto("/statistics");
  await expect(page.getByRole("link", { name: "유가 지도" })).toHaveAttribute("href", "/");
});

test("고속도로에서 고른 노선에 그 유종이 없으면 전체 노선 값을 보이고 알린다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await routeFuel(page);
  await page.goto(`/statistics?scope=highway&region=${encodeURIComponent('["0140"]')}&product=K015`);
  await expect(page.getByRole("heading", { name: "고속도로 전체 · LPG 현재 가격" })).toBeVisible();
  await expect(page.getByText("링크의 지역을 찾지 못해 고속도로 전체 값을 보여 드립니다")).toBeVisible();
  await expect(page.getByRole("radio", { name: "고급유" })).toBeDisabled();
});
