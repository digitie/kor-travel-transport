import { expect, test } from "@playwright/test";

for (const width of [320, 375, 414, 768, 1440]) {
  test(`교통 탭의 버튼·글자·포커스가 스크롤 없이 보인다 ${width}px`, async ({ page }) => {
    test.skip(!process.env.E2E_TRANSPORT_UI_PASSWORD, "로그인 암호 필요");
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/login");
    await page.getByLabel("비밀번호").fill(process.env.E2E_TRANSPORT_UI_PASSWORD!);
    await page.getByRole("button", { name: "로그인", exact: true }).click();
    await expect(page).toHaveURL(/\/$/);
    await page.route("**/transport/collector-status", route => route.fulfill({ json: { scheduler_enabled: true, enabled_sources: [], sources: [] } }));
    await page.route("**/transport/statistics?**", route => route.fulfill({ json: { traffic: [], incidents: [], fuel_prices: [] } }));
    await page.route("**/transport/highways/**", route => route.fulfill({ json: { items: [] } }));
    await page.goto("/transport");
    const tabs = page.getByRole("tablist", { name: "교통·유가 정보 보기" });
    await expect(tabs).toBeVisible();
    for (const name of ["통합 현황", "고속도로", "유가"]) {
      const button = tabs.getByRole("tab", { name, exact: true });
      await button.click();
      await expect(button).toHaveAttribute("aria-selected", "true");
      await expect(page.getByRole("tabpanel", { name, exact: true })).toBeVisible();
      const geometry = await tabs.evaluate(node => {
        const box = node.getBoundingClientRect();
        return { height: node.clientHeight, scrollHeight: node.scrollHeight, width: node.clientWidth, scrollWidth: node.scrollWidth,
          buttons: Array.from(node.querySelectorAll<HTMLElement>('[role="tab"]')).map(tab => {
            const rect = tab.getBoundingClientRect();
            return { contained: rect.top >= box.top && rect.bottom <= box.bottom && rect.left >= box.left && rect.right <= box.right,
              height: rect.height, fits: tab.scrollHeight <= tab.clientHeight && tab.scrollWidth <= tab.clientWidth };
          }) };
      });
      expect(geometry.scrollHeight).toBeLessThanOrEqual(geometry.height);
      expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.width);
      for (const item of geometry.buttons) {
        expect(item.contained).toBe(true);
        expect(item.fits).toBe(true);
        expect(item.height).toBeGreaterThanOrEqual(44);
      }
    }
    await tabs.getByRole("tab", { name: "통합 현황" }).focus();
    await page.keyboard.press("End");
    await page.keyboard.press("Enter");
    await expect(tabs.getByRole("tab", { name: "유가", exact: true })).toHaveAttribute("aria-selected", "true");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
