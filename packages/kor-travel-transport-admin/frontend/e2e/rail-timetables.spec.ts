import { expect, test, type Page } from "@playwright/test";

const password = process.env.E2E_TRANSPORT_UI_PASSWORD;
const place = { id: 71, kind: "rail_station", source: "kric_public_file", name: "불광", longitude: null, latitude: null, line_names: ["3호선"], facilities: [], prices: [], updated_at: "2026-09-27T00:00:00Z" };
const departure = { train_number: "S0312", departure_time: "140030", arrival_time: "140000", origin_name: "대화", destination_name: "오금" };
function response(status = "stored", options: Record<string, unknown> = {}) {
  return { generated_at: new Date().toISOString(), day_code: "9", basis: "calendar", items: [{ place_id: 71, station_name: "불광", line_name: "3호선", status, collected_at: new Date().toISOString(), stale: false, next_departure: departure, items: [departure], ...options }] };
}
test.beforeEach(async ({ page }) => {
  test.skip(!password, "E2E_TRANSPORT_UI_PASSWORD가 필요합니다.");
  await page.goto("/login");
  await page.getByLabel("아이디").fill(process.env.E2E_TRANSPORT_UI_USER ?? "admin");
  await page.getByLabel("비밀번호").fill(password!);
  await page.getByRole("button", { name: "로그인" }).click();
  await expect(page).toHaveURL(/\/$/);
});
async function mockPlaces(page: Page) {
  await page.route("**/transport/features/places?**", (route) => route.fulfill({ json: { items: [place] } }));
}
async function selectStation(page: Page) {
  await page.goto("/rail");
  await page.getByRole("checkbox", { name: /불광/ }).check();
}
for (const width of [320, 375, 414, 768, 1440]) test(`예정 열차·행선지·전체 시간표 ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  await mockPlaces(page);
  let calls = 0;
  await page.route("**/transport/rail/timetables?**", (route) => { calls++; return route.fulfill({ json: response() }); });
  await page.goto("/rail");
  expect(calls).toBe(0);
  await page.getByRole("checkbox", { name: /불광/ }).check();
  await expect(page.getByText("다음 예정 14:00", { exact: true })).toBeVisible();
  await expect(page.getByText("실시간 도착 정보가 아닙니다.", { exact: false })).toBeVisible();
  await page.getByText("전체 예정 시간표 1편").click();
  await expect(page.getByText("대화 출발 열차")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(calls).toBe(1);
});
for (const [status, options, text] of [
  ["unlinked", {}, "공식 역사 코드와 위치 정보가 아직 연결되지 않았습니다."],
  ["not_collected", {}, "선택한 기준의 저장 시간표가 아직 없습니다."],
  ["stored", { items: [], next_departure: null }, "제공기관의 마지막 정상 응답에 시간표가 없습니다."],
  ["stored", { stale: true, next_departure: null }, "48시간이 지난 저장본입니다."],
] as const) test(`예정 시간표 상태 구분 ${status} ${text.slice(0, 8)}`, async ({ page }) => {
  await mockPlaces(page);
  await page.route("**/transport/rail/timetables?**", (route) => route.fulfill({ json: response(status, options) }));
  await selectStation(page);
  await expect(page.getByText(text, { exact: false })).toBeVisible();
  await expect(page.getByText("다음 예정 14:00", { exact: true })).not.toBeVisible();
});
test("공휴일 실패 시 요일 직접 선택과 오류 재시도", async ({ page }) => {
  await mockPlaces(page);
  let calls = 0;
  await page.route("**/transport/rail/timetables?**", (route) => {
    calls++;
    const day = new URL(route.request().url()).searchParams.get("day_code");
    if (calls === 2) return route.fulfill({ status: 503, json: {} });
    return route.fulfill({ json: { ...response(), day_code: day, basis: day ? "selected_period" : "calendar_unavailable", items: [] } });
  });
  await selectStation(page);
  await expect(page.getByText("공휴일을 확인하지 못했습니다.", { exact: false })).toBeVisible();
  await page.getByLabel("시간표 기준").selectOption("8");
  await expect(page.getByRole("alert")).toContainText("시간표를 불러오지 못했습니다");
  await page.getByRole("button", { name: "시간표 새로고침", exact: true }).click();
  await expect(page.getByRole("alert")).not.toBeVisible();
  expect(calls).toBe(3);
});
test("역 선택 해제 후 늦은 시간표 응답을 표시하지 않는다", async ({ page }) => {
  await mockPlaces(page);
  let release: (() => void) | undefined;
  await page.route("**/transport/rail/timetables?**", async (route) => {
    await new Promise<void>((resolve) => { release = resolve; });
    await route.fulfill({ json: response() }).catch(() => {});
  });
  await selectStation(page);
  await expect(page.getByText("저장된 예정 시간표를 확인하는 중입니다…")).toBeVisible();
  await expect.poll(() => Boolean(release)).toBe(true);
  await page.getByRole("button", { name: "불광 선택 해제" }).click();
  release?.();
  await expect(page.getByRole("region", { name: "도시철도 예정 시간표" })).not.toBeVisible();
});
