import { expect, test, type Page } from "@playwright/test";

const password = process.env.E2E_TRANSPORT_UI_PASSWORD;
test.beforeEach(async ({ page }) => {
  test.skip(!password, "E2E_TRANSPORT_UI_PASSWORD가 필요합니다.");
  await page.goto("/login");
  await page.getByLabel("아이디").fill(process.env.E2E_TRANSPORT_UI_USER ?? "admin");
  await page.getByLabel("비밀번호").fill(password!);
  await page.getByRole("button", { name: "로그인" }).click();
  await expect(page).toHaveURL(/\/$/);
});

const screens = [["/bus/express", "고속버스"], ["/bus/intercity", "시외버스"], ["/flights", "비행·공항"], ["/highways", "고속도로"], ["/collections", "수집 상태"]] as const;
for (const width of [320, 375, 414, 768, 1440]) {
  for (const [path, title] of screens) test(`${path} ${width}px 내비게이션·레이아웃`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(path);
    await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await expect(page.getByRole("button", { name: "로그아웃" })).toBeVisible();
    if (width === 320 || width === 1440) await page.screenshot({ path: `test-results/journey-${path.replaceAll("/", "-")}-${width}.png`, fullPage: true });
  });
}

async function mockBus(page: Page) {
  await page.route("**/transport/bus/terminals?**", (route) => route.fulfill({ json: { items: [{ terminal_id: "A", terminal_name: "서울", city_name: "서울" }, { terminal_id: "B", terminal_name: "부산", city_name: "부산" }] } }));
}
test("버스는 명시 조회만 호출하고 429 이후 반복 버튼을 눌러도 제공자를 호출하지 않는다", async ({ page }) => {
  await mockBus(page);
  let calls = 0;
  await page.route("**/transport/bus/timetable?**", (route) => { calls++; return route.fulfill({ status: 429, headers: { "retry-after": "30" }, json: { detail: "rate limited" } }); });
  await page.goto("/bus/express");
  const searches = page.locator(".multi-search");
  await searches.nth(0).getByRole("checkbox", { name: /서울/ }).check();
  await searches.nth(1).getByRole("checkbox", { name: /부산/ }).check();
  expect(calls).toBe(0);
  await page.getByRole("button", { name: "운행편 조회", exact: true }).click();
  await expect(page.locator("p[role=alert]")).toContainText("제공기관 호출 보호");
  await page.getByRole("button", { name: "운행편 조회", exact: true }).click();
  await expect(page.locator("p[role=alert]")).toContainText("다음 조회 가능 시각");
  expect(calls).toBe(1);
});

test("버스 결과는 시각·등급·요금·부분 결과를 읽기 쉽게 표시하고 선택 변경 시 지운다", async ({ page }) => {
  await mockBus(page);
  await page.route("**/transport/bus/timetable?**", (route) => route.fulfill({ json: { service_date: "2026-09-27", fetched_at: new Date().toISOString(), total: 120, truncated: true, items: [{ departure_planned_time: "202609270930", arrival_planned_time: "202609271400", grade_name: "우등", adult_fare: 35000 }] } }));
  await page.goto("/bus/intercity");
  await expect(page.getByLabel("출발일")).toBeDisabled();
  const searches = page.locator(".multi-search");
  await searches.nth(0).getByRole("checkbox", { name: /서울/ }).check();
  await searches.nth(1).getByRole("checkbox", { name: /부산/ }).check();
  await page.getByRole("button", { name: "운행편 조회", exact: true }).click();
  await expect(page.getByText("09:30", { exact: true })).toBeVisible();
  await expect(page.getByText("35,000원", { exact: true })).toBeVisible();
  await expect(page.getByText("전체 120편 중 일부 결과", { exact: false })).toBeVisible();
  await searches.nth(0).getByRole("checkbox", { name: /부산/ }).check();
  await expect(page.getByText("35,000원", { exact: true })).not.toBeVisible();
  await expect(page.getByRole("button", { name: "운행편 조회", exact: true })).toBeDisabled();
});

test("유가 지도는 모든 유종 상세·출처 필터·목록 대체 보기를 제공한다", async ({ page }) => {
  await page.route("**/transport/features/places?**", (route) => {
    const fuel = new URL(route.request().url()).searchParams.get("kind") === "fuel_station";
    return route.fulfill({ json: { total: fuel ? 1 : 0, truncated: false, items: fuel ? [{ id: 1, kind: "fuel_station", source: "opinet_browser", name: "검증 주유소 고속도로 복합휴게소 셀프 충전소 긴 실제 장소명", brand_name: "SK에너지", longitude: 127, latitude: 37, line_names: [], facilities: ["셀프", "세차"], updated_at: "2026-09-27T00:00:00Z", prices: [{ product_code: "B027", price: 1710, observed_at: "2026-09-27T00:00:00Z" }, { product_code: "D047", price: 1610, observed_at: "2026-09-27T00:00:00Z" }] }] : [] } });
  });
  await page.goto("/map");
  await page.getByRole("button", { name: "목록", exact: true }).click();
  await page.getByRole("button", { name: /검증 주유소/ }).click();
  const detail = page.locator(".transport-map-detail");
  await expect(detail.getByText("1,710원/L", { exact: true })).toBeVisible();
  await expect(detail.getByText("1,610원/L", { exact: true })).toBeVisible();
  await expect(detail.getByText("편의시설 · 셀프 · 세차", { exact: true })).toBeVisible();
  await expect(page.getByLabel("선택 장소 상세")).toBeFocused();
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect.poll(() => detail.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    await expect(detail.getByText("1,710원/L", { exact: true })).toBeVisible();
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({ path: "test-results/journey-fuel-detail.png", fullPage: true });
  await page.getByLabel("데이터 출처").selectOption("opinet_browser");
  await page.getByLabel("표시 유종").selectOption("K015");
  await expect(page.getByText("표시할 장소가 없습니다.", { exact: false })).toBeVisible();
});

test("수집 화면은 Dagster 실패를 숨기지 않고 provider 목록을 계속 표시한다", async ({ page }) => {
  await page.route("**/api/dagster/graphql", (route) => route.fulfill({ status: 502, body: "unavailable" }));
  await page.route("**/transport/providers", (route) => route.fulfill({ json: { generated_at: new Date().toISOString(), ferry_window_start: "2026-09-27", ferry_window_end: "2026-10-06", ferry_expected_snapshots: 100, ferry_stored_snapshots: 10, items: [{ source: "opinet", name: "오피넷 주유소·유가", job_name: "fuel_collection_job", enabled: true, mode: "scheduled", status: "not_collected", interval_seconds: 28800, last_started_at: null, last_success_at: null, next_due_at: null, error_code: null }] } }));
  await page.goto("/collections");
  await expect(page.locator("p[role=alert]")).toContainText("Dagster 연결에 실패");
  await expect(page.getByText("수집 이력 없음", { exact: true })).toBeVisible();
  await page.getByText("오피넷 주유소·유가", { exact: true }).click();
  await expect(page.getByText("8시간", { exact: true })).toBeVisible();
});

test("지도는 상한 밖 출처와 공항 코드·영문명 서버 검색 결과를 보존한다", async ({ page }) => {
  const queries: string[] = [];
  await page.route("**/transport/features/places?**", (route) => {
    const params = new URL(route.request().url()).searchParams;
    queries.push(params.get("query") ?? "");
    const airport = params.get("kind") === "airport";
    return route.fulfill({ json: { total: airport ? 1 : 0, truncated: false, available_sources: ["hidden-source"], items: airport ? [{ id: 1, provider_id: "GMP", kind: "airport", source: "airport", name: "김포공항", subtitle: "Gimpo", line_names: [], longitude: 126.8, latitude: 37.5, prices: [], facilities: [], updated_at: new Date().toISOString() }] : [] } });
  });
  await page.goto("/map");
  await page.getByRole("button", { name: "목록", exact: true }).click();
  await expect(page.getByLabel("데이터 출처").locator('option[value="hidden-source"]')).toHaveCount(1);
  for (const query of ["GMP", "Gimpo"]) {
    await page.getByLabel("장소 검색").fill(query);
    await expect.poll(() => queries.includes(query)).toBe(true);
    await expect(page.getByRole("button", { name: /김포공항/ })).toBeVisible();
  }
});

for (const type of ["express", "intercity"]) test(`한국 자정 이후 ${type} 버스 날짜·운행 시각이 일치한다`, async ({ page }) => {
  await page.clock.install({ time: new Date("2026-09-27T14:59:55Z") });
  await mockBus(page);
  const dates: string[] = [];
  await page.route("**/transport/bus/timetable?**", (route) => {
    const date = new URL(route.request().url()).searchParams.get("date")!; dates.push(date);
    return route.fulfill({ json: { service_date: date, fetched_at: new Date().toISOString(), items: [{ departure_planned_time: date.replaceAll("-", "") + "0930", arrival_planned_time: date.replaceAll("-", "") + "1400", adult_fare: 35000 }] } });
  });
  await page.goto(`/bus/${type}`);
  const searches = page.locator(".multi-search");
  await searches.nth(0).getByRole("checkbox", { name: /서울/ }).check();
  await searches.nth(1).getByRole("checkbox", { name: /부산/ }).check();
  await page.getByRole("button", { name: "운행편 조회", exact: true }).click();
  await expect(page.getByText("09:30", { exact: true })).toBeVisible();
  await page.clock.runFor(31_000);
  await expect(page.getByLabel("출발일")).toHaveValue("2026-09-28");
  await expect(page.getByText("35,000원", { exact: true })).not.toBeVisible();
  await page.getByRole("button", { name: "운행편 조회", exact: true }).click();
  await expect.poll(() => dates.at(-1)).toBe("2026-09-28");
  await expect(page.getByText("09:30", { exact: true })).toBeVisible();
  await expect(page.getByText("익일 09:30", { exact: true })).not.toBeVisible();
});
