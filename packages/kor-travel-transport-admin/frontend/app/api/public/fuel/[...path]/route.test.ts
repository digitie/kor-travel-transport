import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GET } from "./route";

const context = (path: string) => ({ params: Promise.resolve({ path: path.split("/") }) });
const request = (path: string) => new NextRequest(`https://fuel.digitie.mywire.org/api/public/fuel/${path}`, {
  headers: { cookie: "admin=secret", authorization: "Bearer private", "if-none-match": '"fuel-etag"', "x-forwarded-host": "other.test" },
});
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
describe("공개 유가 BFF", () => {
  it("관리자 모드·허용 밖 경로에서는 upstream을 호출하지 않는다", async () => {
    const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
    vi.stubEnv("TRANSPORT_UI_MODE", "admin");
    expect((await GET(request("places"), context("places"))).status).toBe(404);
    vi.stubEnv("TRANSPORT_UI_MODE", "fuel");
    for (const path of ["admin/collect", "../features/places", "regions", "stations/0/price-history", "https://other.test/"]) {
      expect((await GET(request(path), context(path))).status).toBe(404);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it("고정된 fuel gateway 경로·반복 query·ETag만 전달한다", async () => {
    vi.stubEnv("TRANSPORT_UI_MODE", "fuel"); vi.stubEnv("BACKEND_INTERNAL_URL", "http://127.0.0.1:12307");
    const fetchMock = vi.fn().mockResolvedValue(new Response('{"items":[]}', { status: 200, headers: { "content-type": "application/json", etag: '"fuel-etag"', "set-cookie": "must-not-leak=1" } }));
    vi.stubGlobal("fetch", fetchMock);
    const result = await GET(request("places?product_codes=B027&product_codes=D047&zoom=10"), context("places"));
    const [target, init] = fetchMock.mock.calls[0];
    expect(String(target)).toBe("http://127.0.0.1:12307/v1/transport/fuel/places?product_codes=B027&product_codes=D047&zoom=10");
    expect([...init.headers]).toEqual([["accept", "application/json"], ["accept-encoding", "identity"], ["if-none-match", '"fuel-etag"']]);
    expect(init.credentials).toBe("omit"); expect(init.redirect).toBe("error");
    expect(result.headers.get("set-cookie")).toBeNull(); expect(result.headers.get("etag")).toBe('"fuel-etag"');
    expect(await result.json()).toEqual({ items: [] });
  });
  it("시군구 가격 분포는 고정 경로로만 전달한다", async () => {
    vi.stubEnv("TRANSPORT_UI_MODE", "fuel"); vi.stubEnv("BACKEND_INTERNAL_URL", "http://127.0.0.1:12307");
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    await GET(request("price-distribution?station_id=7&product_code=B027"), context("price-distribution"));
    expect(String(fetchMock.mock.calls[0][0])).toBe("http://127.0.0.1:12307/v1/transport/fuel/price-distribution?station_id=7&product_code=B027");
    for (const path of ["price-distribution/x", "price-distributions"]) {
      expect((await GET(request(path), context(path))).status).toBe(404);
    }
  });
  it("304는 본문 없이, upstream 실패·재시도 안내는 원래 상태로 돌려준다", async () => {
    vi.stubEnv("TRANSPORT_UI_MODE", "fuel");
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response(null, { status: 304, headers: { etag: '"fuel-etag"' } }))
      .mockResolvedValueOnce(new Response('{"detail":"잠시 후 재시도"}', { status: 503, headers: { "retry-after": "30" } }));
    vi.stubGlobal("fetch", fetchMock);
    const unchanged = await GET(request("places"), context("places"));
    expect(unchanged.status).toBe(304); expect(await unchanged.text()).toBe("");
    const unavailable = await GET(request("statistics"), context("statistics"));
    expect(unavailable.status).toBe(503); expect(unavailable.headers.get("retry-after")).toBe("30");
  });
  it("본문 수신 오류와 크기 초과는 부분 성공으로 보내지 않는다", async () => {
    vi.stubEnv("TRANSPORT_UI_MODE", "fuel");
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response(new ReadableStream({ start(controller) { controller.error(new Error("body failed")); } })))
      .mockResolvedValueOnce(new Response(new Uint8Array(16 * 1024 * 1024 + 1)));
    vi.stubGlobal("fetch", fetchMock);
    expect((await GET(request("places"), context("places"))).status).toBe(502);
    expect((await GET(request("places"), context("places"))).status).toBe(502);
  });
});
