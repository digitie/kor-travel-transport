import { expect, test, type Page } from "@playwright/test";

const password = process.env.E2E_TRANSPORT_UI_PASSWORD;
const now = () => new Date().toISOString();
const day = () => new Date(Date.now() + 9 * 3600_000).toISOString().slice(0, 10);
const stamp = (offset: number) => new Date(Date.now() + offset + 9 * 3600_000).toISOString().replace(/[-:T]/g, "").slice(0, 12);
const metro = { id: 71, kind: "rail_station", source: "kric_public_file", name: "구성", subtitle: "지티엑스에이운영", station_type: "도시/광역철도", line_names: ["GTX-A"], address: "경기도 용인시", phone: "031-000-0000", latitude: 37.3, longitude: 127.1, prices: [], facilities: ["엘리베이터"], updated_at: "2026-10-24T00:00:00Z" };
const airport = { ...metro, id: 1, kind: "airport", name: "김포공항", provider_id: "GMP", line_names: [], subtitle: null };
const terminal = (id: number, name: string) => ({ id, terminal_id: `TEST${id}`, terminal_name: name, city_name: "시험 지역", latitude: 37 + id / 10, longitude: 127, updated_at: now() });
const terminals = [terminal(1, "서울 시험터미널"), terminal(2, "부산 시험터미널"), terminal(3, "대전 시험터미널")];

async function login(page: Page) {
  await page.route("**/transport/providers", (route) => route.fulfill({ json: { generated_at: now(), items: [{ source: "a", name: "정상 소스", mode: "scheduled", enabled: true, status: "success" }], kric_coverage: { station_count: 3, linked_station_count: 2, expected_snapshots: 9, stored_snapshots: 2, fresh_snapshots: 1 } } }));
  await page.route("**/api/dagster/graphql", (route) => route.fulfill({ json: { data: { repositoryOrError: { __typename: "Repository", schedules: [] }, runsOrError: { __typename: "Runs", results: [] }, activeRuns: { __typename: "Runs", results: [] } } } }));
  await page.goto("/login");
  await page.getByLabel("비밀번호").fill(password!);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
}

for (const width of [375, 1440]) test(`운영 홈·노선 중심 도시철도·이후 시간표 ${width}px`, async ({ page }) => {
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
  await expect(page.getByLabel("지금 이후 예정 출발")).toContainText("14:10");
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

for (const width of [375, 1440]) test(`일반철도 종류·역 검색과 실제 형태의 운행편 ${width}px`, async ({ page }) => {
  test.setTimeout(90_000); test.skip(!password, "로그인 암호 필요");
  await page.setViewportSize({ width, height: 1000 }); await login(page);
  await page.route("**/transport/rail/general/catalog", (route) => route.fulfill({ json: { fetched_at: now(), cities: [{ code: "11", name: "서울" }, { code: "21", name: "부산" }], train_classes: [{ code: "0A", name: "KTX-산천" }, { code: "17", name: "SRT" }, { code: "02", name: "무궁화호" }] } }));
  await page.route("**/transport/rail/general/guide?**", (route) => {
    const category = new URL(route.request().url()).searchParams.get("category_code");
    return route.fulfill({ json: { fetched_at: now(), kind: "ktx", category_code: category, total: 1, categories: [{ code: "ktx1", name: "경부선" }], items: category ? [{ provider_id: "10281321", station_name: "서울", address: "서울특별시 용산구", phone: "1588-7788", latitude: 37.55, longitude: 126.97 }] : [] } });
  });
  await page.route("**/transport/rail/general/stations?**", (route) => route.fulfill({ json: { fetched_at: now(), city_code: "11", items: [{ station_id: "NAT010000", station_name: "서울" }, { station_id: "NAT014445", station_name: "부산" }] } }));
  let requestCount = 0;
  let releaseFirst: () => void = () => undefined;
  const firstGate = new Promise<void>((resolve) => { releaseFirst = resolve; });
  await page.route("**/transport/rail/general/timetable?**", async (route) => {
    requestCount += 1;
    if (requestCount === 1) await firstGate;
    expect(new URL(route.request().url()).searchParams.get("train_grade_code")).toBe("0A");
    return route.fulfill({ json: { fetched_at: now(), service_date: day(), total: 2, truncated: false, items: [{ train_number: "001", grade_name: "KTX-산천", departure_station_name: "서울", arrival_station_name: "부산", departure_planned_time: stamp(3600_000), arrival_planned_time: stamp(3 * 3600_000), adult_fare: 59800 }, { train_number: "PAST", grade_name: "KTX", departure_planned_time: stamp(-3600_000), arrival_planned_time: stamp(0) }] } });
  });
  await page.goto("/rail");
  await page.getByLabel("노선", { exact: true }).selectOption("ktx1");
  await page.getByLabel("철도 역 검색 결과").getByRole("button", { name: /서울/ }).click();
  await expect(page.getByRole("link", { name: "1588-7788" })).toHaveAttribute("href", "tel:15887788");
  await expect(page.getByRole("link", { name: "공식 역 안내" })).toHaveAttribute("href", /stationSeq=10281321/);
  await page.getByLabel("열차 종류", { exact: true }).selectOption("0A");
  const from = page.getByRole("group", { name: "출발역", exact: true });
  const to = page.getByRole("group", { name: "도착역", exact: true });
  await from.getByLabel("지역", { exact: true }).selectOption("11");
  await from.getByLabel("출발역 검색").fill("서울");
  await from.getByRole("button", { name: /서울 NAT010000/ }).click();
  await to.getByLabel("지역", { exact: true }).selectOption("21");
  await to.getByLabel("도착역 검색").fill("부산");
  await to.getByRole("button", { name: /부산 NAT014445/ }).click();
  await page.getByRole("button", { name: "예정 운행편 조회" }).click();
  await expect.poll(() => requestCount).toBe(1);
  await page.getByLabel("열차 종류", { exact: true }).selectOption("17");
  await page.getByLabel("열차 종류", { exact: true }).selectOption("0A");
  await expect(page.getByRole("button", { name: "예정 운행편 조회" })).toBeEnabled();
  releaseFirst();
  await page.getByRole("button", { name: "예정 운행편 조회" }).click();
  await expect(page.getByText("59,800원", { exact: true })).toBeVisible();
  await expect(page.getByText("PAST", { exact: false })).toHaveCount(0);
  await page.getByLabel("지금 이후만").uncheck();
  await expect(page.getByText("KTX PAST", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("터미널 목록 대기와 연결 조회 실패를 정상 빈 목록으로 표시하지 않는다", async ({ page }) => {
  test.setTimeout(90_000); test.skip(!password, "로그인 암호 필요"); await login(page);
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/transport/bus/terminals?**", async (route) => { await gate; await route.fulfill({ json: { items: terminals, next_offset: null } }); });
  await page.route("**/transport/bus/connections?**", (route) => route.fulfill({ status: 502, json: { detail: "조회 실패" } }));
  await page.goto("/bus/express");
  const from = page.locator(".terminal-search").first();
  await from.getByLabel("출발 터미널", { exact: true }).fill("서울");
  await expect(from.getByRole("status")).toContainText("터미널 목록 조회 중");
  await expect(from.getByText("조건에 맞는 터미널이 없습니다.")).toHaveCount(0);
  release();
  await from.getByRole("button", { name: /서울 시험터미널/ }).click();
  const to = page.locator(".terminal-search").nth(1);
  await expect(to.getByRole("alert")).toContainText("연결 정보를 확인하지 못했습니다");
  await expect(to.getByText("조건에 맞는 터미널이 없습니다.")).toHaveCount(0);
});

test("버스 출발·도착 양방향 저장 연결과 이후 출발", async ({ page }) => {
  test.setTimeout(90_000); test.skip(!password, "로그인 암호 필요"); await login(page);
  await page.route("**/transport/bus/terminals?**", (route) => route.fulfill({ json: { items: terminals, next_offset: null } }));
  const directions: string[] = [];
  await page.route("**/transport/bus/connections?**", (route) => {
    const params = new URL(route.request().url()).searchParams; directions.push(params.get("direction")!);
    return route.fulfill({ json: { coverage: "stored_routes", items: params.get("direction") === "departure" ? [terminals[1]] : [terminals[0]] } });
  });
  await page.route("**/transport/bus/timetable?**", (route) => route.fulfill({ json: { fetched_at: now(), service_date: day(), total: 1, items: [{ departure_planned_time: stamp(3600_000), arrival_planned_time: stamp(4 * 3600_000), grade_name: "우등", adult_fare: 45000 }] } }));
  await page.goto("/bus/express");
  await page.getByRole("link", { name: "지도 보기", exact: true }).click();
  await expect(page.locator("#bus-map")).toBeInViewport();
  await page.getByLabel("출발 터미널", { exact: true }).fill("서울");
  await page.getByRole("button", { name: /서울 시험터미널 시험 지역/ }).click();
  const to = page.locator(".terminal-search").nth(1);
  await expect(to.getByRole("button", { name: /부산 시험터미널/ })).toBeVisible();
  await expect(to.getByRole("button", { name: /대전 시험터미널/ })).toHaveCount(0);
  await to.getByRole("button", { name: /부산 시험터미널/ }).click();
  await expect.poll(() => directions).toContain("arrival");
  await page.getByRole("button", { name: "운행편 조회", exact: true }).click();
  await expect(page.getByText("45,000원", { exact: true })).toBeVisible();
});

test("공항은 주차·항공편을 자동 조회하고 이후 편부터 표시", async ({ page }) => {
  test.setTimeout(90_000); test.skip(!password, "로그인 암호 필요"); await login(page);
  await page.route("**/transport/features/places?**", (route) => route.fulfill({ json: { items: [airport] } }));
  await page.route("**/parking/current?**", (route) => route.fulfill({ json: { items: [{ parking_lot_id: 1, parking_lot_name: "국내선 주차장", available_spaces: 52, total_spaces: 100, observed_at: now() }] } }));
  await page.route("**/parking/outlook?**", (route) => route.fulfill({ json: { generated_at: now(), hour: 12, weekday: 5, items: [{ parking_lot_id: 1, parking_lot_name: "국내선 주차장", average_available_spaces: 40, minimum_available_spaces: 0, maximum_available_spaces: 80, sample_days: 4, full_days: 1, full_day_ratio: 25, observations: 40, minimum_capacity: 100, maximum_capacity: 100 }] } }));
  await page.route("**/flights/status?**", (route) => route.fulfill({ json: { status: "success", items: [{ flight_number: "FUTURE101", direction: "arrival", origin_airport: "PUS", destination_airport: "GMP", scheduled_at: new Date(Date.now() + 3600_000).toISOString(), estimated_at: null }, { flight_number: "PAST999", direction: "arrival", origin_airport: "PUS", destination_airport: "GMP", scheduled_at: new Date(Date.now() - 3600_000).toISOString(), estimated_at: null }] } }));
  await page.goto("/flights");
  await page.getByRole("button", { name: "입차 예정 시각의 과거 패턴 안내", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("같은 요일·시간대");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText("FUTURE101", { exact: false })).toBeVisible();
  await expect(page.getByText("PAST999", { exact: false })).toHaveCount(0);
  await expect(page.getByText("52", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("1/4일 (25%)", { exact: true })).toBeVisible();
  await page.getByLabel("지금 이후만").uncheck();
  await expect(page.getByText("PAST999", { exact: false })).toBeVisible();
});
