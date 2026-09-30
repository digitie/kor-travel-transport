import { expect, test } from "@playwright/test";

const stamp = "2026-09-30T00:00:00Z";
const sample = [
  { id: 91, kind: "ferry_port", source: "data_go_kr_maritime", provider_id: "PORT91", name: "시험항" },
  { id: 92, kind: "bus_terminal", source: "data_go_kr_tago", provider_id: "BUS92", name: "시험터미널" },
];

for (const width of [375, 1440]) for (const entry of sample) {
  test(`${entry.kind} 좌표 수동 보정 ${width}px`, async ({ page }) => {
    test.skip(!process.env.E2E_TRANSPORT_UI_PASSWORD, "관리자 로그인 암호가 필요합니다.");
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/login");
    await page.getByLabel("비밀번호").fill(process.env.E2E_TRANSPORT_UI_PASSWORD!);
    await page.getByRole("button", { name: "로그인", exact: true }).click();
    await expect(page).toHaveURL(/\/$/);
    let latitude: number | null = null; let longitude: number | null = null;
    const place = () => ({ ...entry, latitude, longitude, location_source: latitude === null ? null : "admin_manual",
      prices: [], facilities: [], line_names: [], updated_at: stamp });
    await page.route("**/transport/features/places?**", (route) => {
      const kind = new URL(route.request().url()).searchParams.get("kind");
      return route.fulfill({ json: { items: kind === entry.kind ? [place()] : [], total: kind === entry.kind ? 1 : 0, truncated: false } });
    });
    let submitted: Record<string, unknown> | undefined;
    await page.route("**/api/admin/place-locations", (route) => {
      submitted = route.request().postDataJSON() as Record<string, unknown>;
      latitude = Number(submitted.latitude); longitude = Number(submitted.longitude);
      return route.fulfill({ json: place() });
    });
    await page.goto("/map");
    await page.getByRole("button", { name: "목록", exact: true }).click();
    await page.locator(".map-place-list button").filter({ hasText: entry.provider_id }).click();
    const editor = page.getByRole("region", { name: "좌표 수동 보정" });
    await expect(editor).toContainText(entry.provider_id);
    await editor.getByLabel("위도").fill("34.2345");
    await editor.getByLabel("경도").fill("127.1234");
    await editor.getByRole("button", { name: "좌표 저장" }).click();
    expect(submitted).toBeUndefined();
    await editor.getByLabel("확인 근거").fill("공식 주소와 시설점 대조");
    await editor.getByRole("button", { name: "좌표 저장" }).click();
    await expect(editor).toContainText("좌표를 저장했습니다.");
    expect(submitted).toMatchObject({ kind: entry.kind, id: entry.id, source: entry.source,
      provider_id: entry.provider_id, expected_latitude: null, expected_longitude: null,
      expected_name: entry.name, expected_manual_revision: null,
      latitude: 34.2345, longitude: 127.1234 });
    await expect(page.getByRole("complementary", { name: "선택 장소 상세" })).toContainText("관리자가 근거를 대조해 보정한");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test("운영 BFF 쓰기 경로의 세션·토큰·backend 연결을 비파괴적으로 검증한다", async ({ page }) => {
  test.skip(process.env.E2E_VERIFY_MANUAL_WRITE_PATH !== "true", "운영 쓰기 경로 확인 시에만 실행합니다.");
  test.skip(!process.env.E2E_TRANSPORT_UI_PASSWORD, "관리자 로그인 암호가 필요합니다.");
  await page.goto("/login");
  await page.getByLabel("비밀번호").fill(process.env.E2E_TRANSPORT_UI_PASSWORD!);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  const sessionCookiePresent = (await page.context().cookies()).some((cookie) => cookie.name === "kor_travel_transport_admin_session");
  const releaseStatus = await page.evaluate(async () => (await fetch("/api/release")).status);
  const result = await page.evaluate(async () => {
    const response = await fetch("/api/admin/place-locations", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ kind: "ferry_port", id: 2147483647, source: "data_go_kr_maritime", provider_id: "nonexistent",
        expected_name: "존재하지 않는 항구", expected_city_name: null,
        expected_latitude: null, expected_longitude: null, expected_location_source: null, expected_manual_revision: null,
        latitude: 34.123, longitude: 127.123, note: "존재하지 않는 테스트 코드" }) });
    return { status: response.status, body: await response.json() as { detail?: string } };
  });
  expect(result.status, JSON.stringify({ sessionCookiePresent, releaseStatus, detail: result.body.detail })).toBe(404);
  expect(result.body.detail).toBe("공식 기준정보에서 해당 장소를 찾지 못했습니다.");
});

test("다른 관리자 보정과 충돌하면 목록을 다시 조회한다", async ({ page }) => {
  test.skip(!process.env.E2E_TRANSPORT_UI_PASSWORD, "관리자 로그인 암호가 필요합니다.");
  await page.goto("/login");
  await page.getByLabel("비밀번호").fill(process.env.E2E_TRANSPORT_UI_PASSWORD!);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  let loads = 0;
  await page.route("**/transport/features/places?**", (route) => {
    const kind = new URL(route.request().url()).searchParams.get("kind");
    if (kind === "ferry_port") loads += 1;
    return route.fulfill({ json: { items: kind === "ferry_port" ? [{ ...sample[0], latitude: null, longitude: null,
      prices: [], facilities: [], line_names: [], updated_at: stamp }] : [], total: kind === "ferry_port" ? 1 : 0, truncated: false } });
  });
  await page.route("**/api/admin/place-locations", (route) => route.fulfill({ status: 409,
    json: { detail: "다른 좌표가 먼저 저장됐습니다. 새로 조회한 뒤 다시 시도해 주세요." } }));
  await page.goto("/map");
  await page.getByRole("button", { name: "목록", exact: true }).click();
  await page.locator(".map-place-list button").filter({ hasText: "PORT91" }).click();
  const editor = page.getByRole("region", { name: "좌표 수동 보정" });
  await editor.getByLabel("위도").fill("34.2345");
  await editor.getByLabel("경도").fill("127.1234");
  await editor.getByLabel("확인 근거").fill("공식 주소와 시설점 대조");
  await editor.getByRole("button", { name: "좌표 저장" }).click();
  await expect(editor).toContainText("다른 좌표가 먼저 저장됐습니다.");
  const before = loads;
  await editor.getByRole("button", { name: "목록 새로 조회" }).click();
  await expect.poll(() => loads).toBeGreaterThan(before);
  await expect(page.getByLabel("장소 검색")).toBeFocused();
});
