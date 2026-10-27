// @vitest-environment jsdom
import { act } from "react";
import { hydrateRoot, type Root } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LoginForm } from "./LoginForm";

let root: Root | undefined;
let host: HTMLDivElement | undefined;
afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  root = undefined;
  host?.remove();
  host = undefined;
  vi.unstubAllGlobals();
});

function server() {
  host = document.createElement("div");
  host.innerHTML = renderToString(<LoginForm nextPath="/map" />);
  document.body.append(host);
  return { host, form: host.querySelector("form")!, username: host.querySelector<HTMLInputElement>("[name=username]")!,
    password: host.querySelector<HTMLInputElement>("[name=password]")!, button: host.querySelector<HTMLButtonElement>("button[type=submit]")! };
}

describe("정규 공통 로그인 산출물 채택", () => {
  it("SSR HTML은 hydration 전 입력과 submit을 닫아 현재 /login으로 기본 제출하지 않는다", () => {
    const { form, username, password, button } = server();
    const native = vi.fn((event: Event) => event.preventDefault());
    form.addEventListener("submit", native);
    password.value = "example";
    expect(username.disabled).toBe(true);
    expect(password.disabled).toBe(true);
    expect(button.disabled).toBe(true);
    expect(button.getAttribute("aria-disabled")).toBe("true");
    button.click();
    expect(native).not.toHaveBeenCalled();
  });

  it("hydration 뒤 실제 앱 callback은 auth JSON만 1회 제출하고 pending·실패 재시도를 유지한다", async () => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    let finish!: (response: Response) => void;
    const fetch = vi.fn(() => new Promise<Response>(resolve => { finish = resolve; }));
    vi.stubGlobal("fetch", fetch);
    const { host: container, username, password, button } = server();
    let nativeSubmits = 0;
    const observe = (event: Event) => { if (!event.defaultPrevented) { nativeSubmits += 1; event.preventDefault(); } };
    document.addEventListener("submit", observe);
    try {
      await act(async () => { root = hydrateRoot(container, <LoginForm nextPath="/map" />); });
      expect(username.disabled).toBe(false);
      expect(password.disabled).toBe(false);
      expect(button.disabled).toBe(false);
      password.value = "example";
      await act(async () => { button.click(); button.click(); });
      expect(fetch).toHaveBeenCalledTimes(1);
      const [path, request] = fetch.mock.calls[0] as unknown as [string, RequestInit];
      expect(path).toBe("/api/auth/login");
      expect(request.method).toBe("POST");
      expect(request.headers).toEqual({ "content-type": "application/json" });
      expect(JSON.parse(request.body as string)).toEqual({ username: "admin", password: "example", next: "/map" });
      expect(password.readOnly).toBe(true);
      expect(button.disabled).toBe(false);
      expect(button.getAttribute("aria-disabled")).toBe("true");
      await act(async () => { finish(new Response("{}", { status: 401 })); });
      expect(password.value).toBe("");
      expect(container.textContent).toContain("아이디와 비밀번호를 확인하고 다시 시도해 주세요.");
      expect(button.getAttribute("aria-disabled")).toBe("false");
      password.value = "retry";
      await act(async () => { button.click(); });
      expect(fetch).toHaveBeenCalledTimes(2);
      await act(async () => { finish(new Response("{}", { status: 401 })); });
      expect(nativeSubmits).toBe(0);
    } finally { document.removeEventListener("submit", observe); }
  });

  it.each([
    [429, "로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요."],
    [503, "로그인 설정을 확인할 수 없습니다. 관리자에게 문의해 주세요."],
    [403, "허용되지 않은 요청입니다. 접속 경로를 확인해 주세요."],
  ])("%i 응답은 비밀번호 오류가 아니라 Common 상태 문구를 보인다", async (status, message) => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status })));
    const { host: container, password, button } = server();
    await act(async () => { root = hydrateRoot(container, <LoginForm nextPath="/map" />); });
    password.value = "example";
    await act(async () => { button.click(); });
    expect(container.textContent).toContain(message);
    expect(container.textContent).not.toContain("아이디와 비밀번호를 확인하고 다시 시도해 주세요.");
  });
});
