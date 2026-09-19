import {
  expect,
  test,
  type APIRequestContext,
  type Locator,
} from "@playwright/test";

const ROUTES = ["/", "/analytics", "/history", "/fees", "/backup"] as const;

/**
 * A click right after a client-side route change can land before React has finished
 * re-attaching event handlers on a slow connection (confirmed via CDP network throttling
 * against the live site: a plain click silently no-ops, but retrying it a moment later
 * succeeds). `expect(...).toPass()` retries the whole click+check until the interaction
 * actually took effect, instead of failing on the first no-op click.
 */
async function clickUntilEffective(
  trigger: Locator,
  check: () => Promise<void>,
) {
  await expect(async () => {
    await trigger.click();
    await check();
  }).toPass({ timeout: 15_000 });
}

async function getJsonWithTransientRetry(
  request: APIRequestContext,
  path: string,
) {
  let response = await request.get(path);
  for (
    let attempt = 0;
    attempt < 3 && [502, 503, 504].includes(response.status());
    attempt += 1
  ) {
    await new Promise((resolve) => setTimeout(resolve, 1_000));
    response = await request.get(path);
  }
  return response;
}

test.describe("live parking-radar dashboard", () => {
  test("paints current data, remembers selection, and exposes the backup route", async ({
    page,
    context,
  }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect(page).toHaveTitle(/parking-radar/i);
    await expect(
      page.getByRole("combobox", { name: "공항 선택" }),
    ).toBeVisible();
    await expect(
      page
        .locator(
          '[data-testid="desktop-lot-table"], [data-testid="mobile-lot-grid"]',
        )
        .first(),
    ).toBeVisible({
      timeout: 20_000,
    });
    await expect(
      page
        .locator(
          '[data-testid="desktop-lot-table"] tbody tr, [data-testid="mobile-lot-grid"] article',
        )
        .first(),
    ).toBeVisible({
      timeout: 20_000,
    });
    // T-039 regression guard: at desktop viewport width, exactly one of the two lot
    // views must render - `.first()` above passes even if both are visible, which is
    // exactly the bug this test would otherwise miss (a plain custom CSS class silently
    // beat a Tailwind `lg:hidden` utility, so the mobile card grid rendered underneath
    // the desktop table at every width).
    await expect(page.getByTestId("desktop-lot-table")).toBeVisible();
    await expect(page.getByTestId("mobile-lot-grid")).toBeHidden();

    const apiHealth = await page.request.get("/api/backend/health");
    expect(apiHealth.status()).toBe(200);
    const healthPayload = await apiHealth.json();
    expect(healthPayload.status).toBe("ok");
    const expectedReleaseSha = process.env.EXPECTED_RELEASE_SHA;
    if (expectedReleaseSha) {
      expect(healthPayload.release_sha).toBe(expectedReleaseSha);
    }

    const collectorStatus = await page.request.get(
      "/api/backend/v1/admin/collector-status",
    );
    expect(collectorStatus.status()).toBe(200);
    const collectorPayload = await collectorStatus.json();
    expect(collectorPayload.client_mode).toBe("live");
    expect(collectorPayload.scheduler_enabled).toBe(true);
    expect(collectorPayload.collect_interval_seconds).toBe(300);
    expect(collectorPayload.effective_collect_interval_seconds).toBe(180);
    expect(collectorPayload.last_run?.status).toBe("success");
    expect(collectorPayload.last_run?.trigger).toBe("scheduler");
    expect(collectorPayload.last_run?.raw_response_count).toBeGreaterThan(0);
    const lastRunFinishedAt = Date.parse(
      collectorPayload.last_run?.finished_at,
    );
    expect(Number.isFinite(lastRunFinishedAt)).toBe(true);
    const lastRunAge = Date.now() - lastRunFinishedAt;
    expect(lastRunAge).toBeGreaterThanOrEqual(0);
    expect(lastRunAge).toBeLessThanOrEqual(300_000);
    const latestObservedAt = Date.parse(
      collectorPayload.latest_snapshot_observed_at,
    );
    expect(Number.isFinite(latestObservedAt)).toBe(true);
    const latestAge = Date.now() - latestObservedAt;
    expect(latestAge).toBeGreaterThanOrEqual(0);
    expect(latestAge).toBeLessThanOrEqual(300_000);

    const airportSelect = page.getByRole("combobox", { name: "공항 선택" });
    await expect
      .poll(() => airportSelect.locator("option").count(), { timeout: 20_000 })
      .toBeGreaterThan(0);
    const airportOptions = await airportSelect
      .locator("option")
      .allTextContents();
    expect(airportOptions.length).toBeGreaterThan(0);
    if (airportOptions.length > 1) {
      await airportSelect.selectOption({ index: 1 });
      await expect
        .poll(async () =>
          (await context.cookies()).some(
            (cookie) => cookie.name === "parking-radar-selection",
          ),
        )
        .toBe(true);
    }

    // The shared selection lives in DashboardProvider, so it must survive a route change.
    await page
      .getByRole("navigation", { name: "주요 메뉴" })
      .getByRole("link", { name: "백업" })
      .click();
    await expect(page).toHaveURL(/\/backup$/);
    await expect(
      page.getByRole("button", { name: /백업 \/ 복원/ }),
    ).toBeVisible();
    await page.getByRole("button", { name: /백업 \/ 복원/ }).click();
    await expect(
      page.getByText(/별도 인증 없이 제공되는 운영 도구/),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "새 백업 만들기" }),
    ).toBeVisible();
    if (process.env.EXERCISE_LIVE_BACKUP === "true") {
      await page.getByRole("button", { name: "새 백업 만들기" }).click();
      await expect(page.getByText(/백업을 만들었습니다:/)).toBeVisible({
        timeout: 180_000,
      });
    }
    await expect(
      page
        .locator(
          '[data-testid="backup-empty-state"], [data-testid="backup-list"]',
        )
        .first(),
    ).toBeVisible({
      timeout: 20_000,
    });
  });

  test("desktop nav switches routes and marks the active tab", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const desktopNav = page.getByRole("navigation", { name: "주요 메뉴" });
    await expect(
      desktopNav.getByRole("link", { name: "현황" }),
    ).toHaveAttribute("aria-current", "page");

    await desktopNav.getByRole("link", { name: "분석" }).click();
    await expect(page).toHaveURL(/\/analytics$/);
    await expect(
      desktopNav.getByRole("link", { name: "분석" }),
    ).toHaveAttribute("aria-current", "page");
    await expect(page.getByRole("tab", { name: "요일별 패턴" })).toBeVisible();

    await clickUntilEffective(
      page.getByRole("tab", { name: "일별 흐름" }),
      () =>
        expect(page.getByRole("tab", { name: "일별 흐름" })).toHaveAttribute(
          "aria-selected",
          "true",
          { timeout: 1_000 },
        ),
    );
  });

  test("exposes the integrated transport API through the frontend proxy", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    await page.goto("/", { waitUntil: "domcontentloaded" });
    for (const path of [
      "/api/backend/v1/transport/highways/traffic?days=1&limit=1",
      "/api/backend/v1/transport/highways/incidents?days=1&limit=1",
      "/api/backend/v1/transport/fuel/stations?days=1&limit=1",
      "/api/backend/v1/transport/statistics?days=1",
    ]) {
      const response = await getJsonWithTransientRetry(page.request, path);
      expect(response.status(), path).toBe(200);
        const payload = await response.json();
        expect(payload.generated_at, path).toBeTruthy();
        if (path.includes("/highways/traffic")) {
          expect(payload.items.length).toBeGreaterThan(0);
          expect(payload.items[0].source).toBe("krex_traffic_flow");
          expect(Date.parse(payload.items[0].collected_at)).toBeGreaterThan(Date.now() - 900_000);
        } else if (path.includes("/fuel/stations")) {
          expect(payload.items.length).toBeGreaterThan(0);
          expect(payload.items[0].source).toBe("opinet_browser");
          expect(payload.items[0].prices.length).toBeGreaterThan(0);
          expect(payload.items[0].prices.some((price: { price: number | null; collected_at: string }) =>
            price.price !== null && price.price > 0 &&
            Date.parse(price.collected_at) >= Date.now() - 13 * 3_600_000 &&
            Date.parse(price.collected_at) <= Date.now() + 60_000,
          )).toBe(true);
        } else if (path.includes("/statistics")) {
          expect(payload.traffic.length).toBeGreaterThan(0);
          expect(payload.fuel_prices.length).toBeGreaterThan(0);
        }
    }

    let statusResponse = await getJsonWithTransientRetry(
      page.request,
      "/api/backend/v1/transport/collector-status",
    );
    expect(statusResponse.status()).toBe(200);
    let statusPayload = await statusResponse.json();
    // 진행 중 실행을 승인하지 않고 실제 종료를 기다린다. 실패 상태는 즉시 거절한다.
    await expect(async () => {
      if (statusPayload.last_run?.status === "running") {
        statusResponse = await getJsonWithTransientRetry(page.request, "/api/backend/v1/transport/collector-status");
        expect(statusResponse.status()).toBe(200);
        statusPayload = await statusResponse.json();
      }
      expect(statusPayload.last_run?.status).not.toBe("running");
    }).toPass({ timeout: 120_000, intervals: [2_000, 5_000] });
      expect(statusPayload.collection_enabled).toBe(true);
      expect(Array.isArray(statusPayload.sources)).toBe(true);
      // 각 소스의 저장 성공을 확인한다. 비활성/샘플/빈 결과는 운영 승인 대상이 아니다.
      expect(statusPayload.scheduler_enabled).toBe(true);
      expect(statusPayload.client_mode).toBe("live");
      expect(statusPayload.last_run?.trigger).toMatch(/^transport_(highway|fuel)_scheduler$/);
      expect(statusPayload.last_run?.status).toBe("success");
      expect(statusPayload.last_run?.error ?? null).toBeNull();
      const runAt = Date.parse(statusPayload.last_run?.finished_at);
      expect(Number.isFinite(runAt)).toBe(true);
      expect(Date.now() - runAt).toBeLessThanOrEqual(900_000);
      for (const name of ["krex_traffic_flow", "krex_traffic_incident", "opinet_browser"]) {
        expect(statusPayload.enabled_sources).toContain(name);
        const source = statusPayload.sources.find((item: { source: string }) => item.source === name);
        expect(source, name).toBeTruthy();
        expect(source.last_error, name).toBeNull();
        const succeededAt = Date.parse(source.last_success_at);
        expect(Number.isFinite(succeededAt), name).toBe(true);
        const maxAge = name === "opinet_browser" ? 13 * 3_600_000 : 900_000;
        expect(Date.now() - succeededAt, name).toBeGreaterThanOrEqual(-60_000);
        expect(Date.now() - succeededAt, name).toBeLessThanOrEqual(maxAge);
      }
  });

  test("mobile bottom tabbar navigates routes and tucks 백업 behind 더보기", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const bottomNav = page.getByRole("navigation", { name: "하단 메뉴" });
    await expect(bottomNav.getByRole("link", { name: "현황" })).toHaveAttribute(
      "aria-current",
      "page",
    );

    await bottomNav.getByRole("link", { name: "과거조회" }).click();
    await expect(page).toHaveURL(/\/history$/);
    await expect(
      bottomNav.getByRole("link", { name: "과거조회" }),
    ).toHaveAttribute("aria-current", "page");

    const moreMenu = page.getByRole("dialog");
    await clickUntilEffective(
      bottomNav.getByRole("button", { name: "더보기" }),
      () => expect(moreMenu).toBeVisible({ timeout: 1_000 }),
    );
    await moreMenu.getByRole("link", { name: "백업" }).click();
    await expect(page).toHaveURL(/\/backup$/);
  });

  // "/" keeps the full 320/375/414/768px sweep (established baseline coverage). The other
  // routes mount useAnalyticsData (flight-status is a live, rate-limited upstream) - checking
  // only the narrowest and widest widths there still catches overflow regressions without
  // multiplying live calls across every intermediate breakpoint for a CSS-only assertion.
  for (const width of [320, 375, 414, 768]) {
    test(`does not create page overflow at ${width}px on /`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/", { waitUntil: "domcontentloaded" });
      await expect(
        page.getByRole("combobox", { name: "공항 선택" }),
      ).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);
    });
  }

  for (const width of [320, 768]) {
    for (const route of ROUTES.filter((route) => route !== "/")) {
      test(`does not create page overflow at ${width}px on ${route}`, async ({
        page,
      }) => {
        await page.setViewportSize({ width, height: 900 });
        await page.goto(route, { waitUntil: "domcontentloaded" });
        await expect(
          page.getByRole("combobox", { name: "공항 선택" }),
        ).toBeVisible();
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - window.innerWidth,
        );
        expect(overflow).toBeLessThanOrEqual(1);
      });
    }
  }
});
