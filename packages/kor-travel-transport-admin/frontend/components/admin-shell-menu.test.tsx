// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

const navigation = vi.hoisted(() => ({ pathname: "/map" }));
vi.mock("next/navigation", () => ({ usePathname: () => navigation.pathname }));
vi.mock("next/link", () => ({ default: ({ href, children, ...props }: { href: string; children: ReactNode }) => <a href={href} {...props}>{children}</a> }));
import { AdminShell } from "./admin-shell";

beforeEach(() => { Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); navigation.pathname = "/map"; });
afterEach(() => vi.unstubAllGlobals());

async function mount() {
  const container = document.createElement("div"); document.body.append(container); const root = createRoot(container);
  await act(async () => root.render(<AdminShell><p>본문</p></AdminShell>));
  const button = container.querySelector<HTMLButtonElement>(".mobile-menu-button")!;
  const menu = () => document.getElementById(button.getAttribute("aria-controls")!)!;
  return { container, root, button, menu };
}

test("모바일 메뉴 버튼은 상태와 무관한 라벨이고 열림은 aria-expanded로 전달한다", async () => {
  const { container, root, button, menu } = await mount();
  try {
    expect(button.getAttribute("aria-label")).toBe("주요 메뉴");
    expect(button.getAttribute("aria-expanded")).toBe("false");
    await act(async () => button.click());
    expect(button.getAttribute("aria-expanded")).toBe("true");
    expect(menu().classList.contains("is-open")).toBe(true);
    expect(button.getAttribute("aria-label")).not.toContain("열기");
  } finally { await act(async () => root.unmount()); container.remove(); }
});

test("열린 메뉴는 Escape로 닫고 초점을 메뉴 버튼으로 되돌린다", async () => {
  const { container, root, button, menu } = await mount();
  try {
    await act(async () => button.click());
    const link = menu().querySelector<HTMLAnchorElement>("a")!;
    link.focus();
    await act(async () => link.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(menu().classList.contains("is-open")).toBe(false);
    expect(document.activeElement).toBe(button);
  } finally { await act(async () => root.unmount()); container.remove(); }
});

test("메뉴 링크 밖의 탐색으로 경로가 바뀌면 열린 메뉴를 닫는다", async () => {
  const { container, root, button, menu } = await mount();
  try {
    await act(async () => button.click());
    expect(menu().classList.contains("is-open")).toBe(true);
    navigation.pathname = "/fuel";  // 뒤로 가기 등으로 경로만 바뀐다.
    await act(async () => root.render(<AdminShell><p>다른 본문</p></AdminShell>));
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(menu().classList.contains("is-open")).toBe(false);
  } finally { await act(async () => root.unmount()); container.remove(); }
});
