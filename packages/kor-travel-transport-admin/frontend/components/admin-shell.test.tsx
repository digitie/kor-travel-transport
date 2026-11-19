import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, expect, test, vi } from "vitest";
import { AdminShell } from "./admin-shell";
import { PageHeader } from "./page-header";
import { NAV_GROUPS, PAGE_HEADINGS } from "./admin-nav";

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

test("셸은 사이드바 landmark·본문 landmark·건너뛰기 링크를 가진다", () => {
  const html = renderToStaticMarkup(
    <AdminShell>
      <p>본문</p>
    </AdminShell>,
  );
  expect(html).toContain('data-testid="admin-shell"');
  expect(html).toContain('data-slot="admin-shell-rail"');
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

test("페이지 제목은 공통 한 줄 상단 바와 설명·액션을 사용한다", () => {
  navigation.pathname = "/admin/dagster";
  const html = renderToStaticMarkup(
    <PageHeader title="전달된 제목" description="전달된 설명" actions={<button type="button">동작</button>} />,
  );
  expect(html).toContain('data-slot="admin-shell-header"');
  expect(html).toContain('title="교통 - 전달된 제목"');
  expect(html).toContain('data-slot="admin-shell-title"');
  expect(html).toContain("전달된 제목");
  expect(html).toContain('data-slot="admin-shell-description"');
  expect(html).toContain("전달된 설명");
  expect(html.match(/<h1\b/g)).toHaveLength(1);
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

test.each([
  ["/", "운영 홈"],
  ["/fuel", "유가 지도"],
  ["/highways", "고속도로"],
  ["/rail/mapping", "지하철역 코드 매핑"],
  ["/rail/timetable", "시간표 조회"],
])("%s 첫 서버 렌더부터 맨 위 한 줄 제목은 '교통 - %s'이고 설명도 같은 줄에 있다", (pathname, page) => {
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
  // hydration 뒤 PageHeader가 덮어써도 바뀌지 않도록 설명도 같은 정본에서 서버 렌더한다.
  expect(html).toMatch(/data-slot="admin-shell-description"[^>]*>[^<]+<\/p>/);
  // 앱 설명 문구(옛 워드마크)는 두지 않는다.
  expect(html).not.toContain("kor-travel-transport admin");
});

test("모든 메뉴 항목은 페이지 제목·설명 정본을 가진다", () => {
  const hrefs = NAV_GROUPS.flatMap((group) => group.items.map((item) => item.href));
  expect(Object.keys(PAGE_HEADINGS).sort()).toEqual([...hrefs].sort());
  for (const heading of Object.values(PAGE_HEADINGS)) {
    expect(heading.title.trim()).not.toBe("");
    expect(heading.description.trim()).not.toBe("");
  }
});
