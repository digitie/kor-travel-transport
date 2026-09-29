import type { APIRequestContext, BrowserContext, Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

const username = process.env.E2E_TRANSPORT_UI_USER ?? "admin";
const password = process.env.E2E_TRANSPORT_UI_PASSWORD;
const expectedReleaseSha = process.env.E2E_TRANSPORT_RELEASE_SHA;
const webBase = process.env.E2E_BASE_URL ?? "https://transport.digitie.mywire.org";
const apiBase = process.env.E2E_TRANSPORT_API_BASE_URL ?? "https://transport-api.digitie.mywire.org";
const dagsterBase = process.env.E2E_TRANSPORT_DAGSTER_BASE_URL ?? "https://transport-dagster.digitie.mywire.org";

type EndpointCase = { name: string; path: string; arrayKey: string };

const statisticsCases: EndpointCase[] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].flatMap((days) => [
  { name: `statistics all ${days}d`, path: `transport/statistics?days=${days}`, arrayKey: "traffic" },
  { name: `statistics route 0010 ${days}d`, path: `transport/statistics?days=${days}&route_no=0010`, arrayKey: "traffic" },
]);
const trafficCases: EndpointCase[] = [1, 2, 3, 4, 5].flatMap((days) => [1, 10, 50, 200].map((limit, index) => ({
  name: `traffic ${days}d limit ${limit}`,
  path: `transport/highways/traffic?days=${days}&limit=${limit}${index % 2 ? "&route_no=0010" : ""}`,
  arrayKey: "items",
})));
const incidentCases: EndpointCase[] = [1, 2, 3, 4, 5].flatMap((days) => [1, 10, 50, 200].map((limit, index) => ({
  name: `incidents ${days}d limit ${limit}`,
  path: `transport/highways/incidents?days=${days}&limit=${limit}${index % 2 ? "&route_no=0010" : ""}`,
  arrayKey: "items",
})));
const fuelCases: EndpointCase[] = [1, 2, 3, 7].flatMap((days) => ["B027", "D047", "B034", "C004", "K015"].map((productCode, index) => ({
  name: `fuel ${productCode} ${days}d`,
  path: `transport/fuel/stations?days=${days}&limit=10&product_code=${productCode}&sido_value=${["11", "26", "27", "28", "41"][index]}`,
  arrayKey: "items",
})));
const endpointCases: EndpointCase[] = [
  { name: "collector status", path: "transport/collector-status", arrayKey: "sources" },
  { name: "saved map places", path: "transport/features/places?limit=10", arrayKey: "items" },
  { name: "saved bus terminals", path: "transport/bus/terminals?service_type=express&limit=10", arrayKey: "items" },
  { name: "all provider status", path: "transport/providers", arrayKey: "items" },
  ...["airport", "rest_area", "ferry_port", "rail_station", "fuel_station"].map((kind) => ({ name: `map ${kind}`, path: `transport/features/places?kind=${kind}&include_unlocated=true&limit=10`, arrayKey: "items" })),
  ...statisticsCases,
  ...trafficCases,
  ...incidentCases,
  ...fuelCases,
];

async function login(page: Page) {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("아이디").fill(username);
  await page.getByLabel("비밀번호").fill(password!);
  await page.getByRole("button", { name: "로그인" }).click();
  await expect(page).toHaveURL(/\/$/);
}

async function expectJsonArray(request: APIRequestContext, url: string, arrayKey: string) {
  let response = await request.get(url);
  for (let attempt = 0; attempt < 2 && [502, 503, 504].includes(response.status()); attempt += 1) {
    await response.dispose();
    await new Promise((resolve) => setTimeout(resolve, (attempt + 1) * 1_000));
    response = await request.get(url);
  }
  expect(response.status()).toBe(200);
  const body = await response.json() as Record<string, unknown>;
  expect(Array.isArray(body[arrayKey])).toBe(true);
}

test.beforeEach(() => { test.skip(!password, "E2E_TRANSPORT_UI_PASSWORD가 필요합니다."); });

test("잘못된 자격증명은 세션을 만들지 않고 로그인 화면에 오류를 남긴다", async ({ page, request }) => {
  await page.goto("/");
  await page.getByLabel("아이디").fill(username);
  await page.getByLabel("비밀번호").fill("invalid-password");
  await page.getByRole("button", { name: "로그인" }).click();
  await expect(page.getByText("아이디 또는 비밀번호가 올바르지 않습니다.", { exact: true })).toBeVisible();
  expect((await request.get("/api/transport/transport/statistics?days=1")).status()).toBe(401);
});

test("느린 7일 통계가 수집 상태 화면을 가로막지 않는다", async ({ browser }) => {
  const context = await browser.newContext({ baseURL: webBase });
  const page = await context.newPage();
  let notifyStatisticsStarted: (() => void) | undefined;
  const statisticsStarted = new Promise<void>((resolve) => { notifyStatisticsStarted = resolve; });
  await page.route("**/api/transport/transport/statistics?days=7", async (route) => {
    notifyStatisticsStarted?.();
    await new Promise((resolve) => setTimeout(resolve, 6_000));
    await route.continue();
  });
  await login(page);
  await statisticsStarted;
  await expect(page.getByRole("heading", { name: "교통정보 찾아보기" })).toBeVisible({ timeout: 5_000 });
  await expect(page.getByText("저장된 7일 통계를 집계하는 중입니다…").first()).toBeVisible();
  await context.close();
});

test("로그아웃 처리 중 늦게 저장된 통계 캐시도 로그인 화면에서 제거한다", async ({ page }) => {
  await login(page);
  await expect(page.getByRole("heading", { name: "교통정보 찾아보기" })).toBeVisible();
  await page.evaluate(() => {
    // form의 React handler 뒤에 완료되는 이전 문서의 비동기 저장을 재현한다.
    document.addEventListener("submit", () => queueMicrotask(() => {
      window.sessionStorage.setItem("kor-travel-transport-dashboard-v1", "late-response");
      window.sessionStorage.setItem("kor-travel-transport-dashboard-v2", "late-response");
    }), { once: true });
  });
  await page.getByRole("button", { name: "로그아웃" }).click();
  await expect(page).toHaveURL(/\/login/);
  await expect.poll(() => page.evaluate(() => ["kor-travel-transport-dashboard-v1", "kor-travel-transport-dashboard-v2"].every((key) => window.sessionStorage.getItem(key) === null))).toBe(true);
});

test.describe("비인증 관리 proxy 경계", () => {
  for (const endpoint of endpointCases) {
    test(`unauthenticated ${endpoint.name}`, async ({ request }) => {
      expect((await request.get(`/api/transport/${endpoint.path}`)).status()).toBe(401);
    });
  }
});

test.describe("공개 저장 transport API 행렬", () => {
  for (const endpoint of endpointCases) {
    test(`public ${endpoint.name}`, async ({ request }) => {
      await expectJsonArray(request, `${apiBase}/v1/${endpoint.path}`, endpoint.arrayKey);
    });
  }
});

test.describe("인증된 관리 proxy 행렬과 UI", () => {
  test.describe.configure({ mode: "serial" });
  let context: BrowserContext;
  let page: Page;

  test.beforeAll(async ({ browser }) => {
    if (!password) return;
    context = await browser.newContext({ baseURL: webBase });
    page = await context.newPage();
    await login(page);
  });
  test.afterAll(async () => { await context?.close(); });

  test("release SHA와 대시보드 저장 스냅샷을 표시한다", async () => {
    if (expectedReleaseSha) {
      const release = await page.request.get("/api/release");
      expect(release.status()).toBe(200);
      expect((await release.json()).releaseSha).toBe(expectedReleaseSha);
    }
    await expect(page.getByRole("heading", { name: "교통정보 찾아보기" })).toBeVisible({ timeout: 20_000 });
  });

  for (const endpoint of endpointCases) {
    test(`private ${endpoint.name}`, async () => {
      await expectJsonArray(page.request, `/api/transport/${endpoint.path}`, endpoint.arrayKey);
    });
  }

  for (const [path, heading] of [["/transport", "교통·유가 현황"], ["/fuel", "교통·유가 현황"], ["/rail", "열차·도시철도"], ["/ferry", "배편"], ["/map", "교통 지도"], ["/api-test", "API 점검"], ["/admin/dagster", "Dagster"]] as const) {
    test(`navigation ${path}`, async () => {
      await page.goto(path);
      await expect(page.getByRole("heading", { name: heading })).toBeVisible();
    });
  }

  test("핵심 교통 화면은 모바일 폭에서도 가로 스크롤 없이 읽힌다", async ({ browser }) => {
    for (const width of [320, 375, 414, 768]) {
      const mobileContext = await browser.newContext({ baseURL: webBase, viewport: { width, height: 900 } });
      const mobilePage = await mobileContext.newPage();
      await login(mobilePage);
      for (const [path, heading] of [["/transport", "교통·유가 현황"], ["/rail", "열차·도시철도"], ["/ferry", "배편"], ["/map", "교통 지도"]] as const) {
        await mobilePage.goto(path);
        await expect(mobilePage.getByRole("heading", { name: heading })).toBeVisible();
        expect(await mobilePage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      }
      await mobileContext.close();
    }
  });

  test("지도는 저장 장소 API를 읽고, VWorld 타일 실패를 명시하며 실시간 항구 시간표를 자동 호출하지 않는다", async ({ browser }) => {
    const mapContext = await browser.newContext({ baseURL: webBase });
    const mapPage = await mapContext.newPage();
    await login(mapPage);
    const timetableRequests: string[] = [];
    const mapPlaceRequests = new Map<string, URL>();
    mapPage.on("request", (request) => {
      if (request.url().includes("/timetable")) timetableRequests.push(request.url());
      if (request.url().includes("/api/transport/transport/features/places?kind=")) {
        const url = new URL(request.url());
        mapPlaceRequests.set(url.searchParams.get("kind") ?? "", url);
      }
    });
    await mapPage.goto("/map");
    await expect(mapPage.getByLabel("교통 장소 지도")).toBeVisible();
    await expect(mapPage.getByLabel("데이터 출처")).toHaveAttribute("role", "combobox");
    await expect(mapPage.getByLabel("장소 목록에서 선택")).toHaveCount(0);
    await expect(mapPage.locator("canvas.maplibregl-canvas")).toBeVisible({ timeout: 20_000 });
    await expect.poll(() => [...mapPlaceRequests.keys()].sort()).toEqual(["airport", "ferry_port", "fuel_station", "highway_incident", "rail_station", "rest_area"]);
    expect([...mapPlaceRequests.values()].every((url) => url.searchParams.get("limit") === "150" && ["min_longitude", "min_latitude", "max_longitude", "max_latitude"].every((key) => url.searchParams.has(key)))).toBe(true);
    await mapPage.waitForTimeout(2_000);
    const tileError = mapPage.getByText("VWorld 지도 타일을 불러오지 못했습니다.", { exact: false });
    if (await tileError.isVisible()) {
      await expect(tileError).toContainText("목록 보기에서 장소를 확인할 수 있습니다.");
    }
    await expect.poll(() => timetableRequests).toEqual([]);
    await mapPage.getByRole("button", { name: "목록", exact: true }).click();
    const placeRows = mapPage.locator(".map-place-list").getByRole("button");
    await expect.poll(() => placeRows.count()).toBeGreaterThan(0);
    await placeRows.first().click();
    await expect(mapPage.locator(".transport-map-detail h2")).not.toHaveText("교통 장소");
    await mapContext.close();
  });

  test("배편 탭은 항구 시간표를 자동 호출하지 않는다", async () => {
    const timetableRequests: string[] = [];
    page.on("request", (request) => { if (request.url().includes("/timetable")) timetableRequests.push(request.url()); });
    await page.goto("/ferry");
    await expect(page.getByLabel("항구 검색")).toBeVisible();
    await expect.poll(() => timetableRequests).toEqual([]);
  });

  test("배편은 다중 선택·운항일 변경 시 저장본만 읽고 늦은 응답을 버린다", async () => {
    const requestedDates: string[] = [];
    const providerRequests: string[] = [];
    const listener = (request: { url: () => string }) => { if (/ports\/[^/?]+\/timetable\?/.test(request.url())) providerRequests.push(request.url()); };
    page.on("request", listener);
    await page.route("**/transport/features/places?kind=ferry_port**", (route) => route.fulfill({ json: { items: [
      ...["alpha", "bravo", "missing"].map((provider_id, index) => ({ id: index + 1, kind: "ferry_port", provider_id, source: "data_go_kr_maritime", name: ["알파 항구", "브라보 항구", "누락 항구"][index], line_names: [], prices: [], facilities: [], latitude: null, longitude: null, updated_at: "2026-09-22T00:00:00Z" })),
    ] } }));
    await page.route("**/transport/ports/timetables?**", async (route) => {
      const params = new URL(route.request().url()).searchParams;
      const date = params.get("date")!; requestedDates.push(date);
      const ids = params.get("port_ids")!.split(",");
      if (ids.length === 1 && ids[0] === "alpha") await new Promise((resolve) => setTimeout(resolve, 500));
      await route.fulfill({ json: { service_date: date, missing_port_ids: ids.filter((id) => id === "missing"), items: ids.filter((id) => id !== "missing").map((id) => ({ port_id: id, service_date: date, fetched_at: "2026-09-27T00:00:00Z", items: [{ vessel_name: id === "alpha" ? "알파호" : "브라보호", departure_port_name: id, arrival_port_name: "제주", departure_planned_time: "0900", arrival_planned_time: "1100", fare: "12000" }] })) } });
    });
    await page.goto("/ferry");
    await page.getByRole("checkbox", { name: /알파 항구/ }).check();
    await page.getByRole("checkbox", { name: /브라보 항구/ }).check();
    await expect(page.getByText("브라보호", { exact: true })).toBeVisible();
    await page.waitForTimeout(600);
    await expect(page.getByText("브라보호", { exact: true })).toBeVisible();
    await page.getByRole("checkbox", { name: /누락 항구/ }).check();
    await expect(page.getByText("이 날짜는 아직 수집 중입니다.", { exact: false })).toBeVisible();
    const futureDate = await page.getByLabel("운항일").getAttribute("max");
    await page.getByLabel("운항일").fill(futureDate!);
    await expect(page.getByRole("heading", { name: `브라보 항구 · ${futureDate}` })).toBeVisible();
    expect(requestedDates).toContain(futureDate);
    expect(providerRequests).toEqual([]);
    await page.unroute("**/transport/features/places?kind=ferry_port**");
    await page.unroute("**/transport/ports/timetables?**");
    page.off("request", listener);
  });

  test("allowlist 밖의 관리 proxy 경로는 숨긴다", async () => {
    expect((await page.request.get("/api/transport/admin/backups")).status()).toBe(404);
    expect((await page.request.get("/api/transport/transport/unknown")).status()).toBe(404);
  });

  test("로그아웃 뒤에는 HTTPS origin을 유지한 로그인 화면으로 돌아간다", async () => {
    await page.goto("/");
    await page.evaluate(() => window.sessionStorage.setItem("kor-travel-transport-dashboard-v2", "stale"));
    await page.getByRole("button", { name: "로그아웃" }).click();
    await expect(page).toHaveURL(/\/login/);
    await expect.poll(() => page.evaluate(() => window.sessionStorage.getItem("kor-travel-transport-dashboard-v2"))).toBeNull();
  });
});

test.describe("공개 gateway 쓰기·비허용 경계", () => {
  for (const path of ["transport/collector-status", "transport/statistics?days=1", "transport/highways/traffic?days=1", "transport/highways/incidents?days=1", "transport/fuel/stations?days=1", "transport/features/places", "transport/bus/terminals?service_type=express", "transport/bus/timetable", "transport/ports/test-port/timetable"]) {
    test(`public POST ${path} is denied`, async ({ request }) => {
      expect((await request.post(`${apiBase}/v1/${path}`)).status()).toBe(403);
    });
  }
  for (const path of ["/v1/admin/backups", "/v1/transport/admin/collect", "/v1/parking/airports"]) {
    test(`public GET ${path} is hidden`, async ({ request }) => {
      expect((await request.get(`${apiBase}${path}`)).status()).toBe(404);
    });
  }
});

test("Dagster health는 공개하되 cross-origin GraphQL POST는 CSRF로 차단한다", async ({ request }) => {
  expect((await request.get(`${dagsterBase}/health`)).status()).toBe(204);
  expect((await request.post(`${dagsterBase}/graphql`, {
    data: { query: "{ __typename }" },
    headers: { Origin: "https://evil.example" },
  })).status()).toBe(403);
});
