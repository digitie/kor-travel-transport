import { expect, test, type Page } from "@playwright/test";
import { failureDiagnostic } from "../lib/dagster-failure-diagnostics";

// 소유자 결정(2026-11-24): 제공기관 원천(또는 호출)이 모두 실패한 실행은 부분 실패 기준과 무관하게 실패다.
// 공항 주차 원천이 모두 실패한 run의 상세 화면이 "등록되지 않은 실행 오류"가 아니라 고정 사유(ALL_SOURCES_FAILED)와
// 시도·실패 원천 수를 보이는지 본다. 단계 실패 문장은 BFF와 같은 서버 정제 함수(`failureDiagnostic`)로 만든다.
const runId = "c3a9e1f2-6b7d-4e58-9a10-2f4b6c8d0e13";
const now = Math.floor(Date.parse("2026-11-24T21:10:00Z") / 1000);
const runs = [{ runId, jobName: "airport_collection_job", status: "FAILURE", startTime: now - 90, endTime: now - 30,
  tags: [{ key: "dagster/code_location", value: "kor-travel-transport" }] }];
const overview = { data: { activeRuns: { __typename: "Runs", results: [] }, repositoryOrError: { __typename: "Repository", schedules: [] },
  runsOrError: { __typename: "Runs", results: runs } } };
const catalog = { jobs: ["airport_collection_job"], schedules: [], sensors: [],
  capabilities: { launch: true, retry: true, cancel: true, schedule: true, sensor: true }, checkedAt: "2026-11-24T21:10:00.000Z" };
const stepFailure = failureDiagnostic({
  __typename: "ExecutionStepFailureEvent", stepKey: "collect_airport_parking",
  message: "주차 원천 2곳이 모두 실패했습니다(ALL_SOURCES_FAILED). 요금·이력 저장분은 유지했고 주차 현재값은 직전 성공 세대를 유지합니다.",
  failureMetadata: { metadataEntries: [
    { label: "error_code", text: "ALL_SOURCES_FAILED" }, { label: "stage", text: "provider_fetch" },
    { label: "status", text: "failed" }, { label: "recovery_hint", text: "CHECK_RUN_DETAIL" },
    { label: "successful_data_preserved", boolValue: true },
    { label: "parking_sources_total", intValue: 2 }, { label: "parking_sources_failed", intValue: 2 },
    { label: "run_id", intValue: 9113 }, { label: "retryable", boolValue: false },
    { label: "source_error_code", text: "PROVIDER_RATE_LIMIT" },
  ] },
});
const detail = {
  runId, jobName: "airport_collection_job", status: "FAILURE", creationTime: now - 100, startTime: now - 90, endTime: now - 30,
  queuedTime: now - 100, canCancel: false, canRetry: true,
  steps: [{ key: "collect_airport_parking", status: "FAILURE", startTime: now - 90, endTime: now - 30, attempts: 1 }],
  events: [{ kind: "ExecutionStepFailureEvent", time: (now - 30) * 1000, step: "collect_airport_parking", title: "단계 실패",
    detail: stepFailure, warning: true, counts: {} }],
  stepsSucceeded: 0, stepsFailed: 1, materializations: 0, cursor: null, hasMore: false, stepsTruncated: false,
  checkedAt: "2026-11-24T21:10:00.000Z", retryOf: null, requestedBy: null,
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

test("서버 정제 문장은 미등록 오류가 아닌 고정 사유와 원천 수다", () => {
  expect(stepFailure).toContain("오류 코드: ALL_SOURCES_FAILED");
  expect(stepFailure).not.toContain("UNKNOWN_FAILURE");
  expect(stepFailure).toContain("실패 단계: 제공기관 요청");
  expect(stepFailure).toContain("시도한 주차 원천 수: 2");
});

for (const width of [390, 1440]) test(`주차 원천이 모두 실패한 공항 수집은 고정 사유와 원천 수를 보여 준다 ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
  await fixture(page);
  await page.goto("/admin/dagster");
  const table = page.getByRole("region", { name: "최근 Dagster 실행 표" });
  await table.getByRole("button", { name: "공항 주차·요금" }).first().click();
  const inspector = page.getByRole("region", { name: "실행 진행 상세" });
  await expect(inspector).toContainText("실행 실패");
  await expect(inspector).toContainText("ALL_SOURCES_FAILED");
  await expect(inspector).toContainText("원천 전부, 또는 한 제공기관의 호출 전부가 실패했습니다");
  await expect(inspector).toContainText("원인 분류: PROVIDER_RATE_LIMIT");
  await expect(inspector).toContainText("시도한 주차 원천 수: 2");
  await expect(inspector).toContainText("실패한 주차 원천 수: 2");
  await expect(inspector).not.toContainText("등록되지 않은 실행 오류");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
