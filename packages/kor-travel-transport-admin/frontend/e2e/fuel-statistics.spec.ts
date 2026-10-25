import { expect, test, type Page } from "@playwright/test";

async function openFilters(page: Page) {
  const trigger = page.locator('[data-slot="map-filter-trigger"]');
  if (await trigger.isVisible() && await trigger.getAttribute("aria-expanded") === "false") await trigger.click();
}

const metrics = { station_count: 12000, average_price: 1700, minimum_price: 1600, maximum_price: 1800,
  price_spread: 200, standard_deviation: 45, saving_50l: 5000, cheapest_station_count: 1,
  generated_at: "2026-10-21T01:00:00Z", cheapest_station: { name: "최저가 시험주유소", address: "서울" } };

test.beforeEach(async ({ page }) => {
  test.skip(process.env.E2E_FUEL_STATISTICS !== "true", "격리 유가 통계 UI 테스트");
  await page.context().addCookies([{ name: "kor_travel_transport_admin_session", value: "isolated-e2e",
    url: process.env.E2E_BASE_URL ?? "http://127.0.0.1:12305", httpOnly: true, sameSite: "Strict" }]);
});

for (const width of [390, 1440]) {
  test(`${width}px 통계 범주·유종 전환과 7일 추이`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.route("**/api/transport/transport/fuel/statistics?*", async (route) => {
      const url = new URL(route.request().url());
      const label = url.searchParams.get("scope") === "highway_direction" ? "경부선 · 상행" : "전국";
      await route.fulfill({ json: { generated_at: metrics.generated_at, update_pending: false,
        history_scope_key: "all", items: [{ ...metrics, scope_key: "all", label }],
        history: Array.from({ length: 7 }, (_, i) => ({ day: `2026-10-${15 + i}`, average_price: 1700 + i, station_count: 12000 })) } });
    });
    await page.goto("/fuel/statistics");
    await expect(page.getByRole("article", { name: "전국 · 휘발유" })).toBeVisible();
    await expect(page.getByRole("img", { name: /최근 7일 평균 유가 추이/ })).toBeVisible();
    await expect(page.getByLabel("주유량(L)", { exact: true })).not.toBeVisible();
    await page.locator(".fuel-driving-details > summary").click();
    await expect(page.getByLabel("주유량(L)", { exact: true })).toBeVisible();
    await page.getByLabel("범위", { exact: true }).selectOption("highway_direction");
    await page.getByLabel("유종", { exact: true }).selectOption("D047");
    await expect(page.getByRole("article", { name: "경부선 · 상행 · 경유" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}

test("조회 실패와 재시도", async ({ page }) => {
  let fail = true;
  await page.route("**/api/transport/transport/fuel/statistics?*", async (route) => {
    if (fail) return route.fulfill({ status: 503, json: { detail: "unavailable" } });
    return route.fulfill({ json: { generated_at: null, update_pending: true, history_scope_key: null, items: [], history: [] } });
  });
  await page.goto("/fuel/statistics");
  await expect(page.getByRole("region", { name: "유가 통계", exact: true }).getByRole("alert")).toContainText("불러오지 못했습니다");
  fail = false;
  await page.getByRole("button", { name: "새로고침", exact: true }).click();
  await expect(page.getByText("첫 수집 완료 후 통계가 생성됩니다.", { exact: false })).toBeVisible();
});

test("지도 요약 마커 수와 독립된 범위 통계를 같은 요청으로 표시한다", async ({ page }) => {
  await page.route("**/api/transport/transport/features/places?*", async (route) => {
    expect(new URL(route.request().url()).searchParams.get("include_fuel_statistics")).toBe("true");
    return route.fulfill({ json: { items: [], total: 12000, truncated: false, clustered: true,
      kind_totals: { fuel_station: 12000 }, available_sources: ["opinet_browser"],
      clusters: [{ id: "test", longitude: 127, latitude: 37, count: 12000, kind_counts: { fuel_station: 12000 } }],
      fuel_statistics: [{ ...metrics, product_code: "B027" }] } });
  });
  await page.goto("/fuel");
  const summary = page.getByRole("region", { name: "현재 지도 범위 유가 통계" });
  await expect(summary).toContainText("1,700");
  await summary.getByRole("button", { name: "지도 범위 유가 통계 안내" }).click();
  await expect(page.getByRole("dialog")).toContainText("12,000개 주유소");
  await expect(page.getByRole("dialog").getByText("최저가 시험주유소", { exact: true })).toBeVisible();
});

test("지도 초기화 오류는 범위 요약 바깥 위에 표시하고 목록에서는 숨긴다", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    Object.defineProperty(HTMLCanvasElement.prototype, "getContext", { value: function (contextId: string, ...args: unknown[]) {
      return contextId === "webgl" || contextId === "webgl2" ? null : Reflect.apply(original, this, [contextId, ...args]);
    } });
  });
  await page.route("**/api/transport/transport/features/places?*", (route) => route.fulfill({ json: { items: [], total: 0, truncated: false, fuel_statistics: [{ ...metrics, product_code: "B027" }] } }));
  await page.goto("/fuel");
  const error = page.locator(".map-feedback").getByRole("alert");
  const summary = page.getByRole("region", { name: "현재 지도 범위 유가 통계" });
  await expect(error).toHaveText(/^지도 (키 없음|표시 불가) · 목록 보기$/);
  await expect(summary).toContainText("1,700");
  const errorBounds = await error.boundingBox();
  const summaryBounds = await summary.boundingBox();
  expect(errorBounds!.y + errorBounds!.height).toBeLessThanOrEqual(summaryBounds!.y);
  await page.getByRole("tab", { name: "목록", exact: true }).click();
  await expect(error).toHaveCount(0);
  await expect(summary).toHaveCount(0);
  await page.getByRole("tab", { name: "지도", exact: true }).click();
  await expect(error).toHaveCount(1);
  await expect(error).toBeVisible();
  await expect(summary).toBeVisible();
  await page.screenshot({ path: `test-results/compact-fuel-${testInfo.project.name}-fallback-375.png`, fullPage: true, animations: "disabled" });
});

for (const width of [375, 1440]) test(`${width}px 가격 갱신 지연은 요약 옆에 남고 재조회·실패·빈 시각을 구분한다`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: width === 375 ? 812 : 900 });
  const priceAt = "2026-10-20T03:10:00Z";
  const place = { id: 42, kind: "fuel_station", source: "opinet_browser", name: "지연 시험주유소", latitude: 37.5, longitude: 127.1,
    prices: [{ product_code: "B027", price: 1705, observed_at: priceAt }], line_names: [], facilities: [], updated_at: metrics.generated_at };
  let release = () => {};
  let markRequested = () => {};
  const requested = new Promise<void>((resolve) => { markRequested = resolve; });
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/transport/transport/features/places?*", async (route) => {
    const query = new URL(route.request().url()).searchParams.get("query");
    if (query === "pending") { markRequested(); await gate; return route.fulfill({ status: 503, json: { detail: "fixture failure" } }); }
    return route.fulfill({ json: { items: [place], total: 1, truncated: false,
      fuel_prices_stale: query !== "fresh", fuel_prices_last_refreshed_at: query === "unknown" ? null : priceAt,
      fuel_statistics: [{ ...metrics, product_code: "B027", generated_at: query === "unknown" ? "" : metrics.generated_at }] } });
  });
  try {
    await page.goto("/fuel");
    const summary = page.getByRole("region", { name: "현재 지도 범위 유가 통계" });
    const stale = summary.getByRole("status");
    await expect(stale).toHaveText("갱신 지연 26.10.20 12:10 KST");
    await expect(page.locator(".map-guidance")).toHaveCount(0);
    for (const theme of ["light", "dark"]) {
      await page.evaluate((dark) => document.documentElement.classList.toggle("dark", dark), theme === "dark");
      const priceBounds = await summary.locator("dl").boundingBox();
      const warningBounds = await stale.boundingBox();
      expect(warningBounds!.y).toBeGreaterThanOrEqual(priceBounds!.y + priceBounds!.height);
      expect(warningBounds!.y - priceBounds!.y - priceBounds!.height).toBeLessThan(10);
      expect(warningBounds!.y + warningBounds!.height).toBeLessThanOrEqual(width === 375 ? 812 : 900);
      await page.screenshot({ path: `test-results/compact-fuel-${testInfo.project.name}-stale-${width}-${theme}.png`, fullPage: false, animations: "disabled" });
    }
    await summary.getByRole("button", { name: "지도 범위 유가 통계 안내" }).click();
    await expect(page.getByRole("dialog")).toContainText("판매 여부");
    await expect(page.getByRole("dialog").getByText(/^수집 기준/)).toContainText("26. 10. 21.");
    await page.keyboard.press("Escape");
    await page.getByRole("tab", { name: "목록", exact: true }).click();
    await expect(summary).toHaveCount(0);
    await expect(page.locator(".map-guidance")).toContainText("유가 갱신 지연");
    await page.locator(".map-place-list").getByRole("button", { name: /지연 시험주유소/ }).click();
    const detail = page.getByRole("complementary", { name: "선택 장소 상세" });
    await expect(detail.getByRole("status")).toHaveText("갱신 지연 26.10.20 12:10 KST");
    await page.getByRole("tab", { name: "지도", exact: true }).click();
    await expect(detail.getByRole("status")).toContainText("갱신 지연");
    await openFilters(page);
    await page.getByLabel("장소 검색", { exact: true }).fill("pending");
    await requested;
    await expect(summary).toContainText("통계 조회 중");
    await expect(summary).not.toContainText("1,700");
    await expect(summary).not.toContainText("갱신 지연");
    release();
    await expect(summary.getByRole("alert")).toContainText("통계를 불러오지 못했습니다");
    await expect(summary).not.toContainText("갱신 지연");
    await page.getByLabel("장소 검색", { exact: true }).fill("unknown");
    await expect(stale).toHaveText("갱신 지연 시각 미확인");
    await summary.getByRole("button", { name: "지도 범위 유가 통계 안내" }).click();
    await expect(page.getByRole("dialog").getByText(/^수집 기준/)).toHaveText("수집 기준 확인되지 않음");
    await page.keyboard.press("Escape");
    await page.getByLabel("장소 검색", { exact: true }).fill("fresh");
    await expect(summary).toContainText("1,700");
    await expect(summary).not.toContainText("갱신 지연");
  } finally { release(); }
});

for (const width of [375, 1440]) test(`${width}px 가격 있는 장소와 빈 통계가 함께 와도 갱신 지연을 표시한다`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: width === 375 ? 812 : 900 });
  const priceAt = "2026-10-20T03:10:00Z";
  const place = { id: 43, kind: "fuel_station", source: "opinet_browser", name: "통계 대기 시험주유소", latitude: 37.5, longitude: 127.1,
    prices: [{ product_code: "B027", price: 1705, observed_at: priceAt }], line_names: [], facilities: [], updated_at: priceAt };
  await page.route("**/api/transport/transport/features/places?*", (route) => route.fulfill({ json: {
    items: [place], total: 1, truncated: false, clustered: false, fuel_statistics: [], fuel_prices_stale: true,
    fuel_prices_last_refreshed_at: new URL(route.request().url()).searchParams.get("query") === "unknown" ? null : priceAt,
  } }));
  await page.goto("/fuel");
  const summary = page.getByRole("region", { name: "현재 지도 범위 유가 통계" });
  const stale = summary.getByRole("status");
  await expect(summary).toContainText("통계 없음 · 수집 완료 후 반영됩니다.");
  await expect(stale).toHaveText("갱신 지연 26.10.20 12:10 KST");
  await expect(page.locator(".kt-map-count")).toHaveText("1건 표시");
  await expect(summary.locator("dl")).toHaveCount(0);
  for (const theme of ["light", "dark"]) {
    await page.evaluate((dark) => document.documentElement.classList.toggle("dark", dark), theme === "dark");
    const warningBounds = (await stale.boundingBox())!;
    expect(warningBounds.y + warningBounds.height).toBeLessThanOrEqual(width === 375 ? 812 : 900);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/compact-fuel-${testInfo.project.name}-empty-stale-${width}-${theme}.png`, fullPage: false, animations: "disabled" });
  }
  await summary.getByRole("button", { name: "지도 범위 유가 통계 안내" }).click();
  await expect(page.getByRole("dialog")).toContainText("판매 여부");
  await expect(page.getByRole("dialog")).toContainText("통계 없음");
  await page.keyboard.press("Escape");
  await page.getByRole("tab", { name: "목록", exact: true }).click();
  await expect(summary).toHaveCount(0);
  await expect(page.locator(".map-guidance")).toContainText("유가 갱신 지연");
  await page.locator(".map-place-list").getByRole("button", { name: /통계 대기 시험주유소/ }).click();
  const detail = page.getByRole("complementary", { name: "선택 장소 상세" });
  await expect(detail).toContainText("1,705원/L");
  await expect(detail.getByRole("status")).toContainText("갱신 지연");
  await page.getByRole("tab", { name: "지도", exact: true }).click();
  await expect(summary.locator("dl")).not.toBeVisible();
  await expect(detail.getByRole("status")).toContainText("갱신 지연");
  await openFilters(page);
  await page.getByLabel("장소 검색", { exact: true }).fill("unknown");
  await expect(stale).toHaveText("갱신 지연 시각 미확인");
  await expect(summary).toContainText("통계 없음");
  await expect(summary).not.toContainText("통계 기준");
});

test("안내를 키보드로 연 뒤 재조회·실패·성공에도 초점과 새 내용만 유지한다", async ({ page }) => {
  let release = () => {};
  let markRequested = () => {};
  const requested = new Promise<void>((resolve) => { markRequested = resolve; });
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/transport/transport/features/places?*", async (route) => {
    const query = new URL(route.request().url()).searchParams.get("query");
    if (query === "pending") { markRequested(); await gate; return route.fulfill({ status: 503, json: { detail: "fixture failure" } }); }
    return route.fulfill({ json: { items: [], total: 0, fuel_statistics: [{ ...metrics, product_code: "B027", average_price: query === "success" ? 1800 : 1700 }] } });
  });
  const changeQueryWithoutMovingFocus = (value: string) => page.getByLabel("장소 검색", { exact: true }).evaluate((input, next) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, next);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }, value);
  try {
    await page.goto("/fuel");
    const summary = page.getByRole("region", { name: "현재 지도 범위 유가 통계" });
    await expect(summary).toContainText("1,700");
    const info = summary.getByRole("button", { name: "지도 범위 유가 통계 안내" });
    await info.focus(); await page.keyboard.press("Enter");
    const popup = page.getByRole("dialog");
    await popup.getByRole("link", { name: "지역·기간별 유가 통계" }).focus();
    await changeQueryWithoutMovingFocus("pending");
    await requested;
    await expect(popup).toContainText("통계 조회 중");
    await expect(popup).not.toContainText("1,700");
    const close = popup.getByRole("button", { name: "안내 닫기" });
    await expect(close).toBeFocused();
    release();
    await expect(popup.getByRole("alert")).toContainText("통계를 불러오지 못했습니다");
    await expect(popup).not.toContainText("1,700");
    await expect(close).toBeFocused();
    await changeQueryWithoutMovingFocus("success");
    await expect(popup).toContainText("1,800");
    await expect(popup).not.toContainText("1,700");
    await expect(close).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(info).toBeFocused();
  } finally { release(); }
});

test.describe("터치 지도 범위 요약", () => {
  test.use({ hasTouch: true });
  for (const width of [320, 375]) test(`${width}px 유종 선택은 44px이며 제목·안내와 겹치지 않는다`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 812 });
    await page.route("**/api/transport/transport/features/places?*", (route) => route.fulfill({ json: { items: [], total: 0, fuel_statistics: ["B027", "D047"].map((product_code) => ({ ...metrics, product_code })) } }));
    await page.goto("/fuel");
    const summary = page.getByRole("region", { name: "현재 지도 범위 유가 통계" });
    const select = page.getByLabel("지도 통계 유종");
    await expect(select).toBeVisible();
    expect(await page.evaluate(() => matchMedia("(pointer: coarse)").matches)).toBe(true);
    const selectBox = (await select.boundingBox())!, titleBox = (await summary.getByRole("heading").boundingBox())!, infoBox = (await summary.getByRole("button", { name: "지도 범위 유가 통계 안내" }).boundingBox())!;
    expect(selectBox.height).toBeGreaterThanOrEqual(44);
    expect(infoBox.width).toBeGreaterThanOrEqual(44); expect(infoBox.height).toBeGreaterThanOrEqual(44);
    expect(titleBox.x + titleBox.width).toBeLessThanOrEqual(selectBox.x);
    expect(selectBox.x + selectBox.width).toBeLessThanOrEqual(infoBox.x);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/compact-fuel-${testInfo.project.name}-touch-${width}.png`, fullPage: false, animations: "disabled" });
  });
});

for (const width of [320, 375, 1440]) test(`${width}px 지도 상부 유가 요약·메타 팝업·프로젝트 톤`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 812 });
  const place = { id: 1, kind: "fuel_station", source: "opinet_browser", name: "압축 시험주유소", brand_name: "시험 브랜드", address: "서울 시험 주소", latitude: 37.5, longitude: 127.1,
    prices: [{ product_code: "B027", price: 1705, observed_at: metrics.generated_at }], line_names: [], facilities: ["셀프"], updated_at: metrics.generated_at };
  await page.route("**/api/transport/transport/features/places?*", (route) => route.fulfill({ json: { items: [place], total: 1, truncated: false, clustered: false, available_sources: [place.source],
    fuel_statistics: [{ ...metrics, product_code: "B027" }, { ...metrics, product_code: "D047", average_price: 1550 }] } }));
  await page.goto("/fuel");
  const summary = page.getByRole("region", { name: "현재 지도 범위 유가 통계" });
  await expect(summary).toContainText("1,700");
  await page.getByLabel("지도 통계 유종").selectOption("D047");
  await expect(summary).toContainText("1,550");
  await page.getByRole("tab", { name: "목록", exact: true }).click();
  await expect(summary).toHaveCount(0);
  await page.locator(".map-place-list").getByRole("button", { name: /압축 시험주유소/ }).click();
  const detail = page.getByRole("complementary", { name: "선택 장소 상세" });
  await expect(detail).toContainText("1,705원/L");
  const address = detail.getByRole("button", { name: "주소 안내", exact: true });
  await address.click();
  await expect(page.getByRole("dialog")).toContainText("서울 시험 주소");
  await page.getByRole("dialog").getByRole("button", { name: /서울 시험 주소/ }).click();
  await expect(page.getByRole("tab", { name: "지도", exact: true })).toHaveAttribute("aria-selected", "true");
  // 주소의 지도 전환으로 목록 상세가 교체되므로 새 지도 상세의 팝업을 다시 연다.
  await expect(detail).toBeVisible();
  await address.click();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(detail).toBeVisible();
  await expect(address).toBeFocused();
  const source = detail.getByRole("button", { name: "데이터 출처 안내", exact: true });
  await source.click();
  await expect(page.getByRole("dialog")).toContainText("기준정보 반영");
  await page.keyboard.press("Escape");
  await expect(source).toBeFocused();
  const stage = page.locator(".fuel-map-stage");
  const bounds = await stage.boundingBox();
  const summaryBounds = await summary.boundingBox();
  const detailBounds = await detail.boundingBox();
  expect(summaryBounds!.y).toBeGreaterThanOrEqual(bounds!.y);
  expect(summaryBounds!.y + summaryBounds!.height).toBeLessThanOrEqual(detailBounds!.y);
  expect(detailBounds!.y + detailBounds!.height).toBeLessThanOrEqual(bounds!.y + bounds!.height);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  for (const theme of ["light", "dark"]) {
    await page.evaluate((dark) => document.documentElement.classList.toggle("dark", dark), theme === "dark");
    const palette = await page.evaluate(() => { const style = getComputedStyle(document.documentElement); return { brand: style.getPropertyValue("--brand").trim(), commonBrand: style.getPropertyValue("--kt-brand").trim(), card: style.getPropertyValue("--card").trim(), commonCard: style.getPropertyValue("--kt-surface-card").trim() }; });
    expect(palette.commonBrand).toBe(palette.brand);
    expect(palette.commonCard).toBe(palette.card);
    const expectedSurface = await page.evaluate(() => { const probe = document.createElement("span"); probe.style.backgroundColor = "var(--kt-surface-card)"; document.body.append(probe); const color = getComputedStyle(probe).backgroundColor; probe.remove(); return color; });
    await expect(page.getByLabel("장소 검색", { exact: true })).toHaveCSS("background-color", expectedSurface);
    await page.screenshot({ path: `test-results/compact-fuel-${testInfo.project.name}-${width}-${theme}.png`, fullPage: true, animations: "disabled" });
  }
});

test("추이 범주와 비교표는 지연 응답 중에도 키보드 포커스를 유지한다", async ({ page }) => {
  let gate: Promise<void> | null = null;
  let release = () => {};
  let started = () => {};
  let requested: Promise<void>;
  const hold = () => {
    gate = new Promise<void>((resolve) => { release = resolve; });
    requested = new Promise<void>((resolve) => { started = resolve; });
  };
  await page.route("**/api/transport/transport/fuel/statistics?*", async (route) => {
    const selected = new URL(route.request().url()).searchParams.get("scope_key") ?? "first";
    if (gate) { const waiting = gate; started(); await waiting; }
    return route.fulfill({ json: { generated_at: metrics.generated_at, update_pending: false,
      history_scope_key: selected, items: ["first", "second"].map((scope_key, i) => ({ ...metrics, scope_key, label: i ? "둘째" : "첫째" })),
      history: [{ day: "2026-10-21", average_price: 1700, station_count: 12000 }] } });
  });
  await page.goto("/fuel/statistics");
  const category = page.getByLabel("추이 범주", { exact: true });
  await expect(category).toBeVisible();
  hold();
  await category.focus();
  await category.selectOption("second");
  await requested!;
  await expect(category).toBeFocused();
  gate = null; release();
  await expect(page.getByRole("article", { name: "둘째 · 휘발유" })).toBeVisible();
  await expect(category).toBeFocused();
  hold();
  const row = page.getByRole("button", { name: "첫째", exact: true });
  await row.click();
  await requested!;
  await expect(row).toBeFocused();
  gate = null; release();
  await expect(page.getByRole("article", { name: "첫째 · 휘발유" })).toBeVisible();
  await expect(row).toBeFocused();
});
