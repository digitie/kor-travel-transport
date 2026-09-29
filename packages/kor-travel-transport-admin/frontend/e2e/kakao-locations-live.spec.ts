import { expect, test } from "@playwright/test";

type Place = { kind: string; name: string; provider_id: string | null; location_source: string; latitude: number | null; longitude: number | null };

test("운영 Kakao 좌표가 저장 API와 지도 목록·상세에 반영된다", async ({ page }) => {
  test.skip(process.env.E2E_VERIFY_KAKAO_PLACE !== "true", "실제 Kakao 적재 검증 시에만 실행합니다.");
  const password = process.env.E2E_TRANSPORT_UI_PASSWORD;
  expect(password, "운영 관리자 로그인 암호가 필요합니다.").toBeTruthy();
  await page.goto("/login");
  await page.getByLabel("비밀번호").fill(password!);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);

  for (const kind of ["ferry_port", "bus_terminal"]) {
    const response = await page.context().request.get(`/api/transport/transport/features/places?kind=${kind}&limit=5000`);
    expect(response.ok()).toBe(true);
    const body = await response.json() as { items: Place[] };
    const selected = body.items.find((place) => place.location_source === "kakao_place" &&
      place.provider_id && place.latitude !== null && place.longitude !== null);
    expect(selected, `${kind}의 Kakao 저장 좌표가 있어야 합니다.`).toBeDefined();

    await page.goto("/map");
    await page.getByRole("button", { name: "목록", exact: true }).click();
    await page.getByLabel("장소 검색").fill(selected!.name);
    const row = page.locator(".map-place-list button").filter({ hasText: selected!.provider_id! }).first();
    await expect(row).toBeVisible();
    await row.click();
    const detail = page.getByLabel("선택 장소 상세");
    await expect(detail.getByText(`${kind === "ferry_port" ? "항구" : "터미널"} 코드 ${selected!.provider_id}`)).toBeVisible();
    await expect(detail.getByText(kind === "ferry_port"
      ? /지도 검색에서 확인한 항만 시설/
      : /카카오맵 장소 검색으로 확인한 터미널 위치/)).toBeVisible();
  }
});
