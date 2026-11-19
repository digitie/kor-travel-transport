import { expect, test, type Locator, type Page } from "@playwright/test";
import { openIsolatedMenuPage, requireLoopbackOrigin } from "./mobile-navigation-fixture";
import { adminMenuButton, adminTitle } from "./admin-shell-fixture";

// @kor-travel/ui 0.2.3 공용 관리자 셸 채택(T-222 소비자): 한 줄 "교통 - 페이지" 제목, 좌측 drawer,
// 단일 포커스 outline(FS-7.8), 유가 지도의 "지역 카드 모두 보기" 토글 삭제.
const pageErrors = new WeakMap<Page, string[]>();
test.beforeEach(({ page, baseURL }) => {
  requireLoopbackOrigin(baseURL);
  const errors: string[] = [];
  pageErrors.set(page, errors);
  page.on("pageerror", (error) => errors.push(`${error.name}: ${error.message}`));
});
test.afterEach(({ page }) => { expect(pageErrors.get(page)).toEqual([]); });

const VIEWPORTS = [["PC", 1280, 900], ["모바일", 390, 844]] as const;
const PAGES = [["/", "운영 홈"], ["/fuel", "유가 지도"], ["/collections", "수집 상태"], ["/rail/timetable", "시간표 조회"]] as const;

for (const [label, width, height] of VIEWPORTS) {
  test(`${label} ${width}px 맨 위 한 줄은 '교통 - 페이지' 제목과 작은 설명만 둔다`, async ({ page, baseURL }) => {
    await page.setViewportSize({ width, height });
    for (const [path, name] of PAGES) {
      await openIsolatedMenuPage(page, baseURL, path);
      const header = page.locator('[data-slot="admin-shell-header"]');
      await expect(header).toHaveCount(1);
      await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
      const title = adminTitle(page, name);
      await expect(title).toBeVisible();
      await expect(header.locator("h1")).toHaveText(`교통 - ${name}`);
      // 한 줄(약 48px) 상단 바이고 문서 맨 위에 붙어 있다.
      const box = (await header.boundingBox())!;
      expect(box.y).toBeCloseTo(0, 0);
      expect(box.height).toBeLessThanOrEqual(56);
      const description = header.locator('[data-slot="admin-shell-description"]');
      await expect(description).toHaveCount(1);
      expect(await description.getAttribute("title")).toBeTruthy();
      const small = await description.evaluate((node) => Number.parseFloat(getComputedStyle(node).fontSize));
      const big = await title.evaluate((node) => Number.parseFloat(getComputedStyle(node).fontSize));
      expect(small).toBeLessThan(big);
      if (width >= 1024) await expect(description).toBeVisible();
      // 옛 워드마크·앱 설명 문구는 화면 어디에도 없다.
      await expect(page.getByText(/kor-travel-transport/)).toHaveCount(0);
      // 본문(main) 안에 두 번째 제목 줄을 그리지 않는다.
      await expect(page.locator("main#main-content [data-slot='admin-shell-header']")).toHaveCount(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    }
    await page.screenshot({ path: test.info().outputPath(`admin-title-${width}.png`) });
  });
}

test("모바일 390px 메뉴는 좌측 drawer로 접히고 닫기 버튼·Escape·링크 이동으로 닫힌다", async ({ page, baseURL }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openIsolatedMenuPage(page, baseURL, "/fuel");
  await expect(page.locator('[data-slot="admin-shell-rail"]')).toBeHidden();
  const menuButton = adminMenuButton(page);
  const drawer = page.getByRole("dialog");
  await expect(drawer).toHaveCount(0);
  await menuButton.click();
  await expect(drawer).toBeVisible();
  const box = (await drawer.boundingBox())!;
  expect(box.x).toBeCloseTo(0, 0);
  expect(box.width).toBeLessThanOrEqual(280);
  await expect(drawer.getByRole("navigation", { name: "주요 메뉴", exact: true }).getByRole("link")).toHaveCount(19);
  await page.screenshot({ path: test.info().outputPath("admin-drawer-390.png") });
  await drawer.getByRole("button", { name: "메뉴 닫기", exact: true }).click();
  await expect(drawer).toHaveCount(0);
  await expect(menuButton).toBeFocused();
  await menuButton.click();
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await menuButton.click();
  await drawer.getByRole("link", { name: "수집 상태", exact: true }).click();
  await expect(page).toHaveURL(/\/collections$/);
  await expect(drawer).toHaveCount(0);
  await expect(adminTitle(page, "수집 상태")).toBeVisible();
  await expect(page.locator("main#main-content")).toBeFocused();
});

type Ring = { outlineStyle: string; outlineWidth: number; outlineOffset: number; borderWidth: number; boxShadow: string; y: number };
async function ring(locator: Locator): Promise<Ring> {
  return locator.evaluate((node) => {
    const style = getComputedStyle(node);
    return {
      outlineStyle: style.outlineStyle,
      outlineWidth: Number.parseFloat(style.outlineWidth),
      outlineOffset: Number.parseFloat(style.outlineOffset),
      borderWidth: Number.parseFloat(style.borderTopWidth),
      boxShadow: style.boxShadow,
      y: node.getBoundingClientRect().y,
    };
  });
}
const visibleOutline = (value: Ring) => value.outlineStyle !== "none" && value.outlineWidth > 0;

for (const [label, width, height] of VIEWPORTS) {
  test(`${label} ${width}px 버튼은 Tab 포커스에 2px outline 하나만, 쉬기·누르기에는 테두리가 굵어지지 않는다`, async ({ page, baseURL }) => {
    await page.setViewportSize({ width, height });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await openIsolatedMenuPage(page, baseURL, "/fuel");
    const targets: [string, Locator][] = [
      ["상단 바 동작(유가 통계)", page.locator('[data-slot="admin-shell-actions"]').getByRole("link", { name: "유가 통계", exact: true })],
      ["지도 보기 탭", page.getByRole("tab", { name: /지도/ }).first()],
      width >= 1024
        ? ["rail 접기", page.getByRole("button", { name: "좌측 메뉴 접기", exact: true })]
        : ["메뉴 열기", adminMenuButton(page)],
    ];
    if (width >= 1024) targets.push(["로그아웃", page.locator('[data-slot="admin-shell-rail"]').getByRole("button", { name: "로그아웃", exact: true })]);
    for (const [name, target] of targets) {
      await expect(target, name).toBeVisible();
      await page.mouse.move(0, height - 1);
      await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
      const rest = await ring(target);
      expect(visibleOutline(rest), `${name} 쉬는 상태 outline ${JSON.stringify(rest)}`).toBe(false);

      await target.hover();
      const hover = await ring(target);
      expect(hover.borderWidth, `${name} hover 테두리`).toBe(rest.borderWidth);
      expect(visibleOutline(hover), `${name} hover outline`).toBe(false);

      const box = (await target.boundingBox())!;
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      const active = await ring(target);
      // 마우스로 누를 때는 테두리가 굵어지거나 이중이 되지 않고 1px 넘게 움직이지 않는다.
      expect(active.borderWidth, `${name} active 테두리`).toBe(rest.borderWidth);
      expect(visibleOutline(active), `${name} active outline ${JSON.stringify(active)}`).toBe(false);
      expect(Math.abs(active.y - rest.y), `${name} active 이동`).toBeLessThanOrEqual(1);
      await page.mouse.move(0, height - 1);
      await page.mouse.up();
      await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());

      await page.keyboard.press("Shift");
      await target.focus();
      expect(await target.evaluate((node) => node.matches(":focus-visible")), `${name} focus-visible`).toBe(true);
      const focus = await ring(target);
      expect(focus, `${name} Tab 포커스 ${JSON.stringify(focus)}`).toMatchObject({ outlineStyle: "solid", outlineWidth: 2, outlineOffset: 2, borderWidth: rest.borderWidth });
      // ring(box-shadow)을 outline에 겹쳐 이중 링을 만들지 않는다.
      expect(focus.boxShadow === "none" || !/\d+px \d+px 0px \d+px/.test(focus.boxShadow), `${name} focus box-shadow ${focus.boxShadow}`).toBe(true);
      await page.screenshot({ path: test.info().outputPath(`focus-${width}-${name}.png`), clip: { x: Math.max(0, box.x - 8), y: Math.max(0, box.y - 8), width: box.width + 16, height: box.height + 16 } });
    }
  });
}

const fuelRegions = [
  ["opinet:11", "서울특별시", 126.98, 37.57], ["opinet:26", "부산광역시", 129.07, 35.18], ["opinet:41", "경기도", 127.2, 37.4],
  ["opinet:42", "강원특별자치도", 128.2, 37.8], ["opinet:46", "전라남도", 126.9, 34.8], ["opinet:47", "경상북도", 128.7, 36.4],
].map(([region_key, label, longitude, latitude]) => ({ region_key, label, product_code: "B027", average_price: 1700, station_count: 10, longitude, latitude }));

for (const [label, width, height] of VIEWPORTS) {
  test(`${label} ${width}px 유가 지도에는 '지역 카드 모두 보기' 토글과 목록이 없고 지역 마커는 키보드로 고른다`, async ({ page, baseURL }) => {
    await page.setViewportSize({ width, height });
    const origin = requireLoopbackOrigin(baseURL);
    let regionResponses = 0;
    await openIsolatedMenuPage(page, baseURL, "/login");
    await page.route((url) => url.origin === origin && url.pathname.endsWith("/features/places"), (route) => {
      regionResponses += 1;
      return route.fulfill({ json: { items: [], total: fuelRegions.length, truncated: false, clustered: true, clusters: [], fuel_regions: fuelRegions, fuel_statistics: [] } });
    });
    await page.goto(`${origin}/fuel`);
    await expect(adminTitle(page, "유가 지도")).toBeVisible();
    const markers = page.locator(".fuel-region-marker");
    await expect.poll(() => regionResponses, { timeout: 20_000 }).toBeGreaterThan(0);
    await expect(markers).toHaveCount(fuelRegions.length, { timeout: 20_000 });
    await expect(page.getByRole("button", { name: /지역 카드/ })).toHaveCount(0);
    await expect(page.getByRole("region", { name: "모든 지역 유가" })).toHaveCount(0);
    await expect(page.locator(".fuel-region-access")).toHaveCount(0);
    // 모든 지역 마커(공간이 모자라 접은 것 포함)는 탭 순서에 있고 접근 이름에 가격을 가진다.
    for (const marker of await markers.all()) {
      await expect(marker).toHaveAttribute("role", "button");
      expect(await marker.evaluate((node) => (node as HTMLElement).tabIndex)).toBe(0);
      await expect(marker).not.toHaveAttribute("aria-hidden", "true");
      await expect(marker).toHaveAttribute("aria-label", /원\/L/);
    }
    const first = markers.first();
    await page.keyboard.press("Shift");
    await first.focus();
    await expect(first).toBeFocused();
    await expect(first.locator(".fuel-region-label")).toBeVisible();
    await page.screenshot({ path: test.info().outputPath(`fuel-regions-${width}.png`) });
  });
}
