import { expect, test, type Page } from "@playwright/test";
import { installParkingFixture } from "./parking-layout-fixture";

// 공개 분석 화면의 "기준 시각"(기간 분석 사전집계 생성 시각). 고정 응답(parking-layout-fixture)이라
// 로컬 미리보기(next start)에서만 돈다: E2E_PARKING_LAYOUT=true E2E_BASE_URL=http://127.0.0.1:<port>
test.beforeEach(() => {
  test.skip(process.env.E2E_PARKING_LAYOUT !== "true", "고정 응답 배치 검증은 로컬 미리보기에서만 실행");
});

function seoulClock(iso: string) {
  return new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Seoul" }).format(new Date(iso));
}

async function openAnalytics(page: Page, width: number, generatedAt: string | null) {
  await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
  await installParkingFixture(page, { analyticsGeneratedAt: generatedAt });
  await page.goto("/analytics");
  await expect(page.getByRole("heading", { name: "분석", level: 2 })).toBeVisible({ timeout: 20_000 });
}

for (const width of [320, 390, 1440]) {
  test(`${width}px: 기준 시각을 제목 아래 한 줄로 보이고, 늦으면 경고 톤`, async ({ page }) => {
    const fresh = new Date(Date.now() - 4 * 60_000).toISOString();
    await openAnalytics(page, width, fresh);
    const stamp = page.getByTestId("analytics-basis");
    await expect(stamp).toHaveText(`기준 시각 ${seoulClock(fresh)}`);
    await expect(stamp).toHaveAttribute("data-tone", "neutral");
    const heading = await page.getByRole("heading", { name: "분석", level: 2 }).boundingBox();
    const box = await stamp.boundingBox();
    expect(heading && box).toBeTruthy();
    // 제목 아래에 놓이고 한 줄이다.
    expect(box!.y).toBeGreaterThanOrEqual(heading!.y + heading!.height - 1);
    expect(box!.height).toBeLessThanOrEqual(24);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);

    const late = new Date(Date.now() - 50 * 60_000).toISOString();
    await openAnalytics(page, width, late);
    await expect(stamp).toContainText(`기준 시각 ${seoulClock(late)}`);
    await expect(stamp).toContainText("갱신 지연");
    await expect(stamp).toHaveAttribute("data-tone", "warning");
    const lateBox = await stamp.boundingBox();
    // 경고 문구는 좁은 화면에서도 화면 안에 들어오고 두 줄을 넘지 않는다.
    expect(lateBox!.x).toBeGreaterThanOrEqual(0);
    expect(lateBox!.x + lateBox!.width).toBeLessThanOrEqual(width);
    expect(lateBox!.height).toBeLessThanOrEqual(40);
    const colors = await stamp.evaluate((node) => {
      const style = getComputedStyle(node);
      return { color: style.color, background: style.backgroundColor };
    });
    expect(colors.background).not.toBe("rgba(0, 0, 0, 0)");
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);

    // 기준 시각이 없는(이전 backend) 응답에서는 줄을 만들지 않는다.
    await openAnalytics(page, width, null);
    await expect(page.getByText("요일별 시간대 평균 잔여 주차면")).toBeVisible({ timeout: 20_000 });
    await expect(stamp).toHaveCount(0);
  });
}
