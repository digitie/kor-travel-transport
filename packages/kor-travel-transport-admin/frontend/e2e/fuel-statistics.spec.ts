import { expect, test } from "@playwright/test";

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
  await expect(summary.getByText("12,000개 주유소")).toBeVisible();
  await expect(summary.getByText("최저가 시험주유소", { exact: true })).toBeVisible();
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
