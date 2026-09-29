import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createSessionValue } from "@/lib/session";
import { POST } from "./route";

const saved = { password: process.env.TRANSPORT_UI_PASSWORD, secret: process.env.TRANSPORT_UI_SESSION_SECRET,
  origin: process.env.TRANSPORT_UI_PUBLIC_ORIGIN, token: process.env.TRANSPORT_ADMIN_WRITE_TOKEN };
const body = { kind: "ferry_port", id: 3, source: "data_go_kr_maritime", provider_id: "P3",
  expected_name: "시험항", expected_city_name: null,
  expected_latitude: null, expected_longitude: null, expected_location_source: null, expected_manual_revision: null,
  latitude: 34.2, longitude: 127.1, note: "공식 주소와 지도 대조" };
async function request(origin = "http://transport.test", payload: object = body, authorized = true) {
  const cookie = authorized ? await createSessionValue("admin") : "";
  return new NextRequest("http://transport.test/api/admin/place-locations", { method: "POST",
    headers: { origin, "content-type": "application/json", cookie: `kor_travel_transport_admin_session=${cookie}` },
    body: JSON.stringify(payload) });
}
afterEach(() => { process.env.TRANSPORT_UI_PASSWORD = saved.password; process.env.TRANSPORT_UI_SESSION_SECRET = saved.secret;
  process.env.TRANSPORT_UI_PUBLIC_ORIGIN = saved.origin; process.env.TRANSPORT_ADMIN_WRITE_TOKEN = saved.token; vi.unstubAllGlobals(); });

describe("POST /api/admin/place-locations", () => {
  it("세션·origin·전용 토큰 없이 쓰지 못한다", async () => {
    process.env.TRANSPORT_UI_PASSWORD = "password"; process.env.TRANSPORT_UI_SESSION_SECRET = "s".repeat(32);
    process.env.TRANSPORT_UI_PUBLIC_ORIGIN = "http://transport.test";
    expect((await POST(await request(undefined, body, false))).status).toBe(401);
    expect((await POST(await request("https://elsewhere.test"))).status).toBe(403);
    expect((await POST(await request())).status).toBe(503);
  });
  it("공식 장소 좌표만 내부 backend로 전달하고 공개 GET proxy를 쓰지 않는다", async () => {
    process.env.TRANSPORT_UI_PASSWORD = "password"; process.env.TRANSPORT_UI_SESSION_SECRET = "s".repeat(32);
    process.env.TRANSPORT_UI_PUBLIC_ORIGIN = "http://transport.test"; process.env.TRANSPORT_ADMIN_WRITE_TOKEN = "w".repeat(40);
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...body, location_source: "admin_manual" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    expect((await POST(await request(undefined, { ...body, kind: "fuel_station" }))).status).toBe(422);
    const response = await POST(await request());
    expect(response.status).toBe(200); expect(response.headers.get("cache-control")).toBe("no-store, private");
    expect(String(fetchMock.mock.calls[0][0])).toContain("/v1/transport/admin/place-locations");
    expect(fetchMock.mock.calls[0][1].headers["x-transport-admin-token"]).toBe("w".repeat(40));
  });
});
