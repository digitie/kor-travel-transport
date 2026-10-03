import { NextRequest } from "next/server";

// 2026-10-02 공개 백업 노출 사고(docs/adr/012-*.md): 공개 웹 앱 프록시는 관리 경로를 어떤
// 메서드·인코딩·대소문자·점 세그먼트 변형으로도 백엔드에 중계하지 않아야 한다.
// `segments`는 Next가 catch-all params로 넘기는 디코드된 세그먼트다.
const DENIED: { url: string; segments: string[] }[] = [
  { url: "v1/admin/backups", segments: ["v1", "admin", "backups"] },
  { url: "v1/admin/backups/", segments: ["v1", "admin", "backups", ""] },
  { url: "v1/admin/backups/restore", segments: ["v1", "admin", "backups", "restore"] },
  { url: "v1/admin/backups/kor-travel-transport-20261002T000000Z.dump", segments: ["v1", "admin", "backups", "kor-travel-transport-20261002T000000Z.dump"] },
  { url: "v1/admin/back%75ps", segments: ["v1", "admin", "backups"] },
  { url: "v1/admin/back%75ps", segments: ["v1", "admin", "back%75ps"] },
  { url: "v1/admin%2Fbackups", segments: ["v1", "admin/backups"] },
  { url: "v1/admin%2fbackups%2frestore", segments: ["v1", "admin/backups/restore"] },
  { url: "v1/Admin/Backups", segments: ["v1", "Admin", "Backups"] },
  { url: "v1/ADMIN/BACKUPS/x.dump", segments: ["v1", "ADMIN", "BACKUPS", "x.dump"] },
  { url: "v1/transport/../admin/backups", segments: ["v1", "transport", "..", "admin", "backups"] },
  { url: "v1/parking/./../admin/backups", segments: ["v1", "parking", ".", "..", "admin", "backups"] },
  { url: "v1/transport/..%2Fadmin%2Fbackups", segments: ["v1", "transport", "../admin/backups"] },
  { url: "v1/transport/..%5Cadmin%5Cbackups", segments: ["v1", "transport", "..\\admin\\backups"] },
  { url: "v1/transport/admin/backups", segments: ["v1", "transport", "admin", "backups"] },
  { url: "v1/admin/collect", segments: ["v1", "admin", "collect"] },
  // 관리자 BFF 전용 좌표 보정 경로(/v1/transport/admin/*)도 공개 프록시가 중계하지 않는다.
  { url: "v1/transport/admin/place-locations", segments: ["v1", "transport", "admin", "place-locations"] },
  { url: "v1/transport/admin/place-locations/capability", segments: ["v1", "transport", "admin", "place-locations", "capability"] },
  { url: "v1/Transport/Admin/place-locations/capability", segments: ["v1", "Transport", "Admin", "place-locations", "capability"] },
  { url: "v1/admin/collector-status/../backups", segments: ["v1", "admin", "collector-status", "..", "backups"] },
  { url: "%2E%2E/v1/admin/backups", segments: ["..", "v1", "admin", "backups"] },
];

describe("public backend proxy refuses admin operations", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("BACKEND_INTERNAL_URL", "http://test-backend:8000");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  for (const method of ["GET", "POST"] as const) {
    test.each(DENIED)(`${method} $url → 404 without an upstream call`, async ({ url, segments }) => {
      const fetchMock = vi.fn(async () => new Response("PGDMP", { status: 200 }));
      vi.stubGlobal("fetch", fetchMock);
      const route = await import("@/app/api/backend/[...path]/route");
      const handler = method === "GET" ? route.GET : route.POST;
      const request = new NextRequest(`https://pr.digitie.mywire.org/api/backend/${url}`, {
        method,
        ...(method === "POST" ? { body: "x", headers: { "content-type": "application/octet-stream" } } : {}),
      });

      const response = await handler(request, { params: Promise.resolve({ path: segments }) });

      expect(response.status).toBe(404);
      expect(fetchMock).not.toHaveBeenCalled();
    });
  }

  test("still proxies the public read-only collector status", async () => {
    const fetchMock = vi.fn(async () => Response.json({ scheduler_enabled: true }));
    vi.stubGlobal("fetch", fetchMock);
    const { GET } = await import("@/app/api/backend/[...path]/route");
    const response = await GET(
      new NextRequest("https://pr.digitie.mywire.org/api/backend/v1/admin/collector-status"),
      { params: Promise.resolve({ path: ["v1", "admin", "collector-status"] }) },
    );

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledWith("http://test-backend:8000/v1/admin/collector-status", expect.anything());
  });

  test("encodes forwarded segments so a decoded separator cannot change the upstream path", async () => {
    const fetchMock = vi.fn(async () => Response.json([]));
    vi.stubGlobal("fetch", fetchMock);
    const { GET } = await import("@/app/api/backend/[...path]/route");
    await GET(
      new NextRequest("https://pr.digitie.mywire.org/api/backend/v1/transport/ports/a%20b/timetable"),
      { params: Promise.resolve({ path: ["v1", "transport", "ports", "a b", "timetable"] }) },
    );

    expect(fetchMock).toHaveBeenCalledWith("http://test-backend:8000/v1/transport/ports/a%20b/timetable", expect.anything());
  });
});
