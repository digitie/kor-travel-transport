import { expect, type Locator, type Page } from "@playwright/test";

/** 공용 관리자 셸의 메뉴 버튼(lg 미만). drawer가 열린 동안은 Radix aria-hidden 때문에 role로 잡히지 않는다. */
export const adminMenuButton = (page: Page): Locator => page.locator('[data-slot="admin-shell-menu-button"]');

/** 맨 위 한 줄 제목 "교통 - 페이지". 페이지 h1은 상단 바에만 있다. */
export const adminTitle = (page: Page, pageName: string): Locator => page.getByRole("heading", { level: 1, name: `교통 - ${pageName}`, exact: true });

/**
 * 메뉴·로그아웃이 보이는 범위. lg 이상은 좌측 rail, 미만은 메뉴 버튼으로 좌측 drawer(dialog)를 연다.
 * drawer가 열리면 메뉴가 DOM에 두 번 있으므로 반드시 돌려준 범위 안에서 찾는다.
 */
export async function adminMenuScope(page: Page): Promise<Locator> {
  const button = adminMenuButton(page);
  if (!(await button.isVisible())) return page.locator('[data-slot="admin-shell-rail"]');
  const drawer = page.getByRole("dialog");
  if (!(await drawer.isVisible())) await button.click();
  await expect(drawer).toBeVisible();
  return drawer;
}
