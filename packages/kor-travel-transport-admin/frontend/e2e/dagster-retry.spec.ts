import { expect, test, type Page, type Request } from "@playwright/test";

// 관리자 Dagster 콘솔의 "재시도"(실패한 수집 job 다시 실행). 브라우저는 /api/dagster/console의 고정 명령만
// 보내고(원문 GraphQL·실행 설정 없음), 서버가 원본 run·요청자를 run 태그에, 요청 시각·결과를 감사 로그에 남긴다.
// 이 spec은 화면 흐름만 본다: BFF 응답은 route로 고정한다(서버 태그·로그는 vitest `route.test.ts`).
const failedRun = "0edf4c1f-5269-43f4-afb9-0919f794cbde";
const retryRun = "5b1d7c3e-9a2f-4c61-8e0b-2f7a4d9c1e55";
const now = Math.floor(Date.parse("2026-11-23T09:30:00Z") / 1000);
const runs = [
  { runId: failedRun, jobName: "fuel_collection_job", status: "FAILURE", startTime: now - 3600, endTime: now - 1800,
    tags: [{ key: "dagster/code_location", value: "kor-travel-transport" }] },
  { runId: "3d0c1b2a-1111-4c22-8d33-444455556666", jobName: "highway_collection_job", status: "SUCCESS", startTime: now - 600, endTime: now - 300,
    tags: [{ key: "dagster/code_location", value: "kor-travel-transport" }] },
];
const overview = { data: { activeRuns: { __typename: "Runs", results: [] }, repositoryOrError: { __typename: "Repository", schedules: [
  { name: "fuel_collection_job_schedule", pipelineName: "fuel_collection_job", cronSchedule: "0 */8 * * *", scheduleState: { status: "RUNNING" } },
] }, runsOrError: { __typename: "Runs", results: runs } } };
const failure = { data: { runsOrError: { __typename: "Runs", results: [{ eventConnection: { cursor: "c1", hasMore: false, events: [
  { __typename: "ExecutionStepFailureEvent", stepKey: "collect_fuel_transport", message: "교통정보 수집에 실패했습니다(status=failed): Opinet browser resource policy failed command=Fetch.failRequest cause=Error. 저장된 성공분과 호출 유예는 유지합니다.", failureMetadata: { metadataEntries: [] } },
  { __typename: "RunFailureEvent", message: "Execution of run failed." },
] } }] } } };
const catalog = { jobs: ["fuel_collection_job", "highway_collection_job"], schedules: [], sensors: [],
  capabilities: { launch: true, retry: true, cancel: true, schedule: true, sensor: true }, checkedAt: "2026-11-23T09:30:00.000Z" };
const detail = (runId: string, status: string, extra: Record<string, unknown> = {}) => ({
  runId, jobName: "fuel_collection_job", status, creationTime: now - 3700, startTime: now - 3600, endTime: status === "QUEUED" ? null : now - 1800,
  queuedTime: now - 3700, canCancel: status === "QUEUED", canRetry: ["FAILURE", "CANCELED"].includes(status),
  steps: [{ key: "collect_fuel_transport", status: status === "QUEUED" ? "NOT_STARTED" : "FAILURE", startTime: now - 3600, endTime: now - 1800, attempts: 1 }],
  events: [], stepsSucceeded: 0, stepsFailed: status === "QUEUED" ? 0 : 1, materializations: 0, cursor: null, hasMore: false, stepsTruncated: false,
  checkedAt: "2026-11-23T09:30:00.000Z", retryOf: null, requestedBy: null, ...extra,
});

async function fixture(page: Page) {
  const actions: Record<string, unknown>[] = [];
  await page.context().addCookies([{ name: "kor_travel_transport_admin_session", value: "isolated-e2e", url: process.env.E2E_BASE_URL ?? "http://127.0.0.1:12351", httpOnly: true, sameSite: "Strict" }]);
  await page.route("**://*.vworld.kr/**", (route) => route.abort());
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    // 같은 화면의 주소 갱신 카드는 이 시험 대상이 아니다. 조회 실패(503) 상태로 둔다.
    if (url.pathname === "/api/address-refresh") return route.fulfill({ status: 503, json: {} });
    if (url.pathname === "/api/dagster/graphql") {
      const body = route.request().postDataJSON() as { operationName?: string };
      return route.fulfill({ json: body.operationName === "TransportDagsterRunFailure" ? failure : overview });
    }
    if (url.pathname === "/api/dagster/console") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      if (body.operation === "catalog") return route.fulfill({ json: catalog });
      if (body.operation === "action") {
        actions.push(body);
        return route.fulfill({ json: { state: "accepted", message: "실행 요청을 확인했습니다. 대기·실행 상태를 아래에서 확인하세요.", runId: retryRun, requestId: body.requestId, replayed: false } });
      }
      if (body.operation === "detail") return route.fulfill({ json: body.runId === retryRun
        ? detail(retryRun, "QUEUED", { retryOf: failedRun, requestedBy: "admin" })
        : detail(String(body.runId), "FAILURE") });
      return route.fulfill({ status: 422, json: { detail: "unexpected" } });
    }
    return route.fulfill({ json: { items: [] } });
  });
  return actions;
}

function consoleRequests(page: Page) {
  const seen: Request[] = [];
  page.on("request", (request) => { if (new URL(request.url()).pathname === "/api/dagster/console") seen.push(request); });
  return seen;
}

for (const width of [390, 1440]) test(`실패한 유가 수집을 관리자 콘솔에서 재시도한다 ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
  const actions = await fixture(page);
  const requests = consoleRequests(page);
  await page.goto("/admin/dagster");
  const table = page.getByRole("region", { name: "최근 Dagster 실행 표" });
  await expect(table).toContainText("주유소·유가");
  await table.getByRole("button", { name: "주유소·유가" }).first().click();
  const inspector = page.getByRole("region", { name: "실행 진행 상세" });
  await expect(inspector).toContainText("실행 실패");
  const retry = inspector.getByRole("button", { name: "재시도", exact: true });
  await expect(retry).toBeVisible();
  await expect(retry).toBeEnabled();
  // 설명은 버튼의 접근성 설명으로 연결된다(무엇을 다시 하는지·감사 기록·유가 예약 규칙).
  await expect(retry).toHaveAccessibleDescription(/요청자·원본 실행을 기록/);
  await expect(retry).toHaveAccessibleDescription(/유가 수집은 직전 시도가 실패였을 때만/);
  const box = await retry.boundingBox();
  expect(box!.height).toBeGreaterThanOrEqual(width === 390 ? 32 : 28);
  await retry.click();

  await expect(inspector.locator("[data-slot=alert]")).toContainText("실행 요청을 확인했습니다");
  await expect(inspector.getByRole("link", { name: "요청한 실행 보기 ↗" })).toHaveAttribute("href", new RegExp(retryRun));
  expect(actions).toHaveLength(1);
  // 브라우저는 고정 명령과 대상 run만 보낸다. 실행 설정·GraphQL 문서·요청자를 보내지 않는다(요청자는 서버 세션).
  expect(Object.keys(actions[0]).sort()).toEqual(["action", "operation", "requestId", "runId"]);
  expect(actions[0]).toMatchObject({ operation: "action", action: "retry", runId: failedRun });
  expect(String(actions[0].requestId)).toMatch(/^[0-9a-f-]{36}$/);
  expect(requests.every((request) => !(request.postData() ?? "").includes("query"))).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/dagster-retry-${width}.png`, fullPage: true });
});

test("재시도로 만든 실행의 상세는 원본 실행과 요청자를 보여 준다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await fixture(page);
  await page.route("**/api/dagster/graphql", (route) => {
    const body = route.request().postDataJSON() as { operationName?: string };
    if (body.operationName === "TransportDagsterRunFailure") return route.fulfill({ json: failure });
    return route.fulfill({ json: { ...overview, data: { ...overview.data, runsOrError: { __typename: "Runs", results: [
      { runId: retryRun, jobName: "fuel_collection_job", status: "QUEUED", startTime: null, endTime: null, tags: [] }, ...runs,
    ] } } } });
  });
  await page.goto("/admin/dagster");
  const table = page.getByRole("region", { name: "최근 Dagster 실행 표" });
  await table.getByRole("button", { name: "주유소·유가" }).first().click();
  const inspector = page.getByRole("region", { name: "실행 진행 상세" });
  await expect(inspector).toContainText("재시도 원본");
  await expect(inspector.getByRole("link", { name: `${failedRun} ↗` })).toHaveAttribute("href", new RegExp(failedRun));
  await expect(inspector).toContainText("admin ·");
  // 대기 중인 재시도 실행에는 다시 재시도 버튼을 두지 않는다(실패·취소 실행만).
  await expect(inspector.getByRole("button", { name: "재시도", exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
