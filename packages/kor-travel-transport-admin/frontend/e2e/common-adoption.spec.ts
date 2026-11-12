import { expect, test } from "@playwright/test";

for (const width of [320, 375, 768, 1440]) test(`공통 RHF 로그인·실패 재시도·폰트 ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  await page.goto("/login");
  const form = page.locator('[data-slot="login-form"]');
  const username = page.getByLabel("아이디", { exact: true });
  const password = page.getByLabel("비밀번호", { exact: true });
  await expect(username).toBeEnabled(); await expect(username).toHaveValue("admin");
  let attempts = 0;
  await page.route("**/api/auth/login", async (route) => {
    attempts += 1;
    await route.fulfill({ status: attempts === 1 ? 401 : 429, json: { detail: "서버 원문을 표시하면 안 됩니다." } });
  });
  await password.fill("isolated-invalid-input");
  await password.press("Enter");
  await expect(form.getByRole("alert")).toContainText("아이디와 비밀번호");
  await expect(password).toHaveValue("");
  await password.fill("isolated-retry");
  await password.press("Enter");
  await expect(form.getByRole("alert")).toContainText("로그인 시도가 너무 많습니다");
  await expect(password).toHaveValue("");
  expect(attempts).toBe(2);
  await expect(page.getByText("서버 원문을 표시하면 안 됩니다.")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(await page.locator("body").evaluate((node) => getComputedStyle(node).fontFamily)).toContain("Pretendard");
  await page.screenshot({ path: `test-results/common-login-${width}.png`, fullPage: true });
});

for (const width of [375, 1440]) test(`지도 다중 필터 입력·칩·Escape·10개 상한 ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  await page.context().addCookies([{ name: "kor_travel_transport_admin_session", value: "isolated-common-ui", url: test.info().project.use.baseURL!, httpOnly: true, sameSite: "Strict" }]);
  const sources = Array.from({ length: 11 }, (_, index) => `fixture-source-${String(index).padStart(2, "0")}`);
  await page.route("**://*.vworld.kr/**", (route) => route.abort());
  await page.route("**/api/transport/**", (route) => route.fulfill({ json: { items: [], total: 0, truncated: false, available_sources: sources } }));
  await page.goto("/fuel");
  const toggle = page.locator('[data-slot="map-filter-trigger"]');
  if (await toggle.isVisible()) await toggle.click();
  const input = page.getByRole("combobox", { name: "데이터 출처" });
  await input.click();
  for (const source of sources.slice(0, 10)) await page.getByRole("option", { name: source, exact: true }).click();
  await expect(page.getByRole("option", { name: sources[10], exact: true })).toBeDisabled();
  await input.press("Escape");
  await expect(page.getByRole("listbox")).toHaveCount(0);
  await expect(page.getByRole("button", { name: `${sources[0]} 선택 해제`, exact: true })).toHaveCount(1);
  await page.getByRole("button", { name: `${sources[0]} 선택 해제`, exact: true }).click();
  await input.fill(sources[10]);
  await input.press("ArrowDown"); await input.press("Enter"); await input.press("Escape");
  await expect(page.getByRole("button", { name: `${sources[10]} 선택 해제`, exact: true })).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

// 공통 패키지 수정 뒤에도 남겨 둘 실제 CSS/Radix 회귀 게이트다.
test("공통 지도 탭은 활성 작업면 하나만 노출한다", async ({ page }) => {
  await page.context().addCookies([{ name: "kor_travel_transport_admin_session", value: "isolated-common-ui", url: test.info().project.use.baseURL!, httpOnly: true, sameSite: "Strict" }]);
  await page.route("**/api/transport/**", (route) => route.fulfill({ json: { items: [], total: 0, truncated: false } }));
  await page.route("**://*.vworld.kr/**", (route) => route.abort());
  await page.goto("/fuel");
  await expect(page.locator('[data-slot="map-stage"]:visible')).toHaveCount(1);
  await page.getByRole("tab", { name: "목록", exact: true }).click();
  await expect(page.locator('[data-slot="map-stage"]:visible')).toHaveCount(1);
  await expect(page.locator('[data-slot="map-stage"][data-view="list"]')).toBeVisible();
});

test("공통 수평 탭은 탭 목록 아래 본문을 배치한다", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 900 });
  await page.context().addCookies([{ name: "kor_travel_transport_admin_session", value: "isolated-common-ui", url: test.info().project.use.baseURL!, httpOnly: true, sameSite: "Strict" }]);
  await page.route("**/api/transport/**", (route) => route.fulfill({ json: {
    airports: [], current: { items: [] }, collector: { latest_snapshot_observed_at: null, latest_snapshot_collected_at: null }, holidays: null,
  } }));
  await page.goto("/parking");
  await expect(page.locator('.parking-views[data-slot="tabs"]')).toHaveCSS("flex-direction", "column");
});
