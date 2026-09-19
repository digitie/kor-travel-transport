import { NextRequest } from "next/server";

describe("backend proxy route", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllGlobals();
  });

  test("proxies allowed backend requests without storing mobile-stale API responses", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify([{ code: "GMP", name_ko: "Gimpo Airport" }]), {
        headers: {
          "cache-control": "public, max-age=3600",
          "content-type": "application/json",
        },
        status: 200,
      })
    );
    vi.stubGlobal("fetch", fetchMock);
    vi.stubEnv("BACKEND_INTERNAL_URL", "http://test-backend:8000");

    const { GET } = await import("@/app/api/backend/[...path]/route");
    const request = new NextRequest("https://pr.digitie.mywire.org/api/backend/v1/airports", {
      headers: {
        accept: "application/json",
        host: "pr.digitie.mywire.org",
      },
    });
    const response = await GET(request, { params: Promise.resolve({ path: ["v1", "airports"] }) });

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store, max-age=0, must-revalidate");
    expect(response.headers.get("content-type")).toContain("application/json");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://test-backend:8000/v1/airports",
      expect.objectContaining({
        cache: "no-store",
        method: "GET",
      })
    );
  });

  test("returns a stable 502 response when the backend connection fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new Error("connection refused");
    }));
    vi.stubEnv("BACKEND_INTERNAL_URL", "http://test-backend:8000");

    const { GET } = await import("@/app/api/backend/[...path]/route");
    const request = new NextRequest("https://pr.digitie.mywire.org/api/backend/health");
    const response = await GET(request, { params: Promise.resolve({ path: ["health"] }) });

    expect(response.status).toBe(502);
    expect(response.headers.get("content-type")).toBe("application/problem+json");
    expect(response.headers.get("cache-control")).toBe("no-store, max-age=0, must-revalidate");
    expect(await response.json()).toEqual({
      type: "about:blank",
      title: "Bad Gateway",
      status: 502,
      detail: "백엔드에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
      instance: "/api/backend/health",
      code: "backend_unavailable",
    });
  });

  test("does not expose manual collection through the public web proxy", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const { POST } = await import("@/app/api/backend/[...path]/route");
    const request = new NextRequest("https://pr.digitie.mywire.org/api/backend/v1/admin/collect", {
      method: "POST",
    });
    const response = await POST(request, { params: Promise.resolve({ path: ["v1", "admin", "collect"] }) });

    expect(response.status).toBe(404);
    expect(response.headers.get("content-type")).toBe("application/problem+json");
    expect(response.headers.get("cache-control")).toBe("no-store, max-age=0, must-revalidate");
    expect(await response.json()).toEqual({
      type: "about:blank",
      title: "Not Found",
      status: 404,
      detail: "Not found",
      instance: "/api/backend/v1/admin/collect",
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test.each(["airports", "v1/unknown"])("returns a problem document for disallowed GET path %s", async (path) => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const { GET } = await import("@/app/api/backend/[...path]/route");
    const request = new NextRequest(`https://pr.digitie.mywire.org/api/backend/${path}?key=private`);
    const response = await GET(request, { params: Promise.resolve({ path: path.split("/") }) });

    expect(response.status).toBe(404);
    expect(response.headers.get("content-type")).toBe("application/problem+json");
    expect(await response.json()).toEqual({
      type: "about:blank",
      title: "Not Found",
      status: 404,
      detail: "Not found",
      instance: `/api/backend/${path}`,
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test.each([404, 502, 504])("preserves an upstream %s problem response", async (status) => {
    const body = JSON.stringify({
      type: "https://example.com/problems/upstream",
      title: "Upstream problem",
      status,
      detail: "백엔드 오류 상세",
      instance: "/v1/airports",
      code: "upstream_error",
    });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, {
      status,
      headers: { "content-type": "application/problem+json" },
    })));

    const { GET } = await import("@/app/api/backend/[...path]/route");
    const request = new NextRequest("https://pr.digitie.mywire.org/api/backend/v1/airports");
    const response = await GET(request, { params: Promise.resolve({ path: ["v1", "airports"] }) });

    expect(response.status).toBe(status);
    expect(response.headers.get("content-type")).toBe("application/problem+json");
    expect(await response.text()).toBe(body);
  });

  test("preserves an upstream legacy JSON error without wrapping it", async () => {
    const body = JSON.stringify({ detail: "기존 백엔드 오류" });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, {
      status: 502,
      headers: { "content-type": "application/json" },
    })));

    const { GET } = await import("@/app/api/backend/[...path]/route");
    const request = new NextRequest("https://pr.digitie.mywire.org/api/backend/health");
    const response = await GET(request, { params: Promise.resolve({ path: ["health"] }) });

    expect(response.status).toBe(502);
    expect(response.headers.get("content-type")).toBe("application/json");
    expect(await response.text()).toBe(body);
  });

  test("aborts a slow backend request and returns 504", async () => {
    vi.useFakeTimers();
    vi.stubEnv("BACKEND_INTERNAL_URL", "http://test-backend:8000");
    vi.stubEnv("BACKEND_PROXY_TIMEOUT_MS", "1000");
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
        })
      )
    );

    try {
      const { GET } = await import("@/app/api/backend/[...path]/route");
      const request = new NextRequest("https://pr.digitie.mywire.org/api/backend/health");
      const responsePromise = GET(request, { params: Promise.resolve({ path: ["health"] }) });
      await vi.advanceTimersByTimeAsync(1_000);
      const response = await responsePromise;

      expect(response.status).toBe(504);
      expect(response.headers.get("content-type")).toBe("application/problem+json");
      expect(response.headers.get("cache-control")).toBe("no-store, max-age=0, must-revalidate");
      expect(await response.json()).toEqual({
        type: "about:blank",
        title: "Gateway Timeout",
        status: 504,
        detail: "백엔드 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.",
        instance: "/api/backend/health",
        code: "backend_timeout",
      });
    } finally {
      vi.useRealTimers();
    }
  });

  test("allows backup operations to use the longer operation timeout", async () => {
    vi.useFakeTimers();
    vi.stubEnv("BACKEND_INTERNAL_URL", "http://test-backend:8000");
    vi.stubEnv("BACKUP_PROXY_TIMEOUT_MS", "2000");
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) =>
        new Promise<Response>((resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
          setTimeout(() => resolve(new Response("[]", { status: 200 })), 1500);
        })
      )
    );

    try {
      const { GET } = await import("@/app/api/backend/[...path]/route");
      const request = new NextRequest("https://pr.digitie.mywire.org/api/backend/v1/admin/backups");
      const responsePromise = GET(request, { params: Promise.resolve({ path: ["v1", "admin", "backups"] }) });
      await vi.advanceTimersByTimeAsync(1_000);
      await vi.advanceTimersByTimeAsync(500);
      const response = await responsePromise;

      expect(response.status).toBe(200);
    } finally {
      vi.useRealTimers();
    }
  });
});
