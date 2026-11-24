import { expect, test, type Page } from "@playwright/test";
import { installParkingFixture } from "./parking-layout-fixture";

// 공개 분석 화면의 "기준 시각"(기간 분석 사전집계 생성 시각). 고정 응답(parking-layout-fixture)이라
// 로컬 미리보기(next start)에서만 돈다: E2E_PARKING_LAYOUT=true E2E_BASE_URL=http://127.0.0.1:<port>
test.beforeEach(() => {
  test.skip(process.env.E2E_PARKING_LAYOUT !== "true", "고정 응답 배치 검증은 로컬 미리보기에서만 실행");
});

function seoulClock(iso: string) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
    hour12: false, timeZone: "Asia/Seoul" }).formatToParts(new Date(iso)).map((part) => [part.type, part.value]));
  return `${parts.month}.${parts.day} ${parts.hour}:${parts.minute} KST`;
}

async function openAnalytics(page: Page, width: number, generatedAt: string | null) {
  await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
  await installParkingFixture(page, { analyticsGeneratedAt: generatedAt });
  await page.goto("/analytics");
  await expect(page.getByRole("heading", { name: "분석", level: 2 })).toBeVisible({ timeout: 20_000 });
}

for (const width of [320, 390, 1440]) {
  test(`${width}px: 기준 시각을 제목 곁에 한 줄로 보이고, 늦으면 경고 톤`, async ({ page }) => {
    // 평소 늦음(수집 + 갱신, 20분까지)은 경고하지 않는다.
    const fresh = new Date(Date.now() - 20 * 60_000).toISOString();
    await openAnalytics(page, width, fresh);
    const stamp = page.getByTestId("analytics-basis");
    await expect(stamp).toHaveText(`분석 기준 ${seoulClock(fresh)}`);
    await expect(stamp).toHaveAttribute("data-tone", "neutral");
    const heading = await page.getByRole("heading", { name: "분석", level: 2 }).boundingBox();
    const box = await stamp.boundingBox();
    expect(heading && box).toBeTruthy();
    // 페이지 머리말 안에서 제목 옆(같은 기준선) 또는 바로 아래(좁은 화면은 줄바꿈)에 놓이고, 한 줄이며 화면 안에 있다.
    await expect(page.locator("header.page-header [data-testid=analytics-basis]")).toHaveCount(1);
    expect(box!.x >= heading!.x + heading!.width - 1 || box!.y >= heading!.y + heading!.height - 1).toBe(true);
    expect(box!.y - (heading!.y + heading!.height)).toBeLessThanOrEqual(8);
    expect(box!.height).toBeLessThanOrEqual(24);
    expect(box!.x + box!.width).toBeLessThanOrEqual(width);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);

    const late = new Date(Date.now() - 50 * 60_000).toISOString();
    await openAnalytics(page, width, late);
    await expect(stamp).toContainText(`분석 기준 ${seoulClock(late)}`);
    await expect(stamp).toContainText("50분 전 집계");
    await expect(stamp).toHaveAttribute("data-tone", "warning");
    const lateBox = await stamp.boundingBox();
    // 경고 문구는 좁은 화면에서도 화면 안에 들어오고 두 줄을 넘지 않는다(조각 단위로만 꺾인다).
    expect(lateBox!.x).toBeGreaterThanOrEqual(0);
    expect(lateBox!.x + lateBox!.width).toBeLessThanOrEqual(width);
    expect(lateBox!.height).toBeLessThanOrEqual(40);
    const colors = await stamp.evaluate((node) => {
      const style = getComputedStyle(node);
      return { color: style.color, background: style.backgroundColor };
    });
    expect(colors.background).not.toBe("rgba(0, 0, 0, 0)");
    // 다크 모드에서도 경고 배경이 남는다(토큰의 다크 정의).
    await page.emulateMedia({ colorScheme: "dark" });
    const darkBackground = await stamp.evaluate((node) => getComputedStyle(node).backgroundColor);
    expect(darkBackground).not.toBe("rgba(0, 0, 0, 0)");
    expect(darkBackground).not.toBe(colors.background);
    await page.emulateMedia({ colorScheme: "light" });
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);

    // 기준 시각이 없는(이전 backend) 응답에서는 줄을 만들지 않는다.
    await openAnalytics(page, width, null);
    await expect(page.getByText("요일별 시간대 평균 잔여 주차면")).toBeVisible({ timeout: 20_000 });
    await expect(stamp).toHaveCount(0);
  });
}
