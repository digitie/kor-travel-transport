// @vitest-environment jsdom
import { act, type ComponentProps } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

const navigation = vi.hoisted(() => ({ pathname: "/map" }));
vi.mock("next/navigation", () => ({ usePathname: () => navigation.pathname }));
vi.mock("next/link", () => ({ default: ({ href, children, ...props }: ComponentProps<"a">) => <a href={href} {...props} onClick={(event) => { props.onClick?.(event); event.preventDefault(); }}>{children}</a> }));
import { AdminShell } from "./admin-shell";
import { PageHeader } from "./page-header";

// 공용 관리자 셸: lg 이상은 접을 수 있는 세로 rail, 미만은 상단 바 메뉴 버튼으로 여는 좌측 drawer(dialog).
const KEY = "kor-travel-transport:sidebar-collapsed";
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  navigation.pathname = "/map";
  localStorage.clear();
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} }));
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); });

async function mount(children = <input aria-label="본문 입력" />) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(<AdminShell>{children}</AdminShell>));
  const rail = () => container.querySelector<HTMLElement>('[data-slot="admin-shell-rail"]')!;
  const nav = () => rail().querySelector<HTMLElement>('nav[aria-label="주요 메뉴"]')!;
  const button = (name: string) => [...document.querySelectorAll<HTMLButtonElement>("button")].find((item) => item.getAttribute("aria-label") === name || item.textContent?.trim() === name);
  const dispose = async () => { await act(async () => { root.unmount(); await new Promise((resolve) => setTimeout(resolve, 0)); }); container.remove(); };
  return { container, root, rail, nav, button, dispose };
}

test("주요 메뉴는 기존 19개 경로를 모두 보이고 drawer는 닫혀 있다", async () => {
  const { nav, dispose } = await mount();
  try {
    expect(nav().querySelectorAll('[data-slot="app-menu-link"]')).toHaveLength(19);
    for (const href of ["/parking-lots", "/rail/timetable", "/parking"]) expect(nav().querySelector(`a[href="${href}"]`)).not.toBeNull();
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  } finally { await dispose(); }
});

test("메뉴 버튼은 좌측 drawer를 열고 메뉴 링크를 누르면 닫는다", async () => {
  const { button, dispose } = await mount();
  try {
    await act(async () => button("메뉴 열기")!.click());
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]')!;
    expect(dialog).not.toBeNull();
    expect(dialog.dataset.slot).toBe("admin-shell-drawer");
    const links = dialog.querySelectorAll('[data-slot="app-menu-link"]');
    expect(links).toHaveLength(19);
    expect(dialog.querySelector('form[action="/api/auth/logout"]')).not.toBeNull();
    await act(async () => (dialog.querySelector<HTMLAnchorElement>('a[href="/fuel"]')!).click());
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  } finally { await dispose(); }
});

test("로그아웃은 스크립트 없이도 동작하는 POST 폼이고 제출 때 대시보드 캐시를 지운다", async () => {
  const { container, dispose } = await mount();
  try {
    expect(container.querySelector('a[href="/api/auth/logout"]')).toBeNull();
    const forms = [...container.querySelectorAll<HTMLFormElement>('form[action="/api/auth/logout"]')];
    expect(forms.length).toBeGreaterThan(0);
    for (const form of forms) {
      expect(form.method).toBe("post");
      expect(form.querySelector('button[type="submit"]')).not.toBeNull();
    }
    sessionStorage.setItem("kor-travel-transport-dashboard-v2", "{}");
    await act(async () => { forms[0].dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
    expect(sessionStorage.getItem("kor-travel-transport-dashboard-v2")).toBeNull();
  } finally { await dispose(); }
});

test("rail 접힘 선택을 저장하고 다시 열 때 복구한다", async () => {
  const { rail, nav, button, dispose } = await mount();
  try {
    expect(rail().dataset.collapsed).toBeUndefined();
    await act(async () => button("좌측 메뉴 접기")!.click());
    expect(rail().dataset.collapsed).toBe("true");
    expect(localStorage.getItem(KEY)).toBe("true");
    expect(button("좌측 메뉴 펼치기")).toBeDefined();
    // 접힌 rail의 링크도 이름과 툴팁을 가진다.
    const fuel = nav().querySelector<HTMLAnchorElement>('a[href="/fuel"]')!;
    expect(fuel.getAttribute("aria-label")).toBe("유가 지도");
    expect(fuel.getAttribute("title")).toBe("유가 지도");
  } finally { await dispose(); }
  const restored = await mount();
  try { expect(restored.rail().dataset.collapsed).toBe("true"); }
  finally { await restored.dispose(); }
});

test("옛 사이드바가 저장한 '1'/'0' 값을 그대로 읽고 같은 형식으로 쓴다", async () => {
  localStorage.setItem(KEY, "1");
  const { rail, button, dispose } = await mount();
  try {
    expect(rail().dataset.collapsed).toBe("true");
    await act(async () => button("좌측 메뉴 펼치기")!.click());
    expect(rail().dataset.collapsed).toBeUndefined();
    expect(localStorage.getItem(KEY)).toBe("0");
  } finally { await dispose(); }
});

test("하위 경로에서는 해당 메뉴 하나만 활성화한다", async () => {
  navigation.pathname = "/rail/mapping/variant";
  const { nav, dispose } = await mount();
  try {
    const selected = nav().querySelectorAll('[aria-current="page"]');
    expect(selected).toHaveLength(1);
    expect(selected[0].getAttribute("href")).toBe("/rail/mapping");
  } finally { await dispose(); }
});

test("브라우저 저장소가 막혀도 rail 접기와 링크를 사용할 수 있다", async () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("저장소 차단"); });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("저장소 차단"); });
  const { rail, nav, button, dispose } = await mount();
  try {
    await act(async () => button("좌측 메뉴 접기")!.click());
    expect(rail().dataset.collapsed).toBe("true");
    expect(nav().querySelectorAll('[data-slot="app-menu-link"]')).toHaveLength(19);
    await act(async () => button("좌측 메뉴 펼치기")!.click());
    expect(rail().dataset.collapsed).toBeUndefined();
  } finally { await dispose(); }
});

test("페이지 헤더는 셸 상단 바 한 줄에 '교통 - 페이지' 제목과 작은 설명만 둔다", async () => {
  navigation.pathname = "/fuel";
  const { container, dispose } = await mount(<PageHeader title="유가 지도" description="주유소별 최신 가격" />);
  try {
    const headers = container.querySelectorAll('[data-slot="admin-shell-header"]');
    expect(headers).toHaveLength(1);
    const h1 = container.querySelectorAll("h1");
    expect(h1).toHaveLength(1);
    expect(h1[0].textContent).toBe("교통 - 유가 지도");
    expect(headers[0].contains(h1[0])).toBe(true);
    const description = headers[0].querySelector<HTMLElement>('[data-slot="admin-shell-description"]')!;
    expect(description.textContent).toBe("주유소별 최신 가격");
    expect(description.title).toBe("주유소별 최신 가격");
    // 본문(main)에는 제목 줄을 다시 그리지 않는다.
    expect(container.querySelector("main")!.querySelector("h1, [data-slot='admin-shell-header']")).toBeNull();
  } finally { await dispose(); }
});
