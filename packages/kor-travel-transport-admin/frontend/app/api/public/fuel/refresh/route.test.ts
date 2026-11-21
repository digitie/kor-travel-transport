import { NextRequest } from "next/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { POST } from "./route";
import { proxy } from "@/proxy";

const origin = "https://fuel.example";
const endpoint = `${origin}/api/public/fuel/refresh`;
const fetchUpstream = vi.fn();

function post({ from = origin, body = '{"station_id":12}', contentType = "application/json" } = {}) {
  return new NextRequest(endpoint, {
    method: "POST",
    headers: { origin: from, "content-type": contentType, authorization: "Bearer untrusted", cookie: "browser=untrusted" },
    body,
  });
}

beforeEach(() => {
  vi.stubEnv("TRANSPORT_UI_MODE", "fuel");
  vi.stubEnv("FUEL_REFRESH_INTERNAL_URL", "http://fuel-internal.test:9999/alternate-path");
  vi.stubEnv("FUEL_REFRESH_INTERNAL_TOKEN", "fixture-only-fuel-manual-refresh-token");
  vi.stubEnv("FUEL_REFRESH_PUBLIC_ORIGIN", origin);
  fetchUpstream.mockReset();
  vi.stubGlobal("fetch", fetchUpstream);
});

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

it("공개 Fuel에서 수동 갱신 경로만 POST를 허용한다", () => {
  expect(proxy(post()).headers.get("x-middleware-next")).toBe("1");
  expect(proxy(new NextRequest(`${origin}/api/public/fuel/places`, { method: "POST" })).status).toBe(405);
});

it("지정한 내부 경로에 서버 전용 토큰과 JSON만 전달한다", async () => {
  const output = { results: [{ station_id: 12, status: "updated" }] };
  fetchUpstream.mockResolvedValue(Response.json(output));
  const response = await POST(post());
  expect(response.status).toBe(200);
  expect(await response.json()).toEqual(output);
  expect(fetchUpstream).toHaveBeenCalledTimes(1);
  const [target, config] = fetchUpstream.mock.calls[0];
  expect(String(target)).toBe("http://fuel-internal.test:9999/v1/internal/fuel/refresh");
  expect(config).toMatchObject({ method: "POST", body: '{"station_id":12}', credentials: "omit", redirect: "error" });
  expect(config.headers).toEqual({
    authorization: "Bearer fixture-only-fuel-manual-refresh-token", "content-type": "application/json", accept: "application/json",
  });
});

it("시 단위 브라우저 조회가 끝난 뒤 내부 정리까지 기다린다", async () => {
  vi.useFakeTimers();
  const timeout = vi.spyOn(AbortSignal, "timeout").mockImplementation((milliseconds) => {
    const controller = new AbortController();
    setTimeout(() => controller.abort(), milliseconds);
    return controller.signal;
  });
  try {
    fetchUpstream.mockImplementation((_target, { signal }: { signal: AbortSignal }) =>
      new Promise<Response>((resolve, reject) => {
        const timer = setTimeout(() => resolve(Response.json({ results: [{ station_id: 12, status: "updated" }] })), 55_000);
        signal.addEventListener("abort", () => {
          clearTimeout(timer);
          reject(signal.reason);
        }, { once: true });
      }));
    const response = POST(post());
    await vi.advanceTimersByTimeAsync(55_000);
    expect((await response).status).toBe(200);
  } finally {
    timeout.mockRestore();
    vi.useRealTimers();
  }
});

it("다른 출처, 큰 본문과 설정하지 않은 기능은 업스트림을 호출하지 않는다", async () => {
  expect((await POST(post({ from: "https://other.example" }))).status).toBe(403);
  expect((await POST(post({ body: JSON.stringify({ value: "a".repeat(4097) }) }))).status).toBe(400);
  expect((await POST(post({ contentType: "text/plain" }))).status).toBe(415);
  vi.stubEnv("FUEL_REFRESH_INTERNAL_TOKEN", "");
  expect((await POST(post())).status).toBe(503);
  expect(fetchUpstream).not.toHaveBeenCalled();
});

it("호출 한도 응답에서는 재시도 시각을 전달하고 공급자 메시지를 숨긴다", async () => {
  fetchUpstream.mockResolvedValue(Response.json({ detail: "upstream private" }, { status: 429, headers: { "retry-after": "30" } }));
  const response = await POST(post());
  expect(response.status).toBe(429);
  expect(response.headers.get("retry-after")).toBe("30");
  expect(await response.json()).toEqual({ detail: "잠시 뒤 다시 시도해 주세요." });
});
