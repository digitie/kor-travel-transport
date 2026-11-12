import { NextRequest } from "next/server";
import { afterEach, expect, test, vi } from "vitest";
import { createSessionValue } from "@/lib/session";
import { GET } from "./route";
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
async function authenticated(path: string) {
 vi.stubEnv("TRANSPORT_UI_USER", "fixture-admin");
 vi.stubEnv("TRANSPORT_UI_PASSWORD", "fixture-only-password");
 vi.stubEnv("TRANSPORT_UI_SESSION_SECRET", "fixture-session-secret-32-characters-long");
 const session = await createSessionValue("fixture-admin");
 return new NextRequest(`http://transport.test/api/transport/${path}`, { headers: { cookie: `kor_travel_transport_admin_session=${session}` } });
}
test.each(["transport/parking-lots?limit=100&q=수지%20%26%20중앙&cursor=a%2Fb%2B%3D", "transport/parking-lots/12", "transport/rail/stations", "transport/rail/stations/274/timetable?day_code=7"])('%s는 인증된 읽기만 같은 query로 중계한다', async path => {
 const context = {params: Promise.resolve({path: path.split("?")[0].split("/")})};
 const upstream = vi.fn().mockResolvedValue(new Response('{"items":[]}', {headers: {"content-type":"application/json"}})); vi.stubGlobal("fetch", upstream);
 const unauthenticated = await GET(new NextRequest(`http://transport.test/api/transport/${path}`), context);
 expect(unauthenticated.status).toBe(401);expect(upstream).not.toHaveBeenCalled();
 const response = await GET(await authenticated(path), context);expect(response.status).toBe(200);
 expect(upstream).toHaveBeenCalledTimes(1);
 const sent = new URL(String(upstream.mock.calls[0][0]));const wanted = new URL(`http://fixture/v1/${path}`);
 expect(sent.pathname).toBe(wanted.pathname);expect([...sent.searchParams]).toEqual([...wanted.searchParams]);
 expect(response.headers.get("cache-control")).toBe("no-store, private");
});
test.each(["transport/parking-lots/0", "transport/parking-lots/admin", "transport/rail/stations/0/timetable", "transport/rail/stations/274/delete", "transport/admin/collect"])('%s는 새 읽기 허용목록에 섞이지 않는다', async path => {
 const upstream = vi.fn();vi.stubGlobal("fetch", upstream);
 expect((await GET(await authenticated(path), {params:Promise.resolve({path:path.split("/")})})).status).toBe(404);
 expect(upstream).not.toHaveBeenCalled();
});
