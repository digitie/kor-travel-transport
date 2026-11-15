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
  const fixture = { data: { repositoryOrError: { __typename: "Repository", schedules: [] }, runsOrError: { __typename: "Runs", results: [] }, activeRuns: { __typename: "Runs", results: [] } } };
  const fetch = vi.fn().mockResolvedValue(Response.json(fixture)); vi.stubGlobal("fetch", fetch);
  const response = await POST(request({ operationName: "TransportDagsterOverview" }));
  const sent = JSON.parse(fetch.mock.calls[0][1].body);
  expect(sent.variables.locationTag).toBe("kor-travel-transport");
  expect(sent.query).toContain('key: "dagster/code_location"');
  expect(await response.json()).toEqual(fixture);
  expect(response.headers.get("cache-control")).toContain("no-store");
});

test("선택 실패는 예외 chain을 읽되 비공개 원문은 브라우저 전송 전에 제거한다", async () => {
  const secret = "fixture-private-token";
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ data: { runsOrError: { __typename: "Runs", results: [{ eventConnection: {
    cursor: null, hasMore: false, events: [{ __typename: "ExecutionStepFailureEvent", stepKey: "collect_highway_transport", message: secret,
      error: { message: `traffic flow response contains invalid records (received_rows=10, parsed_rows=9, invalid_rows=1) https://example.invalid/?key=${secret}`, className: "KrexParseError", stack: [secret] },
    }],
  } }] } } })));
  const response = await POST(request({ operationName: "TransportDagsterRunFailure", variables: { runId: "00000000-0000-0000-0000-000000000001", cursor: null } }));
  const body = await response.text();
  expect(response.status).toBe(200);
  expect(body).toContain("TRAFFIC_FLOW_INVALID_RECORDS");
  expect(body).toContain("불량 행 수: 1");
  expect(body).not.toContain(secret);
  expect(body).not.toContain("https://");
  expect(body).not.toContain('"error"');
});
