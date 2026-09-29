import { expect, test } from "@playwright/test";

for (const width of [320, 375, 768, 1440]) {
  test(`shadcn 로그인 필드와 키보드 제출 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/login");
    await expect(page.locator("[data-slot=card]")).toBeVisible();
    expect(await page.locator("[data-slot=card-header]").evaluate((node) => getComputedStyle(node).gridTemplateColumns.split(" ").length)).toBe(1);
    await expect(page.getByLabel("아이디")).toHaveAttribute("data-slot", "input");
    await expect(page.getByLabel("비밀번호")).toHaveAttribute("data-slot", "input");
    await page.route("**/api/auth/login", (route) => route.fulfill({ status: 401, json: { detail: "아이디 또는 비밀번호를 확인해 주세요." } }));
    await page.getByLabel("비밀번호").fill("invalid-test-only");
    await page.getByLabel("비밀번호").press("Enter");
    await expect(page.locator("[data-slot=field-error]")).toContainText("아이디 또는 비밀번호");
    await expect(page.getByLabel("비밀번호")).toHaveAttribute("aria-invalid", "true");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });

  test(`shadcn 지도 필터·보기 선택 유지 ${width}px`, async ({ page }) => {
    test.skip(!process.env.E2E_TRANSPORT_UI_PASSWORD, "로그인 암호 필요");
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/login");
    await page.getByLabel("아이디").fill("admin");
    await page.getByLabel("비밀번호").fill(process.env.E2E_TRANSPORT_UI_PASSWORD!);
    await page.getByRole("button", { name: "로그인", exact: true }).click();
    await expect(page).toHaveURL(/\/$/);
    await page.route("**://*.vworld.kr/**", (route) => route.abort());
    await page.route("**/transport/features/places?**", (route) => route.fulfill({ json: { items: [], total: 0, truncated: false } }));
    await page.goto("/map");
    await expect(page.getByLabel("장소 검색")).toHaveAttribute("data-slot", "input");
    await expect(page.getByLabel("표시 유종")).toHaveAttribute("role", "combobox");
    const view = page.getByRole("group", { name: "보기 방식", exact: true });
    await view.getByRole("button", { name: "목록", exact: true }).click();
    await expect(view.getByRole("button", { name: "목록", exact: true })).toHaveAttribute("aria-pressed", "true");
    await view.getByRole("button", { name: "목록", exact: true }).press("Space");
    await expect(view.getByRole("button", { name: "목록", exact: true })).toHaveAttribute("aria-pressed", "true");
    await view.getByRole("button", { name: "지도", exact: true }).focus();
    await page.keyboard.press("Space");
    await expect(view.getByRole("button", { name: "지도", exact: true })).toHaveAttribute("aria-pressed", "true");
    await page.getByLabel("장소 검색").focus();
    const selectedColor = await view.getByRole("button", { name: "지도", exact: true }).evaluate((node) => getComputedStyle(node).backgroundColor);
    const unselectedColor = await view.getByRole("button", { name: "목록", exact: true }).evaluate((node) => getComputedStyle(node).backgroundColor);
    expect(selectedColor).not.toBe(unselectedColor);
    expect(selectedColor).not.toBe(await page.locator("html").evaluate((node) => getComputedStyle(node).backgroundColor));
    await expect(page.locator("[data-slot=empty]")).toContainText("지도나 목록에서 장소를 선택");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/shadcn-map-${width}.png`, fullPage: true });
  });
}

test("교통 현황의 shadcn 탭은 키보드와 패널 연결을 유지한다", async ({ page }) => {
  test.skip(!process.env.E2E_TRANSPORT_UI_PASSWORD, "로그인 암호 필요");
  await page.goto("/login");
  await page.getByLabel("비밀번호").fill(process.env.E2E_TRANSPORT_UI_PASSWORD!);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.route("**/transport/collector-status", (route) => route.fulfill({ json: { scheduler_enabled: true, enabled_sources: [], sources: [] } }));
  await page.route("**/transport/statistics?**", (route) => route.fulfill({ json: { traffic: [], incidents: [], fuel_prices: [] } }));
  await page.route("**/transport/highways/**", (route) => route.fulfill({ json: { items: [] } }));
  await page.goto("/transport");
  const tabs = page.getByRole("tablist", { name: "교통·유가 정보 보기" });
  await tabs.getByRole("tab", { name: "통합 현황" }).focus();
  await page.keyboard.press("End");
  await page.keyboard.press("Enter");
  await expect(tabs.getByRole("tab", { name: "유가", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tabpanel", { name: "유가", exact: true })).toContainText("수집 주유소 수");
  await expect(page.getByRole("tabpanel")).toHaveCount(1);
});

test("리뷰 회귀: 긴 항구 이름도 모바일에서 선택 해제할 수 있다", async ({ page }) => {
  test.skip(!process.env.E2E_TRANSPORT_UI_PASSWORD, "로그인 암호 필요");
  await page.setViewportSize({ width: 320, height: 900 });
  await page.goto("/login");
  await page.getByLabel("비밀번호").fill(process.env.E2E_TRANSPORT_UI_PASSWORD!);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  const name = "인천국제여객터미널장기주차장교통센터연안항구";
  await page.route("**/transport/features/places?**", (route) => route.fulfill({ json: { items: [{ id: 1, kind: "ferry_port", name, provider_id: "PORT1", source: "data_go_kr_maritime", line_names: [], latitude: null, longitude: null }] } }));
  await page.route("**/transport/ports/timetables?**", (route) => route.fulfill({ json: { items: [], missing_port_ids: ["PORT1"] } }));
  await page.goto("/ferry");
  await page.getByRole("checkbox", { name }).check();
  const remove = page.getByRole("button", { name: `${name} 선택 해제` });
  await expect(remove).toBeVisible();
  expect(await remove.evaluate((node) => { const box = node.getBoundingClientRect(); return box.left >= 0 && box.right <= innerWidth; })).toBe(true);
  expect(await remove.locator("svg").evaluate((node) => node.getBoundingClientRect().right <= innerWidth)).toBe(true);
  await remove.click();
  await expect(page.getByRole("checkbox", { name })).not.toBeChecked();
});
