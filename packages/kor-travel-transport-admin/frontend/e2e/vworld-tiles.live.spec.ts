import { expect, test } from "@playwright/test";

// 실제 타일을 받아 Firefox와 Chromium에서 같은 배경지도를 검증한다.
// URL에는 공개 브라우저 키가 들어 있으므로 원문을 assertion/로그에 남기지 않는다.
test.describe("VWorld 실제 타일", () => {
    test("교통·유가 지도에서 이미지 타일을 받고 오류 안내 없이 확대한다", async ({ page, browserName }) => {
      test.setTimeout(120_000);
      test.skip(!process.env.E2E_TRANSPORT_UI_PASSWORD, "운영 로그인 암호 필요");
      const images: number[] = [];
      page.on("response", (response) => {
        if (response.url().includes("/req/wmts/") && response.headers()["content-type"]?.startsWith("image/")) images.push(response.status());
      });
      await page.goto("/login");
      await page.getByLabel("아이디").fill("admin");
      await page.getByLabel("비밀번호").fill(process.env.E2E_TRANSPORT_UI_PASSWORD!);
      await page.getByRole("button", { name: "로그인", exact: true }).click();
      await expect(page).toHaveURL(/\/$/, { timeout: 30_000 });
      for (const path of ["/map", "/fuel"]) {
        const previous = images.length;
        await page.goto(path);
        await expect(page.getByRole("button", { name: "Zoom in", exact: true })).toBeVisible();
        await expect.poll(() => images.length, { timeout: 30_000, message: "실제 VWorld 이미지 타일 수신" }).toBeGreaterThan(previous);
        const beforeZoom = images.length;
        await page.getByRole("button", { name: "Zoom in", exact: true }).click();
        await expect.poll(() => images.length, { timeout: 30_000, message: "확대한 영역의 실제 타일 수신" }).toBeGreaterThan(beforeZoom);
        await expect.poll(() => page.locator(".maplibregl-map").evaluate((element) => {
          const map = (element as HTMLElement & { _maplibreMap?: { isMoving(): boolean; areTilesLoaded(): boolean } })._maplibreMap;
          return map !== undefined && !map.isMoving() && map.areTilesLoaded();
        }), { timeout: 30_000, message: "확대와 타일 그리기 완료" }).toBe(true);
        await expect(page.getByText("VWorld 지도 타일을 불러오지 못했습니다.", { exact: false })).toHaveCount(0);
        await page.screenshot({ path: `test-results/vworld-${browserName}-${path.slice(1)}.png`, fullPage: true });
      }
      expect(images.every((status) => status === 200)).toBe(true);
    });
  });
