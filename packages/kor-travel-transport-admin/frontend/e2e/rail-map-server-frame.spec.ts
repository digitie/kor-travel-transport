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
  });
}
