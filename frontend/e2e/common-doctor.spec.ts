import { expect, test, type Page } from "@playwright/test";

async function storedData(page: Page) {
  const now = new Date().toISOString();
  const collector = { scheduler_enabled: false, collect_interval_seconds: 300, manual_collect_enabled: false, manual_collect_min_interval_seconds: 300, client_mode: "sample", enabled_sources: [], data_go_kr_service_key_configured: false, supported_airport_codes: ["GMP"], latest_snapshot_observed_at: now, latest_snapshot_collected_at: now, earliest_snapshot_observed_at: "2026-11-01T00:00:00Z", manual_collect_available_at: null, manual_collect_blocked: false, upstream_rate_limited: false, upstream_rate_limited_until: null, last_run: null, recent_runs: [], effective_collect_interval_seconds: 180, scheduler_safety_buffer_seconds: 120 };
  const bootstrap = {
    airports: [{ code: "GMP", name_ko: "김포 검증 공항", name_en: "Gimpo", source: "kac", parking_lots: [{ id: 1, source_lot_id: "fixture-1", legacy_source_lot_id: null, name: "국내선 검증 주차장", terminal: "국내선", category: "short", is_active: true }] }],
    current: { generated_at: now, items: [{ airport_code: "GMP", airport_name: "김포 검증 공항", parking_lot_id: 1, parking_lot_name: "국내선 검증 주차장", terminal: "국내선", category: "short", observed_at: now, collected_at: now, occupied_spaces: 20, total_spaces: 100, available_spaces: 80, congestion_label: "여유", congestion_ratio: 20, status_level: "stable" }] },
    collector,
    holidays: { generated_at: now, start_date: "2026-11-01", end_date: "2026-11-30", source: "fixture", status: "success", error_message: null, sentence: "", items: [] },
  };
  const requests: URL[] = [];
  await page.route("**/api/backend/**", async route => {
    const url = new URL(route.request().url()); requests.push(url);
    const body = url.pathname.endsWith("dashboard/bootstrap") ? bootstrap
      : url.pathname.endsWith("admin/collector-status") ? collector
        : url.pathname.endsWith("timeseries") ? { generated_at: now, airport_code: "GMP", parking_lot_id: null, days: 7, interval_minutes: 10, future_hours: 0, items: [
          { bucket_at: new Date(Date.now() - 30 * 60_000).toISOString(), available_spaces: 30, occupied_spaces: 70, total_spaces: 100, lot_observations: 1 },
          { bucket_at: now, available_spaces: 80, occupied_spaces: 20, total_spaces: 100, lot_observations: 1 },
        ] }
          : url.pathname.endsWith("fees/calculate") ? { supported: true, airport_code: "GMP", parking_lot_id: 1, vehicle_size: "small", total_fee: 4000, currency: "KRW", message: null, breakdown: [] }
            : { items: [], status: "success", error_message: null };
    await route.fulfill({ json: body });
  });
  return requests;
}

for (const width of [375, 1440]) {
  test(`공개 현재 표·RHF 요금·입력 변경 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); await storedData(page);
    await page.goto("/");
    await expect(page.getByRole("main")).toContainText("국내선 검증 주차장");
    await expect(page.getByTestId(width < 1024 ? "mobile-lot-grid" : "desktop-lot-table")).toBeVisible();
    await page.goto("/fees");
    const entry = page.getByLabel("입차 시각", { exact: true }), exit = page.getByLabel("출차 시각", { exact: true });
    await entry.fill("2026-11-11T10:00"); await exit.fill("2026-11-11T08:00");
    await page.getByRole("button", { name: "요금 계산", exact: true }).click();
    await expect(page.getByText("출차 시각은 입차 시각보다 늦어야 합니다.")).toBeVisible();
    await exit.fill("2026-11-11T12:00"); await page.getByRole("button", { name: "요금 계산", exact: true }).click();
    await expect(page.getByText("₩4,000", { exact: true })).toBeVisible();
    await page.getByRole("combobox", { name: "차량 크기", exact: true }).selectOption("large");
    await expect(page.getByText("₩4,000", { exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(await page.locator("body").evaluate(node => getComputedStyle(node).fontFamily)).toContain("Pretendard");
    await page.screenshot({ path: `test-results/common-public-fees-${width}.png`, fullPage: true });
  });

  test(`공개 과거 차트·날짜 범위·Escape 초점 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); const requests = await storedData(page);
    await page.goto("/history");
    await expect(page.getByTestId("history-chart")).toBeVisible();
    const picker = page.getByRole("button", { name: "날짜 범위 선택", exact: true });
    await picker.click(); await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape"); await expect(page.getByRole("dialog")).toHaveCount(0); await expect(picker).toBeFocused();
    await picker.click();
    const days = page.getByRole("dialog").locator('button[data-day]:not([disabled])');
    const first = await days.first().getAttribute("data-day"), last = await days.last().getAttribute("data-day");
    await days.first().click(); await page.getByRole("dialog").locator(`button[data-day="${last}"]`).click();
    await expect.poll(() => requests.some(url => url.searchParams.get("start_date") === first && url.searchParams.get("end_date") === last)).toBe(true);
    if (await page.getByRole("dialog").count()) await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "최근 7일 보기", exact: true }).click(); await expect(picker).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/common-public-history-${width}.png`, fullPage: true });
  });
}
