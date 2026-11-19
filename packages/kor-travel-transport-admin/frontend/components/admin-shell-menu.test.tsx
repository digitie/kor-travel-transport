// @vitest-environment jsdom
import { act, type ComponentProps } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

const navigation = vi.hoisted(() => ({ pathname: "/map" }));
vi.mock("next/navigation", () => ({ usePathname: () => navigation.pathname }));
vi.mock("next/link", () => ({ default: ({ href, children, ...props }: ComponentProps<"a">) => <a href={href} {...props} onClick={(event) => { props.onClick?.(event); event.preventDefault(); }}>{children}</a> }));
import { AdminShell } from "./admin-shell";
import { PageHeader } from "./page-header";

// 공통 AdminShell: 데스크톱 세로 레일, 모바일 메뉴 버튼과 focus-trapped drawer.
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
  await act(async () => root.render(<AdminShell><PageHeader title="교통 지도" description="현재 교통 자료" /><input aria-label="본문 입력" /></AdminShell>));
  const nav = () => container.querySelector<HTMLElement>('nav[aria-label="주요 메뉴"]')!;
  const menu = () => container.querySelector<HTMLElement>('[data-slot="admin-shell-rail"]')!;
  const button = (name: string) => [...container.querySelectorAll<HTMLButtonElement>("button")].find((item) => item.getAttribute("aria-label") === name || item.textContent?.trim() === name);
  const dispose = async () => { await act(async () => { root.unmount(); await new Promise((resolve) => setTimeout(resolve, 0)); }); container.remove(); };
  return { container, root, nav, menu, button, dispose };
}

test("닫힌 셸은 기존19개 경로와 단일 공통 제목을 유지한다", async () => {
  const { nav, dispose } = await mount();
  try {
    expect(nav().querySelectorAll('[data-slot="app-menu-link"]')).toHaveLength(19);
    for (const href of ["/parking-lots", "/rail/timetable", "/parking"]) expect(nav().querySelector(`a[href="${href}"]`)).not.toBeNull();
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(document.querySelectorAll("h1")).toHaveLength(1);
    expect(document.querySelector("h1")?.textContent).toBe("교통 - 교통 지도");
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
    expect(["1", "true"]).toContain(localStorage.getItem("kor-travel-transport:sidebar-collapsed"));
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
    expect(menu().dataset.collapsed).not.toBe("true");
  } finally { await dispose(); }
});

test("모바일 drawer는19경로를 보이고 이동 뒤 닫으며 본문 입력을 보존한다", async () => {
  const { container, button, dispose } = await mount();
  try {
    const input = container.querySelector<HTMLInputElement>('input[aria-label="본문 입력"]')!;
    input.value = "진행 중 입력";
    await act(async () => button("메뉴 열기")!.click());
    const drawer = document.querySelector<HTMLElement>('[role="dialog"]')!;
    expect(drawer).not.toBeNull();
    expect(drawer.querySelectorAll('[data-slot="app-menu-link"]')).toHaveLength(19);
    await act(async () => drawer.querySelector<HTMLAnchorElement>('a[href="/parking-lots"]')!.click());
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(container.querySelector('input[aria-label="본문 입력"]')).toBe(input);
    expect(input.value).toBe("진행 중 입력");
  } finally { await dispose(); }
});

test("모바일 drawer의 Escape는 메뉴를 닫고 여는 버튼으로 focus를 돌린다", async () => {
  const { button, dispose } = await mount();
  try {
    const trigger = button("메뉴 열기")!;
    trigger.focus();
    await act(async () => trigger.click());
    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
    await act(async () => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(trigger);
  } finally { await dispose(); }
});
