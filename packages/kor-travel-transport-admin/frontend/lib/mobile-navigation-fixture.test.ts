import { afterEach, expect, test, vi } from "vitest";
import type { BrowserContext, Page } from "@playwright/test";
import { openIsolatedMenuPage, requireLoopbackOrigin } from "../e2e/mobile-navigation-fixture";

afterEach(() => vi.unstubAllEnvs());

function fakePage() {
  const addCookies = vi.fn<BrowserContext["addCookies"]>().mockResolvedValue(undefined);
  const dispose = vi.fn<() => Promise<void>>().mockResolvedValue(undefined);
  const route = vi.fn<Page["route"]>().mockResolvedValue({
    dispose,
    [Symbol.asyncDispose]: dispose,
  });
  const goto = vi.fn<Page["goto"]>().mockResolvedValue(null);
  const context = vi.fn(() => ({ addCookies }));
  return { page: { context, route, goto } as unknown as Page, addCookies, route, goto, context };
}

for (const env of [undefined, "http://127.0.0.1:12305"]) {
  test("원격 caller는 E2E 환경변수가 안전해도 부작용 전에 거부한다 " + String(env), async () => {
    vi.stubEnv("E2E_BASE_URL", env);
    const fake = fakePage();
    await expect(openIsolatedMenuPage(fake.page, "https://menu-guard.invalid")).rejects.toThrow("loopback");
    expect(fake.context).not.toHaveBeenCalled();
    expect(fake.addCookies).not.toHaveBeenCalled();
    expect(fake.route).not.toHaveBeenCalled();
    expect(fake.goto).not.toHaveBeenCalled();
  });
}

test.each([
  undefined, "", "file://localhost/fixture", "data:text/html,fixture",
  "http://localhost.example.invalid", "http://127.0.0.1.example.invalid",
  "http://user:fixture@localhost:12305",
])("잘못된 caller 주소 %s는 모의 인증·route·탐색 전에 거부한다", async (baseURL) => {
  const fake = fakePage();
  await expect(openIsolatedMenuPage(fake.page, baseURL)).rejects.toThrow("loopback");
  expect(fake.context).not.toHaveBeenCalled();
  expect(fake.addCookies).not.toHaveBeenCalled();
  expect(fake.route).not.toHaveBeenCalled();
  expect(fake.goto).not.toHaveBeenCalled();
});

test.each(["http://127.0.0.1:12305", "https://localhost:3456", "http://[::1]:12305"])(
  "검증한 실제 caller %s에만 쿠키·API 모의 응답·절대 경로를 결박한다", async (baseURL) => {
    vi.stubEnv("E2E_BASE_URL", "https://ignored-environment.invalid");
    const fake = fakePage();
    await openIsolatedMenuPage(fake.page, baseURL);
    const origin = requireLoopbackOrigin(baseURL);
    expect(fake.addCookies).toHaveBeenCalledTimes(1);
    expect(fake.addCookies.mock.calls[0][0]).toEqual([expect.objectContaining({ url: origin })]);
    expect(fake.route).toHaveBeenCalledTimes(2);
    expect(fake.goto).toHaveBeenCalledWith(origin + "/fuel");
  },
);

test.each(["https://menu-guard.invalid/fuel", "//menu-guard.invalid/fuel", "http://user:fixture@localhost:12305/fuel", "blob:http://localhost:12305/fixture"])(
  "모의 경로 %s도 origin 검사 후에만 사용할 수 있다", async (path) => {
    const fake = fakePage();
    await expect(openIsolatedMenuPage(fake.page, "http://localhost:12305", path)).rejects.toThrow("origin");
    expect(fake.context).not.toHaveBeenCalled();
    expect(fake.addCookies).not.toHaveBeenCalled();
    expect(fake.route).not.toHaveBeenCalled();
    expect(fake.goto).not.toHaveBeenCalled();
  },
);
