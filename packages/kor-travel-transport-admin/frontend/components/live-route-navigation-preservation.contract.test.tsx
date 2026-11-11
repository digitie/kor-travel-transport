import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, expect, test, vi } from "vitest";
import { AdminShell } from "./admin-shell";
const location = vi.hoisted(() => ({ pathname: "/" }));
vi.mock("next/navigation", () => ({ usePathname: () => location.pathname }));
beforeEach(() => { location.pathname = "/"; });
test.each([["/parking-lots", "일반 주차장"], ["/rail/timetable", "시간표 조회"]])("운영 목적지 %s는 탐색할 수 있고 현재 메뉴가 하나다", (path, label) => {
 location.pathname = path;
 const doc = renderToStaticMarkup(<AdminShell><main><h1>{label}</h1></main></AdminShell>);
 const links = doc.match(/<a\b[^>]*>[\s\S]*?<\/a>/g) ?? [];
 const entry = links.find(link => link.includes(`href="${path}"`));
 expect(entry).toBeDefined(); expect(entry).toContain(label);
 const active = links.filter(link => link.includes('aria-current="page"'));
 expect(active).toHaveLength(1); expect(active[0]).toContain(`href="${path}"`);
 expect(doc).toContain(`<h1>${label}</h1>`);
});
