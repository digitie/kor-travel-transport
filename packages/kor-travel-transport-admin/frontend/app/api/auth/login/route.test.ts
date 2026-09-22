import { NextRequest } from "next/server";
import { afterEach, describe, expect, it } from "vitest";

import { POST } from "./route";

const saved = { password: process.env.TRANSPORT_UI_PASSWORD, secret: process.env.TRANSPORT_UI_SESSION_SECRET, origin: process.env.TRANSPORT_UI_PUBLIC_ORIGIN };
function request(body: object) { return new NextRequest("http://transport.test/api/auth/login", { method: "POST", headers: { origin: "http://transport.test", "content-type": "application/json" }, body: JSON.stringify(body) }); }

afterEach(() => { process.env.TRANSPORT_UI_PASSWORD = saved.password; process.env.TRANSPORT_UI_SESSION_SECRET = saved.secret; process.env.TRANSPORT_UI_PUBLIC_ORIGIN = saved.origin; });

describe("POST /api/auth/login", () => {
  it("origin, credentials, local redirect, HttpOnly session을 함께 확인한다", async () => {
    process.env.TRANSPORT_UI_PASSWORD = "correct"; process.env.TRANSPORT_UI_SESSION_SECRET = "s".repeat(32); process.env.TRANSPORT_UI_PUBLIC_ORIGIN = "http://transport.test";
    const response = await POST(request({ username: "admin", password: "correct", next: "https://bad.example" }));
    expect(response.status).toBe(200); expect((await response.json()).next).toBe("/");
    expect(response.headers.get("set-cookie")).toContain("HttpOnly");
  });
  it("다른 origin과 잘못된 암호를 거부한다", async () => {
    process.env.TRANSPORT_UI_PASSWORD = "correct"; process.env.TRANSPORT_UI_SESSION_SECRET = "s".repeat(32); process.env.TRANSPORT_UI_PUBLIC_ORIGIN = "http://transport.test";
    expect((await POST(new NextRequest("http://transport.test/api/auth/login", { method: "POST", headers: { origin: "https://bad.example", "content-type": "application/json" }, body: "{}" }))).status).toBe(403);
    expect((await POST(request({ username: "admin", password: "wrong" }))).status).toBe(401);
  });
});
