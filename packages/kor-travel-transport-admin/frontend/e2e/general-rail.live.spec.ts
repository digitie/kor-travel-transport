import { expect, test } from "@playwright/test";

test("실제 TAGO 서울→부산 시간표를 새 API 저장 경로와 UI에서 확인한다", async ({ page }) => {
  test.setTimeout(90_000);
  const api = process.env.E2E_TRANSPORT_GENERAL_RAIL_API_URL;
  const password = process.env.E2E_TRANSPORT_UI_PASSWORD;
  test.skip(!api || !password, "명시적으로 지정한 일반철도 QA API와 로그인 암호가 필요합니다.");
  await page.goto("/login");
  await page.getByLabel("비밀번호").fill(password!);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  // 배포 전 로컬 새 API로 연결한다. payload를 대역으로 만들지 않고 실제 SDK·DB 응답을 사용한다.
  await page.route("**/api/transport/transport/rail/general/**", async (route) => {
    const original = new URL(route.request().url());
    const path = original.pathname.replace("/api/transport/", "/v1/");
    const response = await route.fetch({ url: `${api}${path}${original.search}`, headers: { accept: "application/json" } });
    expect(response.status()).toBe(200);
    await route.fulfill({ response });
  });
  await page.goto("/rail");
  await page.getByLabel("노선", { exact: true }).selectOption("ktx1");
  const guideResults = page.getByLabel("철도 역 검색 결과");
  await expect(guideResults.getByRole("button")).toHaveCount(19);
  await guideResults.getByRole("button", { name: /^서울 / }).click();
  await expect(page.getByRole("link", { name: "공식 역 안내" })).toHaveAttribute("href", /stationSeq=\d+/);
  await expect(page.getByRole("link", { name: /1588/ })).toHaveAttribute("href", /^tel:/);
  const kinds = page.getByLabel("열차 종류", { exact: true });
  await expect(kinds).toContainText("KTX");
  await expect(kinds).toContainText("SRT");
  await expect(kinds).toContainText("무궁화호");
  const from = page.getByRole("group", { name: "출발역", exact: true });
  const to = page.getByRole("group", { name: "도착역", exact: true });
  await from.getByLabel("지역", { exact: true }).selectOption("11");
  await from.getByLabel("출발역 검색").fill("서울");
  await from.getByRole("button", { name: /^서울 NAT010000$/ }).click();
  await to.getByLabel("지역", { exact: true }).selectOption("21");
  await to.getByLabel("도착역 검색").fill("부산");
  await to.getByRole("button", { name: /^부산 NAT014445$/ }).click();
  await page.getByRole("button", { name: "예정 운행편 조회" }).click();
  await expect(page.locator(".departure-row").first()).toBeVisible();
  await expect(page.locator(".journey-workbench").getByRole("alert")).toHaveCount(0);
  expect(await page.locator(".departure-row").count()).toBeGreaterThan(0);
  await page.screenshot({ path: "test-results/general-rail-live-desktop.png", fullPage: true });
});
