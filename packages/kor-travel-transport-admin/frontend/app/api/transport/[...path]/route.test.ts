import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createSessionValue } from "@/lib/session";
import { GET } from "./route";

const saved = { password: process.env.TRANSPORT_UI_PASSWORD, secret: process.env.TRANSPORT_UI_SESSION_SECRET };
async function protectedRequest(path: string) { process.env.TRANSPORT_UI_PASSWORD = "password"; process.env.TRANSPORT_UI_SESSION_SECRET = "s".repeat(32); const cookie = await createSessionValue("admin"); return new NextRequest(`http://transport.test/api/transport/${path}`, { headers: { cookie: `kor_travel_transport_admin_session=${cookie}` } }); }

afterEach(() => { process.env.TRANSPORT_UI_PASSWORD = saved.password; process.env.TRANSPORT_UI_SESSION_SECRET = saved.secret; vi.unstubAllGlobals(); });

describe("GET /api/transport/[...path]", () => {
  it("세션 없는 요청은 401로, 비허용 path는 404로 막는다", async () => {
    expect((await GET(new NextRequest("http://transport.test/api/transport/transport/statistics"), { params: Promise.resolve({ path: ["transport", "statistics"] }) })).status).toBe(401);
    expect((await GET(await protectedRequest("admin/collect"), { params: Promise.resolve({ path: ["admin", "collect"] }) })).status).toBe(404);
  });
  it("허용한 읽기 path의 query만 backend /v1에 전달한다", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [] }), { status: 429, headers: { "content-type": "application/json", "retry-after": "30" } })); vi.stubGlobal("fetch", fetchMock);
    const request = await protectedRequest("transport/highways/traffic?route_no=1&route_no=10");
    const response = await GET(request, { params: Promise.resolve({ path: ["transport", "highways", "traffic"] }) });
    expect(response.status).toBe(429); expect(response.headers.get("retry-after")).toBe("30"); expect(String(fetchMock.mock.calls[0][0])).toContain("/v1/transport/highways/traffic?route_no=1&route_no=10");
  });
});
