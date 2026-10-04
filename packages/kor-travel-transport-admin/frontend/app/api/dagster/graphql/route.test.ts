import { NextRequest } from "next/server";
import { afterEach, expect, test, vi } from "vitest";
const gate = vi.hoisted(() => ({ authenticated: true, origin: true }));
vi.mock("@/lib/auth", () => ({ hasAdminSession: async () => gate.authenticated }));
vi.mock("@/lib/origin", () => ({ isAllowedOrigin: () => gate.origin }));
import { POST } from "./route";

afterEach(() => { gate.authenticated = true; gate.origin = true; vi.unstubAllGlobals(); });
const request = (body: unknown) => new NextRequest("http://localhost/api/dagster/graphql", { method: "POST", body: JSON.stringify(body) });

test.each([[false, true, 401], [true, false, 403]])("인증·Origin 거부는 upstream에 닿지 않는다", async (authenticated, origin, status) => {
  gate.authenticated = authenticated; gate.origin = origin;
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  expect((await POST(request({ operationName: "TransportDagsterOverview" }))).status).toBe(status);
  expect(fetch).not.toHaveBeenCalled();
});

test("원본 GraphQL·scope 조작·큰 본문은 upstream에 닿지 않는다", async () => {
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  expect((await POST(request({ operationName: "TransportDagsterOverview", query: "mutation { terminateRun }" }))).status).toBe(400);
  expect((await POST(request({ operationName: "TransportDagsterRunFailure", variables: { runId: "00000000-0000-0000-0000-000000000001", locationTag: "foreign" } }))).status).toBe(400);
  expect((await POST(request("x".repeat(5000)))).status).toBe(413);
  expect(fetch).not.toHaveBeenCalled();
});

test("이름 붙은 작업은 서버 소유 scope로 전달하고 본문을 읽은 뒤 반환한다", async () => {
  const fetch = vi.fn().mockResolvedValue(Response.json({ data: { ok: true } })); vi.stubGlobal("fetch", fetch);
  const response = await POST(request({ operationName: "TransportDagsterOverview" }));
  const sent = JSON.parse(fetch.mock.calls[0][1].body);
  expect(sent.variables.locationTag).toBe("kor-travel-transport");
  expect(sent.query).toContain('key: "dagster/code_location"');
  expect(await response.json()).toEqual({ data: { ok: true } });
  expect(response.headers.get("cache-control")).toContain("no-store");
});
