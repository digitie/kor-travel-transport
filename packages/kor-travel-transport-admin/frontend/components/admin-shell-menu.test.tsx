// @vitest-environment jsdom
import { act, type ComponentProps } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

const navigation = vi.hoisted(() => ({ pathname: "/map" }));
vi.mock("next/navigation", () => ({ usePathname: () => navigation.pathname }));
vi.mock("next/link", () => ({ default: ({ href, children, ...props }: ComponentProps<"a">) => <a href={href} {...props} onClick={(event) => { props.onClick?.(event); event.preventDefault(); }}>{children}</a> }));
import { AdminShell } from "./admin-shell";

// map 공용 셸: lg 이상은 접을 수 있는 세로 레일, 미만은 상단 메뉴 띠. 드로어(dialog)는 쓰지 않는다.
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  navigation.pathname = "/map";
  localStorage.clear();
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} }));
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); });

async function mount() {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(<AdminShell><input aria-label="본문 입력" /></AdminShell>));
  const nav = () => container.querySelector<HTMLElement>('nav[aria-label="주요 메뉴"]')!;
  const menu = () => container.querySelector<HTMLElement>("[data-collapsed]")!;
  const button = (name: string) => [...container.querySelectorAll<HTMLButtonElement>("button")].find((item) => item.getAttribute("aria-label") === name || item.textContent?.trim() === name);
  const dispose = async () => { await act(async () => { root.unmount(); await new Promise((resolve) => setTimeout(resolve, 0)); }); container.remove(); };
  return { container, root, nav, menu, button, dispose };
}

test("주요 메뉴는 기존 19개 경로를 모두 보이고 드로어 없이 렌더링한다", async () => {
  const { nav, dispose } = await mount();
  try {
    expect(nav().querySelectorAll('[data-slot="app-menu-link"]')).toHaveLength(19);
    for (const href of ["/parking-lots", "/rail/timetable", "/parking"]) expect(nav().querySelector(`a[href="${href}"]`)).not.toBeNull();
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

test("레일 접힘 선택을 저장하고 다시 열 때 복구한다", async () => {
  const { menu, button, dispose } = await mount();
  try {
    await act(async () => button("좌측 메뉴 접기")!.click());
    expect(menu().dataset.collapsed).toBe("true");
    expect(localStorage.getItem("kor-travel-transport:sidebar-collapsed")).toBe("1");
    expect(button("좌측 메뉴 펼치기")).toBeDefined();
  } finally { await dispose(); }
  const restored = await mount();
  try { expect(restored.menu().dataset.collapsed).toBe("true"); }
  finally { await restored.dispose(); }
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

test("브라우저 저장소가 막혀도 레일 접기와 링크를 사용할 수 있다", async () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("저장소 차단"); });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("저장소 차단"); });
  const { nav, menu, button, dispose } = await mount();
  try {
    await act(async () => button("좌측 메뉴 접기")!.click());
    expect(menu().dataset.collapsed).toBe("true");
    expect(nav().querySelectorAll('[data-slot="app-menu-link"]')).toHaveLength(19);
    await act(async () => button("좌측 메뉴 펼치기")!.click());
    expect(menu().dataset.collapsed).toBe("false");
  } finally { await dispose(); }
});
