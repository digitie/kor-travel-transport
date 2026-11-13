import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, expect, test, vi } from "vitest";
import { AdminShell } from "./admin-shell";
import { PageHeader } from "./page-header";

const navigation = vi.hoisted(() => ({ pathname: "/" }));
vi.mock("next/navigation", () => ({ usePathname: () => navigation.pathname }));

beforeEach(() => {
  navigation.pathname = "/";
});

test.each([
  ["/", "/"],
  ["/map", "/map"],
  ["/map/place/1", "/map"],
  ["/fuel", "/fuel"],
  ["/rail/mapping", "/rail/mapping"],
  ["/rail/mapping/variant", "/rail/mapping"],
  ["/admin/dagster", "/admin/dagster"],
  ["/admin/dagster/runs/example", "/admin/dagster"],
  ["/bus/express/terminal/1", "/bus/express"],
  ["/bus/intercity/terminal/1", "/bus/intercity"],
])("%s 경로는 %s 메뉴만 활성화한다", (pathname, href) => {
  navigation.pathname = pathname;
  const html = renderToStaticMarkup(
    <AdminShell>
      <p>본문</p>
    </AdminShell>,
  );
  const current = (html.match(/<a\b[^>]*>/g) ?? []).filter((tag) => tag.includes('aria-current="page"'));
  expect(current).toHaveLength(1);
  expect(current[0]).toContain(`href="${href}"`);
});

test.each(["/mapping", "/admin/dagster-other", "/bus/expressway"])("%s는 비슷한 접두사의 메뉴를 활성화하지 않는다", (pathname) => {
  navigation.pathname = pathname;
  const html = renderToStaticMarkup(
    <AdminShell>
      <p>본문</p>
    </AdminShell>,
  );
  expect(html).not.toContain('aria-current="page"');
});

test("로그아웃은 버튼으로 두고 링크로 바꾸지 않는다", () => {
  const html = renderToStaticMarkup(
    <AdminShell>
      <p>본문</p>
    </AdminShell>,
  );
  expect(html).toContain(">로그아웃</span>");
  expect(html).not.toMatch(/<a\b[^>]*href="\/api\/auth\/logout"/);
});

test("셸은 사이드바 landmark·본문 landmark·건너뛰기 링크를 가진다", () => {
  const html = renderToStaticMarkup(
    <AdminShell>
      <p>본문</p>
    </AdminShell>,
  );
  expect(html).toContain('data-testid="admin-shell"');
  expect(html).toContain('aria-label="관리자 사이드바"');
  expect(html).toContain('id="main-content"');
  expect(html).toContain('href="#main-content"');
  expect(html).toContain("본문으로 건너뛰기");
});

test("로그인 화면에는 관리 메뉴와 로그아웃이 없다", () => {
  navigation.pathname = "/login";
  const html = renderToStaticMarkup(
    <AdminShell>
      <p>로그인 본문</p>
    </AdminShell>,
  );
  expect(html).toContain("로그인 본문");
  expect(html).not.toContain("관리자 사이드바");
  expect(html).not.toContain("로그아웃");
  expect(html).not.toContain("<nav");
});

test("페이지 헤더는 섹션 라벨·제목·도움말·액션을 map 마크업으로 보여 준다", () => {
  navigation.pathname = "/admin/dagster";
  const html = renderToStaticMarkup(
    <PageHeader title="전달된 제목" description="전달된 설명" actions={<button type="button">동작</button>} />,
  );
  expect(html).toContain('data-slot="admin-shell-header"');
  expect(html).toContain(">운영 관리</p>");
  expect(html).toContain("<h1 class=");
  expect(html).toContain(">전달된 제목</h1>");
  expect(html).toContain('aria-label="도움말: 전달된 제목"');
  expect(html).not.toContain("전달된 설명");
  expect(html).toMatch(/<button[^>]*>동작<\/button>/);
});

test("페이지 헤더는 breadcrumbs가 있으면 섹션 라벨 대신 breadcrumb을 그린다", () => {
  navigation.pathname = "/rail/mapping";
  const html = renderToStaticMarkup(
    <PageHeader
      title="역 코드 매핑"
      breadcrumbs={[
        { label: "기차", href: "/rail" },
        { label: "역 코드 매핑" },
      ]}
    />,
  );
  expect(html).toContain('href="/rail"');
  expect(html).not.toContain(">기차</p>");
});
