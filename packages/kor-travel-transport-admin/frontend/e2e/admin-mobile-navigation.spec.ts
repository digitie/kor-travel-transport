import { expect, test, type Page } from "@playwright/test";
import { openIsolatedMenuPage, requireLoopbackOrigin } from "./mobile-navigation-fixture";
import { adminMenuButton, adminTitle } from "./admin-shell-fixture";

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
// 공용 관리자 셸: 1024px 미만은 상단 바 메뉴 버튼으로 여는 좌측 drawer, 이상은 접을 수 있는 세로 rail.
// drawer가 열리면 메뉴가 DOM에 두 번 있으므로 dialog 범위 안에서 찾는다.
const drawer = (page: Page) => page.getByRole("dialog");
const drawerNav = (page: Page) => drawer(page).getByRole("navigation", { name: "주요 메뉴", exact: true });
const railNav = (page: Page) => page.locator('[data-slot="admin-shell-rail"]').getByRole("navigation", { name: "주요 메뉴", exact: true });
for (const width of [320, 375, 414, 768, 1023]) {
  test("좁은 화면은 상단 바 메뉴 버튼으로 좌측 drawer를 열어 19개 경로를 보인다 " + width + "px", async ({ page, baseURL }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await isolatedPage(page, baseURL);
    await expect(page.locator('[data-slot="admin-shell-rail"]')).toBeHidden();
    await expect(page.getByRole("navigation", { name: "주요 메뉴", exact: true })).toHaveCount(0);
    await expect(adminTitle(page, "유가 지도")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    const menuButton = adminMenuButton(page);
    await expect(menuButton).toBeVisible();
    await expect(menuButton).toHaveAccessibleName("메뉴 열기");
    await menuButton.click();
    await expect(drawer(page)).toBeVisible();
    const drawerBox = (await drawer(page).boundingBox())!;
    expect(drawerBox.x).toBeCloseTo(0, 0);
    expect(drawerBox.width).toBeLessThanOrEqual(280);
    await expect(drawerNav(page).getByRole("link")).toHaveCount(19);
    await expect(drawer(page).getByRole("button", { name: "로그아웃", exact: true })).toBeVisible();
    const current = drawerNav(page).locator('[aria-current="page"]');
    await expect(current).toHaveAttribute("href", "/fuel");
    const target = drawerNav(page).getByRole("link", { name: "시간표 조회", exact: true });
    await target.focus();
    await expect(target).toBeInViewport();
    if (width === 375 || width === 768) await page.screenshot({ path: test.info().outputPath("admin-drawer-" + width + ".png") });
    await target.click();
    await expect(page).toHaveURL(/\/rail\/timetable$/);
    await expect(drawer(page)).toHaveCount(0);
    await expect(page.locator("main#main-content")).toBeFocused();
    await menuButton.click();
    await expect(drawerNav(page).locator('[aria-current="page"]')).toHaveAttribute("href", "/rail/timetable");
    await page.keyboard.press("Escape");
    await expect(drawer(page)).toHaveCount(0);
    await expect(menuButton).toBeFocused();
  });
}
test("PC 세로 rail 접힘은 저장되고 접힌 링크도 이름과 툴팁을 가진다", async ({ page, baseURL }) => {
  await page.setViewportSize({ width: 1024, height: 900 });
  await isolatedPage(page, baseURL);
  const rail = page.locator('[data-slot="admin-shell-rail"]');
  await expect(rail).toHaveCSS("width", "256px");
  await expect(adminMenuButton(page)).toBeHidden();
  await page.getByRole("button", { name: "좌측 메뉴 접기", exact: true }).click();
  await expect(rail).toHaveCSS("width", "64px");
  const fuel = railNav(page).getByRole("link", { name: "유가 지도", exact: true });
  await expect(fuel).toHaveAttribute("title", "유가 지도");
  await page.reload();
  await expect(rail).toHaveCSS("width", "64px");
  // 좁은 화면의 drawer는 rail 접힘과 무관하게 라벨을 모두 보인다.
  await page.setViewportSize({ width: 375, height: 900 });
  await adminMenuButton(page).click();
  await expect(drawerNav(page).getByRole("link", { name: "유가 지도", exact: true }).getByText("유가 지도", { exact: true })).toBeVisible();
  // lg 이상으로 넓히면 열린 drawer를 닫는다.
  await page.setViewportSize({ width: 1280, height: 900 });
  await expect(drawer(page)).toHaveCount(0);
  await expect(rail).toHaveCSS("width", "64px");
  await page.getByRole("button", { name: "좌측 메뉴 펼치기", exact: true }).click();
  await expect(rail).toHaveCSS("width", "256px");
  await expect(railNav(page).getByRole("link", { name: "유가 지도", exact: true })).not.toHaveAttribute("title", "유가 지도");
});
test("로그인 화면은 관리 메뉴 없이 공통 로그인 폼만 표시한다", async ({ page, baseURL }) => {
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto(requireLoopbackOrigin(baseURL) + "/login");
  await expect(page.locator('[data-slot="login-form"]')).toBeVisible();
  await expect(page.getByRole("navigation")).toHaveCount(0);
  await expect(adminMenuButton(page)).toHaveCount(0);
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
