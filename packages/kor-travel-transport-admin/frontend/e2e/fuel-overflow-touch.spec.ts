import { readFileSync } from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { expect, test } from "@playwright/test";
import { openIsolatedMenuPage, requireLoopbackOrigin } from "./mobile-navigation-fixture";

test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

test("overflow 원점의 실제 CSS는 4px 점과 ring을 보존하며 44px touch를 같은 marker에 전달한다", async ({ page, baseURL }) => {
  const origin = requireLoopbackOrigin(baseURL);
  const source = readFileSync(path.resolve("app/globals.css"), "utf8");
  // 실제 제품 CSS가 SUT다. 지도/provider가 아닌 브라우저 hit testing과 bubbling만 격리한다.
  const rules = source.match(/\.fuel-region-[^{]+\{[^}]*\}/g) ?? [];
  expect(rules.length).toBeGreaterThan(5);
  await test.info().attach("product-css-sha256", { body: createHash("sha256").update(source).digest("hex"), contentType: "text/plain" });
  await page.route((url) => /^https?:$/.test(url.protocol) && url.origin !== origin, (route) => route.abort());
  await page.route(`${origin}/__fixture__/fuel-overflow-touch`, (route) => route.fulfill({ contentType: "text/html", body: `<!doctype html>
    <meta name="viewport" content="width=device-width, initial-scale=1"><style>
    :root{--space-xs:4px;--space-sm:8px;--space-md:16px;--kt-focus:blue}
    body{margin:0}#canvas{position:absolute;inset:0;width:390px;height:400px}
    #marker{position:absolute;left:150px;top:150px;width:120px;height:100px}
    #marker>div{position:relative;width:120px;height:100px}
    ${rules.join("\n")}</style><div id="canvas"></div>
    <!-- 변경 없는 MapMarkerButton passThrough DOM 계약: host none, origin/label은 제품 CSS. -->
    <div id="marker" class="fuel-region-marker" data-region-overflow="true" role="button" tabindex="0" aria-label="검증 지역, 휘발유 1700원/L" style="pointer-events:none">
      <div><span><svg class="fuel-region-link" aria-hidden="true" width="1" height="1"></svg><span class="fuel-region-origin" aria-hidden="true"></span><span class="fuel-region-label">검증 지역 1700원/L</span></span></div>
    </div><script>
    window.markerSelections=0;window.canvasTaps=0;
    document.getElementById('marker').addEventListener('click',()=>{window.markerSelections+=1});
    document.getElementById('canvas').addEventListener('click',()=>{window.canvasTaps+=1});
    </script>` }));
  await openIsolatedMenuPage(page, baseURL, "/__fixture__/fuel-overflow-touch");
  const marker = page.locator("#marker");
  const dot = marker.locator(".fuel-region-origin");
  await expect(marker.locator(".fuel-region-label")).toBeHidden();
  const box = await dot.boundingBox(); expect(box).not.toBeNull();
  const center = { x: box!.x + box!.width / 2, y: box!.y + box!.height / 2 };
  expect(box!.width).toBe(4); expect(box!.height).toBe(4);
  // 진짜 Tab은 기존 host를 focus-visible로 만들고 기존 4px 원점에 2px ring을 유지한다.
  await page.keyboard.press("Tab");
  await expect(marker).toBeFocused();
  await expect(marker.locator(".fuel-region-label")).toBeVisible();
  expect(await dot.evaluate((node) => ({ width: node.getBoundingClientRect().width,
    outline: getComputedStyle(node).outlineWidth, offset: getComputedStyle(node).outlineOffset }))).toEqual({ width: 4, outline: "2px", offset: "2px" });
  // 44px 범위 밖은 지도 쪽으로 그대로 통과한다.
  await page.touchscreen.tap(center.x + 30, center.y);
  expect(await page.evaluate(() => (window as unknown as { canvasTaps: number }).canvasTaps)).toBe(1);
  // 4px 점 밖 / 44px target 안을 실제 touch로 누른다. DOM .click()으로 우회하지 않는다.
  await page.touchscreen.tap(center.x + 18, center.y);
  expect(await page.evaluate(() => (window as unknown as { markerSelections: number }).markerSelections)).toBe(1);
  expect(await dot.evaluate((node) => ({ width: getComputedStyle(node, "::before").width,
    height: getComputedStyle(node, "::before").height }))).toEqual({ width: "44px", height: "44px" });
});
