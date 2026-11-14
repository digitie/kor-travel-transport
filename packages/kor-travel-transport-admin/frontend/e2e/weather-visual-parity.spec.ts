import { expect, test, type Locator, type Page } from "@playwright/test";

const widths = [320, 375, 414, 768, 1440];
const paths = ["/map", "/admin/dagster"] as const;
const stamp = "2026-09-28T03:00:00Z";
const dagster = { data: {
  repositoryOrError: { __typename: "Repository", schedules: [{
    name: "airport_schedule", cronSchedule: "*/5 * * * *", pipelineName: "airport_collection_job", scheduleState: { status: "RUNNING" },
  }] },
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
    // Dagster 화면의 주소 갱신 카드는 이 검사의 대상이 아니다. 읽기 실패 상태로 둔다.
    if (url.pathname === "/api/address-refresh") return route.fulfill({ status: 503, json: {} });
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
  await expect(page.locator('[data-slot="admin-shell-header"] h1')).toBeVisible();
  if (pathname === "/map") {
    await expect(page.locator(".map-workbench")).toBeVisible();
    // 좁은 화면의 map 공용 작업면은 필터를 "지도 필터" 버튼 뒤에 접어 둔다.
    const filterToggle = page.getByRole("button", { name: "지도 필터" });
    if (await filterToggle.isVisible()) await filterToggle.click();
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

// 셸은 map 공용 셸(lg 이상 16rem 세로 레일, 미만은 상단 메뉴 띠)이다. Weather 카드형 헤더 검사는 셸 교체로 대체됐다.
for (const width of widths) {
  for (const pathname of paths) {
    test(`map 셸 레일·헤더·본문 패리티 ${pathname} ${width}px`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 });
      const unexpected = await loginWithFixtures(page, pathname);
      const main = page.locator("main#main-content");
      const rail = page.locator('[data-slot="admin-shell-rail"]');
      const nav = page.getByRole("navigation", { name: "주요 메뉴" });
      const header = page.locator('[data-slot="admin-shell-header"]');
      const logout = page.getByRole("button", { name: "로그아웃", exact: true });

      await expect(header.locator("h1")).toBeVisible();
      await expectColor(page.locator("body"), "backgroundColor", "oklch(97.8% .003 250)");
      await expectColor(rail, "backgroundColor", "oklch(99.2% .002 250)");
      await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);
      await expect(nav.locator('[aria-current="page"]')).toHaveAttribute("href", pathname);

      const mainBox = await rectangle(main);
      const headerBox = await rectangle(header);
      const content = await rectangle(pathname === "/map" ? page.locator(".map-workbench") : page.getByRole("region", { name: "최근 Dagster 실행 표" }));
      expect(content.y).toBeGreaterThanOrEqual(headerBox.y + headerBox.height - 1);
      expect(content.x).toBeGreaterThanOrEqual(mainBox.x);
      expect(content.x + content.width).toBeLessThanOrEqual(mainBox.x + mainBox.width + 1);

      const railBox = await rectangle(rail);
      if (width >= 1024) {
        expect(railBox.width).toBeCloseTo(256, 0);
        expect(mainBox.x).toBeCloseTo(railBox.x + railBox.width, 0);
      } else {
        expect(railBox.width).toBeCloseTo(width, 0);
        expect(mainBox.y).toBeGreaterThanOrEqual(railBox.y + railBox.height - 1);
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
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
      expect(unexpected).toEqual([]);
      await page.mouse.move(0, 0);
      await page.evaluate(() => { (document.activeElement as HTMLElement | null)?.blur(); window.scrollTo(0, 0); });
      const screenshot = await page.screenshot({ path: testInfo.outputPath(`weather-${pathname.replaceAll("/", "-")}-${width}.png`), fullPage: true, animations: "disabled" });
      await testInfo.attach("map 셸 시각 패리티", { body: screenshot, contentType: "image/png" });
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
      ? [page.getByLabel("장소 검색"), page.locator('[data-slot="combobox-chips"]').last(), page.getByRole("tablist", { name: "장소 보기" }).getByRole("tab").first()]
      : [page.getByRole("button", { name: "새로고침", exact: true })];
    controls.push(page.getByRole("button", { name: "로그아웃", exact: true }));
    for (const control of controls) await expect.poll(async () => (await rectangle(control)).height).toBeGreaterThanOrEqual(44);

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
