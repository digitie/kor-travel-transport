import { expect, test } from "@playwright/test";
import { openIsolatedMenuPage, requireLoopbackOrigin } from "./mobile-navigation-fixture";

test.use({ javaScriptEnabled: false });

for (const width of [1280, 375]) {
  test("역 지도 작업면은 JavaScript 실행 전에도 유지된다 " + width + "px", async ({ page, baseURL }) => {
    requireLoopbackOrigin(baseURL);
    await page.setViewportSize({ width, height: 900 });
    await openIsolatedMenuPage(page, baseURL, "/rail");
    await expect(page.getByRole("heading", { name: "철도", exact: true })).toBeVisible();
    const guide = page.getByRole("region", { name: "철도 역 지도", exact: true });
    await expect(guide).toBeAttached();
    const box = await guide.boundingBox();
    await test.info().attach("server-map-frame", {
      body: JSON.stringify({ viewport: { width, height: 900 }, box, javaScriptEnabled: false }),
      contentType: "application/json",
    });
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(320);
    await expect(guide.locator(".map-workbench")).toHaveCount(1);
    await expect(guide.getByRole("tab", { name: "지도", exact: true })).toBeVisible();
    await expect(guide.getByRole("tab", { name: "목록", exact: true })).toBeVisible();
    // isVisible()는 overflow로 완전히 잘린 기존 문구도 true였다. 실제 글자 영역을 검사한다.
    const loading = guide.locator("p").filter({ hasText: /^지도를 준비하는 중입니다…$/ });
    await expect(loading).toBeVisible();
    const geometry = await loading.evaluate((element) => {
      if (!(element instanceof HTMLElement)) throw new Error("지도 로딩 문구가 HTML 요소가 아닙니다.");
      const range = document.createRange();
      range.selectNodeContents(element);
      const text = range.getBoundingClientRect();
      let left = Math.max(text.left, 0);
      let top = Math.max(text.top, 0);
      let right = Math.min(text.right, document.documentElement.clientWidth);
      let bottom = Math.min(text.bottom, window.innerHeight);
      const clippingAncestors: { className: string; overflowX: string; overflowY: string }[] = [];
      for (let ancestor: HTMLElement | null = element; ancestor; ancestor = ancestor.parentElement) {
        const style = getComputedStyle(ancestor);
        const clipX = /^(auto|scroll|hidden|clip)$/.test(style.overflowX);
        const clipY = /^(auto|scroll|hidden|clip)$/.test(style.overflowY);
        if (!clipX && !clipY) continue;
        const box = ancestor.getBoundingClientRect();
        const paddingLeft = box.left + ancestor.clientLeft;
        const paddingTop = box.top + ancestor.clientTop;
        if (clipX) {
          left = Math.max(left, paddingLeft);
          right = Math.min(right, paddingLeft + ancestor.clientWidth);
        }
        if (clipY) {
          top = Math.max(top, paddingTop);
          bottom = Math.min(bottom, paddingTop + ancestor.clientHeight);
        }
        clippingAncestors.push({ className: ancestor.className, overflowX: style.overflowX, overflowY: style.overflowY });
      }
      const visibleArea = Math.max(0, right - left) * Math.max(0, bottom - top);
      return {
        textRect: { x: text.x, y: text.y, width: text.width, height: text.height },
        clippedRect: { left, top, right, bottom }, visibleArea,
        visibleRatio: text.width * text.height > 0 ? visibleArea / (text.width * text.height) : 0,
        clippingAncestors,
      };
    });
    await test.info().attach("server-map-loading-text-clipping", {
      body: JSON.stringify({ viewport: { width, height: 900 }, geometry, javaScriptEnabled: false }),
      contentType: "application/json",
    });
    expect(geometry.textRect.width).toBeGreaterThan(0);
    expect(geometry.textRect.height).toBeGreaterThan(0);
    expect(geometry.visibleArea).toBeGreaterThan(0);
    expect(geometry.visibleRatio).toBeGreaterThanOrEqual(0.99);
    await expect(loading).toHaveAttribute("role", "status");
  });
}
