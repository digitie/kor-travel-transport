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
  ["/parking-lots", "/parking-lots"],
  ["/parking", "/parking"],
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

test("셸은 공용 관리자 셸의 rail·상단 바·본문 landmark·건너뛰기 링크를 가진다", () => {
  const html = renderToStaticMarkup(
    <AdminShell>
      <p>본문</p>
    </AdminShell>,
  );
  expect(html).toContain('data-testid="admin-shell"');
  expect(html).toContain('data-slot="admin-shell-rail"');
  expect(html).toContain('data-slot="admin-shell-header"');
  expect(html).toContain('data-slot="admin-shell-menu-button"');
  expect(html).toContain('id="main-content"');
  expect(html).toContain('href="#main-content"');
  expect(html).toContain("본문으로 건너뛰기");
  // 앱 설명 문구(옛 워드마크 "kor-travel-transport admin")는 두지 않는다.
  expect(html).not.toContain("kor-travel-transport");
});

test.each([
  ["/", "홈"],
  ["/fuel", "유가 지도"],
  ["/rail/timetable", "시간표 조회"],
])("%s 첫 서버 렌더의 맨 위 한 줄 제목은 '교통 - %s'다", (pathname, page) => {
  navigation.pathname = pathname;
  const html = renderToStaticMarkup(
    <AdminShell>
      <p>본문</p>
    </AdminShell>,
  );
  const h1 = html.match(/<h1\b[^>]*>([\s\S]*?)<\/h1>/g) ?? [];
  expect(h1).toHaveLength(1);
  const [heading = ""] = h1;
  expect(heading).toContain(`title="교통 - ${page}"`);
  expect(heading.replace(/<[^>]+>/g, "")).toBe(`교통 - ${page}`);
});

test("로그인 화면에는 관리 메뉴와 로그아웃이 없다", () => {
  navigation.pathname = "/login";
  const html = renderToStaticMarkup(
    <AdminShell>
      <p>로그인 본문</p>
    </AdminShell>,
  );
  expect(html).toContain("로그인 본문");
  expect(html).not.toContain("admin-shell");
  expect(html).not.toContain("로그아웃");
  expect(html).not.toContain("<nav");
});

test("셸 밖의 페이지 헤더는 한 줄 상단 바로 제목·작은 설명·동작을 그린다", () => {
  navigation.pathname = "/admin/dagster";
  const html = renderToStaticMarkup(
    <PageHeader title="전달된 제목" description="전달된 설명" actions={<button type="button">동작</button>} />,
  );
  expect(html).toContain('data-slot="admin-shell-header"');
  expect(html).toMatch(/<h1\b[^>]*>전달된 제목<\/h1>/);
  expect(html).toMatch(/<p\b[^>]*data-slot="admin-shell-description"[^>]*title="전달된 설명"[^>]*>전달된 설명<\/p>/);
  expect(html).toMatch(/<button[^>]*>동작<\/button>/);
});
