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
async function openMenu(page: Page) {
  await page.getByRole("button", { name: "메뉴 열기", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "내비게이션 메뉴", exact: true });
  await expect(dialog).toBeVisible();
  return dialog;
}
for (const width of [320, 375, 414, 768, 1023]) {
  test("Geo형 모바일 왼쪽 드로어·세로 메뉴·키보드 " + width + "px", async ({ page, baseURL }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await isolatedPage(page, baseURL);
    await expect(page.getByRole("navigation", { name: "주요 메뉴", exact: true })).toHaveCount(0);
    const dialog = await openMenu(page);
    const nav = dialog.getByRole("navigation", { name: "주요 메뉴", exact: true });
    await expect(nav.getByRole("link")).toHaveCount(19);
    await expect(nav).toHaveCSS("flex-direction", "column");
    await expect(nav.locator("ul").first()).toHaveCSS("flex-direction", "column");
    await expect(dialog.getByRole("button", { name: "메뉴 닫기", exact: true })).toBeFocused();
    const box = (await dialog.boundingBox())!;
    expect(box.x).toBeCloseTo(0, 0);
    expect(box.width).toBeLessThanOrEqual(Math.min(296, width * .88) + 1);
    const last = nav.getByRole("link").last();
    await last.focus();
    await expect(last).toBeFocused();
    await page.keyboard.press("Tab");
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    if (width === 375 || width === 768) await page.screenshot({ path: test.info().outputPath("geo-drawer-" + width + ".png") });
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(page.getByRole("button", { name: "메뉴 열기", exact: true })).toBeFocused();
    await expect(page.locator("body")).not.toHaveCSS("pointer-events", "none");
    await openMenu(page);
    await page.getByRole("link", { name: "시간표 조회", exact: true }).click();
    await expect(page).toHaveURL(/\/rail\/timetable$/);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    const reopened = await openMenu(page);
    await expect(reopened.locator('[aria-current="page"]')).toHaveAttribute("href", "/rail/timetable");
    await page.getByTestId("mobile-menu-backdrop").click({ position: { x: width - 4, y: 100 } });
    await expect(reopened).toHaveCount(0);
    await expect(page.getByRole("button", { name: "메뉴 열기", exact: true })).toBeFocused();
  });
}
test("PC 세로 레일 접힘은 저장되고 모바일 드로어에는 전체 이름이 보인다", async ({ page, baseURL }) => {
  await page.setViewportSize({ width: 1024, height: 900 });
  await isolatedPage(page, baseURL);
  const shell = page.locator(".transport-shell");
  const rail = page.locator('[data-slot="admin-shell-rail"]');
  await expect(rail).toHaveCSS("width", "256px");
  await expect(page.getByRole("navigation", { name: "주요 메뉴", exact: true })).toHaveCSS("flex-direction", "column");
  await page.getByRole("button", { name: "좌측 메뉴 접기", exact: true }).click();
  await expect(shell).toHaveAttribute("data-sidebar-collapsed", "true");
  await expect(rail).toHaveCSS("width", "64px");
  await expect(rail.getByRole("link", { name: "유가 지도", exact: true })).toHaveAttribute("title", "유가 지도");
  await page.reload();
  await expect(rail).toHaveCSS("width", "64px");
  await page.setViewportSize({ width: 375, height: 900 });
  const dialog = await openMenu(page);
  await expect(dialog.getByRole("link", { name: "유가 지도", exact: true }).getByText("유가 지도", { exact: true })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "좌측 메뉴 접기", exact: true })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 1280, height: 900 });
  await expect(rail).toHaveCSS("width", "64px");
  await page.getByRole("button", { name: "좌측 메뉴 펼치기", exact: true }).click();
  await expect(rail).toHaveCSS("width", "256px");
  await page.screenshot({ path: test.info().outputPath("geo-desktop-vertical-1280.png") });
});
test("열린 드로어에서 PC로 전환하면 모달 잠금과 초점을 복구한다", async ({ page, baseURL }) => {
  await page.setViewportSize({ width: 768, height: 900 });
  await isolatedPage(page, baseURL);
  await openMenu(page);
  for (const width of [1024, 375, 1023, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    if (width < 1024) {
      if (width === 375) await openMenu(page);
      await expect(page.getByRole("dialog")).toBeVisible();
    } else {
      await expect(page.getByRole("dialog")).toHaveCount(0);
      await expect(page.locator("main")).toBeFocused();
      await expect(page.locator("body")).not.toHaveCSS("pointer-events", "none");
      await expect(page.getByRole("navigation", { name: "주요 메뉴", exact: true })).toHaveCSS("flex-direction", "column");
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  }
  await page.setViewportSize({ width: 375, height: 900 });
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
for (const path of ["/parking", "/rail/timetable"]) {
  test("지도 외 화면도 Geo형 드로어와 고정 높이 상단 바를 쓴다 " + path, async ({ page, baseURL }) => {
    await page.setViewportSize({ width: 768, height: 900 });
    await isolatedPage(page, baseURL, path);
    const dialog = await openMenu(page);
    await expect(dialog.getByRole("navigation", { name: "주요 메뉴", exact: true }).getByRole("link")).toHaveCount(19);
    await page.keyboard.press("Escape");
    const header = page.locator(".mobile-topbar");
    const height = (await header.boundingBox())!.height;
    await page.setViewportSize({ width: 768, height: 1100 });
    await expect.poll(async () => Math.abs((await header.boundingBox())!.height - height)).toBeLessThan(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  });
}
test("로그인 화면은 관리 메뉴 없이 공통 로그인 폼만 표시한다", async ({ page, baseURL }) => {
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto(requireLoopbackOrigin(baseURL) + "/login");
  await expect(page.locator('[data-slot="login-form"]')).toBeVisible();
  await expect(page.getByRole("navigation")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "메뉴 열기", exact: true })).toHaveCount(0);
});
test("닫힌 드로어에서 화면 높이만 바뀌어도 문서 위치와 입력 초점을 유지한다", async ({ page, baseURL }) => {
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
  await expect(page.getByRole("navigation", { name: "주요 메뉴", exact: true })).toHaveCount(0);
});
