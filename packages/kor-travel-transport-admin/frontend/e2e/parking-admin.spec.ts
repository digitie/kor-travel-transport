import { expect, test, type Page } from "@playwright/test";

const observedAt = "2026-10-25T01:00:00Z";
const lots = [1, 2].map((id) => ({ id, source_lot_id: `GMP-${id}`, legacy_source_lot_id: null, name: `국내선 제${id}주차장`, terminal: "국내선", category: "short", is_active: true }));
const airports = [{ code: "GMP", name_ko: "김포국제공항", name_en: "Gimpo", source: "kac", parking_lots: lots }, { code: "CJU", name_ko: "제주국제공항", name_en: "Jeju", source: "kac", parking_lots: [{ ...lots[0], id: 3, name: "제주 여객 주차장" }] }];
const holidays = { generated_at: observedAt, start_date: "2026-10-01", end_date: "2026-10-31", source: "fixture", status: "success", error_message: null, sentence: "10/24 (토) 시험 공휴일입니다.", items: [{ local_date: "2026-10-24", name: "시험 공휴일", weekday: 5, weekday_name: "토" }] };
const collector = { scheduler_enabled: true, collect_interval_seconds: 300, manual_collect_enabled: false, manual_collect_min_interval_seconds: 300, client_mode: "live", enabled_sources: ["kac_parking"], data_go_kr_service_key_configured: true, supported_airport_codes: ["GMP", "CJU"], latest_snapshot_observed_at: observedAt, latest_snapshot_collected_at: observedAt, earliest_snapshot_observed_at: "2026-10-01T00:00:00Z", manual_collect_available_at: null, manual_collect_blocked: false, upstream_rate_limited: false, upstream_rate_limited_until: null, last_run: null, recent_runs: [], effective_collect_interval_seconds: 300, scheduler_safety_buffer_seconds: 0 };
function series(airport = "GMP", lot: number | null = null) {
  return { generated_at: observedAt, airport_code: airport, parking_lot_id: lot, days: 7, interval_minutes: 10, future_hours: 0, items: Array.from({ length: 7 }, (_, index) => Array.from({ length: 4 }, (_, point) => ({ bucket_at: new Date(Date.UTC(2026, 9, 18 + index, 15 + point * 6)).toISOString(), available_spaces: point === 2 ? 0 : 60 + index * 10 + point * 5, occupied_spaces: 50, total_spaces: 200, lot_observations: point === 2 ? 0 : 1 }))).flat() };
}
function bundle(airport: string, lot: number | null) {
  const hourly = Array.from({ length: 24 }, (_, hour) => ({ hour, average_available_spaces: hour === 3 ? null : 50 + hour, average_occupied_spaces: 100, average_congestion_ratio: 50, observations: hour === 3 ? 0 : 5 }));
  return { threshold_events: [{ parking_lot_id: 2, parking_lot_name: lots[1].name, threshold: 50, crossed_at: observedAt, direction: "down", previous_available_spaces: 55, current_available_spaces: 45 }, { parking_lot_id: 2, parking_lot_name: lots[1].name, threshold: 50, crossed_at: observedAt, direction: "up", previous_available_spaces: 45, current_available_spaces: 55 }], threshold_insights: { generated_at: observedAt, airport_code: airport, parking_lot_id: lot, days: 21, interval_minutes: 10, weekday_items: [{ weekday: 0, weekday_name: "월", threshold: 50, typical_minutes_of_day: 600, sample_count: 2 }], history_items: [{ threshold: 50, local_date: "2026-10-24", weekday: 5, weekday_name: "토", crossed_at: observedAt, minutes_of_day: 600, available_spaces: 45 }] }, weekday_hour_patterns: Array.from({ length: 7 }, (_, weekday) => ({ weekday, weekday_name: ["월", "화", "수", "목", "금", "토", "일"][weekday], hourly_buckets: hourly })), holiday_patterns: { generated_at: observedAt, airport_code: airport, parking_lot_id: lot, source: "fixture", status: "success", error_message: null, items: [{ local_date: "2026-10-24", name: "시험 공휴일", weekday: 5, weekday_name: "토", hourly_buckets: hourly }] }, time_series: series(airport, lot) };
}
type FixtureState = { bootstrapError?: boolean; catalogEmpty?: boolean; empty?: boolean; analyticsError?: boolean; historyError?: boolean; available?: number; marker?: string; feeMode?: "success" | "unsupported" | "error" };
async function fixture(page: Page, state: FixtureState = {}) {
  const requests: string[] = []; const fees: unknown[] = []; const historyQueries: string[] = [];
  await page.context().addCookies([{ name: "kor_travel_transport_admin_session", value: "isolated-parking-e2e", url: process.env.E2E_BASE_URL ?? "http://127.0.0.1:12305", httpOnly: true, sameSite: "Strict" }]);
  await page.route("**/api/**", (route) => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname.replace(/^\/api\/(?:transport\/|backend\/v1\/)/, ""); requests.push(path);
    const airport = url.searchParams.get("airport_code") ?? "GMP", lot = Number(url.searchParams.get("parking_lot_id")) || null;
    const items = airports.flatMap((airport) => airport.parking_lots.map((lot) => ({ airport_code: airport.code, airport_name: airport.name_ko, parking_lot_id: lot.id, parking_lot_name: lot.name, terminal: lot.terminal, category: lot.category, observed_at: observedAt, collected_at: observedAt, occupied_spaces: 100, total_spaces: 200, available_spaces: state.available ?? 100, congestion_label: null, congestion_ratio: 50, status_level: "stable" })));
    if (path === "transport/features/places") return route.fulfill({ json: { items: airports.map((airport, index) => ({ id: index + 10, kind: "airport", provider_id: airport.code, source: "kac", name: airport.name_ko, longitude: 126.8, latitude: 37.5, line_names: [], prices: [], facilities: [], updated_at: observedAt })) } });
    if (path === "parking/current") return route.fulfill({ json: { generated_at: observedAt, items: items.filter((item) => item.airport_code === airport) } });
    if (path === "parking/outlook") return route.fulfill({ json: { generated_at: observedAt, weekday: 6, hour: 10, items: [] } });
    if (path === "dashboard/bootstrap") return state.bootstrapError ? route.fulfill({ status: 503, json: { detail: "공항 조회 시험 오류" } }) : route.fulfill({ json: { airports: state.catalogEmpty ? [] : airports, current: { generated_at: observedAt, items: state.empty ? [] : items }, collector: { ...collector, latest_snapshot_collected_at: state.marker ?? observedAt }, holidays } });
    if (path === "admin/collector-status") return route.fulfill({ json: { ...collector, latest_snapshot_collected_at: state.marker ?? observedAt } });
    if (path === "dashboard/analytics") return state.analyticsError ? route.fulfill({ status: 503, json: { detail: "분석 조회 시험 오류" } }) : route.fulfill({ json: state.empty ? { ...bundle(airport, lot), threshold_events: [], threshold_insights: { ...bundle(airport, lot).threshold_insights, weekday_items: [], history_items: [] }, weekday_hour_patterns: [], holiday_patterns: { ...bundle(airport, lot).holiday_patterns, items: [] }, time_series: { ...series(airport, lot), items: [] } } : bundle(airport, lot) });
    if (path === "parking/analytics/timeseries") { historyQueries.push(url.search); return state.historyError ? route.fulfill({ status: 503, json: { detail: "과거 조회 시험 오류" } }) : route.fulfill({ json: { ...series(airport, lot), ...(state.empty ? { items: [] } : {}), ...(url.searchParams.has("start_date") ? { start_date: url.searchParams.get("start_date"), end_date: url.searchParams.get("end_date"), days: null } : {}), interval_minutes: Number(url.searchParams.get("interval_minutes")) || 10 } }); }
    if (path === "flights/status") return route.fulfill({ json: { generated_at: observedAt, airport_code: airport, local_date: "2026-10-25", source: "fixture", status: "success", error_message: null, items: ["departure", "arrival"].map((direction, index) => ({ airport_code: airport, direction, flight_number: index ? "OZ1002" : "KE1001", airline: "시험 항공", scheduled_at: observedAt, estimated_at: null, marker_at: observedAt, origin_airport: "김포", destination_airport: "제주", status: "예정", line_type: "국내" })) } });
    if (path === "fees/calculate") { fees.push(request.postDataJSON()); if (state.feeMode === "error") return route.fulfill({ status: 503, json: { detail: "요금 조회 시험 오류" } }); if (state.feeMode === "unsupported") return route.fulfill({ json: { supported: false, airport_code: "GMP", vehicle_size: "small", total_fee: null, currency: "KRW", message: "현재 주차장의 요금 계산을 지원하지 않습니다.", breakdown: [] } }); return route.fulfill({ json: { supported: true, airport_code: "GMP", vehicle_size: "small", total_fee: 12000, currency: "KRW", message: null, breakdown: [{ date: "2026-10-25", day_type: "holiday", duration_minutes: 360, applied_fee: 12000 }] } }); }
    return route.fulfill({ status: 404, json: { detail: "fixture가 정의되지 않은 경로" } });
  });
  return { requests, fees, historyQueries };
}
test.beforeEach(() => { test.skip(process.env.E2E_PARKING_ADMIN !== "true", "격리 주차장 fixture 실행"); });

for (const width of [320, 375, 414, 768, 1440]) test(`주차장 네 뷰·분석 네 탭·상태 보존 ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  const { requests, fees } = await fixture(page);
  await page.goto("/parking?airport=GMP&lot=2");
  const parking = page.getByRole("region", { name: "공항 주차장", exact: true });
  await expect(parking).toHaveAttribute("aria-busy", "false");
  await expect(page.getByLabel("세부 주차장", { exact: true })).toHaveValue("2");
  await expect(parking).toContainText("100대");
  const coarse = await page.evaluate(() => matchMedia("(pointer: coarse)").matches);
  if (test.info().project.name.endsWith("-touch")) expect(coarse).toBe(true);
  if (coarse) for (const control of [page.getByLabel("공항 선택", { exact: true }), page.getByLabel("세부 주차장", { exact: true }), parking.getByRole("button", { name: "새로고침", exact: true }), parking.getByRole("tab", { name: "분석", exact: true })]) expect((await control.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  expect((await parking.locator(".detail-ribbon").boundingBox())!.height).toBeLessThan(190);
  if (width < 992) expect((await page.locator(".rail").boundingBox())!.height).toBeLessThan(120);
  expect(requests.filter((path) => !["dashboard/bootstrap", "admin/collector-status"].includes(path))).toEqual([]);
  if (width >= 1024) { await expect(page.getByTestId("desktop-lot-table")).toBeVisible(); await expect(page.getByTestId("mobile-lot-grid")).not.toBeVisible(); } else { await expect(page.getByTestId("mobile-lot-grid")).toBeVisible(); await expect(page.getByTestId("desktop-lot-table")).not.toBeVisible(); }
  await page.screenshot({ path: `test-results/parking-${width}-${test.info().project.name}-current.png`, fullPage: true });
  await expect(page.getByRole("link", { name: "선택 공항의 항공편·지도" })).toHaveAttribute("href", "/flights?airport=GMP&lot=2");
  const current = parking.getByRole("tab", { name: "현황", exact: true }), analytics = parking.getByRole("tab", { name: "분석", exact: true }), history = parking.getByRole("tab", { name: "과거조회", exact: true }), fee = parking.getByRole("tab", { name: "요금계산", exact: true });
  await analytics.click(); await expect(page.getByTestId("weekday-hour-heatmap")).toBeVisible();
  await expect(page.getByTestId("weekday-hour-cell-0-3")).toHaveText("-");
  await page.screenshot({ path: `test-results/parking-${width}-${test.info().project.name}-weekday.png`, fullPage: true });
  await parking.getByRole("tab", { name: "공휴일 패턴" }).click(); await expect(page.getByTestId("holiday-pattern-heatmap")).toBeVisible();
  await parking.getByRole("tab", { name: "임계치", exact: true }).click(); await expect(page.getByTestId("threshold-weekday-grid")).toBeVisible(); await expect(page.getByTestId("threshold-history-scroll")).toBeVisible(); await expect(page.getByTestId("threshold-events-scroll")).toContainText("미만 진입"); await expect(page.getByTestId("threshold-events-scroll")).toContainText("이상 회복");
  await parking.getByRole("tab", { name: "일별 흐름" }).click(); await expect(page.getByTestId("daily-flight-overlay-chart")).toBeVisible();
  await expect(page.getByTestId("daily-overlay-line")).toHaveCount(7);
  expect(await page.getByTestId("daily-overlay-line").first().evaluate((node) => getComputedStyle(node).stroke)).not.toBe("none");
  await page.screenshot({ path: `test-results/parking-${width}-${test.info().project.name}-daily.png`, fullPage: true });
  const dateToggle = page.getByTestId("daily-date-toggles").getByRole("button").first(); await dateToggle.click(); await expect(dateToggle).toHaveAttribute("aria-pressed", "false");
  await page.getByTestId("daily-wide-axis-toggle").check(); await page.getByLabel("출발편", { exact: true }).uncheck();
  await expect(page.getByTestId("daily-flight-marker-button")).toHaveCount(1);
  await page.getByTestId("daily-flight-marker-button").focus(); await page.keyboard.press("Enter"); await expect(page.getByTestId("daily-flight-marker-button")).toHaveAttribute("aria-pressed", "true");
  await history.click(); await expect(page.getByTestId("history-chart")).toBeVisible(); await expect(parking.locator(".history-chart .daily-flight-marker")).toHaveCount(0);
  await expect(page.getByTestId("history-chart").locator(".history-line")).not.toHaveCount(0);
  expect(await page.getByTestId("history-chart").locator(".history-line").first().evaluate((node) => getComputedStyle(node).stroke)).not.toBe("none");
  await expect(page.getByRole("button", { name: "날짜 범위 선택" })).toBeVisible();
  await page.screenshot({ path: `test-results/parking-${width}-${test.info().project.name}-history.png`, fullPage: true });
  await fee.click(); await expect(page.getByRole("combobox", { name: "세부 주차장", exact: true })).toHaveValue("2"); await expect(page.getByRole("combobox", { name: "공항", exact: true })).toHaveCount(0); await expect(page.getByRole("combobox", { name: "주차장", exact: true })).toHaveCount(0);
  await page.getByLabel("입차 시각", { exact: true }).fill("2026-10-25T09:00"); await page.getByLabel("출차 시각", { exact: true }).fill("2026-10-25T15:00");
  await page.getByRole("button", { name: "요금 계산", exact: true }).click(); await expect(parking).toContainText("12,000");
  expect(fees).toEqual([{ airport_code: "GMP", parking_lot_id: 2, vehicle_size: "small", entry_at: "2026-10-25T00:00:00.000Z", exit_at: "2026-10-25T06:00:00.000Z" }]);
  await current.click(); await expect(parking.locator('[role="tabpanel"]:visible')).toHaveCount(1);
  await analytics.click(); await expect(parking.getByRole("tab", { name: "일별 흐름" })).toHaveAttribute("aria-selected", "true"); await expect(dateToggle).toHaveAttribute("aria-pressed", "false"); await expect(page.getByTestId("daily-wide-axis-toggle")).toBeChecked(); await expect(page.getByLabel("출발편", { exact: true })).not.toBeChecked();
  await fee.click(); await expect(page.getByLabel("입차 시각", { exact: true })).toHaveValue("2026-10-25T09:00"); await expect(parking).toContainText("12,000");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/parking-${width}-${test.info().project.name}-fees.png`, fullPage: true });
});

for (const width of [375, 1440]) test(`실패·빈 자료·실제 0과 요금 미지원 구분 ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  const state: FixtureState = { bootstrapError: true };
  await fixture(page, state); await page.goto("/parking");
  const parking = page.getByRole("region", { name: "공항 주차장", exact: true });
  await expect(parking.getByRole("alert")).toContainText("공항 조회 시험 오류");
  await expect(parking.locator(".detail-card strong").first()).toHaveText("—");
  for (const name of ["분석", "과거조회"]) {
    await parking.getByRole("tab", { name, exact: true }).click();
    await expect(parking.getByRole("alert")).toContainText("공항 조회 시험 오류");
    await expect(parking.getByText("분석 자료를 불러오는 중입니다.")).toHaveCount(0);
    await expect(parking.getByText("데이터를 불러오는 중입니다.", { exact: true })).toHaveCount(0);
  }
  await parking.getByRole("tab", { name: "현황", exact: true }).click();
  state.bootstrapError = false; state.available = 0;
  await parking.getByRole("button", { name: "새로고침", exact: true }).click();
  await expect(parking.locator(".detail-card strong").first()).toHaveText("0대");
  state.empty = true; await parking.getByRole("button", { name: "새로고침", exact: true }).click();
  await expect(parking.getByText("조건에 맞는 주차장이 없습니다.")).toBeVisible();
  await expect(parking.locator(".detail-card strong").first()).toHaveText("—");
  state.analyticsError = true; await parking.getByRole("tab", { name: "분석", exact: true }).click();
  await expect(parking.getByRole("alert")).toContainText("분석 조회 시험 오류");
  state.analyticsError = false; await parking.getByRole("button", { name: "새로고침", exact: true }).click();
  await expect(parking.getByText("표시할 요일별 시간대 데이터가 없습니다.")).toBeVisible();
  state.historyError = true; await parking.getByRole("tab", { name: "과거조회", exact: true }).click();
  await expect(parking.getByRole("alert")).toContainText("과거 조회 시험 오류");
  state.historyError = false; await parking.getByRole("button", { name: "새로고침", exact: true }).click();
  await expect(parking.getByText("표시할 과거 시계열 데이터가 없습니다.")).toBeVisible();
  state.feeMode = "unsupported"; await parking.getByRole("tab", { name: "요금계산", exact: true }).click();
  await parking.getByRole("button", { name: "요금 계산", exact: true }).click();
  await expect(parking.getByText("현재 주차장의 요금 계산을 지원하지 않습니다.")).toBeVisible();
  state.feeMode = "error"; await parking.getByRole("button", { name: "요금 계산", exact: true }).click();
  await expect(parking.getByRole("alert")).toContainText("요금 조회 시험 오류");
  await expect(parking.getByText("현재 주차장의 요금 계산을 지원하지 않습니다.")).toHaveCount(0);
  state.catalogEmpty = true; await page.reload();
  for (const name of ["분석", "과거조회", "요금계산"]) {
    await parking.getByRole("tab", { name, exact: true }).click();
    await expect(parking.getByText("저장된 공항이 없습니다.").filter({ visible: true })).toBeVisible();
    await expect(parking.getByText("분석 자료를 불러오는 중입니다.")).toHaveCount(0);
  }
});

test("375px 달력 Portal·범위·자동 집계 간격·Escape·200% 글자", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-10-25T02:00:00Z") });
  await page.setViewportSize({ width: 375, height: 900 });
  const { historyQueries } = await fixture(page); await page.goto("/parking?airport=GMP&view=history");
  const parking = page.getByRole("region", { name: "공항 주차장", exact: true });
  const picker = parking.locator('[data-slot="popover-trigger"]');
  await expect(page.getByTestId("history-chart")).toBeVisible();
  await page.addStyleTag({ content: "html { font-size: 200% !important; }" });
  await picker.click();
  const calendar = page.locator('[data-slot="calendar"]'); await expect(calendar).toBeVisible();
  expect(await calendar.evaluate((node) => { const r = node.getBoundingClientRect(); return r.x >= 0 && r.right <= window.innerWidth; })).toBe(true);
  await expect(calendar.getByRole("button", { name: /26일/ })).toBeDisabled();
  await calendar.getByRole("button", { name: /20일/ }).click();
  await calendar.getByRole("button", { name: /23일/ }).click();
  await expect.poll(() => historyQueries.some((query) => query.includes("start_date=2026-10-20") && query.includes("end_date=2026-10-23") && query.includes("interval_minutes=30") && query.includes("future_hours=0"))).toBe(true);
  await page.keyboard.press("Escape"); await expect(calendar).not.toBeVisible(); await expect(picker).toBeFocused();
  await parking.getByRole("tab", { name: "요금계산", exact: true }).click(); await parking.getByRole("tab", { name: "과거조회", exact: true }).click();
  await expect(parking.getByRole("button", { name: "2026-10-20 ~ 2026-10-23", exact: true })).toBeVisible();
  await parking.getByRole("button", { name: "최근 7일 보기", exact: true }).click(); await expect(picker).toBeFocused();
  for (const [from, to, interval] of [[20, 21, 10], [1, 20, 60]]) {
    await picker.click();
    await calendar.getByRole("button", { name: new RegExp(`10월 ${from}일`) }).click();
    await calendar.getByRole("button", { name: new RegExp(`10월 ${to}일`) }).click();
    await expect.poll(() => historyQueries.some((query) => query.includes(`start_date=2026-10-${String(from).padStart(2, "0")}`) && query.includes(`end_date=2026-10-${to}`) && query.includes(`interval_minutes=${interval}`) && query.includes("future_hours=0"))).toBe(true);
    await page.keyboard.press("Escape");
    await parking.getByRole("button", { name: "최근 7일 보기", exact: true }).click(); await expect(picker).toBeFocused();
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

for (const width of [375, 1440]) test(`공항·주차장 선택으로 항공편과 왕복하고 운영·요금 안내를 연다 ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 }); await fixture(page);
  await page.goto("/parking?airport=CJU&lot=3");
  await expect(page.getByLabel("공항 선택", { exact: true })).toHaveValue("CJU");
  await page.getByRole("button", { name: "주차 자료 갱신 안내", exact: true }).click();
  await expect(page.getByRole("link", { name: "수집 상태·이력", exact: true })).toHaveAttribute("href", "/collections");
  await expect(page.getByRole("link", { name: "공항 주차·요금 수집 실행 ↗", exact: true })).toHaveAttribute("href", /airport_collection_job\/runs/);
  await page.keyboard.press("Escape"); await expect(page.getByRole("button", { name: "주차 자료 갱신 안내", exact: true })).toBeFocused();
  await page.getByRole("link", { name: "선택 공항의 항공편·지도", exact: true }).click();
  await expect(page).toHaveURL(/\/flights\?airport=CJU&lot=3$/);
  await expect(page.getByRole("link", { name: "공항 주차장 전체 보기", exact: true })).toHaveAttribute("href", "/parking?airport=CJU&lot=3");
  await page.getByRole("link", { name: "공항 주차장 전체 보기", exact: true }).click();
  await expect(page.getByLabel("공항 선택", { exact: true })).toHaveValue("CJU"); await expect(page.getByLabel("세부 주차장", { exact: true })).toHaveValue("3");
  await page.getByRole("tab", { name: "요금계산", exact: true }).click();
  const info = page.getByRole("button", { name: "주차요금 기준 안내", exact: true }); await info.focus(); await info.press("Enter");
  await expect(page.getByText("요금의 ‘휴일’은 현재 토·일요일 기준이며 공휴일과 할인 조건은 별도로 계산하지 않습니다.", { exact: false })).toBeVisible();
  await page.keyboard.press("Escape"); await expect(info).toBeFocused();
});

test("15초 상태 확인은 변경 시에만 갱신하고 숨은 분석 탭을 조회하지 않는다", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-10-25T02:00:00Z") });
  const state: FixtureState = {}; const { requests } = await fixture(page, state);
  await page.goto("/parking?airport=GMP");
  const parking = page.getByRole("region", { name: "공항 주차장", exact: true });
  await expect(parking).toHaveAttribute("aria-busy", "false");
  const bootstraps = requests.filter((path) => path === "dashboard/bootstrap").length;
  await page.clock.fastForward(15_100); await expect.poll(() => requests.filter((path) => path === "admin/collector-status").length).toBeGreaterThan(0);
  expect(requests.filter((path) => path === "dashboard/bootstrap")).toHaveLength(bootstraps); expect(requests).not.toContain("dashboard/analytics");
  state.marker = "2026-10-25T02:05:00Z"; await page.clock.fastForward(15_100);
  await expect.poll(() => requests.filter((path) => path === "dashboard/bootstrap").length).toBe(bootstraps + 1); expect(requests).not.toContain("dashboard/analytics");
  await parking.getByRole("tab", { name: "분석", exact: true }).click(); await expect(page.getByTestId("weekday-hour-heatmap")).toBeVisible();
  const bundles = requests.filter((path) => path === "dashboard/analytics").length;
  await parking.getByRole("tab", { name: "현황", exact: true }).click(); state.marker = "2026-10-25T02:10:00Z"; await page.clock.fastForward(15_100);
  await expect.poll(() => requests.filter((path) => path === "dashboard/bootstrap").length).toBe(bootstraps + 2); expect(requests.filter((path) => path === "dashboard/analytics")).toHaveLength(bundles);
});

for (const width of [375, 1440]) test(`공개 parking-radar 네 경로 회귀 ${width}px`, async ({ page }) => {
  test.skip(!process.env.E2E_PUBLIC_PARKING_BASE, "별도 공개 앱 로컬 미리보기 필요");
  await page.setViewportSize({ width, height: 900 }); await fixture(page);
  const base = process.env.E2E_PUBLIC_PARKING_BASE!;
  await page.goto(`${base}/`); await expect(page.getByText("현재 잔여 주차면", { exact: true })).toBeVisible();
  await page.goto(`${base}/analytics`); await expect(page.getByTestId("weekday-hour-heatmap")).toBeVisible();
  await page.getByRole("tab", { name: "임계치", exact: true }).click(); await expect(page.getByTestId("threshold-weekday-grid")).toBeVisible(); expect((await page.getByTestId("threshold-weekday-grid").boundingBox())!.width).toBeGreaterThan(200);
  await page.goto(`${base}/history`); await expect(page.getByTestId("history-chart")).toBeVisible();
  await page.goto(`${base}/fees`); await expect(page.getByRole("combobox", { name: "주차장", exact: true })).toBeVisible(); await page.getByRole("combobox", { name: "주차장", exact: true }).selectOption("2"); await page.getByRole("button", { name: "요금 계산", exact: true }).click(); await expect(page.locator(".quote-total")).toContainText("12,000");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
