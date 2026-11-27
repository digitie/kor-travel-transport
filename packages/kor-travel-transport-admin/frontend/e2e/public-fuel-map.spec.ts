import { expect, test, type Page } from "@playwright/test";
import { isolatePublicFuel } from "./public-fuel-isolation";

// 공개 유가 화면(TRANSPORT_UI_MODE=fuel 서버)을 격리 응답으로 검사한다. 유가 BFF는 page.route가 대신하고
// 외부 요청은 막는다(배경지도 타일만 성공 이미지, public-fuel-isolation.ts). 위치는 브라우저 context의 권한·좌표 모의로 준다.
const metrics = { station_count: 12, average_price: 1700, minimum_price: 1600, maximum_price: 1800,
  price_spread: 200, standard_deviation: 45, saving_50l: 5000, cheapest_station_count: 1,
  generated_at: "2026-11-21T01:00:00Z", cheapest_station: { name: "최저가 시험주유소", address: "서울" } };
const SEOUL = { latitude: 37.5665, longitude: 126.978 };

test.beforeEach(async ({ page }) => {
  test.skip(process.env.E2E_PUBLIC_FUEL !== "true", "공개 유가(TRANSPORT_UI_MODE=fuel) 격리 UI 테스트");
  await isolatePublicFuel(page);
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
    // 두 상자를 차례로 재므로 그 사이에 요약이 움직이면 어긋나 보인다. n150 repeat-each=10에서 잡힌 34px 어긋남은 두 측정 사이에 생긴
    // "지도 타일 오류" 알림(34.5px)이었다 — 이제 isolatePublicFuel이 타일을 성공시킨다. 자리 잡은 배치를 재는 poll은 그대로 둔다.
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

for (const width of [375, 1440]) {
  test(`${width}px 자동 재조회 대기는 범위 요약 줄에서 알리고 요약을 밀거나 자르지 않는다`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: width < 1000 ? 812 : 900 });
    // 요약 위 줄의 배경지도 알림이 측정 사이에 생기지 않게 타일은 isolatePublicFuel이 성공시킨다(FUEL-PUBLIC-MAP-RETRY-E2E).
    const seen = new Map<string, number>();
    // 같은 조건의 첫 응답만 혼잡(429, Retry-After 2초). 화면은 한 번 자동으로 다시 묻는다.
    await page.route("**/api/public/fuel/places?*", async (route) => {
      const url = route.request().url(); const count = (seen.get(url) ?? 0) + 1; seen.set(url, count);
      if (count === 1) return route.fulfill({ status: 429, headers: { "retry-after": "2", "content-type": "application/problem+json" },
        json: { detail: "장소 지도 조회가 혼잡합니다. 잠시 후 다시 시도하세요." } });
      return route.fallback();
    });
    await page.goto("/");
    const summary = summaryOf(page);
    const status = summary.locator(".public-fuel-summary-body").getByRole("status");
    await expect(status).toHaveText("다시 조회 중…");
    const waiting = (await summary.boundingBox())!;
    expect(waiting.x).toBeGreaterThanOrEqual(0);
    expect(waiting.x + waiting.width).toBeLessThanOrEqual(width);
    expect(await singleLine(page, ".public-fuel-summary-body [role=status]")).toEqual([true]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    // 격리 환경의 지도 타일·SDK 안내 알림은 세지 않는다. 재조회 대기 중에는 조회 실패 알림이 없다.
    await expect(page.getByRole("alert").filter({ hasText: "조회 실패" })).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath(`public-fuel-retrying-${width}.png`), animations: "disabled" });
    // 재조회가 성공하면 같은 자리(요약 위치 그대로)에 평균가가 들어온다. 표시는 새 요소가 아니라 화면을 밀지 않는다.
    await expect(summary.locator('dl[aria-label="휘발유"]')).toContainText("1,700", { timeout: 8000 });
    const settled = (await summary.boundingBox())!;
    expect(Math.abs(settled.y - waiting.y)).toBeLessThanOrEqual(1);
    await expect(summary).not.toContainText("다시 조회 중");
    await expect(page.getByRole("alert").filter({ hasText: "조회 실패" })).toHaveCount(0);
  });
}

for (const width of [375, 1440]) {
  test(`${width}px 배경지도를 못 그리면 요약 위에 한 줄로 알리고 없는 목록 보기로 안내하지 않는다`, async ({ page }) => {
    await page.setViewportSize({ width, height: width < 1000 ? 812 : 900 });
    // isolatePublicFuel이 성공시키는 타일을 이 시험에서만 모두 실패시킨다(나중에 등록한 route가 먼저).
    await page.route("https://api.vworld.kr/req/wmts/**", route => route.abort());
    await page.goto("/");
    const summary = summaryOf(page);
    await expect(summary.locator('dl[aria-label="휘발유"]')).toContainText("1,700");
    // 격리 e2e는 VWorld 키 빌드가 기준이다(testing.md). 타일이 모두 실패하면 첫 idle 뒤 "지도 타일 오류"만 — "· 목록 보기"는 없다.
    const notice = page.locator(".map-feedback [role=alert]");
    await expect(notice).toHaveText("지도 타일 오류", { timeout: 15_000 });
    // 알림은 요약 위 줄에 있고 요약은 화면 안에 남는다(알림이 생기면 요약이 그만큼 내려간다 — 새 안내라 자리를 미리 비우지 않는다).
    const [noticeBox, summaryBox] = [(await notice.boundingBox())!, (await summary.boundingBox())!];
    expect(noticeBox.y + noticeBox.height).toBeLessThanOrEqual(summaryBox.y);
    expect(summaryBox.x + summaryBox.width).toBeLessThanOrEqual(width);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
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
