import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createSessionValue } from "@/lib/session";
import { GET, POST } from "./route";

const saved = { password: process.env.TRANSPORT_UI_PASSWORD, secret: process.env.TRANSPORT_UI_SESSION_SECRET };
async function protectedRequest(path: string) { process.env.TRANSPORT_UI_PASSWORD = "password"; process.env.TRANSPORT_UI_SESSION_SECRET = "s".repeat(32); const cookie = await createSessionValue("admin"); return new NextRequest(`http://transport.test/api/transport/${path}`, { headers: { cookie: `kor_travel_transport_admin_session=${cookie}` } }); }

afterEach(() => { process.env.TRANSPORT_UI_PASSWORD = saved.password; process.env.TRANSPORT_UI_SESSION_SECRET = saved.secret; vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

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
  it.each(["dashboard/bootstrap", "dashboard/analytics", "admin/collector-status", "parking/analytics/timeseries"])("주차장 읽기 %s도 인증이 필요하다", async (path) => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}")); vi.stubGlobal("fetch", fetchMock);
    const context = { params: Promise.resolve({ path: path.split("/") }) };
    expect((await GET(new NextRequest(`http://transport.test/api/transport/${path}`), context)).status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
    expect((await GET(await protectedRequest(path), context)).status).toBe(200);
    expect(String(fetchMock.mock.calls[0][0])).toContain(`/v1/${path}`);
  });
});

describe("POST /api/transport/fees/calculate", () => {
  const calculate = { params: Promise.resolve({ path: ["fees", "calculate"] }) };
  async function request(body = "{}", headers: Record<string, string> = {}) {
    const session = await protectedRequest("fees/calculate");
    return new NextRequest(session.url, { method: "POST", headers: { cookie: session.headers.get("cookie")!, origin: "http://transport.test", "content-type": "application/json", ...headers }, body });
  }
  it("세션·origin·경로를 검사하고 요금 계산 외 POST를 중계하지 않는다", async () => {
    vi.stubEnv("TRANSPORT_UI_PUBLIC_ORIGIN", "http://transport.test");
    const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
    expect((await POST(new NextRequest("http://transport.test/api/transport/fees/calculate", { method: "POST", body: "{}" }), calculate)).status).toBe(401);
    expect((await POST(await request(), { params: Promise.resolve({ path: ["admin", "collect"] }) })).status).toBe(404);
    expect((await POST(await request("{}", { origin: "https://foreign.test" }), calculate)).status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
    vi.unstubAllEnvs();
  });
  it("JSON·실제 body·선언 크기를 검사한다", async () => {
    vi.stubEnv("TRANSPORT_UI_PUBLIC_ORIGIN", "http://transport.test");
    const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
    expect((await POST(await request("{}", { "content-type": "text/plain" }), calculate)).status).toBe(415);
    expect((await POST(await request("{broken"), calculate)).status).toBe(400);
    expect((await POST(await request("{}", { "content-length": "4097" }), calculate)).status).toBe(413);
    expect((await POST(await request(JSON.stringify({ value: "x".repeat(5000) })), calculate)).status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
    vi.unstubAllEnvs();
  });
  it("JSON만 기존 /v1/fees/calculate에 전달하고 상태·응답·no-store를 유지한다", async () => {
    vi.stubEnv("TRANSPORT_UI_PUBLIC_ORIGIN", "http://transport.test");
    const payload = { airport_code: "GMP", parking_lot_id: 2, vehicle_size: "small", entry_at: "2026-10-25T00:00:00Z", exit_at: "2026-10-25T06:00:00Z" };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "요금 규칙 없음" }), { status: 422, headers: { "content-type": "application/json" } })); vi.stubGlobal("fetch", fetchMock);
    const response = await POST(await request(JSON.stringify(payload)), calculate);
    expect(response.status).toBe(422); expect(response.headers.get("cache-control")).toBe("no-store, private");
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/v1\/fees\/calculate$/);
    expect(JSON.parse(new TextDecoder().decode(fetchMock.mock.calls[0][1].body))).toEqual(payload);
    expect(await response.json()).toEqual({ detail: "요금 규칙 없음" });
    vi.unstubAllEnvs();
  });
});

describe("새 역·지역 평균 읽기의 인증된 중계",()=>{
 it.each(["transport/fuel/regions","transport/rail/stations","transport/rail/stations/274/timetable"])("%s는 인증 후 GET으로 중계한다",async path=>{
  const fetchMock=vi.fn().mockResolvedValue(new Response('{"items":[]}',{headers:{"content-type":"application/json"}}));vi.stubGlobal("fetch",fetchMock);
  const context={params:Promise.resolve({path:path.split("/")})};
  expect((await GET(new NextRequest(`http://transport.test/api/transport/${path}`),context)).status).toBe(401);
  expect(fetchMock).not.toHaveBeenCalled();
  const response=await GET(await protectedRequest(path),context);
  expect(response.status).toBe(200);expect(String(fetchMock.mock.calls[0][0])).toContain(`/v1/${path}`);
 });
});
