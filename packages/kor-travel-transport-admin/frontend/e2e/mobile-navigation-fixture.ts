import type { Page } from "@playwright/test";

export function requireLoopbackOrigin(baseURL: string | undefined): string {
  let url: URL;
  try { url = new URL(baseURL ?? ""); } catch { throw new Error("격리 메뉴 회귀 검사는 loopback HTTP(S) 주소만 사용할 수 있습니다."); }
  if (!["http:", "https:"].includes(url.protocol) || !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || url.username || url.password) {
    throw new Error("격리 메뉴 회귀 검사는 loopback HTTP(S) 주소만 사용할 수 있습니다.");
  }
  return url.origin;
}

export async function openIsolatedMenuPage(page: Page, baseURL: string | undefined, path = "/fuel"): Promise<void> {
  const origin = requireLoopbackOrigin(baseURL);
  const target = new URL(path, origin);
  if (!["http:", "https:"].includes(target.protocol) || target.origin !== origin || target.username || target.password) {
    throw new Error("격리 메뉴 경로는 검증한 origin을 벗어날 수 없습니다.");
  }
  // caller의 실제 baseURL과 경로를 검사한 후에만 모의 쿠키·응답을 설치한다.
  await page.context().addCookies([{
    name: "kor_travel_transport_admin_session", value: "isolated-mobile-navigation",
    url: origin, httpOnly: true, sameSite: "Strict",
  }]);
  await page.route("https://api.vworld.kr/**", (route) => route.abort());
  await page.route((url) => url.origin === origin && url.pathname.startsWith("/api/transport/"), (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/catalog")) return route.fulfill({ json: { cities: [], train_classes: [], items: [] } });
    return route.fulfill({ json: {
      items: [], total: 0, truncated: false, stale: false, available_sources: [],
      airports: [], current: { items: [] }, collector: {}, holidays: null,
    } });
  });
  await page.goto(target.href);
}
