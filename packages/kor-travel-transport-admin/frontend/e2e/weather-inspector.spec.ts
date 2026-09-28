import { expect, test, type Page } from "@playwright/test";
import { MAP_FALLBACK_IMAGE } from "../lib/map-fallback";

const stamp = "2026-09-28T03:00:00Z";
const base = { source: "data_go_kr_maritime", prices: [], facilities: [], line_names: [], latitude: 37.5, longitude: 127, updated_at: stamp };
const port = { ...base, id: 1, kind: "ferry_port", provider_id: "SEA1", name: "시험항" };
const airport = { ...base, id: 2, kind: "airport", provider_id: "GMP", name: "김포공항" };
const rail = { ...base, id: 3, kind: "rail_station", provider_id: "KRIC3", name: "서울역", line_names: ["1호선"] };
const fuel = { ...base, id: 4, kind: "fuel_station", name: "시험주유소", brand_name: "시험 브랜드", prices: ["B027", "B034", "D047", "K015", "C004"].map((product_code) => ({ product_code, price: 1700, observed_at: stamp })) };

async function places(page: Page) {
  await page.route("**://*.vworld.kr/**", (route) => route.abort());
  await page.route("**/transport/features/places?**", (route) => {
    const kind = new URL(route.request().url()).searchParams.get("kind");
    return route.fulfill({ json: { items: [port, airport, rail, fuel].filter((place) => place.kind === kind), total: 1, truncated: false } });
  });
}
test.beforeEach(async ({ page }) => {
  test.skip(!process.env.E2E_TRANSPORT_UI_PASSWORD, "운영 로그인 암호 필요");
  await page.goto("/login");
  await page.getByLabel("아이디").fill("admin");
  await page.getByLabel("비밀번호").fill(process.env.E2E_TRANSPORT_UI_PASSWORD!);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await places(page);
});

for (const width of [320, 375, 414, 768, 1440]) test(`Weather 우측 상세 · 항구 저장 시간표 ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 });
  const provider: string[] = [];
  page.on("request", (request) => { if (/ports\/[^/?]+\/timetable\?/.test(request.url())) provider.push(request.url()); });
  const dates: string[] = [];
  await page.route("**/transport/ports/timetables?**", (route) => {
    const date = new URL(route.request().url()).searchParams.get("date")!; dates.push(date);
    return route.fulfill({ json: { service_date: date, missing_port_ids: [], items: [{ port_id: "SEA1", service_date: date, fetched_at: stamp, items: [{ vessel_name: "시험호", departure_port_name: "시험항", arrival_port_name: "제주항", departure_planned_time: "0900", arrival_planned_time: "1100", fare: "12000" }] }] } });
  });
  await page.goto("/map");
  await page.getByLabel("장소 목록에서 선택").selectOption("ferry_port:1");
  const panel = page.getByRole("complementary", { name: "선택 장소 상세" });
  await expect(panel.getByRole("heading", { name: "시험항", exact: true })).toBeVisible();
  await expect(panel.getByText("시험호", { exact: true })).toBeVisible();
  await expect(panel.getByText("12,000원", { exact: true })).toBeVisible();
  await panel.getByLabel("운항일").selectOption("9");
  await expect.poll(() => dates.length).toBe(2);
  await expect(panel.getByText("시험호", { exact: true })).toBeVisible();
  expect((Date.parse(dates[1]) - Date.parse(dates[0])) / 86400000).toBe(9);
  expect(provider).toEqual([]);
  if (width === 1440) {
    const map = await page.locator(".map-primary").boundingBox(); const detail = await panel.boundingBox();
    expect(detail!.x).toBeGreaterThanOrEqual(map!.x + map!.width);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/weather-inspector-${width}.png`, fullPage: true });
  await panel.getByRole("button", { name: "장소 상세 닫기" }).click();
  await expect(panel.getByLabel("장소 목록에서 선택")).toBeFocused();
  await expect(panel.getByRole("heading", { name: "시험항", exact: true })).toHaveCount(0);
});

for (const mode of ["missing", "empty", "error"] as const) test(`항구 상세 ${mode} 상태를 구분한다`, async ({ page }) => {
  await page.route("**/transport/ports/timetables?**", (route) => route.fulfill({ status: mode === "error" ? 503 : 200, json: { items: mode === "empty" ? [{ port_id: "SEA1", service_date: "2026-09-28", fetched_at: stamp, items: [] }] : [], missing_port_ids: ["SEA1"] } }));
  await page.goto("/map"); await page.getByLabel("장소 목록에서 선택").selectOption("ferry_port:1");
  await expect(page.getByRole("complementary", { name: "선택 장소 상세" })).toContainText(mode === "missing" ? "아직 저장되지 않았습니다" : mode === "empty" ? "결항을 의미하지는 않습니다" : "시간표를 불러오지 못했습니다");
});

test("공항 선택은 저장 주차만 조회하고 출도착은 클릭 후 호출한다", async ({ page }) => {
  let calls = 0;
  await page.route("**/parking/current?**", (route) => route.fulfill({ json: { items: [{ parking_lot_name: "제1주차장", available_spaces: 123, total_spaces: 500, observed_at: stamp }] } }));
  await page.route("**/flights/status?**", (route) => { calls++; return route.fulfill({ json: { status: "success", error_message: null, items: [{ flight_number: "KE123", direction: "departure", airline: "대한항공", origin_airport: "김포", destination_airport: "제주", scheduled_at: stamp, estimated_at: null, status: "예정" }] } }); });
  await page.goto("/map"); await page.getByLabel("장소 목록에서 선택").selectOption("airport:2");
  const panel = page.getByRole("complementary", { name: "선택 장소 상세" });
  await expect(panel).toContainText("여유 123 / 500면"); expect(calls).toBe(0);
  await panel.getByRole("button", { name: "오늘 출도착 조회" }).click();
  await expect(panel).toContainText("KE123"); expect(calls).toBe(1);
  await panel.getByLabel("운항 방향").selectOption("arrival");
  await expect(panel).not.toContainText("KE123"); expect(calls).toBe(1);
});

test("공항 429는 버튼을 다시 눌러도 즉시 재호출하지 않는다", async ({ page }) => {
  let calls = 0;
  await page.route("**/parking/current?**", (route) => route.fulfill({ json: { items: [] } }));
  await page.route("**/flights/status?**", (route) => { calls++; return route.fulfill({ status: 429, headers: { "retry-after": "60" }, json: {} }); });
  await page.goto("/map"); await page.getByLabel("장소 목록에서 선택").selectOption("airport:2");
  await page.getByRole("button", { name: "오늘 출도착 조회" }).click();
  await expect(page.locator("[data-slot=alert]")).toBeVisible();
  await page.getByRole("button", { name: "오늘 출도착 조회" }).click();
  await expect(page.locator("[data-slot=alert]")).toContainText("다음 조회 가능 시각"); expect(calls).toBe(1);
  await page.getByRole("button", { name: "장소 상세 닫기" }).click();
  await page.getByLabel("장소 목록에서 선택").selectOption("airport:2");
  await page.getByRole("button", { name: "오늘 출도착 조회" }).click();
  await expect(page.locator("[data-slot=alert]")).toContainText("다음 조회 가능 시각"); expect(calls).toBe(1);
});

test("도시철도 상세 시간표와 간결한 주유소·항구 마커", async ({ page }) => {
  let departures = 0;
  await page.route("**/transport/rail/departures?**", (route) => { departures++; return route.fulfill({ json: {} }); });
  await page.route("**/transport/rail/timetables?**", (route) => route.fulfill({ json: { generated_at: stamp, basis: "calendar", day_code: "8", items: [{ place_id: 3, station_name: "서울역", line_name: "1호선", status: "not_collected", items: [] }] } }));
  await page.goto("/map"); await page.getByLabel("장소 목록에서 선택").selectOption("rail_station:3");
  await expect(page.getByRole("complementary", { name: "선택 장소 상세" })).toContainText("저장 시간표가 아직 없습니다");
  await expect(page.locator(".journey-marker.rail_station")).toHaveText("서울역 1호선"); expect(departures).toBe(0);
  await page.getByLabel("장소 목록에서 선택").selectOption("fuel_station:4");
  const marker = page.locator(".journey-marker.fuel_station");
  await expect(marker).toBeVisible();
  for (const label of ["휘발유", "고급유", "경유", "LPG", "등유"]) await expect(marker).toContainText(label);
  await expect(marker).not.toContainText("원/L"); await expect(marker).not.toContainText("주유소");
  await expect(page.getByRole("complementary", { name: "선택 장소 상세" })).toContainText("시험 브랜드");
});

const snapshot = { data: { activeRuns: { __typename: "Runs", results: [] }, repositoriesOrError: { __typename: "RepositoryConnection", nodes: [{ schedules: [{ name: "ferry_schedule", pipelineName: "ferry_timetable_collection_job", cronSchedule: "45 */4 * * *", scheduleState: { status: "RUNNING" } }] }] }, runsOrError: { __typename: "Runs", results: [{ runId: "sample-run-123456789", jobName: "ferry_timetable_collection_job", status: "SUCCESS", startTime: 100, endTime: 200 }] } } };
for (const width of [320, 375, 414, 768, 1440]) test(`Weather Dagster 표·펼치기·갱신 실패 ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 });
  let calls = 0;
  await page.route("**/api/dagster/graphql", (route) => ++calls === 1 ? route.fulfill({ json: snapshot }) : route.fulfill({ status: 503, json: {} }));
  await page.goto("/admin/dagster");
  await expect(page.getByRole("region", { name: "최근 Dagster 실행 표" })).toContainText("성공");
  const button = page.getByRole("button", { name: "여객선 10일 시간표" });
  await button.click(); await expect(button).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByText("ferry_schedule", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "새로고침", exact: true }).click();
  await expect(page.locator("[data-slot=alert]")).toContainText("마지막 확인 결과");
  await expect(page.getByRole("region", { name: "최근 Dagster 실행 표" })).toContainText("성공");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/weather-dagster-${width}.png`, fullPage: true });
});

test("Dagster 최초 실패를 빈 실행 목록으로 오인하지 않는다", async ({ page }) => {
  await page.route("**/api/dagster/graphql", (route) => route.fulfill({ status: 503, json: {} }));
  await page.goto("/admin/dagster"); await expect(page.locator("[data-slot=alert]")).toContainText("상태를 불러오지 못했습니다");
  await expect(page.getByText("최근 Dagster 실행이 없습니다.")).toHaveCount(0);
});

test("늦게 도착한 항구 시간표가 새로 선택한 공항에 섞이지 않는다", async ({ page }) => {
  await page.route("**/transport/ports/timetables?**", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 800));
    await route.fulfill({ json: { items: [{ port_id: "SEA1", service_date: "2026-09-28", fetched_at: stamp, items: [{ vessel_name: "늦은 응답호" }] }] } });
  });
  await page.route("**/parking/current?**", (route) => route.fulfill({ json: { items: [] } }));
  await page.goto("/map"); await page.getByLabel("장소 목록에서 선택").selectOption("ferry_port:1");
  await expect(page.getByText("저장 시간표 확인 중…")).toBeVisible();
  await page.getByLabel("장소 목록에서 선택").selectOption("airport:2");
  await expect(page.getByRole("heading", { name: "김포공항", exact: true })).toBeVisible();
  await page.waitForTimeout(900);
  await expect(page.getByText("늦은 응답호")).toHaveCount(0);
});

const dashboardStatus = { scheduler_enabled: true, enabled_sources: [], sources: [] };
const statistics = { traffic: [], incidents: [], fuel_prices: [] };
for (const cached of [false, true]) test(`통계 실패 안내는 실제 이전 결과 존재 여부를 반영한다 (${cached})`, async ({ page }) => {
  await page.evaluate(({ cached, dashboardStatus, statistics }) => {
    sessionStorage.removeItem("kor-travel-transport-dashboard-v2");
    if (cached) sessionStorage.setItem("kor-travel-transport-dashboard-v2", JSON.stringify({ savedAt: Date.now(), status: dashboardStatus, statistics, traffic: { items: [] }, incidents: { items: [] } }));
  }, { cached, dashboardStatus, statistics });
  await page.route("**/transport/collector-status", (route) => route.fulfill({ json: dashboardStatus }));
  await page.route("**/transport/highways/**", (route) => route.fulfill({ json: { items: [] } }));
  let calls = 0;
  await page.route("**/transport/statistics?**", (route) => ++calls === 1 ? route.fulfill({ status: 504, json: {} }) : route.fulfill({ json: statistics }));
  await page.goto("/transport");
  const alert = page.locator("[data-slot=alert]");
  await expect(alert).toContainText(cached ? "이전 조회 결과를 표시" : "통계를 아직 불러오지 못했습니다");
  if (!cached) await expect(alert).not.toContainText("이전 조회");
  await page.getByRole("button", { name: "통계 다시 조회" }).click();
  await expect(alert).toHaveCount(0); expect(calls).toBe(2);
});

test("통계 수동 재시도는 화면당 3회까지이며 자동 반복하지 않는다", async ({ page }) => {
  await page.evaluate(() => sessionStorage.removeItem("kor-travel-transport-dashboard-v2"));
  await page.route("**/transport/collector-status", (route) => route.fulfill({ json: dashboardStatus }));
  let calls = 0;
  await page.route("**/transport/statistics?**", (route) => { calls++; return route.fulfill({ status: 504, json: {} }); });
  await page.goto("/transport");
  for (let index = 0; index < 3; index++) {
    const button = page.getByRole("button", { name: "통계 다시 조회" });
    await expect(button).toBeEnabled(); await button.click();
    await expect(page.getByRole("button", { name: "통계 확인 중…" })).toHaveCount(0);
  }
  await expect(page.getByRole("button", { name: "통계 다시 조회" })).toBeDisabled(); expect(calls).toBe(4);
});

for (const tiles of ["즉시 실패", "지연 실패", "지연 성공"]) test(`리뷰 회귀: 동일 좌표 묶음은 확대 한계 대신 장소 선택을 제공한다 (${tiles})`, async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  let tileRequests = 0;
  const decodeErrors: string[] = [];
  page.on("console", (message) => { if (/decode|InvalidStateError/i.test(message.text())) decodeErrors.push(message.text()); });
  await page.route("**://*.vworld.kr/**", async (route) => {
    tileRequests++;
    if (tiles !== "즉시 실패") await new Promise((resolve) => setTimeout(resolve, 500));
    if (tiles === "지연 성공") return route.fulfill({ contentType: "image/png", body: Buffer.from(MAP_FALLBACK_IMAGE.split(",")[1], "base64") });
    return route.abort();
  });
  let placeRequests = 0;
  await page.route("**/transport/features/places?**", (route) => {
    placeRequests++;
    const kind = new URL(route.request().url()).searchParams.get("kind");
    return route.fulfill({ json: { items: [port, airport, rail, fuel].filter((place) => place.kind === kind).map((place) => ({ ...place, latitude: 36.2, longitude: 127.8 })), total: 1, truncated: false } });
  });
  await page.route("**/parking/current?**", (route) => route.fulfill({ json: { items: [] } }));
  await page.goto("/map");
  await page.locator("canvas.maplibregl-canvas").scrollIntoViewIfNeeded();
  // 실제 타일 호출 없이도 카메라 이동으로 지도 viewport 계산을 완료한다.
  await page.getByLabel("장소 목록에서 선택").selectOption("rail_station:3");
  await page.getByRole("button", { name: "3개 위치 묶음 펼치기" }).click();
  expect(tileRequests).toBeGreaterThan(0);
  expect(decodeErrors).toEqual([]);
  if (tiles !== "지연 성공") await expect(page.getByText("VWorld 지도 타일을 불러오지 못했습니다. 목록 보기에서 장소를 확인할 수 있습니다.")).toBeVisible();
  const choices = page.getByRole("region", { name: "겹친 장소 선택" });
  await expect(choices).toBeVisible();
  await expect(choices.getByRole("button").first()).toBeFocused();
  // 선택 목록이 열린 뒤 viewport 재조회가 끝나도 버튼이 사라지면 안 된다.
  const previousRequests = placeRequests;
  await page.getByRole("button", { name: "Zoom in", exact: true }).click();
  await expect.poll(() => placeRequests).toBeGreaterThan(previousRequests);
  await expect(choices).toBeVisible();
  await choices.getByRole("button", { name: "김포공항", exact: true }).click();
  await expect(page.getByRole("heading", { name: "김포공항", exact: true })).toBeVisible();
  await expect(choices).toHaveCount(0);
});

for (const [status, message] of [["disabled", "비활성화"], ["config_error", "설정을 확인"], ["rate_limited", "호출 제한"], ["upstream_error", "확인하지 못했습니다"]]) {
  test(`리뷰 회귀: 항공편 ${status}는 정상 0편이 아니다`, async ({ page }) => {
    let calls = 0;
    await page.route("**/parking/current?**", (route) => route.fulfill({ json: { items: [] } }));
    await page.route("**/flights/status?**", (route) => { calls++; return route.fulfill({ json: { status, error_message: null, items: [] } }); });
    await page.goto("/map");
    await page.getByLabel("장소 목록에서 선택").selectOption("airport:2");
    await page.getByRole("button", { name: "오늘 출도착 조회" }).click();
    await expect(page.locator("[data-slot=alert]")).toContainText(message);
    await expect(page.getByText("등록된 항공편이 없습니다.", { exact: false })).toHaveCount(0);
    if (status === "rate_limited") {
      await page.getByRole("button", { name: "장소 상세 닫기" }).click();
      await page.getByLabel("장소 목록에서 선택").selectOption("airport:2");
      await page.getByRole("button", { name: "오늘 출도착 조회" }).click();
      await expect(page.locator("[data-slot=alert]")).toContainText("다음 조회 가능 시각");
      expect(calls).toBe(1);
    }
  });
}

test("리뷰 회귀: 최근 30건 밖의 장시간 작업도 집계·표시한다", async ({ page }) => {
  await page.route("**/api/dagster/graphql", (route) => route.fulfill({ json: { data: {
    ...snapshot.data,
    activeRuns: { __typename: "Runs", results: [{ runId: "old-ferry-run", jobName: "ferry_timetable_collection_job", status: "STARTED", startTime: Date.now() / 1000 - 5 * 3600, endTime: null }] },
  } } }));
  await page.goto("/admin/dagster");
  await expect(page.locator("[data-slot=alert]")).toContainText("1개 실행");
  await expect(page.getByRole("region", { name: "최근 Dagster 실행 표" })).toContainText("old-ferry-run");
});
