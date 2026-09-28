import { expect, test } from "@playwright/test";

const now = "2026-09-28T03:00:00Z";
const place = { id: 71, kind: "rail_station", source: "kric_public_file", name: "불광", longitude: 126.93, latitude: 37.61, line_names: ["3호선"], prices: [], facilities: [], updated_at: now };
const row = { place_id: 71, status: "stored", stale: false, collected_at: now, departure_count: 2, next_departure: { departure_time: "121000", destination_name: "오금" } };

async function waitForMap(page: import("@playwright/test").Page) {
  await page.locator(".embedded-map").scrollIntoViewIfNeeded();
  // WebGL 준비와 마커 데이터의 기대값은 별도 조건으로 검증한다.
  await expect(page.getByText("지도를 준비하는 중입니다…", { exact: true })).toBeHidden({ timeout: 30_000 });
}
test.beforeEach(async ({ page }) => {
  test.skip(!process.env.E2E_TRANSPORT_UI_PASSWORD, "운영 로그인 암호 필요");
  await page.goto("/login");
  await page.getByLabel("아이디").fill("admin");
  await page.getByLabel("비밀번호").fill(process.env.E2E_TRANSPORT_UI_PASSWORD!);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.clock.install({ time: new Date(now) });
  await page.route("**://*.vworld.kr/**", (route) => route.abort());
  await page.route("**/transport/features/places?**", (route) => route.fulfill({ json: { items: [place] } }));
  await page.route("**/transport/rail/timetables?**", (route) => route.fulfill({ json: { generated_at: now, basis: "calendar", day_code: "8", items: [] } }));
});

for (const width of [375, 1440]) for (const [changes, basis, label] of [
  [{}, "calendar", "예정 12:10 · 오금행"],
  [{ stale: true }, "calendar", "시간표 갱신 필요"],
  [{ status: "not_collected" }, "calendar", "시간표 수집 대기"],
  [{ status: "unlinked" }, "calendar", "시간표 연결 전"],
  [{}, "calendar_unavailable", "운행일 확인 필요"],
] as const) test(`간결한 역 마커 · 기존 ${label} 상태 ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 });
  const requests: string[] = [];
  await page.route("**/transport/rail/departures?**", (route) => {
    requests.push(new URL(route.request().url()).searchParams.get("place_ids")!);
    return route.fulfill({ json: { generated_at: now, basis, items: [{ ...row, ...changes }] } });
  });
  await page.goto("/rail");
  await page.getByRole("checkbox", { name: /불광/ }).check();
  await waitForMap(page);
  const marker = page.locator(".journey-marker.rail_station");
  await expect(marker).toHaveText("불광 3호선");
  await expect(marker).not.toContainText(label);
  expect(requests).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("button", { name: "목록", exact: true }).click();
  await page.clock.runFor(61_000);
  expect(requests).toHaveLength(0);
});

test("간결한 마커를 위해 다음 열차 API를 주기적으로 호출하지 않는다", async ({ page }) => {
  let calls = 0;
  await page.route("**/transport/rail/departures?**", (route) => ++calls === 1
    ? route.fulfill({ json: { generated_at: now, basis: "calendar", items: [row] } })
    : route.fulfill({ status: 503, json: {} }));
  await page.goto("/rail");
  await page.getByRole("checkbox", { name: /불광/ }).check();
  await waitForMap(page);
  const marker = page.locator(".journey-marker.rail_station");
  await expect(marker).toHaveText("불광 3호선");
  await page.clock.runFor(61_000);
  await expect(marker).toHaveText("불광 3호선");
  expect(calls).toBe(0);
  await expect(marker).not.toContainText("12:10");
});

test("목록에서 오래 머문 뒤 지도에 복귀하면 느린 새 응답을 기다리는 동안 지난 열차를 숨긴다", async ({ page }) => {
  let calls = 0;
  await page.route("**/transport/rail/departures?**", (route) => ++calls === 1
    ? route.fulfill({ json: { generated_at: now, basis: "calendar", items: [row] } })
    : new Promise<void>(() => {}));
  await page.goto("/rail");
  await page.getByRole("checkbox", { name: /불광/ }).check();
  await waitForMap(page);
  const marker = page.locator(".journey-marker.rail_station");
  await expect(marker).toHaveText("불광 3호선");
  await page.getByRole("button", { name: "목록", exact: true }).click();
  // 시계만 바꾸고 주기 타이머를 실행하지 않아 첫 5초의 거짓 표시를 숨기지 않는다.
  await page.clock.setSystemTime(new Date("2026-09-28T04:00:00Z"));
  await page.getByRole("button", { name: "지도", exact: true }).click();
  await expect(marker).toHaveText("불광 3호선");
  expect(calls).toBe(0);
  await expect(marker).not.toContainText("12:10");
});
