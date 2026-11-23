import { expect, test, type Locator, type Page } from "@playwright/test";
import { installParkingFixture } from "./parking-layout-fixture";

// 공개 parking-radar 화면의 비율 회귀. 운영 API 대신 고정 응답(parking-layout-fixture)을 쓰므로
// 로컬 미리보기(next start)에서만 돈다: E2E_PARKING_LAYOUT=true E2E_BASE_URL=http://127.0.0.1:<port>
test.beforeEach(() => {
  test.skip(process.env.E2E_PARKING_LAYOUT !== "true", "고정 응답 배치 검증은 로컬 미리보기에서만 실행");
});

const ROUTES = ["/", "/analytics", "/history", "/fees"] as const;

async function box(locator: Locator) {
  const value = await locator.boundingBox();
  expect(value, "요소가 화면에 배치돼야 한다").not.toBeNull();
  return value!;
}

async function horizontalOverflow(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
}

async function openCurrent(page: Page, width: number) {
  await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
  await installParkingFixture(page);
  await page.goto("/");
  await expect(page.getByText("현재 잔여 주차면", { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".parking-pie-canvas canvas").first()).toBeVisible({ timeout: 20_000 });
}

for (const width of [320, 390]) {
  test(`모바일 ${width}px: 넘침 없음·44px 터치 표적·한 줄 필터와 버튼`, async ({ page }) => {
    await openCurrent(page, width);
    for (const route of ROUTES) {
      if (route !== "/") await page.goto(route);
      await expect(page.getByRole("combobox", { name: "공항 선택" })).toBeVisible();
      expect(await horizontalOverflow(page), `${route} 가로 넘침`).toBeLessThanOrEqual(0);
    }
    await page.goto("/");
    await expect(page.locator(".parking-pie-canvas canvas").first()).toBeVisible({ timeout: 20_000 });

    // 상단 바는 한 줄(관리자 상단 바 min-h-12와 같은 높이대).
    expect((await box(page.locator("header").first())).height).toBeLessThanOrEqual(56);

    const airport = page.getByRole("combobox", { name: "공항 선택" });
    const lot = page.getByRole("combobox", { name: "세부 주차장" });
    const refresh = page.getByRole("button", { name: "새로고침" });
    const [airportBox, lotBox, refreshBox] = [await box(airport), await box(lot), await box(refresh)];
    for (const target of [airportBox, lotBox, refreshBox]) expect(target.height).toBeGreaterThanOrEqual(44);
    expect(refreshBox.width).toBeGreaterThanOrEqual(44);
    // 두 select는 한 줄이고 주차장 칸이 더 넓다(구분자가 뒤에 있는 긴 주차장 이름).
    expect(Math.abs(airportBox.y - lotBox.y)).toBeLessThanOrEqual(1);
    expect(lotBox.width).toBeGreaterThan(airportBox.width);
    for (const link of await page.getByRole("navigation", { name: "하단 메뉴" }).getByRole("link").all()) {
      expect((await box(link)).height).toBeGreaterThanOrEqual(44);
    }

    // 요약 셋: 390px은 합계 한 줄 전체 + 나머지 둘이 반씩, 320px은 반 칸에 긴 주차장 이름이 꺾이므로 한 열.
    // 어느 쪽이든 카드는 낮고(이름이 두 줄로 꺾이지 않고) 값 글자가 20px을 넘지 않는다.
    const cards = page.locator(".detail-ribbon > *");
    await expect(cards).toHaveCount(3);
    const [total, tight, roomy] = [await box(cards.nth(0)), await box(cards.nth(1)), await box(cards.nth(2))];
    const ribbon = await box(page.locator(".detail-ribbon"));
    expect(total.width).toBeGreaterThan(ribbon.width - 2);
    if (width >= 375) {
      expect(Math.abs(tight.y - roomy.y)).toBeLessThanOrEqual(1);
      expect(Math.abs(tight.width - roomy.width)).toBeLessThanOrEqual(1);
      expect(Math.abs(tight.height - roomy.height)).toBeLessThanOrEqual(1);
    } else {
      for (const card of [tight, roomy]) expect(card.width).toBeGreaterThan(ribbon.width - 2);
    }
    for (const card of [total, tight, roomy]) expect(card.height).toBeLessThanOrEqual(width >= 375 ? 110 : 100);
    const valueSize = await cards.nth(0).locator("strong").evaluate((node) => parseFloat(getComputedStyle(node).fontSize));
    expect(valueSize).toBeLessThanOrEqual(20);

    // 도넛은 수치 옆에 놓이고 카드 폭의 절반을 넘지 않는다(이전: 폭 전체 240px 원).
    const pieCard = page.locator(".parking-pie-card").first();
    const [pieBox, chartBox, valuesBox] = [await box(pieCard), await box(pieCard.locator(".parking-pie-canvas")), await box(pieCard.locator(".parking-pie-values"))];
    expect(chartBox.width).toBeGreaterThanOrEqual(80);
    expect(chartBox.width).toBeLessThanOrEqual(pieBox.width * 0.45);
    expect(Math.abs(chartBox.width - chartBox.height)).toBeLessThanOrEqual(1);
    expect(valuesBox.x).toBeGreaterThan(chartBox.x + chartBox.width);
    expect(pieBox.height).toBeLessThanOrEqual(180);

    // 버튼 글자가 두 줄로 꺾이지 않는다.
    await page.goto("/history");
    const range = page.getByRole("button", { name: "날짜 범위 선택" });
    await expect(range).toBeVisible({ timeout: 20_000 });
    const rangeBox = await box(range);
    expect(rangeBox.height).toBeGreaterThanOrEqual(44);
    expect(rangeBox.height).toBeLessThanOrEqual(48);
  });
}

test("데스크톱 1440px: 본문 폭·요약 한 줄·도넛 카드 비율", async ({ page }) => {
  await openCurrent(page, 1440);
  for (const route of ROUTES) {
    if (route !== "/") await page.goto(route);
    await expect(page.getByRole("combobox", { name: "공항 선택" })).toBeVisible();
    expect(await horizontalOverflow(page), `${route} 가로 넘침`).toBeLessThanOrEqual(0);
  }
  await page.goto("/");
  await expect(page.locator(".parking-pie-canvas canvas").first()).toBeVisible({ timeout: 20_000 });

  const header = await box(page.locator("header").first());
  expect(header.height).toBeLessThanOrEqual(56);
  await expect(page.getByRole("navigation", { name: "주요 메뉴" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "하단 메뉴" })).toBeHidden();

  const shell = await box(page.locator("main .page-shell").first());
  expect(shell.width).toBeLessThanOrEqual(1200);

  // 관리자와 같은 컨트롤 높이(36px)·반경(6px)·카드 반경(8px), 카드 그림자 없음.
  const refresh = page.getByRole("button", { name: "새로고침" });
  expect((await box(refresh)).height).toBe(36);
  await expect(refresh).toHaveText(/새로고침/);
  const select = page.getByRole("combobox", { name: "공항 선택" });
  expect((await box(select)).height).toBe(36);
  expect(await select.evaluate((node) => getComputedStyle(node).borderTopLeftRadius)).toBe("6px");
  const card = page.locator(".detail-ribbon > *").first();
  expect(await card.evaluate((node) => getComputedStyle(node).borderTopLeftRadius)).toBe("8px");
  expect(await card.evaluate((node) => getComputedStyle(node).boxShadow)).toBe("none");

  const cards = page.locator(".detail-ribbon > *");
  const tops = await Promise.all([0, 1, 2].map(async (index) => (await box(cards.nth(index))).y));
  expect(Math.max(...tops) - Math.min(...tops)).toBeLessThanOrEqual(1);
  expect((await box(cards.first())).height).toBeLessThanOrEqual(100);

  // 도넛 카드는 한 줄에 셋 이상, 높이가 고르고 낮다.
  const pies = page.locator(".parking-pie-card");
  const pieTops = await Promise.all((await pies.all()).map(async (pie) => (await box(pie)).y));
  expect(pieTops.filter((top) => Math.abs(top - pieTops[0]) <= 1).length).toBeGreaterThanOrEqual(3);
  for (const pie of await pies.all()) {
    const pieBox = await box(pie);
    const chart = await box(pie.locator(".parking-pie-canvas"));
    expect(pieBox.height).toBeLessThanOrEqual(180);
    expect(chart.width).toBeLessThanOrEqual(pieBox.width * 0.45);
  }

  await expect(page.getByTestId("desktop-lot-table")).toBeVisible();
  await expect(page.getByTestId("mobile-lot-grid")).toBeHidden();

  // 여러 원이 겹친 묶음 카드(김해 P1·P2)에서도 수치 글자가 카드 밖으로 나가지 않는다.
  await page.getByRole("combobox", { name: "공항 선택" }).selectOption("PUS");
  await expect(page.locator(".parking-pie-card").first()).toContainText("1. P1 여객주차장");
  await expect(page.locator(".parking-pie-canvas canvas").first()).toBeVisible({ timeout: 20_000 });
  const spill = await page.locator(".parking-pie-card").evaluateAll((cards) => cards.flatMap((card) => {
    const edge = card.getBoundingClientRect().right;
    return [...card.querySelectorAll(".parking-pie-values span")].filter((node) => node.getBoundingClientRect().right > edge + 0.5).map((node) => node.textContent);
  }));
  expect(spill).toEqual([]);
});
