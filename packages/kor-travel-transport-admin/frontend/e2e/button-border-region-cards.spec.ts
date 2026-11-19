import { expect, test, type Locator, type Page } from "@playwright/test";
import { openIsolatedMenuPage, requireLoopbackOrigin } from "./mobile-navigation-fixture";

// FS-7.8 버튼 테두리 회귀(로컬 Button 래퍼의 outline-solid)와 유가 지도 "지역 카드 모두 보기" 토글 삭제.
const pageErrors = new WeakMap<Page, string[]>();
test.beforeEach(({ page, baseURL }) => {
  requireLoopbackOrigin(baseURL);
  const errors: string[] = [];
  pageErrors.set(page, errors);
  page.on("pageerror", (error) => errors.push(`${error.name}: ${error.message}`));
});
test.afterEach(({ page }) => { expect(pageErrors.get(page)).toEqual([]); });

const VIEWPORTS = [["PC", 1280, 900], ["모바일", 390, 844]] as const;
/** 공통 셸 메뉴 버튼(lg 미만). drawer가 열린 동안은 Radix aria-hidden 때문에 role로 잡히지 않는다. */
const menuButton = (page: Page) => page.locator('[data-slot="admin-shell-menu-button"]');

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
// box-shadow ring은 투명하지 않고 spread가 0보다 큰 그림자다(투명 0px 그림자 목록은 링이 아니다).
const hasRing = (shadow: string) => shadow.split(/,(?![^(]*\))/).some((part) => {
  const lengths = [...part.matchAll(/(-?\d+(?:\.\d+)?)px/g)].map((match) => Number(match[1]));
  return lengths.length >= 4 && lengths[3] > 0 && !/rgba\(0, 0, 0, 0\)/.test(part);
});

for (const [label, width, height] of VIEWPORTS) {
  test(`${label} ${width}px 버튼은 Tab 포커스에 2px outline 하나만, 쉬기·hover·누르기에는 테두리가 굵어지지 않는다`, async ({ page, baseURL }) => {
    await page.setViewportSize({ width, height });
    await page.emulateMedia({ reducedMotion: "reduce" });
    // 로컬 Button/buttonVariants(옛 outline-solid 회귀 대상)와 셸 버튼을 함께 본다.
    const targets: [string, string, (page: Page) => Locator][] = [
      ["상단 바 동작 링크(유가 통계)", "/fuel", (p) => p.locator('[data-slot="admin-shell-actions"]').getByRole("link", { name: /유가 통계/ })],
      ["본문 Button(수집 상태)", "/collections", (p) => p.locator('main [data-slot="button"]:visible').first()],
      width >= 1024
        ? ["rail 접기", "/fuel", (p) => p.getByRole("button", { name: "좌측 메뉴 접기", exact: true })]
        : ["메뉴 열기", "/fuel", (p) => menuButton(p)],
    ];
    if (width >= 1024) targets.push(["로그아웃", "/fuel", (p) => p.locator('[data-slot="admin-shell-rail"]').getByRole("button", { name: "로그아웃", exact: true })]);
    for (const [name, path, find] of targets) {
      await openIsolatedMenuPage(page, baseURL, path);
      const target = find(page);
      await expect(target, name).toBeVisible();
      await page.mouse.move(0, height - 1);
      await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
      const rest = await ring(target);
      expect(visibleOutline(rest), `${name} 쉬는 상태 outline ${JSON.stringify(rest)}`).toBe(false);

      await target.hover();
      const hover = await ring(target);
      expect(hover.borderWidth, `${name} hover 테두리`).toBe(rest.borderWidth);
      expect(visibleOutline(hover), `${name} hover outline ${JSON.stringify(hover)}`).toBe(false);

      const box = (await target.boundingBox())!;
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      const active = await ring(target);
      // 마우스로 누를 때는 테두리가 굵어지거나 이중이 되지 않고 1px 넘게 움직이지 않는다.
      expect(active.borderWidth, `${name} active 테두리`).toBe(rest.borderWidth);
      expect(visibleOutline(active), `${name} active outline ${JSON.stringify(active)}`).toBe(false);
      expect(Math.abs(active.y - rest.y), `${name} active 이동`).toBeLessThanOrEqual(1);
      // 클릭이 성립하지 않도록 밖으로 끌어낸 뒤 놓는다.
      await page.mouse.move(0, height - 1);
      await page.mouse.up();
      await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());

      await page.keyboard.press("Shift");
      await target.focus();
      expect(await target.evaluate((node) => node.matches(":focus-visible")), `${name} focus-visible`).toBe(true);
      const focus = await ring(target);
      expect(focus, `${name} Tab 포커스 ${JSON.stringify(focus)}`).toMatchObject({ outlineStyle: "solid", outlineWidth: 2, outlineOffset: 2, borderWidth: rest.borderWidth });
      expect(hasRing(focus.boxShadow), `${name} focus box-shadow ring ${focus.boxShadow}`).toBe(false);
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
    // 접힌 카드가 있으면 그것을, 없으면 첫 카드를 키보드로 고른다. 포커스 때 카드가 보인다.
    const overflowed = page.locator('.fuel-region-marker[data-region-overflow="true"]');
    const target = (await overflowed.count()) > 0 ? overflowed.first() : markers.first();
    await page.keyboard.press("Shift");
    await target.focus();
    await expect(target).toBeFocused();
    await expect(target.locator(".fuel-region-label")).toBeVisible();
    await page.screenshot({ path: test.info().outputPath(`fuel-regions-${width}.png`) });
    await page.keyboard.press("Enter");
    await expect.poll(() => regionResponses, { timeout: 20_000 }).toBeGreaterThan(1);
  });
}
