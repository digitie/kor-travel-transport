import { expect, test, type Page, type Request, type Route } from "@playwright/test";

// 공개 유가(TRANSPORT_UI_MODE=fuel) 맨 위 줄(지역 아이콘 + 유종·필터 한 곳 선택, 필터 버튼·서랍 없음)과 지역 칩 하나
// (고른 지역, 고르기 전에는 지도 중심 시군구, 중심을 모르면 화면에서 주유소가 가장 많은 시군구).
// 필터는 서버가 적용하므로 places 요청 query로 확인하고, 응답은 그 query를 흉내 낸 격리 응답이다.
// 스크린샷은 E2E_SCREENSHOT_DIR이 있으면 그곳에도 저장한다.
const generated = "2026-11-21T22:00:00Z";
const metrics = { station_count: 12, average_price: 1700, minimum_price: 1600, maximum_price: 1800, price_spread: 200,
  standard_deviation: 45, saving_50l: 5000, cheapest_station_count: 1, generated_at: generated, cheapest_station: { name: "최저가", address: "서울" } };
const catalog = { items: [
  { sido_value: "01", sido_name: "서울", sigungu: [{ sigungu_value: "0101", sigungu_name: "종로구", station_count: 20, bounds: [126.95, 37.56, 127.02, 37.6] }] },
  { sido_value: "15", sido_name: "충북", sigungu: [
    { sigungu_value: "1501", sigungu_name: "영동군", station_count: 30, bounds: [127.6, 36.0, 128.0, 36.3] },
    { sigungu_value: "1502", sigungu_name: "옥천군", station_count: 29, bounds: [127.5, 36.2, 127.8, 36.45] },
    { sigungu_value: "1503", sigungu_name: "청주시 상당구", station_count: 40, bounds: [127.45, 36.55, 127.65, 36.7] },
  ] },
] };

async function shot(page: Page, name: string, testInfo: { outputPath: (name: string) => string }) {
  await page.screenshot({ path: testInfo.outputPath(name), animations: "disabled" });
  if (process.env.E2E_SCREENSHOT_DIR) await page.screenshot({ path: `${process.env.E2E_SCREENSHOT_DIR}/${name}`, animations: "disabled" });
}

// 서버의 지도 중심 시군구(가장 가까운 주유소 근사)를 흉내 낸다: 경도 127.3 서쪽은 서울 중구, 동쪽은 충북 영동군.
// 화면 1순위(옥천군)·지역 이동에서 고르는 곳(서울 종로구)과 일부러 다르게 둬 칩의 근거를 구별한다.
const CENTER_WEST = { sido_value: "01", sido_name: "서울", sigungu_value: "0102", sigungu_name: "중구", method: "nearest_station", distance_m: 400 };
const CENTER_EAST = { sido_value: "15", sido_name: "충북", sigungu_value: "1501", sigungu_name: "영동군", method: "nearest_station", distance_m: 900 };
const centerFor = (url: URL) => Number(url.searchParams.get("center_longitude")) < 127.3 ? CENTER_WEST : CENTER_EAST;

const placeRequests: URL[] = [];
test.beforeEach(async ({ page }) => {
  test.skip(process.env.E2E_PUBLIC_FUEL !== "true", "공개 유가(TRANSPORT_UI_MODE=fuel) 격리 UI 테스트");
  placeRequests.length = 0;
  await page.route((url) => /^https?:$/.test(url.protocol) && !["127.0.0.1", "localhost"].includes(url.hostname), (route) => route.abort());
  await page.route("**/api/public/fuel/places?*", (route: Route) => {
    const url = new URL(route.request().url());
    placeRequests.push(url);
    // 필터 개수만큼 주유소 수가 줄어든 서버 응답을 흉내 낸다.
    const active = ["self_only", "open_24h", "carwash", "maintenance", "cvs", "kpetro", "brands", "near_min"].filter(key => url.searchParams.has(key)).length;
    return route.fulfill({ json: {
      items: [], total: 0, truncated: false, clustered: false, available_sources: [],
      fuel_statistics: [{ ...metrics, product_code: "B027", station_count: 12 - active }],
      fuel_prices_stale: false, fuel_prices_last_refreshed_at: generated,
      fuel_viewport_sigungu: [{ sido_value: "15", sido_name: "충북", sigungu_value: "1502", sigungu_name: "옥천군", station_count: 12 - active }],
      fuel_viewport_sigungu_total: 1,
      ...(url.searchParams.has("center_longitude") ? { fuel_center_sigungu: centerFor(url) } : {}),
    } });
  });
  await page.route("**/api/public/fuel/area-catalog", (route: Route) => route.fulfill({ json: catalog }));
});

const summaryOf = (page: Page) => page.getByRole("region", { name: "현재 지도 범위 유가 통계" });
const lastPlaces = () => placeRequests.at(-1)!;
const waitPlaces = (page: Page, check: (url: URL) => boolean) => page.waitForRequest((request: Request) => {
  const url = new URL(request.url());
  return url.pathname.endsWith("/api/public/fuel/places") && check(url);
});
const noHorizontalScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);
const FILTER_KEYS = ["self_only", "open_24h", "carwash", "maintenance", "cvs", "kpetro", "brands", "near_min"];
const filterTrigger = (page: Page) => summaryOf(page).getByRole("button", { name: /^유종·필터/ });
const filterMenu = (page: Page) => page.getByRole("dialog", { name: "유종·필터" });
const regionChips = (page: Page) => summaryOf(page).locator(".fuel-sigungu-chips .fuel-sigungu-chip:not(.fuel-sigungu-clear)");

for (const width of [320, 390, 1440]) {
  test(`${width}px 맨 위 줄: 지역 아이콘과 유종·필터 하나, '지도 범위' 글씨와 필터 버튼은 없다`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: width < 1000 ? 844 : 900 });
    await page.goto("/");
    const summary = summaryOf(page);
    await expect(summary).toContainText("12개 주유소");
    // 제목 글씨 "지도 범위"·따로 있던 필터/지역 글자 버튼이 없다(영역 이름은 aria-label로만 남는다).
    await expect(summary).not.toContainText("지도 범위");
    await expect(summary.getByRole("heading", { level: 2 })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^필터/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "지역", exact: true })).toHaveCount(0);
    await expect(page.locator(".public-fuel-tools, .fuel-filter-drawer")).toHaveCount(0);
    const region = summary.getByRole("button", { name: "지역 이동" });
    await expect(region).toHaveText("");
    const trigger = filterTrigger(page);
    const [regionBox, triggerBox, summaryBox] = [(await region.boundingBox())!, (await trigger.boundingBox())!, (await summary.boundingBox())!];
    // 지역 아이콘은 요약의 맨 위 줄 첫 칸(유종·필터와 같은 줄, 왼쪽)에 있고, 그보다 위에 다른 조작이 없다.
    expect(regionBox.width).toBeGreaterThanOrEqual(44); expect(regionBox.height).toBeGreaterThanOrEqual(44);
    expect(Math.abs((regionBox.y + regionBox.height / 2) - (triggerBox.y + triggerBox.height / 2))).toBeLessThanOrEqual(2);
    expect(regionBox.x + regionBox.width).toBeLessThanOrEqual(triggerBox.x);
    expect(regionBox.y - summaryBox.y).toBeLessThanOrEqual(10);
    for (const control of await summary.locator("button, input, select").all()) {
      const box = await control.boundingBox();
      if (box) expect(box.y).toBeGreaterThanOrEqual(regionBox.y - 1);
    }
    expect(triggerBox.x + triggerBox.width).toBeLessThanOrEqual(summaryBox.x + summaryBox.width);
    // 아이콘 버튼은 툴팁으로 이름을 알린다.
    await region.hover();
    await expect(page.getByRole("tooltip")).toHaveText("지역 이동");
    expect(await noHorizontalScroll(page)).toBe(true);
    await shot(page, `fuel-ui3-top-row-${width}.png`, testInfo);
  });

  test(`${width}px 지역 이동: 아이콘 → 시/도 → 구/군/시 → 확인하면 지도가 옮겨지고 그 지역 하나만 보인다`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: width < 1000 ? 844 : 900 });
    await page.goto("/");
    // 고르기 전에는 지도 중심 시군구(서버 fuel_center_sigungu) 하나만 보인다. 화면 1순위(옥천군)가 아니다.
    await expect(regionChips(page)).toHaveCount(1);
    await expect(regionChips(page)).toHaveText("충북 영동군");
    await expect(summaryOf(page).locator(".fuel-sigungu-chips")).toHaveAttribute("aria-label", "지도 중심 지역 가격 통계");
    const opener = summaryOf(page).getByRole("button", { name: "지역 이동" });
    await opener.click();
    const dialog = page.getByRole("dialog", { name: "지역 이동" });
    await expect(dialog).toBeVisible();
    // 지금 보이는 지역(중심 영동군)이 선택된 채 열린다.
    await expect(dialog.getByRole("radio", { name: "충북" })).toBeChecked();
    await expect(dialog.getByRole("radio", { name: "영동군" })).toBeChecked();
    // 열림 확대 애니메이션(scale)이 끝난 뒤에 잰다.
    await dialog.evaluate(node => Promise.all(node.getAnimations({ subtree: true }).map(animation => animation.finished)));
    for (const option of await dialog.locator(".fuel-region-option").all()) expect((await option.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    const box = (await dialog.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x + box.width).toBeLessThanOrEqual(width);
    await shot(page, `fuel-ui3-region-picker-${width}.png`, testInfo);
    // 취소하면 아이콘 버튼으로 초점이 돌아온다.
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(opener).toBeFocused();
    await opener.click();
    await dialog.getByRole("radio", { name: "서울" }).check();
    await expect(dialog.getByRole("button", { name: "구/군/시 선택" })).toBeDisabled();
    await dialog.getByRole("radio", { name: "종로구" }).check();
    const moved = waitPlaces(page, url => {
      const [west, south, east, north] = ["min_longitude", "min_latitude", "max_longitude", "max_latitude"].map(key => Number(url.searchParams.get(key)));
      return west <= 126.985 && east >= 126.985 && south <= 37.58 && north >= 37.58;
    });
    await dialog.getByRole("button", { name: "서울 종로구 지역으로 이동" }).click();
    await expect(dialog).toHaveCount(0);
    const request = new URL((await moved).url());
    expect(Number(request.searchParams.get("zoom"))).toBeGreaterThanOrEqual(10);
    // 마우스로 닫아 초점이 아이콘으로 돌아와도 툴팁이 열려 아래 지역 칩을 가리지 않는다.
    await expect(opener).toBeFocused();
    await expect(page.locator('[data-slot="tooltip-content"]')).toHaveCount(0);
    // 서버가 화면 안 시군구로 옥천군을 돌려줘도, 고른 지역(서울 종로구) 하나만 보인다.
    await expect(regionChips(page)).toHaveCount(1);
    await expect(regionChips(page)).toHaveText("서울 종로구");
    await expect(summaryOf(page)).not.toContainText("옥천군");
    await expect(summaryOf(page)).not.toContainText("영동군");
    await expect(summaryOf(page).locator(".fuel-sigungu-chips")).toHaveAttribute("aria-label", "선택한 지역 가격 통계");
    await expect(summaryOf(page).getByRole("button", { name: /^서울 종로구 휘발유 가격 통계/ })).toBeVisible();
    expect(await noHorizontalScroll(page)).toBe(true);
    await shot(page, `fuel-ui3-region-selected-${width}.png`, testInfo);
    // 다시 열면 고른 지역이 선택돼 있다.
    await opener.click();
    await expect(dialog.getByRole("radio", { name: "종로구" })).toBeChecked();
    await dialog.getByRole("button", { name: "취소" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page.locator('[data-slot="tooltip-content"]')).toHaveCount(0);
    // 해제하면 다시 지도 중심 시군구(지금은 옮겨 간 서울 쪽, 모의 서버는 서울 중구) 하나로 돌아가고 초점은 그 칩에 남는다.
    await summaryOf(page).getByRole("button", { name: "서울 종로구 선택 해제" }).click();
    await expect(summaryOf(page).locator(".fuel-sigungu-chips")).toHaveAttribute("aria-label", "지도 중심 지역 가격 통계");
    await expect(regionChips(page)).toHaveText("서울 중구");
    await expect(regionChips(page)).toBeFocused();
  });

  test(`${width}px 지역 칩 기본값은 지도 중심 시군구이고 지도를 옮기면 따라간다`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: width < 1000 ? 844 : 900 });
    await page.goto("/");
    const group = summaryOf(page).locator(".fuel-sigungu-chips");
    await expect(regionChips(page)).toHaveText("충북 영동군");
    await expect(group).toHaveAttribute("aria-label", "지도 중심 지역 가격 통계");
    // 중심은 조회 범위의 가운데다(범위에서만 나오므로 요청 수가 늘지 않는다). 첫 이동 알림 전 기본 범위 요청에는 없다.
    expect(placeRequests[0].searchParams.has("center_longitude")).toBe(false);
    const first = placeRequests.filter(url => url.searchParams.has("center_longitude")).at(-1)!;
    const middle = (low: string, high: string) => (Number(first.searchParams.get(low)) + Number(first.searchParams.get(high))) / 2;
    expect(Number(first.searchParams.get("center_longitude"))).toBeCloseTo(middle("min_longitude", "max_longitude"), 4);
    expect(Number(first.searchParams.get("center_latitude"))).toBeCloseTo(middle("min_latitude", "max_latitude"), 4);
    expect(await noHorizontalScroll(page)).toBe(true);
    await shot(page, `fuel-ui4-center-east-${width}.png`, testInfo);
    // 지도를 오른쪽으로 끌면(중심이 서쪽으로) 중심 시군구가 서울 중구로 바뀐다.
    const canvas = page.locator(".maplibregl-canvas");
    const box = (await canvas.boundingBox())!;
    const drag = async (dx: number) => {
      const from = { x: box.x + box.width / 2 - dx / 2, y: box.y + box.height * .75 };
      await page.mouse.move(from.x, from.y);
      await page.mouse.down();
      for (let step = 1; step <= 10; step++) await page.mouse.move(from.x + dx * step / 10, from.y);
      // 손을 떼기 전에 멈춰 관성 이동을 없앤다(이동 거리가 두 번의 끌기에서 대칭이 되게).
      await page.waitForTimeout(300);
      await page.mouse.up();
    };
    const moved = waitPlaces(page, url => Number(url.searchParams.get("center_longitude")) < 127.3);
    await drag(Math.round(box.width * .6));
    await moved;
    await expect(regionChips(page)).toHaveText("서울 중구");
    await expect(group).toHaveAttribute("aria-label", "지도 중심 지역 가격 통계");
    expect(await noHorizontalScroll(page)).toBe(true);
    await shot(page, `fuel-ui4-center-west-${width}.png`, testInfo);
    // 되돌리면 다시 영동군. 처음과 같은 조회 범위라 화면의 응답 캐시를 써서 새 요청 없이 바뀐다(중심이 캐시 키를 늘리지 않는다).
    const before = placeRequests.length;
    await drag(-Math.round(box.width * .6));
    await expect(regionChips(page)).toHaveText("충북 영동군");
    expect(placeRequests.slice(before).every(url => Number(url.searchParams.get("center_longitude")) >= 127.3)).toBe(true);
  });

  test(`${width}px 중심을 정하지 못하면(null·옛 API) 화면에서 주유소가 가장 많은 시군구로 되돌아간다`, async ({ page }) => {
    let center: "null" | "missing" = "null";
    // 나중에 등록한 route가 먼저 처리된다.
    await page.route("**/api/public/fuel/places?*", (route: Route) => route.fulfill({ json: {
      items: [], total: 0, truncated: false, clustered: false, available_sources: [],
      fuel_statistics: [{ ...metrics, product_code: "B027" }], fuel_prices_stale: false, fuel_prices_last_refreshed_at: generated,
      fuel_viewport_sigungu: [{ sido_value: "15", sido_name: "충북", sigungu_value: "1502", sigungu_name: "옥천군", station_count: 12 }],
      fuel_viewport_sigungu_total: 1, ...(center === "null" ? { fuel_center_sigungu: null } : {}),
    } }));
    await page.setViewportSize({ width, height: width < 1000 ? 844 : 900 });
    await page.goto("/");
    const group = summaryOf(page).locator(".fuel-sigungu-chips");
    await expect(regionChips(page)).toHaveText(/충북 옥천군/);
    await expect(group).toHaveAttribute("aria-label", "지도 대표 지역 가격 통계");
    center = "missing";
    await page.reload();
    await expect(regionChips(page)).toHaveText(/충북 옥천군/);
    await expect(group).toHaveAttribute("aria-label", "지도 대표 지역 가격 통계");
  });

  test(`${width}px 맨 위 유종·필터: 각 항목이 서버 query로 적용되고 저장된다`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: width < 1000 ? 844 : 900 });
    await page.goto("/");
    await expect(summaryOf(page)).toContainText("12개 주유소");
    const trigger = filterTrigger(page);
    await expect(trigger).toHaveAccessibleName("유종·필터: 전체 유종");
    await trigger.click();
    const menu = filterMenu(page);
    await expect(menu).toBeVisible();
    const box = (await menu.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(width);
    expect(box.y + box.height).toBeLessThanOrEqual(width < 1000 ? 844 : 900);
    await expect(menu).not.toContainText(/믿음|직영|스마트|면세유|화물차|LIGHT|DARK|SYSTEM|테마/);
    for (const legend of ["유종", "주유소 조건", "브랜드"]) await expect(menu.getByRole("group", { name: legend })).toBeVisible();
    await shot(page, `fuel-ui3-filter-menu-${width}.png`, testInfo);
    // 유종 하나(휘발유) → 지도 최저가 범위 사용 가능
    await expect(menu.getByRole("combobox", { name: /지도 최저가/ })).toBeDisabled();
    let next = waitPlaces(page, url => url.searchParams.get("product_codes") === "B027");
    await menu.getByRole("checkbox", { name: "휘발유", exact: true }).check();
    await next;
    next = waitPlaces(page, url => url.searchParams.get("near_min") === "70");
    await menu.getByRole("combobox", { name: /지도 최저가/ }).selectOption("70");
    await next;
    for (const [label, key] of [["'24시' 만", "open_24h"], ["'셀프주유' 만", "self_only"], ["'자동세차' 만", "carwash"], ["'경정비' 만", "maintenance"], ["'편의점' 만", "cvs"], ["'품질인증주유소' 만", "kpetro"]] as const) {
      const control = menu.getByRole("checkbox", { name: label });
      expect((await control.locator("xpath=..").boundingBox())!.height).toBeGreaterThanOrEqual(44);
      next = waitPlaces(page, url => url.searchParams.get(key) === "true");
      await control.check();
      await next;
    }
    // 휘발유에서 LPG 충전 전용 상표는 비활성이고 보내지 않는다: 11 − 알뜰 − 2 = 8개.
    await expect(menu.getByRole("checkbox", { name: /SK가스/ })).toBeDisabled();
    next = waitPlaces(page, url => (url.searchParams.get("brands") ?? "").split(",").length === 8 && !url.searchParams.get("brands")!.includes("ALT"));
    await menu.getByRole("checkbox", { name: /알뜰주유소/ }).uncheck();
    await next;
    // 상표를 전부 끄는 것은 막는다(모두 꺼짐 ≠ 전체 보임): 마지막 하나는 꺼지지 않고 그 상표만 보낸다.
    for (const name of ["SK에너지", "GS칼텍스", "HD현대오일뱅크", "S-OIL", "NH-OIL(농협)", "EX-OIL(고속)", "남해화학클린오일"]) {
      await menu.getByRole("checkbox", { name, exact: true }).uncheck();
    }
    await expect.poll(() => lastPlaces().searchParams.get("brands")).toBe("ETC");
    const lastBrand = menu.getByRole("checkbox", { name: "기타", exact: true });
    await lastBrand.click();
    await expect(lastBrand).toBeChecked();
    expect(lastPlaces().searchParams.get("brands")).toBe("ETC");
    // 브랜드 전체 선택으로 되돌린 뒤 알뜰만 다시 끈다.
    next = waitPlaces(page, url => !url.searchParams.has("brands"));
    await menu.getByRole("checkbox", { name: "브랜드 전체 선택" }).check();
    await next;
    next = waitPlaces(page, url => (url.searchParams.get("brands") ?? "").split(",").length === 8);
    await menu.getByRole("checkbox", { name: /알뜰주유소/ }).uncheck();
    await next;
    await menu.evaluate(node => { node.scrollTop = node.scrollHeight; });
    await shot(page, `fuel-ui3-filter-menu-applied-${width}.png`, testInfo);
    // 닫으면 트리거로 초점이 돌아오고, 트리거가 유종과 적용 조건 수를 알린다.
    await page.keyboard.press("Escape");
    await expect(menu).toHaveCount(0);
    await expect(trigger).toBeFocused();
    await expect(trigger).toHaveAccessibleName("유종·필터: 휘발유, 조건 8개 적용 중");
    await expect(trigger).toContainText("휘발유");
    await expect(summaryOf(page)).toContainText("4개 주유소");
    await shot(page, `fuel-ui3-filter-applied-summary-${width}.png`, testInfo);
    // 새로고침 뒤에도 유지된다.
    await page.reload();
    await expect.poll(() => lastPlaces()?.searchParams.get("self_only")).toBe("true");
    expect(lastPlaces().searchParams.get("brands")).not.toContain("ALT");
    expect(lastPlaces().searchParams.get("near_min")).toBe("70");
    expect(lastPlaces().searchParams.get("product_codes")).toBe("B027");
    await expect(filterTrigger(page)).toHaveAccessibleName("유종·필터: 휘발유, 조건 8개 적용 중");
    // 유종을 하나 더 고르면 지도 최저가는 보내지 않는다(서버 422 회피).
    await filterTrigger(page).click();
    next = waitPlaces(page, url => url.searchParams.get("product_codes") === "B027,D047");
    await filterMenu(page).getByRole("checkbox", { name: "경유", exact: true }).check();
    const both = new URL((await next).url());
    expect(both.searchParams.has("near_min")).toBe(false);
    await expect(filterMenu(page).getByRole("combobox", { name: /지도 최저가/ })).toBeDisabled();
    // 초기화는 유종과 필터를 함께 처음으로 돌린다.
    next = waitPlaces(page, url => !FILTER_KEYS.some(key => url.searchParams.has(key)) && !url.searchParams.has("product_codes"));
    await filterMenu(page).getByRole("button", { name: "초기화" }).click();
    await next;
    await expect(filterMenu(page).getByRole("checkbox", { name: "전체 유종" })).toBeChecked();
    await filterMenu(page).getByRole("button", { name: "닫기" }).click();
    await expect(filterTrigger(page)).toHaveAccessibleName("유종·필터: 전체 유종");
    await expect(filterTrigger(page)).toBeFocused();
    expect(await noHorizontalScroll(page)).toBe(true);
  });
}

test("유종·필터는 키보드로 열고 닫으며 초점이 팝오버 안에 머문다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const trigger = filterTrigger(page);
  await trigger.focus();
  await page.keyboard.press("Enter");
  const menu = filterMenu(page);
  await expect(menu).toBeVisible();
  for (let i = 0; i < 40; i++) {
    await page.keyboard.press("Tab");
    expect(await menu.evaluate(node => node.contains(document.activeElement))).toBe(true);
  }
  // 스페이스로 체크박스를 바꾸면 바로 적용된다.
  await menu.getByRole("checkbox", { name: "'셀프주유' 만" }).focus();
  const next = waitPlaces(page, url => url.searchParams.get("self_only") === "true");
  await page.keyboard.press("Space");
  await next;
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
  await expect(trigger).toHaveAccessibleName("유종·필터: 전체 유종, 조건 1개 적용 중");
});
