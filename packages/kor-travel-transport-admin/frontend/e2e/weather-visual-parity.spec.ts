import { expect, test, type Locator, type Page } from "@playwright/test";

const widths = [320, 375, 414, 768, 1440];
const paths = ["/map", "/admin/dagster"] as const;
const stamp = "2026-09-28T03:00:00Z";
const dagster = { data: {
  repositoriesOrError: { __typename: "RepositoryConnection", nodes: [{ schedules: [{
    name: "airport_schedule", cronSchedule: "*/5 * * * *", pipelineName: "airport_collection_job", scheduleState: { status: "RUNNING" },
  }] }] },
  runsOrError: { __typename: "Runs", results: [{
    runId: "visual-parity-run", jobName: "airport_collection_job", status: "SUCCESS",
    startTime: Date.parse(stamp) / 1000 - 60, endTime: Date.parse(stamp) / 1000,
  }] },
  activeRuns: { __typename: "Runs", results: [] },
} };

async function loginWithFixtures(page: Page, pathname: string) {
  const unexpected: string[] = [];
  // 로그인 전에 차단하여 초기 화면·prefetch도 제공자에 도달하지 않는다.
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    const origin = new URL(page.url()).origin;
    if (origin !== "null" && url.origin !== origin && /^https?:$/.test(url.protocol)) return route.abort();
    if (url.pathname === "/api/dagster/graphql") return route.fulfill({ json: dagster });
    if (url.pathname === "/api/transport/transport/features/places") {
      return route.fulfill({ json: { items: [], total: 0, truncated: false } });
    }
    if (url.pathname.startsWith("/api/") && !url.pathname.startsWith("/api/auth/")) {
      unexpected.push(url.pathname);
      return route.abort();
    }
    return route.continue();
  });
  await page.goto(`/login?next=${encodeURIComponent(pathname)}`);
  await page.getByLabel("아이디").fill(process.env.E2E_TRANSPORT_UI_USER ?? "admin");
  await page.getByLabel("비밀번호").fill(process.env.E2E_TRANSPORT_UI_PASSWORD!);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`${pathname}$`));
  await expect(page.locator(".page-header h1")).toBeVisible();
  if (pathname === "/map") {
    await expect(page.getByLabel("장소 검색")).toBeVisible();
    await expect(page.locator(".map-workbench")).not.toContainText("조회 중");
  } else {
    await expect(page.getByRole("region", { name: "최근 Dagster 실행 표" })).toContainText("visual-parity");
  }
  await page.evaluate(() => document.fonts.ready);
  return unexpected;
}

async function rectangle(locator: Locator) {
  await expect(locator).toBeVisible();
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  return box!;
}

async function expectColor(locator: Locator, property: "backgroundColor" | "color", expected: string) {
  const colors = await locator.evaluate((node, args) => {
    // Tailwind의 lab 변환과 브라우저의 oklch 직렬화는 동일 색상을 다르게 표현한다.
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 1;
    const context = canvas.getContext("2d")!;
    const rgba = (color: string) => {
      context.clearRect(0, 0, 1, 1);
      context.fillStyle = color;
      context.fillRect(0, 0, 1, 1);
      return Array.from(context.getImageData(0, 0, 1, 1).data);
    };
    return { actual: rgba(getComputedStyle(node)[args.property]), expected: rgba(args.expected) };
  }, { property, expected });
  for (let channel = 0; channel < 4; channel++) {
    expect(Math.abs(colors.actual[channel] - colors.expected[channel]), `${property} RGBA 채널 ${channel}`).toBeLessThanOrEqual(1);
  }
}

test.beforeEach(() => {
  test.skip(!process.env.E2E_TRANSPORT_UI_PASSWORD, "E2E_TRANSPORT_UI_PASSWORD가 필요합니다.");
});

for (const width of widths) {
  for (const pathname of paths) {
    test(`Weather 레일·헤더·본문 패리티 ${pathname} ${width}px`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 });
      const unexpected = await loginWithFixtures(page, pathname);
      const main = page.locator("main#main-content");
      const rail = page.locator(".rail");
      const nav = page.locator(".rail-nav.nav");
      const header = page.locator(".page-header-wrap .page-header");
      const logout = page.locator('.rail-footer button[type="submit"]');
      const gutter = width <= 672 ? 12 : width <= 992 ? 16 : 24;

      await expect(page.locator(".admin-layout")).toBeVisible();
      await expect(rail.locator(".rail-shell .rail-header")).toBeVisible();
      await expect(main.locator(".page-body")).toBeVisible();
      await expect(header.locator(".page-path")).toHaveText(pathname);
      await expect(header.locator("h1")).toHaveCSS("font-size", "24px");
      await expect(header).toHaveCSS("padding-left", "24px");
      await expect(header).toHaveCSS("padding-right", "24px");
      await expect(header).toHaveCSS("border-top-style", "solid");
      await expect(header).toHaveCSS("border-top-left-radius", "18px");
      await expectColor(page.locator("html"), "backgroundColor", "oklch(97.8% .003 250)");
      await expectColor(rail, "backgroundColor", "oklch(99.2% .002 250)");
      await expectColor(nav.locator('[aria-current="page"] svg'), "color", "oklch(47% .14 255)");
      await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);
      await expect(nav.locator('[aria-current="page"]')).toHaveAttribute("href", pathname);

      const mainBox = await rectangle(main);
      const headerBox = await rectangle(header);
      const content = await rectangle(page.locator(pathname === "/map" ? ".map-workbench" : ".journey-workbench"));
      // 여백 회귀가 있어도 나머지 레일·액션 검사와 전체 스크린샷을 남긴다.
      expect.soft(headerBox.x - mainBox.x, "헤더 왼쪽 여백").toBeCloseTo(gutter, 0);
      expect.soft(mainBox.x + mainBox.width - headerBox.x - headerBox.width, "헤더 오른쪽 여백").toBeCloseTo(gutter, 0);
      expect.soft(content.x - mainBox.x, "본문 왼쪽 여백").toBeCloseTo(gutter, 0);
      expect.soft(mainBox.x + mainBox.width - content.x - content.width, "본문 오른쪽 여백").toBeCloseTo(gutter, 0);
      expect(content.y).toBeGreaterThanOrEqual(headerBox.y + headerBox.height);
      if (pathname === "/admin/dagster") {
        const summary = page.locator(".ops-grid");
        const columns = await summary.evaluate((node) => getComputedStyle(node).gridTemplateColumns.split(" ").length);
        expect(columns).toBe(width <= 672 ? 1 : width <= 992 ? 2 : 4);
        await expect.soft(summary).toHaveCSS("gap", "16px");
        for (const card of await summary.locator('[data-slot="card"]').all()) {
          expect.soft((await rectangle(card)).height).toBeGreaterThanOrEqual(160);
          await expect.soft(card.locator('[data-slot="card-title"]')).toHaveCSS("font-size", "12px");
        }
        await expect(summary.locator("strong")).toHaveCount(4);
        for (const value of await summary.locator("strong").all()) await expect(value).toHaveCSS("font-size", "30px");
        const actions = await rectangle(header.locator(".page-header-actions"));
        expect(actions.x).toBeGreaterThanOrEqual(headerBox.x + 24);
        expect(actions.x + actions.width).toBeLessThanOrEqual(headerBox.x + headerBox.width - 24);
        if (width <= 672) {
          for (const action of await header.locator('.page-header-actions [data-slot="button"]').all()) {
            await expect.soft(action).toHaveCSS("flex-grow", "1");
            if (width === 320) expect.soft((await rectangle(action)).width).toBeCloseTo(actions.width, 0);
          }
        }
      }

      const railBox = await rectangle(rail);
      if (width > 992) {
        expect(railBox.width).toBeCloseTo(272, 0);
        expect(mainBox.x).toBeCloseTo(railBox.x + railBox.width, 0);
        await expect(nav).toHaveCSS("flex-direction", "column");
      } else {
        expect(railBox.width).toBeCloseTo(width, 0);
        expect(mainBox.y).toBeGreaterThanOrEqual(railBox.y + railBox.height);
        await expect(nav).toHaveCSS("flex-direction", "row");
        await expect(nav).toHaveCSS("overflow-x", "auto");
        const first = await rectangle(nav.locator("a").first());
        const last = await rectangle(nav.locator("a").last());
        expect(first.y).toBeCloseTo(last.y, 0);
        await nav.locator("a").last().focus();
        await expect(nav.locator("a").last()).toBeFocused();
      }

      await expect(logout).toBeVisible();
      await logout.focus();
      await expect(logout).toBeFocused();
      await expect(logout).toBeInViewport();
      const logoutBox = await rectangle(logout);
      expect(logoutBox.x).toBeGreaterThanOrEqual(0);
      expect(logoutBox.x + logoutBox.width).toBeLessThanOrEqual(width);
      // trial 클릭으로 가림·pointer-events 회귀도 검사하되 세션은 유지한다.
      await logout.click({ trial: true });
      const controls = pathname === "/map"
        ? [page.getByLabel("장소 검색"), page.getByLabel("표시 유종"), page.getByRole("group", { name: "보기 방식", exact: true }).getByRole("button").first()]
        : [page.locator(".page-header-actions button").first()];
      for (const control of controls) expect((await rectangle(control)).height).toBeCloseTo(36, 0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
      expect(unexpected).toEqual([]);
      await page.mouse.move(0, 0);
      await page.evaluate(() => { (document.activeElement as HTMLElement | null)?.blur(); window.scrollTo(0, 0); });
      const screenshot = await page.screenshot({ path: testInfo.outputPath(`weather-${pathname.replaceAll("/", "-")}-${width}.png`), fullPage: true, animations: "disabled" });
      await testInfo.attach("Weather 시각 패리티", { body: screenshot, contentType: "image/png" });
    });
  }
}

test.describe("터치 환경", () => {
  test.use({ hasTouch: true });

  for (const pathname of paths) test(`coarse 포인터의 컨트롤과 로그아웃 ${pathname}`, async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 1000 });
    const unexpected = await loginWithFixtures(page, pathname);
    expect(await page.evaluate(() => matchMedia("(pointer: coarse)").matches)).toBe(true);
    const controls = pathname === "/map"
      ? [page.getByLabel("장소 검색"), page.getByLabel("표시 유종"), page.getByRole("group", { name: "보기 방식", exact: true }).getByRole("button").first()]
      : [page.locator(".page-header-actions button").first()];
    controls.push(page.getByRole("button", { name: "로그아웃", exact: true }));
    for (const control of controls) expect((await rectangle(control)).height).toBeGreaterThanOrEqual(44);

    await page.evaluate(() => {
      for (const version of [1, 2]) sessionStorage.setItem(`kor-travel-transport-dashboard-v${version}`, "cached");
      document.addEventListener("submit", () => queueMicrotask(() => {
        for (const version of [1, 2]) sessionStorage.setItem(`kor-travel-transport-dashboard-v${version}`, "late-response");
      }), { once: true });
    });
    const request = page.waitForRequest((request) => new URL(request.url()).pathname === "/api/auth/logout");
    await page.getByRole("button", { name: "로그아웃", exact: true }).click();
    expect((await request).method()).toBe("POST");
    await expect(page).toHaveURL(/\/login/);
    await expect.poll(() => page.evaluate(() => [1, 2].map((version) => sessionStorage.getItem(`kor-travel-transport-dashboard-v${version}`)))).toEqual([null, null]);
    expect(unexpected).toEqual([]);
  });
});
