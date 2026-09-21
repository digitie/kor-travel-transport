import { afterEach, describe, expect, it, vi } from "vitest";

import { createSessionValue, loginIsConfigured, verifySessionValue } from "./session";

const original = { password: process.env.TRANSPORT_UI_PASSWORD, secret: process.env.TRANSPORT_UI_SESSION_SECRET, user: process.env.TRANSPORT_UI_USER, nodeEnv: process.env.NODE_ENV };

afterEach(() => { process.env.TRANSPORT_UI_PASSWORD = original.password; process.env.TRANSPORT_UI_SESSION_SECRET = original.secret; process.env.TRANSPORT_UI_USER = original.user; Object.assign(process.env, { NODE_ENV: original.nodeEnv }); vi.restoreAllMocks(); });

describe("관리 UI 세션", () => {
  it("서명된 현재 사용자 세션만 승인한다", async () => {
    process.env.TRANSPORT_UI_USER = "operator"; process.env.TRANSPORT_UI_PASSWORD = "password"; process.env.TRANSPORT_UI_SESSION_SECRET = "x".repeat(32);
    const value = await createSessionValue("operator");
    expect(await verifySessionValue(value)).toBe(true);
    expect(await verifySessionValue(`${value}tampered`)).toBe(false);
  });
  it("운영에서 짧은 세션 비밀은 설정 오류로 처리한다", () => {
    Object.assign(process.env, { NODE_ENV: "production" }); process.env.TRANSPORT_UI_PASSWORD = "password"; process.env.TRANSPORT_UI_SESSION_SECRET = "short";
    expect(loginIsConfigured()).toBe(false);
  });
});
