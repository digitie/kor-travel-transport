import { readFile } from "node:fs/promises";

import { expect, test } from "@playwright/test";

const initial = {
  schema_version: 1,
  revision: "a".repeat(64),
  catalog_sha256: "b".repeat(64),
  catalog_updated_at: "2026-10-20T00:00:00Z",
  mappings_updated_at: null,
  station_count: 1,
  mapped_count: 0,
  automatic_mapped_count: 0,
  manual_mapped_count: 0,
  unmatched_count: 1,
  stations: [{ operator_code: "S", operator_name: "서울교통공사", line_code: "1", line_name: "1호선",
    station_code: "0150", station_name: "서울역", rail_station_id: null,
    rail_station_identity_key: null, match_method: "unmatched" as const }],
  places: [{ id: 10, identity_key: "rail_station:kric:0150", operator_name: "서울교통공사",
    line_name: "1호선", station_number: "0150", station_name: "서울역" }],
  mappings: [],
};

async function provideMockAdminSession(page: import("@playwright/test").Page) {
  const baseURL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:12305";
  await page.context().addCookies([{ name: "kor_travel_transport_admin_session", value: "isolated-e2e-session",
    url: baseURL, httpOnly: true, sameSite: "Strict" }]);
}

test.beforeEach(() => {
  test.skip(process.env.E2E_KRIC_MAPPING_E2E !== "true",
    "격리된 KRIC 매핑 브라우저 테스트는 E2E_KRIC_MAPPING_E2E=true일 때만 실행합니다.");
});

test("역명 차이를 관리자 수동 매핑하고 JSON으로 내보낸다", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 900 });
  await provideMockAdminSession(page);
  let saved: { expected_revision: string; mappings: Array<Record<string, string>> } | undefined;
  await page.route("**/api/admin/rail-station-mappings", async (route) => {
    if (route.request().method() === "GET") return route.fulfill({ json: initial });
    saved = route.request().postDataJSON() as typeof saved;
    const updated = { ...initial, revision: "c".repeat(64), mappings_updated_at: "2026-10-20T01:00:00Z",
      mapped_count: 1, manual_mapped_count: 1, unmatched_count: 0,
      stations: initial.stations.map((station) => ({ ...station, rail_station_id: 10,
        rail_station_identity_key: "rail_station:kric:0150", match_method: "manual" as const })),
      mappings: saved?.mappings ?? [] };
    return route.fulfill({ json: updated });
  });

  await page.goto("/rail/mapping", { waitUntil: "domcontentloaded" });
  const editor = page.getByRole("region", { name: "서울역 역 매핑 편집" });
  await expect(editor).toBeVisible();
  await page.getByLabel("연결할 KRIC 기준 역 검색").fill("서울역");
  await page.getByRole("listbox", { name: "역 검색 결과" }).getByRole("option", { name: /서울역/ }).click();
  await page.getByPlaceholder("예: 역 번호와 운영기관 자료 대조").fill("KRIC 역 번호·운영기관 대조");
  await editor.getByRole("button", { name: "수동으로 연결" }).click();
  await expect(page.getByRole("status")).toContainText("수동 매핑을 저장했습니다.");
  await expect(page.getByRole("status")).toBeFocused();
  expect(saved).toMatchObject({ expected_revision: "a".repeat(64), mappings: [{
    operator_code: "S", line_code: "1", station_code: "0150",
    rail_station_identity_key: "rail_station:kric:0150", note: "KRIC 역 번호·운영기관 대조",
  }] });
  await expect(page.locator(".rail-map-metrics")).toContainText("수동 연결");

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "JSON 내보내기" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe("kric-rail-station-mappings.json");
  const exported = JSON.parse(await readFile((await file.path())!, "utf8")) as Record<string, unknown>;
  expect(exported).toMatchObject({ schema_version: 1, stations: [{ operator_code: "S", line_code: "1",
    station_code: "0150", station_name: "서울역" }], places: [{ identity_key: "rail_station:kric:0150",
      station_name: "서울역", operator_name: "서울교통공사", line_name: "1호선" }],
    manual_mappings: [{ rail_station_identity_key: "rail_station:kric:0150" }] });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("다른 변경이 먼저 저장되면 오래된 매핑을 덮지 않는다", async ({ page }) => {
  await provideMockAdminSession(page);
  await page.route("**/api/admin/rail-station-mappings", async (route) => {
    if (route.request().method() === "GET") return route.fulfill({ json: initial });
    return route.fulfill({ status: 409, json: { detail: "역 코드나 매핑이 변경됐습니다. 새로고침 후 다시 저장해 주세요." } });
  });
  await page.goto("/rail/mapping", { waitUntil: "domcontentloaded" });
  await page.getByLabel("연결할 KRIC 기준 역 검색").fill("서울역");
  await page.getByRole("listbox", { name: "역 검색 결과" }).getByRole("option", { name: /서울역/ }).click();
  await page.getByRole("button", { name: "수동으로 연결" }).click();
  await expect(page.locator("p[role='alert']")).toContainText("새로고침 후 다시 저장해 주세요.");
});

test("검색 결과가 바뀌면 편집 대상도 현재 목록의 역으로 이동한다", async ({ page }) => {
  await provideMockAdminSession(page);
  const stations = [initial.stations[0], ...Array.from({ length: 100 }, (_, index) => ({
    ...initial.stations[0], line_code: String(index + 2), line_name: `${index + 2}호선`,
    station_code: String(index + 2).padStart(4, "0"), station_name: `시험역${index + 1}`,
  }))];
  await page.route("**/api/admin/rail-station-mappings", (route) => route.fulfill({
    json: { ...initial, station_count: stations.length, unmatched_count: stations.length, stations },
  }));

  await page.goto("/rail/mapping", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("region", { name: "서울역 역 매핑 편집" })).toBeVisible();
  await page.getByLabel("역명·운영기관·노선·코드 검색").fill("시험역100");
  await expect(page.getByRole("option", { name: /시험역100/ })).toBeVisible();
  await page.getByRole("option", { name: /시험역100/ }).click();
  await expect(page.getByRole("region", { name: "시험역100 역 매핑 편집" })).toBeVisible();
  await page.getByLabel("역명·운영기관·노선·코드 검색").fill("");
  await expect(page.getByRole("region", { name: "서울역 역 매핑 편집" })).toBeVisible();
  await expect(page.getByRole("option", { name: /서울역/ })).toHaveAttribute("aria-selected", "true");
});

test("늦게 도착한 새로고침 응답이 성공한 매핑 저장을 되돌리지 않는다", async ({ page }) => {
  await provideMockAdminSession(page);
  let holdNextGet = false;
  let releaseStaleResponse = () => {};
  let notifyStaleRequest = () => {};
  const staleGate = new Promise<void>((resolve) => { releaseStaleResponse = resolve; });
  const staleRequestStarted = new Promise<void>((resolve) => { notifyStaleRequest = resolve; });
  await page.route("**/api/admin/rail-station-mappings", async (route) => {
    if (route.request().method() === "GET") {
      if (!holdNextGet) return route.fulfill({ json: initial });
      holdNextGet = false;
      notifyStaleRequest();
      await staleGate;
      return route.fulfill({ json: initial });
    }
    const updated = { ...initial, revision: "c".repeat(64), mappings_updated_at: "2026-10-20T01:00:00Z",
      mapped_count: 1, manual_mapped_count: 1, unmatched_count: 0,
      stations: initial.stations.map((station) => ({ ...station, rail_station_id: 10,
        rail_station_identity_key: "rail_station:kric:0150", match_method: "manual" as const })),
      mappings: [{ operator_code: "S", line_code: "1", station_code: "0150",
        rail_station_identity_key: "rail_station:kric:0150", note: "수동 연결" }] };
    return route.fulfill({ json: updated });
  });

  await page.goto("/rail/mapping", { waitUntil: "domcontentloaded" });
  const editor = page.getByRole("region", { name: "서울역 역 매핑 편집" });
  await expect(editor).toBeVisible();
  holdNextGet = true;
  await page.getByRole("button", { name: "새로고침" }).click();
  await staleRequestStarted;
  await page.getByLabel("연결할 KRIC 기준 역 검색").fill("서울역");
  await page.getByRole("listbox", { name: "역 검색 결과" }).getByRole("option", { name: /서울역/ }).click();
  await page.getByPlaceholder("예: 역 번호와 운영기관 자료 대조").fill("수동 연결");
  await editor.getByRole("button", { name: "수동으로 연결" }).click();
  await expect(page.getByRole("status")).toBeFocused();
  releaseStaleResponse();
  await page.getByRole("checkbox", { name: "미연결 우선 보기" }).uncheck();
  const updatedEditor = page.getByRole("region", { name: "서울역 역 매핑 편집" });
  await expect(updatedEditor.locator(".rail-map-badge")).toHaveText("수동 연결");
  await expect(page.locator(".rail-map-metrics")).toContainText("수동 연결");
  await expect(page.locator("p[role='alert']")).toHaveCount(0);
});
