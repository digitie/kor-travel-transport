import { NextRequest } from "next/server";
import { afterEach, describe, expect, it } from "vitest";

import { createSessionValue, SESSION_COOKIE } from "@/lib/session";

import { GET } from "./route";

const saved = {
  release: process.env.TRANSPORT_ADMIN_RELEASE_SHA,
  password: process.env.TRANSPORT_UI_PASSWORD,
  secret: process.env.TRANSPORT_UI_SESSION_SECRET,
};

afterEach(() => {
  process.env.TRANSPORT_ADMIN_RELEASE_SHA = saved.release;
  process.env.TRANSPORT_UI_PASSWORD = saved.password;
  process.env.TRANSPORT_UI_SESSION_SECRET = saved.secret;
});

describe("GET /api/release", () => {
  it("로그인 세션에만 실행 이미지의 release SHA를 제공한다", async () => {
    process.env.TRANSPORT_ADMIN_RELEASE_SHA = "a".repeat(40);
    process.env.TRANSPORT_UI_PASSWORD = "correct";
    process.env.TRANSPORT_UI_SESSION_SECRET = "s".repeat(32);
    const session = await createSessionValue("admin");
    const request = new NextRequest("http://transport.test/api/release", { headers: { cookie: `${SESSION_COOKIE}=${session}` } });

    const response = await GET(request);
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ releaseSha: "a".repeat(40) });
  });

  it("세션이 없으면 release SHA를 노출하지 않는다", async () => {
    const response = await GET(new NextRequest("http://transport.test/api/release"));
    expect(response.status).toBe(401);
  });
});
