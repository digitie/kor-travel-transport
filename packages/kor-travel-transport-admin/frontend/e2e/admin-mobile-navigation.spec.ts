import { expect, test, type Page } from "@playwright/test";
import { openIsolatedMenuPage, requireLoopbackOrigin } from "./mobile-navigation-fixture";

const pageErrors = new WeakMap<Page, string[]>();
test.beforeEach(({ page, baseURL }) => {
  requireLoopbackOrigin(baseURL);
  const errors: string[] = [];
  pageErrors.set(page, errors);
  page.on("pageerror", (error) => errors.push(error.name));
});
test.afterEach(({ page }) => { expect(pageErrors.get(page)).toEqual([]); });
async function isolatedPage(page: Page, baseURL: string | undefined, path = "/fuel") {
  await openIsolatedMenuPage(page, baseURL, path);
  await expect(page.locator("main")).toBeVisible();
}
// map 공용 셸: 1024px 미만은 상단 메뉴 띠(가로 스크롤), 이상은 접을 수 있는 세로 레일. 드로어(dialog)는 쓰지 않는다.
const nav = (page: Page) => page.getByRole("navigation", { name: "주요 메뉴", exact: true });
for (const width of [320, 375, 414, 768, 1023]) {
  test("좁은 화면은 드로어 없이 상단 메뉴 띠로 19개 경로를 보인다 " + width + "px", async ({ page, baseURL }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await isolatedPage(page, baseURL);
    await expect(nav(page).getByRole("link")).toHaveCount(19);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "메뉴 열기", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "로그아웃", exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    const current = nav(page).locator('[aria-current="page"]');
    await expect(current).toHaveAttribute("href", "/fuel");
    await expect(current).toBeInViewport();
    const target = nav(page).getByRole("link", { name: "시간표 조회", exact: true });
    await target.focus();
    await expect(target).toBeInViewport();
    await target.click();
    await expect(page).toHaveURL(/\/rail\/timetable$/);
    await expect(nav(page).locator('[aria-current="page"]')).toHaveAttribute("href", "/rail/timetable");
    if (width === 375 || width === 768) await page.screenshot({ path: test.info().outputPath("map-shell-" + width + ".png") });
  });
}
test("PC 세로 레일 접힘은 저장되고 접힌 링크도 이름과 툴팁을 가진다", async ({ page, baseURL }) => {
  await page.setViewportSize({ width: 1024, height: 900 });
  await isolatedPage(page, baseURL);
  const rail = page.locator('[data-slot="admin-shell-rail"]');
  await expect(rail).toHaveCSS("width", "256px");
  await page.getByRole("button", { name: "좌측 메뉴 접기", exact: true }).click();
  await expect(rail).toHaveCSS("width", "64px");
  const fuel = nav(page).getByRole("link", { name: "유가 지도", exact: true });
  await expect(fuel).toHaveAttribute("title", "유가 지도");
  await page.reload();
  await expect(rail).toHaveCSS("width", "64px");
  await page.setViewportSize({ width: 375, height: 900 });
  await expect(nav(page).getByRole("link", { name: "유가 지도", exact: true }).getByText("유가 지도", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 900 });
  await expect(rail).toHaveCSS("width", "64px");
  await page.getByRole("button", { name: "좌측 메뉴 펼치기", exact: true }).click();
  await expect(rail).toHaveCSS("width", "256px");
  await expect(nav(page).getByRole("link", { name: "유가 지도", exact: true })).not.toHaveAttribute("title", "유가 지도");
});
test("로그인 화면은 관리 메뉴 없이 공통 로그인 폼만 표시한다", async ({ page, baseURL }) => {
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto(requireLoopbackOrigin(baseURL) + "/login");
  await expect(page.locator('[data-slot="login-form"]')).toBeVisible();
  await expect(page.getByRole("navigation")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "메뉴 열기", exact: true })).toHaveCount(0);
});
test("화면 높이만 바뀌어도 문서 위치와 입력 초점을 유지한다", async ({ page, baseURL }) => {
  await page.setViewportSize({ width: 375, height: 300 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await isolatedPage(page, baseURL, "/rail/timetable");
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  const control = page.locator("main input").last();
  await control.focus();
  const maxScroll = await page.evaluate(() => document.documentElement.scrollHeight - innerHeight);
  expect(maxScroll).toBeGreaterThan(0);
  await page.evaluate(() => window.scrollTo({ top: Math.min(document.documentElement.scrollHeight - innerHeight, 100), behavior: "instant" }));
  const before = await page.evaluate(() => window.scrollY);
  await expect(control).toBeFocused();
  await page.setViewportSize({ width: 375, height: 280 });
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  expect(await page.evaluate(() => window.scrollY)).toBe(before);
  await expect(control).toBeFocused();
});
