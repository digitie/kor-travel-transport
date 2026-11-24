import { expect, test } from "@playwright/test";

// #263 후속: 무효 원천 행만 격리한 부분 성공은 운영 상태 목록에서 공항·고속도로 모두 "부분 성공(격리 N건)"이다.
// 실패 배지(destructive)나 "수집 실패" 안내로 보이지 않는다. provider 응답은 route로 고정한다.
const item = (source: string, name: string, job: string, status: string, isolated: number | null, jobIsolated: number) => ({
  source, name, job_name: job, job_status: "partial_success", enabled: true, mode: "scheduled", status,
  interval_seconds: 300, last_started_at: "2026-11-24T09:25:00Z", last_success_at: "2026-11-24T09:26:00Z",
  next_due_at: "2026-11-24T09:30:00Z", error_code: null, isolated_rows: isolated, job_isolated_rows: jobIsolated,
});

for (const viewport of [{ width: 390, height: 844 }, { width: 1440, height: 900 }]) {
  test(`격리만 있는 부분 성공을 실패와 구분해 보인다 ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.context().addCookies([{ name: "kor_travel_transport_admin_session", value: "isolated-provider-e2e",
      url: process.env.E2E_BASE_URL ?? "http://127.0.0.1:12351", httpOnly: true, sameSite: "Strict" }]);
    await page.route("**://*.vworld.kr/**", (route) => route.abort());
    await page.route("**/api/**", async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith("/transport/providers")) return route.fulfill({ json: {
        generated_at: "2026-11-24T09:30:00Z", ferry_window_start: "2026-11-24", ferry_window_end: "2026-12-03",
        ferry_expected_snapshots: 0, ferry_stored_snapshots: 0, items: [
          item("kac_parking", "한국공항공사 주차", "airport_collection_job", "shared_job_partial_success", 1, 1),
          item("krex_traffic_flow", "고속도로 소통", "highway_collection_job", "partial_success", 3, 3),
          item("krex_traffic_incident", "고속도로 돌발", "highway_collection_job", "success", null, 3),
        ] } });
      if (url.pathname === "/api/address-refresh") return route.fulfill({ status: 503, json: {} });
      if (url.pathname === "/api/dagster/graphql") return route.fulfill({ json: { data: {
        activeRuns: { __typename: "Runs", results: [] }, repositoryOrError: { __typename: "Repository", schedules: [] },
        runsOrError: { __typename: "Runs", results: [] } } } });
      return route.fulfill({ json: { items: [] } });
    });
    await page.goto("/collections");
    const airport = page.locator("details.provider-row").filter({ hasText: "한국공항공사 주차" });
    const highway = page.locator("details.provider-row").filter({ hasText: "고속도로 소통" });
    const incident = page.locator("details.provider-row").filter({ hasText: "고속도로 돌발" });
    await expect(airport.locator("summary")).toContainText("공동 작업 부분 성공(격리 1건)");
    await expect(highway.locator("summary")).toContainText("부분 성공(격리 3건)");
    // 격리 배지는 실패(destructive)가 아니라 경고 톤이다.
    await expect(airport.locator("summary [data-tone]").first()).toHaveAttribute("data-tone", "warning");
    for (const row of [airport, highway, incident]) {
      await row.locator("summary").click();
      await expect(row).not.toContainText("수집 실패");
      await expect(row).not.toContainText("일부 실패");
    }
    await expect(highway).toContainText("무효 행 3건을 격리하고 나머지는 저장했습니다");
    await expect(incident).toContainText("부분 성공(격리 3건)");  // 공동 작업 상태
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}
