import { expect, test } from "@playwright/test";

for (const width of [375, 1440]) test(`실제 저장 배편 기준자료를 검색한다 ${width}px`, async ({ page }) => {
  test.skip(!process.env.E2E_TRANSPORT_UI_PASSWORD, "실제 로그인 비밀번호 환경변수가 필요합니다.");
  await page.setViewportSize({ width, height: 900 });
  await page.goto("/login");
  await page.getByLabel("아이디").fill(process.env.E2E_TRANSPORT_UI_USER ?? "admin");
  await page.getByLabel("비밀번호").fill(process.env.E2E_TRANSPORT_UI_PASSWORD!);
  await page.getByRole("button", { name: "로그인" }).click();
  await expect(page).toHaveURL(/\/$/);
  const response = page.waitForResponse((r) => r.url().includes("/api/transport/transport/ferry/reference") && r.status() === 200);
  await page.goto("/ferry");
  const data = await (await response).json();
  expect(data.items).toHaveLength(4);
  expect(data.items.every((s: {data: {items: unknown[]} | null}) => s.data && s.data.items.length > 0)).toBe(true);
  await expect(page.getByRole("heading", { name: "항로·터미널 찾아보기" })).toBeVisible();
  const references = page.getByRole("region", { name: "항로·터미널 찾아보기" });
  await expect(references.getByText("여객항로", { exact: true })).toBeVisible();
  await expect(references.getByText("도선항로", { exact: true })).toBeVisible();
  await expect(references.getByText("과거 조사자료", { exact: false })).toBeVisible();
  await expect(references.getByText("출발지 미제공", { exact: false }).first()).toBeVisible();
  await references.getByLabel("항로·시설 검색").fill("제주");
  await expect(references.getByText("제주", { exact: false }).first()).toBeVisible();
  await references.getByLabel("항로·시설 검색").fill("없는검증항로_492");
  await expect(references.getByText("검색 결과 없음", { exact: true })).toHaveCount(4);
  await references.getByLabel("항로·시설 검색").clear();
  await expect(references.getByRole("link", { name: /원문 출처/ })).toHaveCount(4);
  if (process.env.E2E_FERRY_TIMETABLE_PORT) {
    const timetable = page.waitForResponse((r) => r.url().includes("/transport/ports/timetables?") && r.status() === 200);
    await page.goto(`/ferry?port=${encodeURIComponent(process.env.E2E_FERRY_TIMETABLE_PORT)}`);
    const saved = await (await timetable).json();
    expect(saved.items.some((item: {items: unknown[]}) => item.items.length > 0)).toBe(true);
    await expect(page.getByRole("heading", { name: "오늘 운항 비교" })).toBeVisible();
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/vadahub-ferry-${width}.png`, fullPage: true });
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  await expect(page).toHaveURL(/\/login/);
});
