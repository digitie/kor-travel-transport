import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, expect, test, vi } from "vitest";
import { AdminShell, PageHeader } from "./admin-shell";

const navigation = vi.hoisted(() => ({ pathname: "/" }));
vi.mock("next/navigation", () => ({ usePathname: () => navigation.pathname }));

beforeEach(() => { navigation.pathname = "/"; });

test.each([
  ["/", "/"],
  ["/map", "/map"],
  ["/map/place/1", "/map"],
  ["/admin/dagster", "/admin/dagster"],
  ["/admin/dagster/runs/example", "/admin/dagster"],
  ["/bus/express/terminal/1", "/bus/express"],
  ["/bus/intercity/terminal/1", "/bus/intercity"],
])("%s 경로는 %s 메뉴만 활성화한다", (pathname, href) => {
  navigation.pathname = pathname;
  const html = renderToStaticMarkup(<AdminShell><p>본문</p></AdminShell>);
  const current = (html.match(/<a\b[^>]*>/g) ?? []).filter((tag) => tag.includes('aria-current="page"'));
  expect(current).toHaveLength(1);
  expect(current[0]).toContain(`href="${href}"`);
});

test.each(["/mapping", "/admin/dagster-other", "/bus/expressway"])("%s는 비슷한 접두사의 메뉴를 활성화하지 않는다", (pathname) => {
  navigation.pathname = pathname;
  const html = renderToStaticMarkup(<AdminShell><p>본문</p></AdminShell>);
  expect(html).not.toContain('aria-current="page"');
});

test("로그아웃은 POST 제출 폼과 제출 버튼을 유지한다", () => {
  const html = renderToStaticMarkup(<AdminShell><p>본문</p></AdminShell>);
  const form = html.match(/<form\b[^>]*>[\s\S]*?<\/form>/)?.[0];
  expect(form).toContain('action="/api/auth/logout"');
  expect(form).toMatch(/method="post"/i);
  expect(form).toMatch(/<button\b[^>]*type="submit"/);
  expect(html).not.toMatch(/<a\b[^>]*href="\/api\/auth\/logout"/);
});

test("로그인 화면에는 관리 메뉴와 로그아웃 폼이 없다", () => {
  navigation.pathname = "/login";
  const html = renderToStaticMarkup(<AdminShell><p>로그인 본문</p></AdminShell>);
  expect(html).toContain("로그인 본문");
  expect(html).not.toContain("/api/auth/logout");
  expect(html).not.toContain("<nav");
});

test("페이지 헤더는 현재 경로·전달된 제목·액션을 보존한다", () => {
  navigation.pathname = "/admin/dagster";
  const html = renderToStaticMarkup(<PageHeader title="전달된 제목" description="전달된 설명" actions={<button type="button">동작</button>} />);
  expect(html).toMatch(/class="[^"]*\bpage-header-wrap\b/);
  expect(html).toMatch(/class="[^"]*\bpage-path\b[^"]*">\/admin\/dagster</);
  expect(html).toContain("<h1>전달된 제목</h1>");
  expect(html).toContain("전달된 설명");
  expect(html).toMatch(/class="page-header-actions"><button[^>]*>동작<\/button>/);
});
