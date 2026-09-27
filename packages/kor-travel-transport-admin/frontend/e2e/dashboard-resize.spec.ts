import { expect, test } from "@playwright/test";

test("실제 통계 차트는 데스크톱에서 모바일로 줄여도 카드 밖으로 잘리지 않는다", async ({ page }) => {
  test.skip(!process.env.E2E_TRANSPORT_UI_PASSWORD, "운영 로그인 암호 필요");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.route("**/api/transport/transport/collector-status", (route) => route.fulfill({ json: { scheduler_enabled: true, enabled_sources: [], sources: [] } }));
  await page.route("**/api/transport/transport/statistics?days=7", (route) => route.fulfill({ json: {
    traffic: Array.from({ length: 8 }, (_, index) => ({ route_no: `00${index}0`, direction: "상행", observations: 1, average_speed: 80 + index })),
    incidents: [],
    fuel_prices: ["B027", "B034", "C004", "D047", "K015"].map((product_code) => ({ product_code, stations: 10, average_price: 1800 })),
  } }));
  await page.route("**/api/transport/transport/highways/**", (route) => route.fulfill({ json: { items: [] } }));
  await page.goto("/login");
  await page.getByLabel("아이디").fill("admin");
  await page.getByLabel("비밀번호").fill(process.env.E2E_TRANSPORT_UI_PASSWORD!);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page.getByRole("img", { name: "노선별 평균 속도 그래프", exact: true }).locator("canvas")).toBeVisible();
  await expect(page.getByRole("list", { name: "유종별 평균 가격 그래프 수치" }).locator("li")).toHaveCount(5);
  for (const width of [375, 320, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect.poll(() => page.locator(".panel, .transport-chart canvas").evaluateAll((nodes) => nodes.every((node) => {
      const bounds = node.getBoundingClientRect();
      return bounds.width > 0 && bounds.left >= 0 && bounds.right <= innerWidth;
    }))).toBe(true);
    await expect(page.locator(".error")).toHaveCount(0);
  }
});
