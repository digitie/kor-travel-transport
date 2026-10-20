import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createSessionValue } from "@/lib/session";
import { GET, POST } from "./route";

const saved = { password: process.env.TRANSPORT_UI_PASSWORD, secret: process.env.TRANSPORT_UI_SESSION_SECRET,
  origin: process.env.TRANSPORT_UI_PUBLIC_ORIGIN, token: process.env.TRANSPORT_ADMIN_WRITE_TOKEN };
const mapping = { operator_code: "O1", line_code: "L1", station_code: "S1", rail_station_identity_key: "line|L1|역", note: "공식 코드와 역번호 대조" };
async function request(method: "GET" | "POST", { origin = "http://transport.test", authorized = true, payload = { expected_revision: "a".repeat(64), mappings: [mapping] }, contentType = "application/json" } = {}) {
  const cookie = authorized ? await createSessionValue("admin") : "";
  return new NextRequest("http://transport.test/api/admin/rail-station-mappings", { method,
    headers: { origin, "content-type": contentType, cookie: `kor_travel_transport_admin_session=${cookie}` },
    ...(method === "POST" ? { body: JSON.stringify(payload) } : {}),
  });
}
function setup() { process.env.TRANSPORT_UI_PASSWORD = "password"; process.env.TRANSPORT_UI_SESSION_SECRET = "s".repeat(32);
  process.env.TRANSPORT_UI_PUBLIC_ORIGIN = "http://transport.test"; }
afterEach(() => { process.env.TRANSPORT_UI_PASSWORD = saved.password; process.env.TRANSPORT_UI_SESSION_SECRET = saved.secret;
  process.env.TRANSPORT_UI_PUBLIC_ORIGIN = saved.origin; process.env.TRANSPORT_ADMIN_WRITE_TOKEN = saved.token; vi.unstubAllGlobals(); });

describe("/api/admin/rail-station-mappings", () => {
  it("GET은 관리자 세션과 내부 전용 토큰을 요구하고 캐시하지 않는다", async () => {
    setup(); process.env.TRANSPORT_ADMIN_WRITE_TOKEN = "w".repeat(40);
    expect((await GET(await request("GET", { authorized: false }))).status).toBe(401);
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ stations: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const response = await GET(await request("GET"));
    expect(response.status).toBe(200); expect(response.headers.get("cache-control")).toBe("no-store, private");
    expect(String(fetchMock.mock.calls[0][0])).toContain("/v1/transport/admin/rail-station-mappings");
    expect(fetchMock.mock.calls[0][1].headers["x-transport-admin-token"]).toBe("w".repeat(40));
  });

  it("POST는 origin과 매핑 형식 검증 후 수동 변경만 내부 API에 전달한다", async () => {
    setup(); process.env.TRANSPORT_ADMIN_WRITE_TOKEN = "w".repeat(40);
    expect((await POST(await request("POST", { origin: "https://elsewhere.test" }))).status).toBe(403);
    expect((await POST(await request("POST", { contentType: "text/plain" }))).status).toBe(415);
    expect((await POST(await request("POST", { payload: { expected_revision: "bad", mappings: [] } }))).status).toBe(422);
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 })); vi.stubGlobal("fetch", fetchMock);
    const response = await POST(await request("POST"));
    expect(response.status).toBe(200);
    expect(fetchMock.mock.calls[0][1].body).toBe(JSON.stringify({ expected_revision: "a".repeat(64), mappings: [mapping] }));
  });
});
