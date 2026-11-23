import { expect, test, type Page } from "@playwright/test";

// 고속도로·공항 수집이 원천의 일부 무효 행만 격리하고 나머지를 저장한 실행(부분 성공)의 상세 화면.
// 실행은 실패가 아니라 완료로 보이고, 처리 내역에 고정 사유(INVALID_ROWS_ISOLATED)와 격리·수신·불량 행 수가 보인다.
// BFF 응답은 route로 고정한다(메타데이터 → 이벤트 변환은 vitest `dagster-console-server.test.ts`).
const runId = "7a2c9e41-3b5d-4f80-9c1e-6d4b2a8f0e17";
const now = Math.floor(Date.parse("2026-11-24T09:30:00Z") / 1000);
const runs = [{ runId, jobName: "highway_collection_job", status: "SUCCESS", startTime: now - 120, endTime: now - 60,
  tags: [{ key: "dagster/code_location", value: "kor-travel-transport" }, { key: "kortravel/collection-outcome", value: "partial" }] }];
const overview = { data: { activeRuns: { __typename: "Runs", results: [] }, repositoryOrError: { __typename: "Repository", schedules: [] },
  runsOrError: { __typename: "Runs", results: runs } } };
const catalog = { jobs: ["highway_collection_job"], schedules: [], sensors: [],
  capabilities: { launch: true, retry: true, cancel: true, schedule: true, sensor: true }, checkedAt: "2026-11-24T09:30:00.000Z" };
const detail = {
  runId, jobName: "highway_collection_job", status: "SUCCESS", creationTime: now - 130, startTime: now - 120, endTime: now - 60,
  queuedTime: now - 130, canCancel: false, canRetry: false,
  steps: [{ key: "collect_highway_transport", status: "SUCCESS", startTime: now - 120, endTime: now - 60, attempts: 1 }],
  events: [{ kind: "ExecutionStepOutputEvent", time: (now - 60) * 1000, step: "collect_highway_transport", title: "단계 결과",
    detail: "오류 코드: INVALID_ROWS_ISOLATED\n원인: 원천 응답의 일부 행이 규격과 달라 그 행만 격리하고 나머지는 저장했습니다.",
    warning: true, counts: { isolated_rows: 2, received_rows: 8251, invalid_rows: 2, traffic_snapshot_count: 8249 } }],
  stepsSucceeded: 1, stepsFailed: 0, materializations: 0, cursor: null, hasMore: false, stepsTruncated: false,
  checkedAt: "2026-11-24T09:30:00.000Z", retryOf: null, requestedBy: null,
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

for (const width of [390, 1440]) test(`격리 행이 있는 고속도로 수집은 완료와 격리 건수를 함께 보여 준다 ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
  await fixture(page);
  await page.goto("/admin/dagster");
  const table = page.getByRole("region", { name: "최근 Dagster 실행 표" });
  await table.getByRole("button", { name: "고속도로 소통·돌발" }).first().click();
  const inspector = page.getByRole("region", { name: "실행 진행 상세" });
  await expect(inspector).toContainText("실행 완료");
  await expect(inspector).toContainText("INVALID_ROWS_ISOLATED");
  await expect(inspector).toContainText("격리 행 2");
  await expect(inspector).toContainText("수신 행 8,251");
  await expect(inspector).toContainText("불량 행 2");
  // 완료된 실행이라 재시도 버튼은 없다(격리 행은 같은 응답을 다시 받아도 같다).
  await expect(inspector.getByRole("button", { name: "재시도", exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
