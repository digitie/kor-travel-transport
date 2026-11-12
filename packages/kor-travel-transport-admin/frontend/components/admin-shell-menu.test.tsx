// @vitest-environment jsdom
import { act, type ComponentProps } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

const navigation = vi.hoisted(() => ({ pathname: "/map" }));
vi.mock("next/navigation", () => ({ usePathname: () => navigation.pathname }));
vi.mock("next/link", () => ({ default: ({ href, children, ...props }: ComponentProps<"a">) => <a href={href} {...props} onClick={(event) => { props.onClick?.(event); event.preventDefault(); }}>{children}</a> }));
import { AdminShell } from "./admin-shell";

let mobile = false;
const mediaListeners = new Set<() => void>();
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  navigation.pathname = "/map";
  mobile = false;
  mediaListeners.clear();
  localStorage.clear();
  vi.stubGlobal("matchMedia", (query: string) => ({
    get matches() { return query.includes("1023") && mobile; },
    media: query,
    addEventListener: (_type: string, listener: () => void) => mediaListeners.add(listener),
    removeEventListener: (_type: string, listener: () => void) => mediaListeners.delete(listener),
  }));
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); });
async function changeMobile(value: boolean) {
  await act(async () => { mobile = value; for (const listener of [...mediaListeners]) listener(); });
}
async function mount() {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(<AdminShell><input aria-label="본문 입력" /></AdminShell>));
  const nav = () => document.querySelector<HTMLElement>('nav[aria-label="주요 메뉴"]')!;
  const shell = () => container.querySelector<HTMLElement>(".transport-shell")!;
  const click = async (selector: string) => { await act(async () => document.querySelector<HTMLButtonElement>(selector)!.click()); };
  const dispose = async () => { await act(async () => { root.unmount(); await new Promise((resolve) => setTimeout(resolve, 0)); }); container.remove(); };
  return { container, root, nav, shell, click, dispose };
}
test("PC 세로 메뉴는 기존 19개 경로와 POST 로그아웃을 보존한다", async () => {
  const { container, nav, dispose } = await mount();
  try {
    expect(nav().querySelectorAll('[data-slot="app-menu-link"]')).toHaveLength(19);
    expect(nav().querySelector('a[href="/parking-lots"]')).not.toBeNull();
    expect(nav().querySelector('a[href="/rail/timetable"]')).not.toBeNull();
    expect(container.querySelector('form[action="/api/auth/logout"]')?.getAttribute("method")).toBe("post");
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  } finally { await dispose(); }
});
test("모바일은 기본 닫힘이며 공통 Radix 드로어의 열기·닫기가 동작한다", async () => {
  mobile = true;
  const { nav, click, dispose } = await mount();
  try {
    expect(nav()).toBeNull();
    await click(".mobile-menu-toggle");
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain("내비게이션 메뉴");
    expect(nav().querySelectorAll('[data-slot="app-menu-link"]')).toHaveLength(19);
    expect(document.activeElement?.getAttribute("aria-label")).toBe("메뉴 닫기");
    await click(".sidebar-close");
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    await vi.waitFor(() => expect(document.activeElement?.getAttribute("aria-label")).toBe("메뉴 열기"));
  } finally { await dispose(); }
});
test("PC 접힘 선택과 아이콘 링크 이름·title을 저장하고 복구한다", async () => {
  const { nav, shell, click, dispose } = await mount();
  try {
    await click(".sidebar-collapse");
    expect(shell().dataset.sidebarCollapsed).toBe("true");
    expect(localStorage.getItem("kor-travel-transport:sidebar-collapsed")).toBe("1");
    expect(nav().querySelector('[aria-current="page"]')?.getAttribute("aria-label")).toBe("교통 지도");
    expect(nav().querySelector('[aria-current="page"]')?.getAttribute("title")).toBe("교통 지도");
  } finally { await dispose(); }
  const restored = await mount();
  try { expect(restored.shell().dataset.sidebarCollapsed).toBe("true"); }
  finally { await restored.dispose(); }
});
test("PC에서 접어도 모바일 드로어는 전체 이름을 표시하고 PC 복귀 시 접힘을 유지한다", async () => {
  localStorage.setItem("kor-travel-transport:sidebar-collapsed", "1");
  const { nav, shell, click, dispose } = await mount();
  try {
    await changeMobile(true);
    expect(nav()).toBeNull();
    await click(".mobile-menu-toggle");
    expect(nav().textContent).toContain("교통 지도");
    expect(nav().querySelector('[aria-current="page"]')?.getAttribute("title")).toBeNull();
    await changeMobile(false);
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(shell().dataset.sidebarCollapsed).toBe("true");
    await changeMobile(true);
    expect(nav()).toBeNull();
  } finally { await dispose(); }
});
test("모바일 경로 변경은 드로어를 닫고 새 경로 하나만 활성화한다", async () => {
  mobile = true;
  const { root, nav, click, dispose } = await mount();
  try {
    await click(".mobile-menu-toggle");
    navigation.pathname = "/rail/mapping/variant";
    await act(async () => root.render(<AdminShell><p>다른 본문</p></AdminShell>));
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    await click(".mobile-menu-toggle");
    const selected = nav().querySelectorAll('[aria-current="page"]');
    expect(selected).toHaveLength(1);
    expect(selected[0].getAttribute("href")).toBe("/rail/mapping");
    expect(nav().querySelectorAll('[data-slot="app-menu-link"]')).toHaveLength(19);
  } finally { await dispose(); }
});
test("모바일에서 이미 선택한 링크를 눌러도 메뉴를 닫는다", async () => {
  mobile = true;
  const { nav, click, dispose } = await mount();
  try {
    await click(".mobile-menu-toggle");
    await act(async () => nav().querySelector<HTMLAnchorElement>('[aria-current="page"]')!.click());
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  } finally { await dispose(); }
});
test("브라우저 저장소가 막혀도 PC 메뉴 접기와 링크를 사용할 수 있다", async () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("저장소 차단"); });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("저장소 차단"); });
  const { nav, shell, click, dispose } = await mount();
  try {
    await click(".sidebar-collapse");
    expect(shell().dataset.sidebarCollapsed).toBe("true");
    expect(nav().querySelectorAll('[data-slot="app-menu-link"]')).toHaveLength(19);
  } finally { await dispose(); }
});
