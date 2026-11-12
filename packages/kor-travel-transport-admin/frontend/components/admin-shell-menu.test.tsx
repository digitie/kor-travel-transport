// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

const navigation = vi.hoisted(() => ({ pathname: "/map" }));
vi.mock("next/navigation", () => ({ usePathname: () => navigation.pathname }));
vi.mock("next/link", () => ({ default: ({ href, children, ...props }: { href: string; children: ReactNode }) => <a href={href} {...props}>{children}</a> }));
import { AdminShell } from "./admin-shell";

const viewport = { mobile: true, reducedMotion: false };
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  navigation.pathname = "/map";
  viewport.mobile = true;
  viewport.reducedMotion = false;
  localStorage.clear();
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("prefers-reduced-motion") ? viewport.reducedMotion : viewport.mobile,
  }));
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); });

async function mount() {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(<AdminShell><p>본문</p></AdminShell>));
  const nav = () => container.querySelector<HTMLElement>('nav[aria-label="주요 메뉴"]')!;
  const shell = () => container.querySelector<HTMLElement>(".transport-shell")!;
  const dispose = async () => { await act(async () => root.unmount()); container.remove(); };
  return { container, root, nav, shell, dispose };
}

test("공통 메뉴의 19개 링크는 개별 팝업 버튼 없이 항상 내비게이션에 있다", async () => {
  const { container, nav, dispose } = await mount();
  try {
    expect(nav().querySelectorAll('[data-slot="app-menu-link"]')).toHaveLength(19);
    expect(container.querySelector(".mobile-menu-button")).toBeNull();
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(nav().querySelector('a[href="/parking-lots"]')).not.toBeNull();
    expect(nav().querySelector('a[href="/rail/timetable"]')).not.toBeNull();
  } finally { await dispose(); }
});

test("데스크톱 접힘 상태는 저장하고 아이콘 링크의 접근 가능한 이름과 title을 유지한다", async () => {
  const { container, nav, shell, dispose } = await mount();
  try {
    const toggle = container.querySelector<HTMLButtonElement>(".sidebar-collapse")!;
    await act(async () => toggle.click());
    expect(shell().dataset.sidebarCollapsed).toBe("true");
    expect(localStorage.getItem("kor-travel-transport:sidebar-collapsed")).toBe("1");
    expect(toggle.getAttribute("aria-label")).toBe("좌측 메뉴 펼치기");
    const current = nav().querySelector<HTMLAnchorElement>('[aria-current="page"]')!;
    expect(current.getAttribute("aria-label")).toBe("교통 지도");
    expect(current.title).toBe("교통 지도");
    await act(async () => toggle.click());
    expect(shell().dataset.sidebarCollapsed).toBe("false");
    expect(localStorage.getItem("kor-travel-transport:sidebar-collapsed")).toBe("0");
  } finally { await dispose(); }
});

test("새로 열어도 저장한 데스크톱 접힘 선택을 복구하고 전체 메뉴를 유지한다", async () => {
  localStorage.setItem("kor-travel-transport:sidebar-collapsed", "1");
  const { nav, shell, dispose } = await mount();
  try {
    expect(shell().dataset.sidebarCollapsed).toBe("true");
    expect(nav().querySelectorAll('[data-slot="app-menu-link"]')).toHaveLength(19);
  } finally { await dispose(); }
});

test("경로가 바뀌면 가장 구체적인 공통 메뉴 하나만 활성화한다", async () => {
  const { root, nav, dispose } = await mount();
  try {
    navigation.pathname = "/rail/mapping/variant";
    await act(async () => root.render(<AdminShell><p>다른 본문</p></AdminShell>));
    const selected = nav().querySelectorAll('[aria-current="page"]');
    expect(selected).toHaveLength(1);
    expect(selected[0].getAttribute("href")).toBe("/rail/mapping");
    expect(nav().querySelectorAll('[data-slot="app-menu-link"]')).toHaveLength(19);
  } finally { await dispose(); }
});

test("좁은 화면의 활성 항목은 reduced-motion에 맞춰 수평 중앙으로 스크롤한다", async () => {
  const { nav, dispose } = await mount();
  try {
    const current = nav().querySelector<HTMLElement>('[aria-current="page"]')!;
    const scroll = vi.fn();
    current.scrollIntoView = scroll;
    viewport.reducedMotion = true;
    await act(async () => { window.dispatchEvent(new Event("resize")); });
    expect(scroll).toHaveBeenLastCalledWith({ block: "nearest", inline: "center", behavior: "auto" });
    viewport.reducedMotion = false;
    await act(async () => { window.dispatchEvent(new Event("resize")); });
    expect(scroll).toHaveBeenLastCalledWith({ block: "nearest", inline: "center", behavior: "smooth" });
    viewport.mobile = false;
    scroll.mockClear();
    await act(async () => { window.dispatchEvent(new Event("resize")); });
    expect(scroll).not.toHaveBeenCalled();
  } finally { await dispose(); }
});

test("브라우저 저장소가 막혀도 메뉴 접기와 링크를 사용할 수 있다", async () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("저장소 차단"); });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("저장소 차단"); });
  const { container, nav, shell, dispose } = await mount();
  try {
    await act(async () => container.querySelector<HTMLButtonElement>(".sidebar-collapse")!.click());
    expect(shell().dataset.sidebarCollapsed).toBe("true");
    expect(nav().querySelectorAll('[data-slot="app-menu-link"]')).toHaveLength(19);
  } finally { await dispose(); }
});
