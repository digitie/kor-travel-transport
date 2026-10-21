import { expect, test } from "@playwright/test";

test.beforeEach(() => {
  test.skip(process.env.E2E_FUEL_STATISTICS_LIVE !== "true" || !process.env.E2E_TRANSPORT_UI_PASSWORD,
    "실제 API·DB를 사용하는 유가 UI 검증은 명시적으로 활성화합니다.");
});

test("실제 로그인·통계 API·지도 범위·모바일/데스크톱 화면", async ({ page, request }) => {
  test.setTimeout(120_000);
  // 브라우저 응답을 대체하지 않는다. BFF 인증도 실제로 통과해야 한다.
  expect((await request.get("/api/transport/transport/fuel/statistics")).status()).toBe(401);
  await page.goto("/login?next=/fuel/statistics");
  await page.getByLabel("아이디").fill(process.env.E2E_TRANSPORT_UI_USER ?? "admin");
  await page.getByLabel("비밀번호").fill(process.env.E2E_TRANSPORT_UI_PASSWORD!);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/fuel\/statistics$/);
  const region = page.getByRole("region", { name: "유가 통계", exact: true });
  await expect(region.getByRole("article").first()).toBeVisible({ timeout: 30_000 });
  const timings: Array<{ scope: string; milliseconds: number; groups: number; history: number }> = [];
  for (const scope of ["nationwide", "sido", "sigungu", "highways", "highway", "highway_direction"]) {
    const start = Date.now();
    const response = await page.request.get(`/api/transport/transport/fuel/statistics?scope=${scope}&product_code=B027`);
    expect(response.status()).toBe(200);
    const payload = await response.json();
    expect(payload.items.length).toBeGreaterThan(0);
    expect(payload.items[0].station_count).toBeGreaterThan(0);
    expect(payload.history.length).toBeGreaterThan(0);
    timings.push({ scope, milliseconds: Date.now() - start, groups: payload.items.length, history: payload.history.length });
  }
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.getByLabel("범위", { exact: true }).selectOption("highway_direction");
    await expect(region).toHaveAttribute("aria-busy", "false");
    await expect(region.getByRole("article").first()).toBeVisible();
    await expect(region.getByRole("img", { name: /최근 7일 평균 유가 추이/ })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`fuel-statistics-${width}.png`), fullPage: true });
  }
  await page.goto("/fuel");
  const viewport = page.getByRole("region", { name: "현재 지도 범위 유가 통계" });
  await expect(viewport.getByRole("article").first()).toBeVisible({ timeout: 30_000 });
  await expect(viewport).toHaveAttribute("aria-busy", "false");
  if (process.env.E2E_FUEL_MAP_CAMERA === "true") {
    const endpoint = "/api/transport/transport/features/places";
    const observation: { latest?: URL } = {};
    page.on("request", (req) => { const url = new URL(req.url()); if (url.pathname === endpoint) observation.latest = url; });
    const canvas = page.locator(".maplibregl-canvas");
    await expect(canvas).toBeVisible();
    for (let i = 0; i < 2; i += 1) {
      const zoom = Number(observation.latest?.searchParams.get("zoom") ?? 7);
      const changed = page.waitForResponse((response) => {
        const url = new URL(response.url());
        return url.pathname === endpoint && Number(url.searchParams.get("zoom")) > zoom;
      });
      await page.locator(".maplibregl-ctrl-zoom-in").click();
      expect((await changed).status()).toBe(200);
      await expect(viewport).toHaveAttribute("aria-busy", "false");
    }
    const beforePan = observation.latest?.searchParams.get("min_longitude");
    const panned = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === endpoint && url.searchParams.get("min_longitude") !== beforePan;
    });
    await canvas.focus(); await page.keyboard.press("ArrowRight");
    const response = await panned;
    const result = await response.json();
    expect(response.status()).toBe(200);
    expect(result.fuel_statistics.length).toBeGreaterThan(0);
    for (const item of result.fuel_statistics) expect(item.station_count).toBeLessThanOrEqual(result.total);
    await expect(viewport).toHaveAttribute("aria-busy", "false");
  }
  await page.screenshot({ path: test.info().outputPath("fuel-map-statistics.png"), fullPage: true });
  await test.info().attach("실제 유가 API 응답 시간", { body: JSON.stringify(timings, null, 2), contentType: "application/json" });
});
