import { expect, test, type Page } from "@playwright/test";

// 좌표 보강(VWorld·카카오)의 호출 몇 건만 실패한 기준정보 실행은 run SUCCESS + `kortravel/collection-outcome=partial`이다
// (BUS-REF-PARTIAL-20261124). 예전에는 같은 실행이 FAILURE라 실패 목록에 섞였다. 관리자 Dagster 콘솔은 이 실행을
// "자료 확인 필요 실행 · 부분 완료"로 따로 보여야 한다. 이 spec은 화면 흐름만 본다: BFF 응답은 route로 고정한다.
const partialRun = "7a1e2b3c-4d5e-4f60-8a9b-0c1d2e3f4a5b";
const now = Math.floor(Date.parse("2026-11-24T18:40:00Z") / 1000);
const runs = [
  { runId: partialRun, jobName: "bus_reference_collection_job", status: "SUCCESS", startTime: now - 600, endTime: now - 300,
    tags: [{ key: "dagster/code_location", value: "kor-travel-transport" },
      { key: "kortravel/collection-outcome", value: "partial" }] },
  { runId: "3d0c1b2a-1111-4c22-8d33-444455556666", jobName: "highway_collection_job", status: "SUCCESS", startTime: now - 200, endTime: now - 100,
    tags: [{ key: "dagster/code_location", value: "kor-travel-transport" }] },
];
const overview = { data: { activeRuns: { __typename: "Runs", results: [] }, repositoryOrError: { __typename: "Repository", schedules: [
  { name: "bus_reference_collection_job_schedule", pipelineName: "bus_reference_collection_job", cronSchedule: "30 3 * * *", scheduleState: { status: "RUNNING" } },
] }, runsOrError: { __typename: "Runs", results: runs } } };
const catalog = { jobs: ["bus_reference_collection_job", "highway_collection_job"], schedules: [], sensors: [],
  capabilities: { launch: true, retry: true, cancel: true, schedule: true, sensor: true }, checkedAt: "2026-11-24T18:40:00.000Z" };
const steps = ["collect_bus_reference", "enrich_new_reference_locations", "prepare_reference_exports"];
const detail = {
  runId: partialRun, jobName: "bus_reference_collection_job", status: "SUCCESS", creationTime: now - 700, startTime: now - 600,
  endTime: now - 300, queuedTime: now - 700, canCancel: false, canRetry: false,
  steps: steps.map((key) => ({ key, status: "SUCCESS", startTime: now - 600, endTime: now - 300, attempts: 1 })),
  events: [], stepsSucceeded: 3, stepsFailed: 0, materializations: 0, cursor: null, hasMore: false, stepsTruncated: false,
  checkedAt: "2026-11-24T18:40:00.000Z", retryOf: null, requestedBy: null,
};

async function fixture(page: Page) {
  await page.context().addCookies([{ name: "kor_travel_transport_admin_session", value: "isolated-e2e", url: process.env.E2E_BASE_URL ?? "http://127.0.0.1:12351", httpOnly: true, sameSite: "Strict" }]);
  await page.route("**://*.vworld.kr/**", (route) => route.abort());
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/address-refresh") return route.fulfill({ status: 503, json: {} });
    if (url.pathname === "/api/dagster/graphql") return route.fulfill({ json: overview });
    if (url.pathname === "/api/dagster/console") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      if (body.operation === "catalog") return route.fulfill({ json: catalog });
      if (body.operation === "detail") return route.fulfill({ json: detail });
      return route.fulfill({ status: 422, json: { detail: "unexpected" } });
    }
    return route.fulfill({ json: { items: [] } });
  });
}

for (const width of [390, 1440]) test(`좌표 보강 일부 실패 실행은 실패가 아닌 부분 완료로 보인다 ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
  await fixture(page);
  await page.goto("/admin/dagster");
  await expect(page.getByText("이번 조회의 자료 확인 필요 실행 1건")).toBeVisible();
  const warning = page.getByRole("button", { name: `고속·시외버스 터미널 · 부분 완료 · ${partialRun.slice(0, 8)}` });
  await expect(warning).toBeVisible();
  await warning.click();
  const inspector = page.getByRole("region", { name: "실행 진행 상세" });
  // 실패가 아닌 완료 실행이고, 좌표 보강 뒤의 export 준비 단계까지 돌았다.
  await expect(inspector).toContainText("실행 완료");
  await expect(inspector).toContainText("완료 3 · 실패 0");
  await expect(inspector).toContainText("prepare_reference_exports · 실행 완료");
  // 성공한 실행이므로 재시도 버튼은 없다(실패·취소 실행만).
  await expect(inspector.getByRole("button", { name: "재시도", exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/dagster-partial-outcome-${width}.png`, fullPage: true });
});
