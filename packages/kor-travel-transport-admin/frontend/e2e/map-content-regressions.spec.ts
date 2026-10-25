import { expect, test, type Page } from "@playwright/test";
import type { Place } from "@/lib/journey";

const at = "2026-10-25T01:00:00Z";
const port: Place = { id: 1, provider_id: "U1", kind: "ferry_port", source: "data_go_kr_maritime", name: "좌표없는항구", address: "시험 섬 주소", phone: "061-123-4567", facilities: ["대합실"], line_names: [], prices: [], longitude: null, latitude: null, updated_at: at };
const mixedPorts = [port, ...Array.from({ length: 5 }, (_, i) => ({ ...port, id: i + 2, provider_id: `P${i + 2}`, name: `시험항구${i + 2}`, longitude: i % 2 ? null : 127.1, latitude: i % 2 ? null : 37.3 }))];

async function session(page: Page) {
  await page.context().addCookies([{ name: "kor_travel_transport_admin_session", value: "isolated-e2e", url: process.env.E2E_BASE_URL ?? "http://127.0.0.1:12351", httpOnly: true, sameSite: "Strict" }]);
}
async function openFilters(page: Page) {
  const workspace = page.locator('[data-slot="map-workspace"]');
  await expect(workspace).toBeVisible();
  const trigger = workspace.locator('[data-slot="map-filter-trigger"]');
  if (await trigger.isVisible() && await trigger.getAttribute("aria-expanded") === "false") await trigger.click();
}
test.beforeEach(async ({ page }) => {
  test.skip(process.env.E2E_MAP_CONTENT !== "true", "격리 지도 내용 회귀 fixture 필요");
  await session(page);
});

for (const width of [375, 1440]) {
  test(`도시철도 검색 전 숨긴 역은 목록 건수에 포함하지 않는다 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const station = { ...port, id: 71, kind: "rail_station", name: "시험역", source: "kric_public_file", subtitle: "시험기관", line_names: ["시험선"], longitude: 127.1, latitude: 37.3 };
    await page.route("**/api/**", (route) => route.fulfill({ json: { items: [station] } }));
    await page.goto("/rail/metro");
    const count = page.locator(".kt-map-count");
    await expect(count).toHaveText("1건 표시");
    await page.getByRole("tab", { name: "목록", exact: true }).click();
    await expect(page.locator(".map-place-list .place-row")).toHaveCount(0); await expect(count).toHaveText("0건 표시");
    await openFilters(page); await page.getByLabel("역 검색", { exact: true }).fill("시험역");
    await expect(page.locator(".map-place-list .place-row")).toHaveCount(1); await expect(count).toHaveText("1건 표시");
    await page.getByLabel("역 검색", { exact: true }).clear(); await expect(count).toHaveText("0건 표시");
  });

  for (const path of ["/bus/express", "/bus/intercity"]) test(`${path} 목록 건수는 가까운 장소나 실제 검색 행만 센다 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const terminal = { id: 1, terminal_id: "T1", terminal_name: "시험터미널", city_name: "시험도시", longitude: 127.1, latitude: 37.3, updated_at: at };
    await page.route("**/api/**", (route) => route.fulfill({ json: { items: [terminal], next_offset: null } }));
    await page.goto(path); const count = page.locator(".kt-map-count");
    await expect(count).toHaveText("1건 표시");
    await page.getByRole("tab", { name: "목록", exact: true }).click();
    const rows = page.locator(".terminal-search .station-results button");
    await expect(rows).toHaveCount(0); await expect(count).toHaveText("0건 표시");
    const from = page.getByLabel("출발 터미널", { exact: true }), to = page.getByLabel("도착 터미널", { exact: true });
    await from.fill("시험"); await expect(rows).toHaveCount(1); await expect(count).toHaveText("1건 표시");
    await to.fill("시험"); await expect(rows).toHaveCount(2); await expect(count).toHaveText("2건 표시");
    await from.clear(); await expect(count).toHaveText("1건 표시");
    await to.clear(); await expect(count).toHaveText("0건 표시");
  });

  test(`항구 목록 건수는 상위 60개 표시 제한과 검색을 따른다 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const ports = Array.from({ length: 61 }, (_, index) => ({ ...port, id: index + 1, provider_id: `U${index + 1}`, name: `항구${index + 1}` }));
    await page.route("**/api/**", (route) => route.fulfill({ json: { items: ports } }));
    await page.goto("/ferry"); await page.getByRole("tab", { name: "목록", exact: true }).click();
    const count = page.locator(".kt-map-count");
    await expect(page.getByRole("checkbox")).toHaveCount(60); await expect(count).toHaveText("60건 표시");
    await expect(page.locator(".multi-search").getByRole("status")).toContainText("61개 결과");
    await expect(page.getByText("상위 60곳을 표시합니다. 검색어를 입력해 범위를 좁혀 주세요.", { exact: true })).toBeVisible();
    await page.getByLabel("항구 검색", { exact: true }).fill("항구61");
    await expect(page.getByRole("checkbox")).toHaveCount(1); await expect(count).toHaveText("1건 표시");
    await page.getByLabel("항구 검색", { exact: true }).clear(); await expect(count).toHaveText("60건 표시");
  });

  test(`좌표 없는 항구 상세는 비교 선택과 독립적으로 열고 초점을 복원한다 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    let ports = [port];
    await page.route("**/api/**", (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith("/features/places")) return route.fulfill({ json: { items: ports } });
      return route.fulfill({ json: { service_date: url.searchParams.get("date"), items: [], missing_port_ids: [] } });
    });
    await page.goto("/ferry");
    await page.getByRole("tab", { name: "목록", exact: true }).click();
    const choices = page.getByRole("checkbox");
    await expect(choices).toHaveCount(1);
    await choices.first().check();
    const detail = page.getByRole("complementary", { name: "선택 장소 상세" });
    await expect(detail).toHaveCount(0);
    const inspect = page.getByRole("button", { name: "좌표없는항구 상세 보기", exact: true });
    await expect(inspect).toBeVisible();
    await inspect.focus(); await inspect.press("Enter");
    await expect(detail).toBeFocused();
    await expect(page.getByRole("tab", { name: "목록", exact: true })).toHaveAttribute("aria-selected", "true");
    await expect(detail.getByRole("link", { name: "061-123-4567", exact: true })).toHaveAttribute("href", "tel:0611234567");
    for (const text of ["시험 섬 주소", "대합실", "출처"]) await expect(detail).toContainText(text);
    await page.keyboard.press("Escape");
    await expect(detail).toHaveCount(0); await expect(inspect).toBeFocused(); await expect(choices.first()).toBeChecked();
    ports = mixedPorts;
    await openFilters(page); await page.getByRole("button", { name: "저장 정보 새로고침", exact: true }).click();
    await expect(choices).toHaveCount(6);
    for (let i = 1; i < 5; i++) await choices.nth(i).check();
    await expect(choices.nth(5)).toBeDisabled();
    const sixth = page.getByRole("button", { name: "시험항구6 상세 보기", exact: true });
    await expect(sixth).toBeEnabled(); await sixth.click(); await expect(detail).toBeFocused();
    await expect(detail).toContainText("시험항구6");
    await expect(page.locator(".multi-search").getByRole("status")).toContainText("5/5곳 선택");
    await page.keyboard.press("Escape"); await expect(sixth).toBeFocused();
    await page.getByRole("tab", { name: "지도", exact: true }).click(); await page.getByRole("tab", { name: "목록", exact: true }).click();
    for (let i = 0; i < 5; i++) await expect(choices.nth(i)).toBeChecked();
  });

  test(`항구 목록 건수는 좌표·지도 선택과 별개로 검색 결과를 센다 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    let ports = [port];
    await page.route("**/api/**", (route) => {
      const url = new URL(route.request().url());
      return route.fulfill({ json: url.pathname.endsWith("/features/places") ? { items: ports } : { service_date: url.searchParams.get("date"), items: [], missing_port_ids: [] } });
    });
    await page.goto("/ferry"); await page.getByRole("tab", { name: "목록", exact: true }).click();
    const count = page.locator(".kt-map-count");
    await expect(page.getByRole("checkbox")).toHaveCount(1); await expect(count).toHaveText("1건 표시");
    ports = mixedPorts;
    await openFilters(page); await page.getByRole("button", { name: "저장 정보 새로고침", exact: true }).click();
    await expect(page.getByRole("checkbox")).toHaveCount(6); await expect(count).toHaveText("6건 표시");
    await page.getByRole("tab", { name: "지도", exact: true }).click(); await expect(count).toHaveText("3건 표시");
    await page.getByRole("tab", { name: "목록", exact: true }).click();
    await page.getByRole("checkbox", { name: /좌표없는항구/ }).check(); await expect(count).toHaveText("6건 표시");
    await page.getByRole("tab", { name: "지도", exact: true }).click(); await expect(count).toHaveText("0건 표시");
    await page.getByRole("tab", { name: "목록", exact: true }).click(); await expect(count).toHaveText("6건 표시");
    await page.getByLabel("항구 검색", { exact: true }).fill("시험항구2"); await expect(count).toHaveText("1건 표시");
    await page.getByLabel("항구 검색", { exact: true }).fill("미등록검색XYZ"); await expect(count).toHaveText("0건 표시");
  });

  for (const path of ["/rail/metro", "/rail"]) test(`${path} 빈 검색은 로딩·실패와 구분하고 결과 행을 가리지 않는다 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    let phase: "pending" | "failed" | "success" = "pending";
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const station = { id: 71, kind: "rail_station", source: "kric_public_file", name: "시험역", subtitle: "시험기관", provider_id: "S1", line_names: ["시험선"], facilities: [], prices: [], longitude: 127.1, latitude: 37.3, updated_at: at };
    await page.route("**/api/**", async (route) => {
      const url = new URL(route.request().url());
      const target = url.pathname.endsWith(path === "/rail/metro" ? "/features/places" : "/rail/general/guide");
      if (target) {
        if (phase === "pending") await gate;
        if (phase === "failed") return route.fulfill({ status: 503, json: { detail: "역 fixture 조회 실패" } });
        return route.fulfill({ json: path === "/rail/metro" ? { items: [station] } : { fetched_at: at, stale: false, kind: "ktx", category_code: "A", total: 1, categories: [{ code: "A", name: "시험선" }], items: [{ provider_id: "S1", station_name: "시험역", latitude: 37.3, longitude: 127.1 }] } });
      }
      return route.fulfill({ json: { fetched_at: at, cities: [], train_classes: [], items: [] } });
    });
    try {
      await page.goto(path); await page.getByRole("tab", { name: "목록", exact: true }).click();
      const list = page.locator(".map-place-list"), empty = list.getByText(/조건에 맞는 역이 없습니다/);
      await expect(list.getByRole("status")).toContainText(path === "/rail/metro" ? "불러오는 중" : "조회 중"); await expect(empty).toHaveCount(0);
      phase = "failed"; release(); await expect(list.getByRole("alert")).toBeVisible(); await expect(empty).toHaveCount(0);
      phase = "success"; await openFilters(page);
      await page.getByRole("button", { name: path === "/rail/metro" ? "새로고침" : "다시 조회", exact: true }).click();
      await expect(page.getByRole("option", { name: path === "/rail/metro" ? "시험선 · 시험기관" : "시험선", exact: true })).toHaveCount(1);
      await page.getByLabel("노선", { exact: true }).selectOption({ label: path === "/rail/metro" ? "시험선 · 시험기관" : "시험선" });
      const search = page.getByLabel(path === "/rail/metro" ? "역 검색" : "역 이름", { exact: true });
      await search.fill("없는역명"); await expect(empty).toBeVisible(); await expect(list.locator(".place-row")).toHaveCount(0);
      expect(await empty.evaluate((element) => getComputedStyle(element).position)).toBe("static");
      await search.fill("시험역"); await expect(empty).toHaveCount(0);
      const row = list.getByRole("button", { name: /시험역/ }); await expect(row).toBeVisible();
      const r = (await row.boundingBox())!, l = (await list.boundingBox())!; expect(r.y).toBeGreaterThanOrEqual(l.y);
    } finally { release(); }
  });
}
