import { expect, test, type Page } from "@playwright/test";

async function session(page: Page) {
  await page.context().addCookies([{ name: "kor_travel_transport_admin_session", value: "isolated-domain-fixture", url: test.info().project.use.baseURL!, httpOnly: true, sameSite: "Strict" }]);
  await page.route("**://*.vworld.kr/**", route => route.abort());
}
const terminals = [
  { id: 1, terminal_id: "SEO", terminal_name: "서울", city_name: "서울", latitude: null, longitude: null, updated_at: "2026-11-11T00:00:00Z" },
  { id: 2, terminal_id: "BUS", terminal_name: "부산", city_name: "부산", latitude: null, longitude: null, updated_at: "2026-11-11T00:00:00Z" },
];

for (const width of [375, 1440]) {
  test(`버스 검색·시간표·날짜 변경 ${width}px`, async ({ page }) => {
    await session(page); await page.setViewportSize({ width, height: 900 });
    await page.route("**/api/transport/**", async route => {
      const url = new URL(route.request().url());
      const data = url.pathname.endsWith("bus/timetable")
        ? { service_date: url.searchParams.get("date"), fetched_at: new Date().toISOString(), items: [{ departure_planned_time: "235900", arrival_planned_time: "275900", departure_terminal_name: "서울", arrival_terminal_name: "검증 도착 터미널", grade_name: "우등", adult_fare: 20000 }] }
        : { items: terminals, next_offset: null };
      await route.fulfill({ json: data });
    });
    await page.goto("/bus/express");
    const filters = page.locator('[data-slot="map-filter-trigger"]');
    if (await filters.isVisible()) await filters.click();
    await page.getByRole("button", { name: "출발·도착 검색", exact: true }).click();
    await page.getByLabel("출발 터미널", { exact: true }).fill("서울");
    await page.locator('.terminal-search').nth(0).getByRole("button", { name: /^서울/ }).click();
    await page.locator('.terminal-search').nth(1).getByRole("button", { name: /^부산/ }).click();
    await page.getByRole("button", { name: "운행편 조회", exact: true }).click();
    await page.locator('#bus-departures input[type="checkbox"]').uncheck();
    await expect(page.locator('#bus-departures')).toContainText("검증 도착 터미널");
    if (await filters.isVisible() && await filters.getAttribute("aria-expanded") === "false") await filters.click();
    const date = page.getByLabel("출발일", { exact: true });
    const next = new Date(`${await date.inputValue()}T00:00:00Z`); next.setUTCDate(next.getUTCDate() + 1);
    await date.fill(next.toISOString().slice(0, 10));
    await expect(page.locator('#bus-departures')).not.toContainText("검증 도착 터미널");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/transport-bus-${width}.png`, fullPage: true });
  });

  test(`공항 오류·항공편 독립 표시 ${width}px`, async ({ page }) => {
    await session(page); await page.setViewportSize({ width, height: 900 });
    const now = new Date().toISOString(), future = new Date(Date.now() + 3600_000).toISOString();
    await page.route("**/api/transport/**", async route => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("parking/current")) return route.fulfill({ status: 503, json: { detail: "주차 검증 오류" } });
      const data = path.endsWith("features/places")
        ? { items: [{ id: 1, kind: "airport", provider_id: "GMP", source: "fixture", name: "김포 검증 공항", latitude: null, longitude: null, line_names: [], prices: [], facilities: [], updated_at: now }] }
        : path.endsWith("flights/status")
          ? { status: "success", error_message: null, items: [{ flight_number: "TEST1101", direction: "departure", airline: "검증 항공사", scheduled_at: future, estimated_at: null, origin_airport: "GMP", destination_airport: "CJU", status: "예정" }] }
          : { items: [], generated_at: now };
      await route.fulfill({ json: data });
    });
    await page.goto("/flights");
    await expect(page.getByRole("main").getByRole("alert")).toContainText("주차 현황을 불러오지 못했습니다.");
    await expect(page.locator('#airport-flights')).toContainText("TEST1101");
    await expect(page.getByText("주차 현황을 확인하는 중입니다…", { exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/transport-flights-${width}.png`, fullPage: true });
  });
}
