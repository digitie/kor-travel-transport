import { expect, test } from "@playwright/test";

const username = process.env.E2E_TRANSPORT_UI_USER ?? "admin";
const password = process.env.E2E_TRANSPORT_UI_PASSWORD;
const apiBase = process.env.E2E_TRANSPORT_API_BASE_URL ?? "https://transport-api.digitie.mywire.org";
const dagsterBase = process.env.E2E_TRANSPORT_DAGSTER_BASE_URL ?? "https://transport-dagster.digitie.mywire.org";

test.beforeEach(() => { test.skip(!password, "E2E_TRANSPORT_UI_PASSWORD가 필요합니다."); });

test("관리 UI 인증·저장 스냅샷·로그아웃 경계를 검증한다", async ({ page, request }) => {
  await page.goto("/"); await expect(page).toHaveURL(/\/login/);
  expect((await request.get("/api/transport/transport/statistics")).status()).toBe(401);
  await page.getByLabel("아이디").fill(username); await page.getByLabel("비밀번호").fill(password!); await page.getByRole("button", { name: "로그인" }).click();
  await expect(page).toHaveURL(/\/$/); await expect(page.getByRole("heading", { name: "통합 교통정보 현황" })).toBeVisible();
  await expect(page.getByText("수집 소스")).toBeVisible({ timeout: 20_000 });
  const status = await page.request.get("/api/transport/transport/collector-status"); expect(status.status()).toBe(200); expect(Array.isArray((await status.json()).sources)).toBe(true);
  await page.getByRole("button", { name: "로그아웃" }).click(); await expect(page).toHaveURL(/\/login/);
});

test("공개 API와 Dagster gateway의 분리된 경계를 검증한다", async ({ request }) => {
  const health = await request.get(`${apiBase}/health`); expect(health.status()).toBe(200); expect((await health.json()).status).toBe("ok");
  const statistics = await request.get(`${apiBase}/v1/transport/statistics?days=1`); expect(statistics.status()).toBe(200); expect(Array.isArray((await statistics.json()).traffic)).toBe(true);
  expect((await request.get(`${dagsterBase}/health`)).status()).toBe(204);
  expect((await request.post(`${dagsterBase}/graphql`, { data: { query: "{ __typename }" } })).status()).toBe(401);
});
