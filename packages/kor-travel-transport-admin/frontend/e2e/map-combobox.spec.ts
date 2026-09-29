import { expect, test } from "@playwright/test";

const stamp = "2026-09-29T00:00:00Z";
const place = { id: 1, kind: "fuel_station", source: "opinet_browser", name: "다중필터 시험주유소", longitude: 127, latitude: 37, line_names: [], facilities: [], updated_at: stamp,
  prices: [{ product_code: "B027", price: 1700, observed_at: stamp }, { product_code: "D047", price: 1600, observed_at: stamp }] };

test("지도는 휴게소와 돌발 정보를 각각 조회하고 상세·출처를 표시한다", async ({ page }) => {
  const requests: string[] = [];
  await page.route("**/transport/features/places?**", (route) => {
    const kind = new URL(route.request().url()).searchParams.get("kind")!; requests.push(kind);
    const rows = kind === "rest_area" ? [{ ...place, kind, name: "시험휴게소", source: "krex_rest_area", prices: [], line_names: ["경부고속도로"], facilities: ["주차장"] }]
      : kind === "highway_incident" ? [{ ...place, kind, name: "시험분기점", source: "krex_traffic_incident", prices: [], line_names: ["0010 · 경부고속도로"], subtitle: "사고 · 처리중", address: "1차로 통제" }] : [];
    return route.fulfill({ json: { total: rows.length, items: rows, available_sources: rows.map((row) => row.source), truncated: false } });
  });
  await page.goto("/map");
  await page.getByRole("button", { name: "목록", exact: true }).click();
  await page.locator(".map-place-list").getByRole("button", { name: /시험휴게소/ }).click();
  await expect(page.getByLabel("선택 장소 상세").getByText("편의시설 · 주차장")).toBeVisible();
  await page.getByRole("button", { name: "장소 상세 닫기" }).click();
  await page.locator(".map-place-list").getByRole("button", { name: /시험분기점/ }).click();
  const detail = page.getByLabel("선택 장소 상세");
  await expect(detail.getByText("0010 · 경부고속도로", { exact: true })).toBeVisible();
  await expect(detail.getByText("사고 · 처리중", { exact: true })).toBeVisible();
  await expect(detail.getByText("1차로 통제", { exact: true })).toBeVisible();
  expect(requests).toEqual(expect.arrayContaining(["rest_area", "highway_incident"]));
});

test.beforeEach(async ({ page }) => {
  test.skip(!process.env.E2E_TRANSPORT_UI_PASSWORD, "로그인 암호 필요");
  await page.goto("/login");
  await page.getByLabel("비밀번호").fill(process.env.E2E_TRANSPORT_UI_PASSWORD!);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.route("**://*.vworld.kr/**", (route) => route.abort());
});

test("좌표 미확인 항구·버스 터미널은 지도 대신 검색 목록과 상세에서 찾는다", async ({ page }) => {
  const requests: URLSearchParams[] = [];
  await page.route("**/transport/features/places?**", (route) => {
    const params = new URL(route.request().url()).searchParams;
    requests.push(params);
    const rows = params.get("kind") === "ferry_port"
      ? [{ ...place, id: 401, kind: "ferry_port", source: "data_go_kr_maritime", provider_id: "SEA97580", name: "백야도", longitude: null, latitude: null, prices: [] }]
      : params.get("kind") === "bus_terminal"
        ? [{ ...place, id: 402, kind: "bus_terminal", source: "data_go_kr_tago", provider_id: "NAI2551901", name: "강릉", longitude: null, latitude: null, subtitle: "시외버스 · 강원도", prices: [] }]
        : [];
    return route.fulfill({ json: { items: rows.filter((row) => !params.get("query") || row.name.includes(params.get("query")!)), total: rows.length,
      available_sources: rows.map((row) => row.source), truncated: false } });
  });
  await page.goto("/map");
  await page.getByRole("button", { name: "목록", exact: true }).click();
  await expect(page.locator(".map-place-list").getByRole("button", { name: /백야도/ })).toBeVisible();
  await expect(page.locator(".map-place-list").getByRole("button", { name: /강릉/ })).toBeVisible();
  await page.locator(".map-place-list").getByRole("button", { name: /백야도/ }).click();
  await expect(page.getByLabel("선택 장소 상세").getByText(/항구 코드 SEA97580/)).toBeVisible();
  await page.getByRole("button", { name: "장소 상세 닫기" }).click();
  await page.getByLabel("장소 검색").fill("강릉");
  await expect.poll(() => requests.some((params) => params.get("kind") === "bus_terminal" &&
    params.get("include_unlocated") === "true" && params.get("query") === "강릉")).toBe(true);
  await expect(page.locator(".map-place-list").getByRole("button", { name: /강릉/ })).toBeVisible();
  await page.locator(".map-place-list").getByRole("button", { name: /강릉/ }).click();
  await expect(page.getByLabel("선택 장소 상세").getByText(/터미널 코드 NAI2551901/)).toBeVisible();
  expect(requests.some((params) => params.get("kind") === "ferry_port" && params.get("include_unlocated") === "true")).toBe(true);
});

for (const width of [320, 375, 768, 1440]) {
  test(`지도 다중 필터 검색·해제·중복 선택 제거 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const requests: URLSearchParams[] = [];
    await page.route("**/transport/features/places?**", (route) => {
      const params = new URL(route.request().url()).searchParams;
      requests.push(params);
      return route.fulfill({ json: { available_sources: ["opinet_browser", "second-source"], items: params.get("kind") === "fuel_station" ? [place] : [], total: 1, truncated: false } });
    });
    await page.goto("/map");
    await expect(page.getByLabel("장소 목록에서 선택")).toHaveCount(0);
    const products = page.getByRole("combobox", { name: "표시 유종" });
    await products.fill("휘발유");
    await page.getByRole("option", { name: "휘발유", exact: true }).click();
    await products.fill("경유");
    await page.getByRole("option", { name: "경유", exact: true }).click();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("button", { name: "휘발유 선택 해제", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "경유 선택 해제", exact: true })).toBeVisible();
    await expect.poll(() => requests.some((params) => params.get("product_codes") === "B027,D047")).toBe(true);
    const source = page.getByRole("combobox", { name: "데이터 출처" });
    await source.fill("second-source");
    await page.getByRole("option", { name: "second-source", exact: true }).click();
    await source.fill("주유소");
    await page.getByRole("option", { name: "전국 주유소·유가 정보", exact: true }).click();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("button", { name: "휘발유 선택 해제", exact: true })).toBeVisible();
    await expect.poll(() => requests.some((params) => params.get("sources") === "second-source,opinet_browser")).toBe(true);
    await page.getByRole("button", { name: "목록", exact: true }).click();
    await page.locator(".map-place-list").getByRole("button", { name: /다중필터 시험주유소/ }).click();
    await page.getByRole("button", { name: "장소 상세 닫기" }).click();
    await expect(page.getByLabel("장소 검색")).toBeFocused();
    await page.getByRole("button", { name: "휘발유 선택 해제", exact: true }).click();
    await expect.poll(() => requests.some((params) => params.get("product_codes") === "D047")).toBe(true);
    await page.getByRole("button", { name: "경유 선택 해제", exact: true }).click();
    await expect(products).toHaveAttribute("placeholder", "전체 유종");
    await expect.poll(() => requests.filter((params) => params.get("kind") === "fuel_station").at(-1)?.has("product_codes")).toBe(false);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await source.fill("없는 출처");
    await expect(page.getByText("검색 결과가 없습니다.", { exact: true })).toBeVisible();
    await expect(page.getByRole("status")).toHaveAttribute("aria-live", "polite");
    await page.keyboard.press("Escape");
  });

  test(`지도 유종 키보드 다중 선택 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route("**/transport/features/places?**", (route) => route.fulfill({ json: { items: [], total: 0, truncated: false } }));
    await page.goto("/map");
    const input = page.getByRole("combobox", { name: "표시 유종" });
    await input.fill("LPG");
    await input.press("ArrowDown");
    await input.press("Enter");
    await expect(page.getByRole("button", { name: "LPG 선택 해제" })).toBeVisible();
    await input.press("Escape");
    await expect(page.getByRole("listbox")).toHaveCount(0);
    await expect(input).toBeFocused();
    await input.press("Escape");
    await expect(page.getByRole("button", { name: "LPG 선택 해제" })).toBeVisible();
  });
}

test("유종은 OR로 표시하고 새 조회 실패 시 이전 장소를 숨긴다", async ({ page }) => {
  const rows = ["B027", "D047", "K015"].map((product_code, index) => ({ ...place, id: index + 1, name: `유종 전용 ${product_code}`, prices: [{ product_code, price: 1500, observed_at: stamp }] }));
  await page.route("**/transport/features/places?**", (route) => {
    const params = new URL(route.request().url()).searchParams;
    return params.has("query") ? route.fulfill({ status: 503, json: {} }) : route.fulfill({ json: { items: params.get("kind") === "fuel_station" ? rows : [], total: 3, truncated: false } });
  });
  await page.goto("/map");
  await page.getByRole("button", { name: "목록", exact: true }).click();
  const input = page.getByRole("combobox", { name: "표시 유종" });
  for (const name of ["휘발유", "경유"]) {
    await input.fill(name);
    await page.getByRole("option", { name, exact: true }).click();
  }
  await input.press("Escape");
  const list = page.locator(".map-place-list");
  await expect(list.getByRole("button", { name: /B027/ })).toBeVisible();
  await expect(list.getByRole("button", { name: /D047/ })).toBeVisible();
  await expect(list.getByRole("button", { name: /K015/ })).toHaveCount(0);
  await page.getByLabel("장소 검색").fill("새로운 조건");
  await expect(page.getByText("주유소·철도역·항구·공항·휴게소·도로 돌발 조회 실패")).toBeVisible();
  await expect(list.getByRole("button")).toHaveCount(0);
});

test("작은 가로 화면에서도 combobox 마지막 항목까지 스크롤한다", async ({ page }) => {
  await page.setViewportSize({ width: 640, height: 280 });
  await page.route("**/transport/features/places?**", (route) => route.fulfill({ json: { items: [], total: 0, truncated: false } }));
  await page.goto("/map");
  await page.getByRole("combobox", { name: "표시 유종" }).click();
  const list = page.getByRole("listbox");
  await expect(list).toBeVisible();
  const popup = page.locator('[data-slot="combobox-content"]');
  expect(await list.evaluate((node) => node.clientHeight)).toBeLessThanOrEqual(await popup.evaluate((node) => node.clientHeight));
  const last = page.getByRole("option", { name: "등유", exact: true });
  await last.scrollIntoViewIfNeeded();
  await expect(last).toBeInViewport();
  await last.click();
  await expect(page.getByRole("button", { name: "등유 선택 해제" })).toBeVisible();
});

test("고급유 필터는 최신 가격이 없는 주유소를 제외하고 복수 유종은 OR로 표시한다", async ({ page }) => {
  const rows = [2000, null, 0, undefined].map((price, index) => ({
    ...place, id: index + 1, name: `고급유 가격 시험 ${index}`,
    prices: [{ product_code: "D047", price: 1600, observed_at: stamp },
      ...(price === undefined ? [] : [{ product_code: "B034", price, observed_at: stamp }])],
  }));
  // 서버의 잘못된/이전 응답이 섞여도 지도와 목록이 가격 미제공을 판매로 표시하면 안 된다.
  await page.route("**/transport/features/places?**", (route) => route.fulfill({ json: {
    items: new URL(route.request().url()).searchParams.get("kind") === "fuel_station" ? rows : [],
    total: rows.length, truncated: false,
  } }));
  await page.goto("/map");
  await page.getByRole("button", { name: "목록", exact: true }).click();
  const input = page.getByRole("combobox", { name: "표시 유종" });
  await input.fill("고급유");
  await page.getByRole("option", { name: "고급유", exact: true }).click();
  await input.press("Escape");
  const list = page.locator(".map-place-list");
  await expect(list.getByRole("button")).toHaveCount(1);
  await expect(list.getByRole("button", { name: /고급유 가격 시험 0/ })).toBeVisible();
  await input.fill("경유");
  await page.getByRole("option", { name: "경유", exact: true }).click();
  await input.press("Escape");
  await expect(list.getByRole("button")).toHaveCount(4);
});

test("검색 debounce 중 선택한 이전 장소가 새 빈 결과에 남지 않는다", async ({ page }) => {
  await page.clock.install();
  await page.route("**/transport/features/places?**", (route) => {
    const params = new URL(route.request().url()).searchParams;
    return route.fulfill({ json: { items: !params.has("query") && params.get("kind") === "fuel_station" ? [place] : [], total: 0, truncated: false } });
  });
  await page.goto("/map");
  await page.getByRole("button", { name: "목록", exact: true }).click();
  const row = page.locator(".map-place-list").getByRole("button", { name: /다중필터 시험주유소/ });
  await expect(row).toBeVisible();
  await page.clock.pauseAt(await page.evaluate(() => Date.now() + 1000));
  await page.getByLabel("장소 검색").fill("없는 장소");
  await row.click();
  await expect(page.getByRole("button", { name: "장소 상세 닫기" })).toBeVisible();
  await page.clock.runFor(300);
  await expect(page.locator(".map-place-list").getByRole("button")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "장소 상세 닫기" })).toHaveCount(0);
});

test("출처 10개 선택 제한과 해제 후 재선택을 제공한다", async ({ page }) => {
  const sources = Array.from({ length: 11 }, (_, index) => `source-${String(index).padStart(2, "0")}`);
  await page.route("**/transport/features/places?**", (route) => route.fulfill({ json: { available_sources: sources, items: [], total: 0, truncated: false } }));
  await page.goto("/map");
  const input = page.getByRole("combobox", { name: "데이터 출처" });
  for (const name of sources.slice(0, 10)) {
    await input.fill(name);
    await page.getByRole("option", { name, exact: true }).click();
  }
  await input.fill(sources[10]);
  await expect(page.getByRole("option", { name: sources[10], exact: true })).toBeDisabled();
  await input.press("Escape");
  await page.getByRole("button", { name: `${sources[0]} 선택 해제`, exact: true }).click();
  await input.fill(sources[10]);
  await page.getByRole("option", { name: sources[10], exact: true }).click();
  await expect(page.getByRole("button", { name: `${sources[10]} 선택 해제`, exact: true })).toBeVisible();
});

test.describe("다중 선택 터치 해제", () => {
  test.use({ hasTouch: true, viewport: { width: 375, height: 900 } });
  test("칩 해제 버튼도 44px 터치 영역을 제공한다", async ({ page }) => {
    await page.route("**/transport/features/places?**", (route) => route.fulfill({ json: { items: [], total: 0, truncated: false } }));
    await page.goto("/map");
    const input = page.getByRole("combobox", { name: "표시 유종" });
    await input.fill("휘발유");
    await page.getByRole("option", { name: "휘발유", exact: true }).click();
    await input.press("Escape");
    const remove = page.getByRole("button", { name: "휘발유 선택 해제", exact: true });
    const bounds = await remove.boundingBox();
    expect(bounds!.width).toBeGreaterThanOrEqual(44);
    expect(bounds!.height).toBeGreaterThanOrEqual(44);
    await remove.tap();
    await expect(remove).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
});

test("낮은 화면에서 휠 스크롤만으로 마지막 옵션 전체를 표시한다", async ({ page }) => {
  await page.setViewportSize({ width: 640, height: 280 });
  const sources = Array.from({ length: 11 }, (_, index) => `source-${String(index).padStart(2, "0")}`);
  await page.route("**/transport/features/places?**", (route) => route.fulfill({ json: { available_sources: sources, items: [], total: 0, truncated: false } }));
  await page.goto("/map");
  await page.getByRole("combobox", { name: "데이터 출처" }).click();
  await expect(page.locator('[data-slot="combobox-empty"]')).toHaveCSS("display", "block");
  const list = page.getByRole("listbox");
  const listBox = (await list.boundingBox())!;
  await page.mouse.move(listBox.x + 20, listBox.y + 20);
  await page.mouse.wheel(0, 10000);
  const last = page.getByRole("option", { name: sources[10], exact: true });
  const popup = page.locator('[data-slot="combobox-content"]');
  await expect.poll(async () => {
    const row = (await last.boundingBox())!;
    const box = (await popup.boundingBox())!;
    return Math.min(row.y + row.height, box.y + box.height) - Math.max(row.y, box.y);
  }).toBeGreaterThanOrEqual(44);
});

test("모바일에서 긴 출처 옵션의 전체 이름을 줄바꿈한다", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 900 });
  const source = "long-source-" + "a".repeat(57);
  await page.route("**/transport/features/places?**", (route) => route.fulfill({ json: { available_sources: [source], items: [], total: 0, truncated: false } }));
  await page.goto("/map");
  await page.getByRole("combobox", { name: "데이터 출처" }).click();
  const option = page.getByRole("option", { name: source, exact: true });
  await expect(option).toBeVisible();
  expect(await option.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
});
