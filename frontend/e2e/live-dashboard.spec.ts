import {
  expect,
  test,
  type APIRequestContext,
  type Locator,
} from "@playwright/test";
import { isFreshHighwayObservation } from "./transport-freshness";

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
    expect(collectorPayload.last_run?.trigger).toBe("dagster_airport");
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

  test("pages 30-day parking history without repeating a parking lot observation", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const first = await getJsonWithTransientRetry(
      page.request, "/api/backend/v1/parking/history?days=30&limit=2",
    );
    expect(first.status()).toBe(200);
    const firstPage = await first.json();
    expect(firstPage.items).toHaveLength(2);
    expect(typeof firstPage.next_cursor).toBe("string");
    expect(firstPage.items[0].airport_code).toBeTruthy();
    expect(firstPage.items[0].parking_lot_id).toBeGreaterThan(0);

    const second = await getJsonWithTransientRetry(
      page.request,
      `/api/backend/v1/parking/history?days=30&limit=2&cursor=${encodeURIComponent(firstPage.next_cursor)}`,
    );
    expect(second.status()).toBe(200);
    const secondPage = await second.json();
    expect(secondPage.items).toHaveLength(2);
    expect(typeof secondPage.next_cursor).toBe("string");
    const third = await getJsonWithTransientRetry(
      page.request,
      `/api/backend/v1/parking/history?days=30&limit=2&cursor=${encodeURIComponent(secondPage.next_cursor)}`,
    );
    expect(third.status()).toBe(200);
    const thirdPage = await third.json();
    expect(thirdPage.items).toHaveLength(2);
    const keys = [...firstPage.items, ...secondPage.items, ...thirdPage.items].map(
      (item: { observed_at: string; parking_lot_id: number }) =>
        `${item.observed_at}:${item.parking_lot_id}`,
    );
    expect(new Set(keys).size).toBe(6);
    const referenceResponse = await getJsonWithTransientRetry(
      page.request, "/api/backend/v1/parking/history?days=30&limit=1000",
    );
    expect(referenceResponse.status()).toBe(200);
    const reference = await referenceResponse.json();
    const referenceKeys = reference.items.map(
      (item: { observed_at: string; parking_lot_id: number }) =>
        `${item.observed_at}:${item.parking_lot_id}`,
    );
    const startIndex = referenceKeys.indexOf(keys[0]);
    expect(startIndex).toBeGreaterThanOrEqual(0);
    expect(keys).toEqual(referenceKeys.slice(startIndex, startIndex + 6));
  });

  test("exposes the integrated transport API through the frontend proxy", async ({
    page,
  }) => {
    test.setTimeout(1_200_000);
    await page.goto("/", { waitUntil: "domcontentloaded" });
    let runningHighwayRunIds: number[] = [];
    // 다른 소스의 후속 성공이 아직 진행 중인 fuel 실행을 가리지 못하게 한다.
    // last_started는 조회 전, last_success는 데이터 저장 transaction과 함께 확정된다.
    await expect(async () => {
      const response = await getJsonWithTransientRetry(page.request, "/api/backend/v1/transport/collector-status");
      expect(response.status()).toBe(200);
      const status = await response.json();
      expect(status.collection_enabled).toBe(true);
      expect(status.scheduler_enabled).toBe(true);
      expect(status.client_mode).toBe("live");
      expect(status.last_run?.trigger).toMatch(/^transport_dagster_(highway|fuel)$/);
      // 5분 주기 작업과 검사 시점이 겹치면 가장 최근 실행은 정상적으로 진행 중이다.
      // 오래 멈춘 실행은 아래 시작 시각 검증으로 계속 실패 처리한다.
      expect(["success", "running"]).toContain(status.last_run?.status);
      expect(status.last_run?.error ?? null).toBeNull();
      const latestHighwayRun = status.recent_runs.find(
        (run: { trigger: string }) => run.trigger === "transport_dagster_highway",
      );
      expect(latestHighwayRun, "최근 고속도로 수집 실행이 없음").toBeTruthy();
      expect(["success", "running"], "최근 고속도로 수집 실패").toContain(latestHighwayRun.status);
      expect(latestHighwayRun.error ?? null).toBeNull();
      expect(Array.isArray(status.running_runs)).toBe(true);
      // 최근 10건 밖으로 밀린 고아 실행도 별도 활성 목록에서 확인한다.
      expect(status.running_run_count).toBe(status.running_runs.length);
      for (const run of status.running_runs as Array<{ id: number; trigger: string; started_at: string }>) {
        const age = Date.now() - Date.parse(run.started_at);
        const maxAge = run.trigger === "transport_dagster_fuel" ? 135 * 60_000 : 15 * 60_000;
        expect(Number.isFinite(age), `수집 실행 ${run.id}`).toBe(true);
        expect(age, `수집 실행 ${run.id} 허용 시간을 초과`).toBeLessThanOrEqual(maxAge);
      }
      runningHighwayRunIds = [...new Set(
        [...status.recent_runs, ...status.running_runs]
          .filter((run: { trigger: string; status: string }) =>
            run.trigger === "transport_dagster_highway" && run.status === "running")
          .map((run: { id: number }) => run.id),
      )];
      const runAt = Date.parse(status.last_run?.status === "running"
        ? status.last_run?.started_at : status.last_run?.finished_at);
      expect(Number.isFinite(runAt)).toBe(true);
      expect(Date.now() - runAt).toBeLessThanOrEqual(
        status.last_run?.status === "running" && status.last_run?.trigger === "transport_dagster_fuel"
          ? 135 * 60_000 : 900_000,
      );
      expect(Array.isArray(status.sources)).toBe(true);
      for (const name of ["krex_traffic_flow", "krex_traffic_incident", "opinet_browser"]) {
        expect(status.enabled_sources).toContain(name);
        const source = status.sources.find((item: { source: string }) => item.source === name);
        expect(source, name).toBeTruthy();
        const succeededAt = Date.parse(source.last_success_at);
        expect(Number.isFinite(succeededAt), name).toBe(true);
        // OPINET은 기본 8시간 throttle을 쓰며, 재시작 중 취소된 실행도 다음 8시간
        // 예약을 보존한다. 정상 저장본은 한 예약을 건너뛴 최대 16시간과 작은 여유를
        // 허용하되, provider quota를 우회해 재호출하지 않는다.
        const maxAge = name === "opinet_browser" ? 17 * 3_600_000 : 900_000;
        expect(Date.now() - succeededAt, name).toBeGreaterThanOrEqual(-60_000);
        expect(Date.now() - succeededAt, name).toBeLessThanOrEqual(maxAge);
        // 배포·작업자 재시작 중 취소된 시도는 provider quota 보호를 위해 다음 실행을
        // 예약한다. 마지막 저장 성공의 최신성은 계속 확인하되, 이 예약 상태 자체를
        // live E2E 실패로 간주하지 않는다.
        if (source.last_error !== null) {
          const nextDueAt = Date.parse(source.next_due_at);
          expect(Number.isFinite(nextDueAt), `${name}: 재시도 예약`).toBe(true);
          expect(nextDueAt, `${name}: 재시도 예약이 현재 이후`).toBeGreaterThan(Date.now());
        }
      }
    }).toPass({ timeout: 120_000, intervals: [2_000, 5_000] });

    // 고속도로 작업은 정상 상한이 짧다. 처음 관측한 각 실행이 실제 success로
    // 끝나야 한다. 정상 유가 작업은 최대 2시간이므로 여기서 강제 종료를 기다리지 않는다.
    if (runningHighwayRunIds.length > 0) {
      await expect(async () => {
        const response = await getJsonWithTransientRetry(page.request, "/api/backend/v1/transport/collector-status");
        expect(response.status()).toBe(200);
        const status = await response.json();
        for (const id of runningHighwayRunIds) {
          const run = status.recent_runs.find((item: { id: number }) => item.id === id);
          expect(run, `수집 실행 ${id}이 완료 전 목록에서 사라짐`).toBeTruthy();
          expect(run.status, `수집 실행 ${id}이 정상 종료되지 않음`).toBe("success");
        }
      }).toPass({ timeout: 900_000, intervals: [5_000] });
    }

    // 모든 소스의 저장 완료를 확인한 뒤 API를 새로 조회한다.
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
          expect(
            payload.items.some((item: Record<string, unknown>) => isFreshHighwayObservation(item)),
            "소통 관측·저장 시각의 최신성",
          ).toBe(true);
        } else if (path.includes("/fuel/stations")) {
          expect(payload.items.length).toBeGreaterThan(0);
          expect(payload.items[0].source).toBe("opinet_browser");
          expect(payload.items[0].prices.length).toBeGreaterThan(0);
          expect(payload.items[0].prices.some((price: { price: number | null; collected_at: string }) =>
            price.price !== null && price.price > 0 &&
            Date.parse(price.collected_at) >= Date.now() - 17 * 3_600_000 &&
            Date.parse(price.collected_at) <= Date.now() + 60_000,
          )).toBe(true);
        } else if (path.includes("/statistics")) {
          expect(payload.traffic.length).toBeGreaterThan(0);
          expect(payload.fuel_prices.length).toBeGreaterThan(0);
        }
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
