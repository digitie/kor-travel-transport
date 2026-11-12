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
  await expect(page.getByRole("navigation", { name: "주요 메뉴", exact: true })).toBeVisible();
}

for (const width of [320, 375, 414, 768, 1023]) {
  test("공통 모바일 상단 가로 메뉴·활성 스크롤·키보드 " + width + "px", async ({ page, baseURL }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await isolatedPage(page, baseURL);
    const nav = page.getByRole("navigation", { name: "주요 메뉴", exact: true });
    await expect(page.locator(".mobile-menu-button")).toHaveCount(0);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.locator(".sidebar-collapse")).toBeHidden();
    await expect(nav.getByRole("link")).toHaveCount(19);
    await expect(nav).toHaveCSS("flex-direction", "row");
    await expect(nav.locator("ul").first()).toHaveCSS("flex-direction", "row");
    await expect(page.getByRole("button", { name: "로그아웃", exact: true })).toBeVisible();
    await expect(page.locator("body")).not.toHaveCSS("pointer-events", "none");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    const wrapper = page.locator(".rail-nav");
    expect(await wrapper.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
    const last = nav.getByRole("link").last();
    await last.focus();
    await expect(last).toBeFocused();
    const linkBox = await last.boundingBox();
    const wrapperBox = await wrapper.boundingBox();
    expect(linkBox!.x).toBeGreaterThanOrEqual(wrapperBox!.x - 1);
    expect(linkBox!.x + linkBox!.width).toBeLessThanOrEqual(wrapperBox!.x + wrapperBox!.width + 1);
    await page.keyboard.press("Escape");
    await expect(nav).toBeVisible();
    await page.goto(requireLoopbackOrigin(baseURL) + "/rail/timetable");
    const active = page.getByRole("navigation", { name: "주요 메뉴", exact: true }).locator('[aria-current="page"]');
    await expect(active).toHaveAttribute("href", "/rail/timetable");
    await expect.poll(async () => {
      const item = await active.boundingBox();
      const menu = await wrapper.boundingBox();
      return Math.abs(item!.x + item!.width / 2 - menu!.x - menu!.width / 2);
    }).toBeLessThan(8);
    if (width === 375 || width === 768) {
      await page.screenshot({ path: test.info().outputPath("mobile-strip-" + width + ".png") });
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  });
}

test("1024px 데스크톱 레일 접힘은 저장되고 좁은 화면의 전체 메뉴를 가리지 않는다", async ({ page, baseURL }) => {
  await page.setViewportSize({ width: 1024, height: 900 });
  await isolatedPage(page, baseURL);
  const shell = page.locator(".transport-shell");
  const rail = page.locator('[data-slot="admin-shell-rail"]');
  await expect(rail).toBeVisible();
  await expect(page.getByRole("navigation", { name: "주요 메뉴", exact: true })).toHaveCSS("flex-direction", "column");
  await page.getByRole("button", { name: "좌측 메뉴 접기", exact: true }).click();
  await expect(shell).toHaveAttribute("data-sidebar-collapsed", "true");
  await expect(rail).toHaveCSS("width", "64px");
  await expect(rail.getByRole("link", { name: "유가 지도", exact: true })).toHaveAttribute("title", "유가 지도");
  await page.reload();
  await expect(shell).toHaveAttribute("data-sidebar-collapsed", "true");
  await expect(rail).toHaveCSS("width", "64px");
  await page.setViewportSize({ width: 375, height: 900 });
  const nav = page.getByRole("navigation", { name: "주요 메뉴", exact: true });
  await expect(nav).toHaveCSS("flex-direction", "row");
  await expect(nav.getByRole("link")).toHaveCount(19);
  await nav.getByRole("link", { name: "유가 지도", exact: true }).scrollIntoViewIfNeeded();
  await expect(nav.getByText("유가 지도", { exact: true })).toBeVisible();
  await expect(page.locator(".sidebar-collapse")).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});

test("모바일·데스크톱 전환 뒤에도 메뉴와 본문 조작이 모달에 막히지 않는다", async ({ page, baseURL }) => {
  await page.setViewportSize({ width: 768, height: 900 });
  await isolatedPage(page, baseURL);
  for (const width of [1024, 375, 1023, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    const nav = page.getByRole("navigation", { name: "주요 메뉴", exact: true });
    await expect(nav).toBeVisible();
    await expect(nav).toHaveCSS("flex-direction", width < 1024 ? "row" : "column");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.locator("body")).not.toHaveCSS("pointer-events", "none");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  }
});

for (const path of ["/parking", "/rail/timetable"]) {
  test("지도 외 화면에도 같은 상단 모바일 메뉴를 사용한다 " + path, async ({ page, baseURL }) => {
    await page.setViewportSize({ width: 768, height: 900 });
    await isolatedPage(page, baseURL, path);
    const nav = page.getByRole("navigation", { name: "주요 메뉴", exact: true });
    await expect(nav).toHaveCSS("flex-direction", "row");
    await expect(nav.getByRole("link")).toHaveCount(19);
    await expect(page.locator(".mobile-menu-button")).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await page.evaluate(() => document.fonts.ready.then(() => undefined));
    const rail = page.locator('[data-slot="admin-shell-rail"]');
    const railHeight = (await rail.boundingBox())!.height;
    await page.setViewportSize({ width: 768, height: 1100 });
    await expect.poll(async () => Math.abs((await rail.boundingBox())!.height - railHeight)).toBeLessThan(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  });
}

test("로그인 화면은 관리 메뉴 없이 공통 로그인 폼만 표시한다", async ({ page, baseURL }) => {
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto(requireLoopbackOrigin(baseURL) + "/login");
  await expect(page.locator('[data-slot="login-form"]')).toBeVisible();
  await expect(page.getByRole("navigation")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "로그아웃", exact: true })).toHaveCount(0);
});

test("긴 화면의 높이만 바뀌어도 문서 스크롤과 입력 포커스를 유지한다", async ({ page, baseURL }) => {
  await page.setViewportSize({ width: 375, height: 300 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await isolatedPage(page, baseURL, "/rail/timetable");
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  const control = page.locator("main input").last();
  await control.focus();
  const maxScroll = await page.evaluate(() => document.documentElement.scrollHeight - innerHeight);
  expect(maxScroll).toBeGreaterThan(200);
  await page.evaluate(() => window.scrollTo({ top: Math.min(document.documentElement.scrollHeight - innerHeight, 280), behavior: "instant" }));
  expect(await page.locator(".rail-nav").evaluate((element) => element.getBoundingClientRect().bottom)).toBeLessThan(0);
  const before = await page.evaluate(() => window.scrollY);
  await expect(control).toBeFocused();
  await page.setViewportSize({ width: 375, height: 280 });
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  expect(await page.evaluate(() => window.scrollY)).toBe(before);
  await expect(control).toBeFocused();
});
