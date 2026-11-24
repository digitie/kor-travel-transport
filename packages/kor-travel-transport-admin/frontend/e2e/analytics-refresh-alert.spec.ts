import { expect, test, type Page } from "@playwright/test";

// ANALYTICS-REFRESH-ALERT-20261124: 공항 통계 사전집계 갱신이 밀리면 운영 요약(홈)에 경보와 운영 상태 행으로 보인다.
// provider 응답은 route로 고정한다(실제 backend 판정은 backend 시험이 맡는다).
const analytics = (status: string, alerting: boolean, pendingSeconds: number | null) => ({
  status, alerting, generated_at: "2026-11-24T05:00:00Z",
  pending_since: pendingSeconds === null ? null : "2026-11-24T05:05:00Z", pending_seconds: pendingSeconds,
  warn_after_seconds: 900, fallback_after_seconds: 2400,
});

async function openHome(page: Page, viewport: { width: number; height: number }, cache: unknown) {
  await page.setViewportSize(viewport);
  await page.context().addCookies([{ name: "kor_travel_transport_admin_session", value: "analytics-refresh-e2e",
    url: process.env.E2E_BASE_URL ?? "http://127.0.0.1:12351", httpOnly: true, sameSite: "Strict" }]);
  await page.route("**://*.vworld.kr/**", (route) => route.abort());
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/transport/providers")) return route.fulfill({ json: {
      generated_at: "2026-11-24T05:30:00Z", ferry_window_start: "2026-11-24", ferry_window_end: "2026-12-03",
      ferry_expected_snapshots: 0, ferry_stored_snapshots: 0, items: [], airport_analytics_cache: cache } });
    if (url.pathname === "/api/dagster/graphql") return route.fulfill({ json: { data: {
      activeRuns: { __typename: "Runs", results: [] }, repositoryOrError: { __typename: "Repository", schedules: [] },
      runsOrError: { __typename: "Runs", results: [] } } } });
    return route.fulfill({ json: { items: [] } });
  });
  await page.goto("/");
  await expect(page.getByText("운영 상태", { exact: true })).toBeVisible({ timeout: 20_000 });
}

for (const viewport of [{ width: 390, height: 844 }, { width: 1440, height: 900 }]) {
  test(`사전집계 갱신 지연은 경보로, 정상은 운영 상태 행으로만 보인다 ${viewport.width}px`, async ({ page }) => {
    await openHome(page, viewport, analytics("delayed", true, 1500));
    const alert = page.getByTestId("analytics-refresh-alert");
    await expect(alert).toContainText("공항 통계 사전집계 갱신 지연");
    await expect(alert).toContainText("25분째");
    await expect(alert.getByRole("link", { name: "공항 수집 실행" })).toHaveAttribute("href", /airport_collection_job/);
    const row = page.getByTestId("analytics-refresh-status");
    await expect(row).toContainText("갱신 지연");
    await expect(row.locator("[data-tone]").first()).toHaveAttribute("data-tone", "warning");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

    await openHome(page, viewport, analytics("stale", true, 2700));
    await expect(alert).toContainText("원본 계산 중");
    await expect(alert).toHaveAttribute("role", "alert");
    await expect(row.locator("[data-tone]").first()).toHaveAttribute("data-tone", "destructive");

    await openHome(page, viewport, analytics("ok", false, null));
    await expect(row).toContainText("정상");
    await expect(row).toContainText("생성");
    await expect(alert).toHaveCount(0);

    // 이전 backend(필드 없음)에서는 행 값이 비고 경보도 없다.
    await openHome(page, viewport, undefined);
    await expect(page.getByText("공항 통계 사전집계")).toBeVisible();
    await expect(row).toHaveCount(0);
    await expect(alert).toHaveCount(0);
  });
}
