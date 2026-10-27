import { NextRequest } from "next/server";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { createSessionValue } from "@/lib/session";
import { GET, POST } from "./route";
const saved = { ...process.env };
const payload = { expected_revision: "a".repeat(64), candidate_revision: "b".repeat(64) };
async function request(method: string, value: unknown = payload, { authorized = true, origin = "http://transport.test", contentType = "application/json", raw = false } = {}) {
  const cookie = authorized ? await createSessionValue("admin") : "";
  return new NextRequest("http://transport.test/api/admin/rail-station-mappings/automatic", { method, headers: { origin, "content-type": contentType, cookie: `kor_travel_transport_admin_session=${cookie}` }, ...(method === "POST" ? { body: raw ? value as string : JSON.stringify(value) } : {}) });
}
beforeEach(() => { process.env.TRANSPORT_UI_PASSWORD = "password"; process.env.TRANSPORT_UI_SESSION_SECRET = "s".repeat(32); process.env.TRANSPORT_UI_PUBLIC_ORIGIN = "http://transport.test"; process.env.TRANSPORT_ADMIN_WRITE_TOKEN = "w".repeat(40); });
afterEach(() => { for (const key of ["TRANSPORT_UI_PASSWORD", "TRANSPORT_UI_SESSION_SECRET", "TRANSPORT_UI_PUBLIC_ORIGIN", "TRANSPORT_ADMIN_WRITE_TOKEN"]) { if (saved[key] === undefined) delete process.env[key]; else process.env[key] = saved[key]; } vi.unstubAllGlobals(); });
test("GET/POST는 세션 없이 upstream에 접근하지 않는다", async () => {
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  expect((await GET(await request("GET", null, { authorized: false }))).status).toBe(401);
  expect((await POST(await request("POST", payload, { authorized: false }))).status).toBe(401); expect(fetch).not.toHaveBeenCalled();
});
test("미리보기는 내부토큰으로 자동 경로만 GET하고 private no-store다", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response('{"can_apply":true}', { status: 200 })); vi.stubGlobal("fetch", fetch);
  const result = await GET(await request("GET")); expect(result.status).toBe(200); expect(result.headers.get("cache-control")).toBe("no-store, private");
  expect(String(fetch.mock.calls[0][0])).toContain("/v1/transport/admin/rail-station-mappings/automatic"); expect(fetch.mock.calls[0][1].headers["x-transport-admin-token"]).toBe("w".repeat(40)); expect(fetch.mock.calls[0][1].method).toBe("GET");
});
test("POST는 두 revision만 전송하며 수동배열/note 등 추가필드를 거절한다", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response("{}")); vi.stubGlobal("fetch", fetch);
  for (const value of [{ ...payload, mappings: [] }, { ...payload, note: "raw" }, { expected_revision: payload.expected_revision }, { ...payload, candidate_revision: "bad" }, [], null]) expect((await POST(await request("POST", value))).status).toBe(422);
  expect(fetch).not.toHaveBeenCalled(); expect((await POST(await request("POST"))).status).toBe(200); expect(fetch.mock.calls[0][1].body).toBe(JSON.stringify(payload));
});
test("origin/JSON/본문 크기/문법을 upstream 전에 차단한다", async () => {
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  expect((await POST(await request("POST", payload, { origin: "https://other.test" }))).status).toBe(403);
  expect((await POST(await request("POST", payload, { contentType: "text/plain" }))).status).toBe(415);
  expect((await POST(await request("POST", "x".repeat(2049), { raw: true }))).status).toBe(413);
  expect((await POST(await request("POST", "{", { raw: true }))).status).toBe(422); expect(fetch).not.toHaveBeenCalled();
});
test("409/503은 상태와오류를 유지하고 캐시하지 않는다", async () => {
  for (const status of [409, 503]) { vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "새 미리보기 필요" }), { status })));
    const result = await POST(await request("POST")); expect(result.status).toBe(status); expect(result.headers.get("cache-control")).toBe("no-store, private"); expect(await result.json()).toEqual({ detail: "새 미리보기 필요" }); }
});
test("미설정 토큰503과 전송실패502를 연결0으로 바꾸지 않는다", async () => {
  const fetch = vi.fn().mockRejectedValue(new Error("offline")); vi.stubGlobal("fetch", fetch);
  process.env.TRANSPORT_ADMIN_WRITE_TOKEN = "short"; expect((await GET(await request("GET"))).status).toBe(503); expect(fetch).not.toHaveBeenCalled();
  process.env.TRANSPORT_ADMIN_WRITE_TOKEN = "w".repeat(40); expect((await GET(await request("GET"))).status).toBe(502);
});
