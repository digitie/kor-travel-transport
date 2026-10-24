import { expect, test, type Page } from "@playwright/test";

const password = process.env.E2E_TRANSPORT_UI_PASSWORD;
const now = () => new Date().toISOString();
const metro = { id: 71, kind: "rail_station", source: "kric_public_file", name: "구성", subtitle: "지티엑스에이운영", station_type: "도시/광역철도", line_names: ["GTX-A"], address: "경기도 용인시", phone: "031-000-0000", latitude: 37.3, longitude: 127.1, prices: [], facilities: ["엘리베이터"], updated_at: "2026-10-24T00:00:00Z" };
const airport = { ...metro, id: 1, kind: "airport", name: "김포공항", provider_id: "GMP", line_names: [], subtitle: null };

async function login(page: Page) {
  await page.route("**/transport/providers", (route) => route.fulfill({ json: { generated_at: now(), items: [{ source: "a", name: "정상 소스", mode: "scheduled", enabled: true, status: "success" }], kric_coverage: { station_count: 3, linked_station_count: 2, expected_snapshots: 9, stored_snapshots: 2, fresh_snapshots: 1 } } }));
  await page.route("**/api/dagster/graphql", (route) => route.fulfill({ json: { data: { repositoryOrError: { __typename: "Repository", schedules: [] }, runsOrError: { __typename: "Runs", results: [] }, activeRuns: { __typename: "Runs", results: [] } } } }));
  await page.goto("/login");
  await page.getByLabel("비밀번호").fill(password!);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
}

for (const width of [320, 375, 414, 768, 1440]) test(`운영 홈·노선 중심 도시철도·이후 시간표 ${width}px`, async ({ page }) => {
  test.setTimeout(90_000); test.skip(!password, "로그인 암호 필요");
  await page.setViewportSize({ width, height: 1000 });
  await login(page);
  await expect(page.getByRole("heading", { name: "운영 홈", exact: true })).toBeVisible();
  if (width === 375) {
    await page.getByRole("button", { name: "주요 메뉴 열기" }).click();
    await expect(page.getByRole("link", { name: "도시철도", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "주요 메뉴 열기" }).click();
    await expect(page.getByRole("link", { name: "도시철도", exact: true })).not.toBeVisible();
  }
  await expect(page.getByTestId("home-stat-sources")).toContainText("1");
  await expect(page.getByRole("link", { name: "통합", exact: true })).toHaveCount(0);
  await page.route("**/transport/features/places?**", (route) => route.fulfill({ json: { items: [metro] } }));
  await page.route("**/transport/rail/timetables?**", (route) => route.fulfill({ json: { generated_at: now(), basis: "calendar", day_code: "8", items: [{ place_id: metro.id, station_name: metro.name, line_name: "GTX-A", status: "stored", stale: false, collected_at: now(), next_departure: { departure_time: "140000", train_number: "A1", destination_name: "동탄" }, upcoming_departures: [{ departure_time: "140000", train_number: "A1", destination_name: "동탄" }, { departure_time: "141000", train_number: "A2", destination_name: "동탄" }], items: [{ departure_time: "140000", train_number: "A1", destination_name: "동탄" }] }] } }));
  await page.goto("/rail/metro");
  await expect(page.locator(".station-results")).toHaveCount(0);
  await page.getByLabel("노선", { exact: true }).selectOption({ label: "GTX-A · 지티엑스에이운영" });
  await page.locator(".station-results").getByRole("button", { name: /구성/ }).click();
  await expect(page.getByRole("heading", { name: /구성 지티엑스에이운영/ })).toBeVisible();
  await expect(page.getByRole("link", { name: "031-000-0000" })).toHaveAttribute("href", "tel:0310000000");
  await expect(page.getByText("엘리베이터", { exact: false })).toBeVisible();
  const overlay = page.getByRole("complementary", { name: "선택 장소 상세" });
  await expect(overlay).toHaveCSS("position", "absolute");
  const stage = await page.locator(".embedded-map .map-primary").first().boundingBox();
  expect(stage!.width).toBeGreaterThan(width === 1440 ? 800 : 250);
  expect(stage!.height).toBeGreaterThan(500);
  if (width === 375) expect(stage!.y).toBeLessThan(600);
  const panel = await overlay.boundingBox();
  expect(panel!.height).toBeLessThan(stage!.height - 30);
  await page.getByRole("button", { name: /경기도 용인시 · 지도에서 보기/ }).click();
  await expect(page.getByText("다음 예정 14:00", {exact: true})).toBeVisible();
  await page.screenshot({ path: `test-results/metro-journey-${width}.png`, fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.keyboard.press("Escape");
  await expect(overlay).toHaveCount(0);
  const stationButton = page.locator(".station-results").getByRole("button", { name: /구성/ });
  await stationButton.focus();
  await stationButton.press("Enter");
  await expect(overlay).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(overlay).toHaveCount(0);
  await expect(stationButton).toBeFocused();
});

test("공항은 주차·항공편을 자동 조회하고 이후 편부터 표시", async ({ page }) => {
  test.setTimeout(90_000); test.skip(!password, "로그인 암호 필요"); await login(page);
  await page.route("**/transport/features/places?**", (route) => route.fulfill({ json: { items: [airport] } }));
  await page.route("**/parking/current?**", (route) => route.fulfill({ json: { items: [{ parking_lot_id: 1, parking_lot_name: "국내선 주차장", available_spaces: 52, total_spaces: 100, observed_at: now() }] } }));
  await page.route("**/flights/status?**", (route) => route.fulfill({ json: { status: "success", items: [{ flight_number: "FUTURE101", direction: "arrival", origin_airport: "PUS", destination_airport: "GMP", scheduled_at: new Date(Date.now() + 3600_000).toISOString(), estimated_at: null }, { flight_number: "PAST999", direction: "arrival", origin_airport: "PUS", destination_airport: "GMP", scheduled_at: new Date(Date.now() - 3600_000).toISOString(), estimated_at: null }] } }));
  await page.goto("/flights");
  await page.getByRole("button", { name: "오늘 출도착 항공편 안내", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("공항 선택 시 자동 조회");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText("FUTURE101", { exact: false })).toBeVisible();
  await expect(page.getByText("PAST999", { exact: false })).toHaveCount(0);
  await expect(page.getByText("52", { exact: true }).first()).toBeVisible();
  await page.getByLabel("지금 이후만").uncheck();
  await expect(page.getByText("PAST999", { exact: false })).toBeVisible();
});

for (const failure of [false, true]) test(`공항 목록 ${failure ? "실패" : "빈 응답"}에서 하위 조회를 기다리지 않는다`, async ({page}) => {
  test.skip(!password, "로그인 암호 필요"); await login(page);
  const requests: string[] = [];
  page.on("request", (request) => { if (/parking\/current|flights\/status/.test(request.url())) requests.push(request.url()); });
  await page.route("**/transport/features/places?**", (route) => failure ? route.fulfill({status: 502, json: {detail: "오류"}}) : route.fulfill({json: {items: []}}));
  await page.goto("/flights");
  await expect(page.getByText(failure ? "공항 목록을 확인하지 못했습니다." : "저장된 공항이 없습니다.", {exact: true}).first()).toBeVisible();
  await expect(page.getByText("주차 현황을 확인하는 중입니다…", {exact: true})).toHaveCount(0);
  await expect(page.getByText("항공편을 확인하는 중입니다…", {exact: true})).toHaveCount(0);
  expect(requests).toEqual([]);
});

test("버스는 입력 전 목록 요청을 하지 않고 이름 검색으로 시작한다", async ({page}) => {
  test.skip(!password, "로그인 암호 필요"); await login(page);
  const queries: string[] = [];
  await page.route("**/transport/bus/terminals?**", (route) => { queries.push(new URL(route.request().url()).searchParams.get("query") ?? ""); return route.fulfill({json: {items: [{terminal_id: "T1", terminal_name: "서울 시험터미널", city_name: "서울"}]}}); });
  await page.goto("/bus/express");
  await expect(page.getByRole("button", {name: "운행편 조회", exact: true})).toBeDisabled();
  expect(queries).toEqual([]);
  await page.getByLabel("출발 터미널", {exact: true}).fill("서울");
  await expect(page.getByRole("checkbox", {name: /서울 시험터미널/})).toBeVisible();
  expect(queries).toEqual(["서울"]);
});

test("공항 주차 조회 실패 후 KPI가 조회 중으로 남지 않는다", async ({page}) => {
  test.skip(!password, "로그인 암호 필요"); await login(page);
  await page.route("**/transport/features/places?**", (route) => route.fulfill({json: {items: [airport]}}));
  await page.route("**/parking/current?**", (route) => route.fulfill({status: 502, json: {detail: "오류"}}));
  await page.route("**/flights/status?**", (route) => route.fulfill({json: {status: "success", items: []}}));
  await page.goto("/flights");
  await expect(page.getByText("조회 실패", {exact: true})).toBeVisible();
  await expect(page.getByText("조회 중", {exact: true})).toHaveCount(0);
});
