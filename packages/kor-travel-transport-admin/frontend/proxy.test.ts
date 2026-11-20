import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { proxy } from "./proxy";

function request(path: string, method = "GET") {
  return new NextRequest(`https://fuel.digitie.mywire.org${path}`, { method, headers: { cookie: "kor_travel_transport_admin_session=old-admin-cookie" } });
}
afterEach(() => vi.unstubAllEnvs());
describe("공개 유가 전용 실행", () => {
  it("루트는 공개 지도로 rewrite하며 지도 자산과 BFF만 허용한다", () => {
    vi.stubEnv("TRANSPORT_UI_MODE", "fuel");
    expect(proxy(request("/?product=B027")).headers.get("x-middleware-rewrite")).toBe("https://fuel.digitie.mywire.org/public/fuel?product=B027");
    for (const path of ["/public/fuel", "/api/public/fuel/places", "/_next/static/test.js", "/maplibre/maplibre-gl-worker.mjs", "/fuel-brands/sk.gif"]) {
      expect(proxy(request(path)).headers.get("x-middleware-next")).toBe("1");
    }
  });
  it("관리자 cookie가 있어도 관리자·인증·범용 API와 쓰기를 열지 않는다", () => {
    vi.stubEnv("TRANSPORT_UI_MODE", "fuel");
    for (const path of ["/login", "/fuel", "/api/auth/login", "/api/transport/transport/fuel/stations", "/api/admin/place-locations"]) expect(proxy(request(path)).status).toBe(404);
    expect(proxy(request("/api/public/fuel/places", "POST")).status).toBe(405);
    expect(proxy(request("/", "POST")).status).toBe(405);
  });
  it("기존 관리자 실행의 로그인 전환은 유지한다", () => {
    vi.stubEnv("TRANSPORT_UI_MODE", "admin");
    const result = proxy(new NextRequest("https://transport.test/fuel"));
    expect(result.status).toBe(307);
    expect(result.headers.get("location")).toContain("/login?next=");
  });
});
