import { expect, test, type Page } from "@playwright/test";

// 이전 유가 통계 세대 정리(prune) 결과가 관리자 실행 상세에 보인다(수집 실패 감사 2026-11-23 §2.5 P2 "prune 실패 비가시").
// 정리는 원천 성공과 분리된다: 정리 실패는 경고·고정 안내로, 예산 소진(따라잡는 중)은 경고 없는 안내로 보인다.
// BFF 응답(/api/dagster/console)은 서버가 metadata를 안전한 처리 내역으로 바꾼 모양 그대로 route로 고정한다
// (metadata → 안내 문구 변환 자체는 vitest `dagster-console-server.test.ts`).
const now = Math.floor(Date.parse("2026-11-24T09:30:00Z") / 1000);
const failedCleanupRun = "6a1f2b3c-4d5e-4f60-8a71-92b3c4d5e6f7";
const catchingUpRun = "7b2a3c4d-5e6f-4071-8b82-a3c4d5e6f708";
const runs = [
  { runId: failedCleanupRun, jobName: "fuel_collection_job", status: "SUCCESS", startTime: now - 7200, endTime: now - 1800,
    tags: [{ key: "dagster/code_location", value: "kor-travel-transport" }] },
  { runId: catchingUpRun, jobName: "rest_area_fuel_price_collection_job", status: "SUCCESS", startTime: now - 900, endTime: now - 840,
    tags: [{ key: "dagster/code_location", value: "kor-travel-transport" }] },
];
const overview = { data: { activeRuns: { __typename: "Runs", results: [] }, repositoryOrError: { __typename: "Repository", schedules: [] },
  runsOrError: { __typename: "Runs", results: runs } } };
const catalog = { jobs: ["fuel_collection_job", "rest_area_fuel_price_collection_job"], schedules: [], sensors: [],
  capabilities: { launch: true, retry: true, cancel: true, schedule: true, sensor: true }, checkedAt: "2026-11-24T09:30:00.000Z" };
const outputEvent = (detail: string, warning: boolean, pruned: number) => ({
  kind: "ExecutionStepOutputEvent", time: now - 1800, step: "collect_fuel_transport", title: "처리 결과", detail, warning,
  counts: { fuel_price_count: 41000, fuel_statistics_pruned_rows: pruned },
});
const detail = (runId: string, jobName: string, events: unknown[]) => ({
  runId, jobName, status: "SUCCESS", creationTime: now - 7300, startTime: now - 7200, endTime: now - 1800, queuedTime: now - 7300,
  canCancel: false, canRetry: false,
  steps: [{ key: "collect_fuel_transport", status: "SUCCESS", startTime: now - 7200, endTime: now - 1800, attempts: 1 }],
  events, stepsSucceeded: 1, stepsFailed: 0, materializations: 0, cursor: null, hasMore: false, stepsTruncated: false,
  checkedAt: "2026-11-24T09:30:00.000Z", retryOf: null, requestedBy: null,
});
const details: Record<string, unknown> = {
  [failedCleanupRun]: detail(failedCleanupRun, "fuel_collection_job", [
    outputEvent("자료 수집 완료\n원본 보존 · 이전 유가 통계 정리 실패 · 다음 수집에서 다시 정리\n정상 저장분 보존", true, 5000),
  ]),
  [catchingUpRun]: detail(catchingUpRun, "rest_area_fuel_price_collection_job", [
    outputEvent("자료 수집 완료\n이전 유가 통계 정리 진행 중 · 남은 세대는 다음 수집에서 이어 정리\n정상 저장분 보존", false, 120000),
  ]),
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
      if (body.operation === "detail" && typeof body.runId === "string" && details[body.runId]) return route.fulfill({ json: details[body.runId] });
      return route.fulfill({ status: 422, json: { detail: "unexpected" } });
    }
    return route.fulfill({ json: { items: [] } });
  });
}

for (const width of [390, 1440]) test(`이전 유가 통계 정리 실패와 따라잡기 진행이 실행 상세에 보인다 ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
  await fixture(page);
  await page.goto("/admin/dagster");
  const table = page.getByRole("region", { name: "최근 Dagster 실행 표" });
  await expect(table).toContainText("주유소·유가");
  await table.getByRole("button", { name: "주유소·유가" }).first().click();
  const inspector = page.getByRole("region", { name: "실행 진행 상세" });
  const history = inspector.getByRole("list", { name: "안전한 처리 내역" });
  await expect(history).toContainText("이전 유가 통계 정리 실패 · 다음 수집에서 다시 정리");
  await expect(history).toContainText("자료 수집 완료");
  await expect(history).toContainText("정리한 이전 통계 행 5,000");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/dagster-fuel-cleanup-${width}.png`, fullPage: true });
});
