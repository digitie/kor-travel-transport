import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  test.skip(!process.env.E2E_TRANSPORT_UI_PASSWORD, "비밀번호 환경변수가 필요합니다.");
  await page.goto("/login");
  await page.getByLabel("아이디").fill(process.env.E2E_TRANSPORT_UI_USER ?? "admin");
  await page.getByLabel("비밀번호").fill(process.env.E2E_TRANSPORT_UI_PASSWORD!);
  await page.getByRole("button", { name: "로그인" }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.route("**/transport/features/places?kind=ferry_port**", (route) => route.fulfill({ json: { items: ["A", "B"].map((id, index) => ({ id: index + 1, provider_id: id, kind: "ferry_port", source: "data_go_kr_maritime", name: `${id}항구`, line_names: [], prices: [], facilities: [], longitude: null, latitude: null, updated_at: new Date().toISOString() })) } }));
});

test("배편 선택 해제는 로딩을 해제하고 딥링크 새로고침은 복수 선택을 보존한다", async ({ page }) => {
  let delay = true;
  await page.route("**/transport/ports/timetables?**", async (route) => {
    if (delay) await new Promise((resolve) => setTimeout(resolve, 600));
    const params = new URL(route.request().url()).searchParams;
    await route.fulfill({ json: { service_date: params.get("date"), items: [], missing_port_ids: params.get("port_ids")!.split(",") } });
  });
  await page.goto("/ferry?port=A");
  await expect(page.getByRole("checkbox", { name: /A항구/ })).toBeChecked();
  await page.getByRole("checkbox", { name: /A항구/ }).uncheck();
  await expect(page.getByRole("button", { name: "저장 정보 새로고침" })).toBeEnabled();
  delay = false;
  await page.getByRole("checkbox", { name: /A항구/ }).check();
  await page.getByRole("checkbox", { name: /B항구/ }).check();
  await page.getByRole("button", { name: "저장 정보 새로고침" }).click();
  await expect(page.getByRole("checkbox", { name: /B항구/ })).toBeChecked();
  await expect(page.getByText("2/5곳 선택", { exact: false })).toBeVisible();
});

test("한국 자정 이후 배편 입력·제목·요청 날짜가 함께 전환된다", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-09-27T14:59:55Z") });
  const dates: string[] = [];
  await page.route("**/transport/ports/timetables?**", (route) => {
    const date = new URL(route.request().url()).searchParams.get("date")!; dates.push(date);
    return route.fulfill({ json: { service_date: date, items: [{ port_id: "A", service_date: date, fetched_at: "2026-09-27T00:00:00Z", items: [] }], missing_port_ids: [] } });
  });
  await page.goto("/ferry?port=A");
  await expect(page.getByLabel("운항일")).toHaveValue("2026-09-27");
  await expect.poll(() => dates).toContain("2026-09-27");
  await page.clock.runFor(31_000);
  await expect(page.getByLabel("운항일")).toHaveValue("2026-09-28");
  await expect(page.getByRole("heading", { name: "A항구 · 2026-09-28" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "오늘 운항 비교" })).toBeVisible();
  expect(dates).toContain("2026-09-28");
});

for (const width of [375, 1440]) test(`같은 이름의 항구는 코드로 선택·조회·해제한다 ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  const codes = ["SEA10070", "SEA96540"];
  await page.route("**/transport/features/places?kind=ferry_port**", (route) => route.fulfill({ json: { items: codes.map((code, index) => ({ id: index + 1, provider_id: code, kind: "ferry_port", source: "data_go_kr_maritime", name: "육도", line_names: [], prices: [], facilities: [], longitude: null, latitude: null, updated_at: new Date().toISOString() })) } }));
  const requests: string[][] = [];
  await page.route("**/transport/ports/timetables?**", (route) => {
    const params = new URL(route.request().url()).searchParams;
    const ids = params.get("port_ids")!.split(","); requests.push(ids);
    return route.fulfill({ json: { service_date: params.get("date"), missing_port_ids: [], items: ids.map((code) => ({ port_id: code, port_name: "육도", service_date: params.get("date"), fetched_at: new Date().toISOString(), items: [{ vessel_name: code === codes[0] ? "첫째호" : "둘째호", departure_port_name: "육도", arrival_port_name: "검증항", departure_planned_time: "0900", arrival_planned_time: "1000", fare: "10000" }] })) } });
  });
  await page.goto(`/ferry?port=${codes[1]}`);
  await expect(page.getByRole("checkbox", { name: /육도 · SEA96540/ })).toBeChecked();
  await expect(page.getByRole("checkbox", { name: /육도 · SEA10070/ })).not.toBeChecked();
  await expect(page.getByText("둘째호", { exact: true })).toBeVisible();
  await expect(page.getByText("첫째호", { exact: true })).not.toBeVisible();
  await page.getByRole("checkbox", { name: /육도 · SEA10070/ }).check();
  await expect(page.getByText("첫째호", { exact: true })).toBeVisible();
  await expect(page.getByText("둘째호", { exact: true })).toBeVisible();
  expect(requests.at(-1)).toEqual([codes[1], codes[0]]);
  await page.getByRole("button", { name: "육도 · SEA96540 · 지역 미확인 선택 해제" }).click();
  await expect(page.getByText("둘째호", { exact: true })).not.toBeVisible();
  await expect(page.getByText("첫째호", { exact: true })).toBeVisible();
  await page.getByLabel("항구 검색", { exact: true }).fill(codes[1]);
  await expect(page.getByRole("checkbox", { name: /육도 · SEA96540/ })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /육도 · SEA10070/ })).not.toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("알 수 없는 항구 코드 딥링크는 이름으로 임의 연결하지 않는다", async ({ page }) => {
  let calls = 0;
  await page.route("**/transport/ports/timetables?**", (route) => { calls++; return route.fulfill({ json: {} }); });
  await page.goto("/ferry?port=UNKNOWN");
  await expect(page.locator("p[role=alert]")).toContainText("링크의 항구 코드");
  expect(calls).toBe(0);
  await expect(page.getByRole("checkbox", { name: /A항구/ })).not.toBeChecked();
});
