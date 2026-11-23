import { expect, test, type Page } from "@playwright/test";

// 공개 유가 화면(TRANSPORT_UI_MODE=fuel 서버)을 격리 응답으로 검사한다. 유가 BFF는 page.route가 대신하고
// 외부 지도 타일은 막는다. 위치는 브라우저 context의 권한·좌표 모의로 준다.
const metrics = { station_count: 12, average_price: 1700, minimum_price: 1600, maximum_price: 1800,
  price_spread: 200, standard_deviation: 45, saving_50l: 5000, cheapest_station_count: 1,
  generated_at: "2026-11-21T01:00:00Z", cheapest_station: { name: "최저가 시험주유소", address: "서울" } };
const SEOUL = { latitude: 37.5665, longitude: 126.978 };

test.beforeEach(async ({ page }) => {
  test.skip(process.env.E2E_PUBLIC_FUEL !== "true", "공개 유가(TRANSPORT_UI_MODE=fuel) 격리 UI 테스트");
  await page.route((url) => /^https?:$/.test(url.protocol) && !["127.0.0.1", "localhost"].includes(url.hostname), (route) => route.abort());
  await page.route("**/api/public/fuel/places?*", (route) => route.fulfill({ json: {
    items: [], total: 0, truncated: false, clustered: false, available_sources: [],
    fuel_statistics: [{ ...metrics, product_code: "B027" }, { ...metrics, product_code: "D047", average_price: 1550, minimum_price: 1450 }],
    fuel_prices_stale: false, fuel_prices_last_refreshed_at: metrics.generated_at,
  } }));
});

const summaryOf = (page: Page) => page.getByRole("region", { name: "현재 지도 범위 유가 통계" });
const locateButton = (page: Page) => page.getByRole("button", { name: "내 위치 주변 유가 보기" });
// 글자 줄 수를 Range의 줄 상자로 센다(높이·padding 추정 대신 실제 줄바꿈 여부).
const singleLine = async (page: Page, selector: string) => page.locator(selector).evaluateAll(nodes => nodes.map(node => {
  const range = document.createRange(); range.selectNodeContents(node);
  const tops = new Set([...range.getClientRects()].filter(rect => rect.width > 0).map(rect => Math.round(rect.top + rect.height / 2)));
  return [...tops].every(top => Math.abs(top - [...tops][0]) <= 4);
}));

for (const width of [320, 390, 1440]) {
  test(`${width}px 범위 요약은 접지 않고 맨 위 지역 아이콘·유종·필터와 평균 유가를 바로 보인다`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: width < 1000 ? 844 : 900 });
    await page.goto("/");
    const summary = summaryOf(page);
    await expect(summary).toBeVisible();
    // 펼치기·닫기 없이 처음부터 유종·필터 선택과 평균가가 보인다. 펼침 상태를 가진 것은 유종·필터 팝오버 트리거뿐이다.
    await expect(summary.getByRole("button", { name: "범위 요약 닫기" })).toHaveCount(0);
    await expect(summary.locator("[aria-expanded]:not(.public-fuel-filter-trigger)")).toHaveCount(0);
    const combo = summary.getByRole("button", { name: /^유종·필터/ });
    await expect(combo).toBeVisible();
    // 따로 있던 필터 버튼과 "지도 범위" 글씨는 없다.
    await expect(page.getByRole("button", { name: /^필터/ })).toHaveCount(0);
    await expect(summary).not.toContainText("지도 범위");
    await expect(summary.getByRole("definition").first()).toBeVisible();
    await expect(summary.locator('dl[aria-label="휘발유"]')).toContainText("평균");
    await expect(summary.locator('dl[aria-label="휘발유"]')).toContainText("1,700");
    await expect(summary.locator('dl[aria-label="경유"]')).toContainText("1,550");
    // 지역 아이콘과 유종·필터는 맨 위 한 줄에 나란히 놓이고 서로 겹치지 않는다.
    // 첫 응답 뒤 지역 칩·가격 아이콘이 자리를 잡는 동안 머리 줄이 잠깐 다시 배치된다. 자리 잡은 배치를 잰다
    // (n150 repeat-each=10에서 측정 시점에 따라 34px 어긋남이 한 번 잡혔다).
    await expect.poll(async () => {
      const combo = (await summary.locator(".public-fuel-summary-products").boundingBox())!;
      const region = (await summary.getByRole("button", { name: "지역 이동" }).boundingBox())!;
      return Math.abs((region.y + region.height / 2) - (combo.y + combo.height / 2));
    }).toBeLessThanOrEqual(12);
    const comboBox = (await summary.locator(".public-fuel-summary-products").boundingBox())!;
    const regionBox = (await summary.getByRole("button", { name: "지역 이동" }).boundingBox())!;
    expect(regionBox.height).toBeLessThanOrEqual(48);
    expect(regionBox.x + regionBox.width).toBeLessThanOrEqual(comboBox.x);
    expect(await singleLine(page, ".public-fuel-filter-trigger-value")).toEqual([true]);
    const summaryBox = (await summary.boundingBox())!;
    expect(summaryBox.x).toBeGreaterThanOrEqual(0);
    expect(summaryBox.x + summaryBox.width).toBeLessThanOrEqual(width);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    // 유종을 고르면 그 유종의 평균가만 남는다.
    await combo.click();
    await page.getByRole("dialog", { name: "유종·필터" }).getByRole("checkbox", { name: "경유", exact: true }).check();
    await page.keyboard.press("Escape");
    await expect(combo).toHaveAccessibleName("유종·필터: 경유");
    await expect(summary.locator('dl[aria-label="휘발유"]')).toHaveCount(0);
    await expect(summary.locator('dl[aria-label="경유"]')).toContainText("1,550");
    await page.screenshot({ path: testInfo.outputPath(`public-fuel-summary-${width}.png`), animations: "disabled" });
  });
}

test.describe("내 위치 · 권한 허용", () => {
  test.use({ permissions: ["geolocation"], geolocation: SEOUL });
  test("390px 권한 허용 시 바로 위치를 찾고 오류 문구를 남기지 않는다", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await expect(summaryOf(page)).toBeVisible();
    await locateButton(page).click();
    await expect(locateButton(page)).not.toHaveAttribute("aria-busy", "true");
    await expect(page.locator(".public-fuel-location [role=status]")).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });

  test("첫 저정밀 요청이 시간 초과여도 고정밀 재시도로 위치를 찾는다", async ({ page }) => {
    await page.addInitScript(() => {
      const original = navigator.geolocation.getCurrentPosition.bind(navigator.geolocation);
      const calls: PositionOptions[] = [];
      (window as unknown as { locateCalls: PositionOptions[] }).locateCalls = calls;
      navigator.geolocation.getCurrentPosition = (success, error, options) => {
        calls.push(options ?? {});
        if (calls.length === 1) { setTimeout(() => error?.({ code: 3, message: "timeout" } as GeolocationPositionError), 50); return; }
        original(success, error, options);
      };
    });
    await page.goto("/");
    await locateButton(page).click();
    await expect.poll(() => page.evaluate(() => (window as unknown as { locateCalls: PositionOptions[] }).locateCalls.length)).toBe(2);
    await expect(locateButton(page)).not.toHaveAttribute("aria-busy", "true");
    await expect(page.locator(".public-fuel-location [role=status]")).toHaveCount(0);
    const calls = await page.evaluate(() => (window as unknown as { locateCalls: PositionOptions[] }).locateCalls);
    expect(calls[0]).toMatchObject({ enableHighAccuracy: false, maximumAge: 60_000 });
    expect(calls[1]).toMatchObject({ enableHighAccuracy: true });
  });
});

test.describe("내 위치 · 권한 거부", () => {
  test.use({ permissions: [] });
  test("390px 권한 거부는 설정 안내를 보이고 재시도 버튼 없이 한 줄 버튼만 남긴다", async ({ page, context }, testInfo) => {
    await context.clearPermissions();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await expect(summaryOf(page)).toBeVisible();
    await locateButton(page).click();
    const status = page.locator(".public-fuel-location [role=status]");
    await expect(status).toContainText("위치 권한이 거부되었습니다");
    await expect(page.getByRole("button", { name: "다시 시도" })).toHaveCount(0);
    await expect(locateButton(page)).not.toHaveAttribute("aria-busy", "true");
    const box = (await status.boundingBox())!;
    expect(box.x + box.width).toBeLessThanOrEqual(390);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("public-fuel-location-denied-390.png"), animations: "disabled" });
  });

  test("320px 위치 확인 불가는 다시 시도 버튼을 한 줄로 보이고 재시도로 회복한다", async ({ page }, testInfo) => {
    await page.addInitScript(() => {
      let calls = 0;
      navigator.geolocation.getCurrentPosition = (success, error) => {
        calls += 1;
        if (calls <= 2) { setTimeout(() => error?.({ code: 2, message: "unavailable" } as GeolocationPositionError), 20); return; }
        setTimeout(() => success({ coords: { latitude: 37.5665, longitude: 126.978, accuracy: 30 }, timestamp: Date.now() } as GeolocationPosition), 20);
      };
      navigator.geolocation.watchPosition = () => 1;
    });
    await page.setViewportSize({ width: 320, height: 700 });
    await page.goto("/");
    await locateButton(page).click();
    const status = page.locator(".public-fuel-location [role=status]");
    await expect(status).toContainText("현재 위치를 확인할 수 없습니다");
    const retry = page.getByRole("button", { name: "다시 시도" });
    await expect(retry).toBeVisible();
    expect(await singleLine(page, ".public-fuel-location-retry")).toEqual([true]);
    expect((await retry.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    const panel = (await page.locator(".public-fuel-location-status").boundingBox())!;
    expect(panel.x + panel.width).toBeLessThanOrEqual(320);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("public-fuel-location-retry-320.png"), animations: "disabled" });
    await retry.click();
    await expect(status).toHaveCount(0);
    await expect(locateButton(page)).not.toHaveAttribute("aria-busy", "true");
  });
});
