import { NextRequest } from "next/server";
import { afterEach, describe, expect, it } from "vitest";

import { POST } from "./route";

const savedOrigin = process.env.TRANSPORT_UI_PUBLIC_ORIGIN;
afterEach(() => {
  if (savedOrigin === undefined) delete process.env.TRANSPORT_UI_PUBLIC_ORIGIN;
  else process.env.TRANSPORT_UI_PUBLIC_ORIGIN = savedOrigin;
});

describe("POST /api/auth/logout", () => {
  it("허용 origin의 세션을 지우고 현재 HTTPS origin을 보존하는 상대 redirect를 반환한다", async () => {
    process.env.TRANSPORT_UI_PUBLIC_ORIGIN = "https://transport.test";
    const response = await POST(new NextRequest("http://127.0.0.1:12305/api/auth/logout", {
      method: "POST",
      headers: { origin: "https://transport.test" },
    }));

    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("/login");
    expect(response.headers.get("set-cookie")).toContain("Max-Age=0");
  });
});
