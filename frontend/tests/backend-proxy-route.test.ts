import { NextRequest } from "next/server";
import { createServer } from "node:http";
import { brotliCompressSync, brotliDecompressSync, constants, gunzipSync, gzipSync } from "node:zlib";

describe("backend proxy route", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
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

  test("does not forward compressed Content-Length after fetch decodes JSON", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response('{"items":[1,2,3]}', {
      headers: { "content-type": "application/json", "content-length": "4" },
    })));
    const { GET } = await import("@/app/api/backend/[...path]/route");
    const request = new NextRequest("https://pr.digitie.mywire.org/api/backend/v1/parking/history?limit=3");
    const response = await GET(request, { params: Promise.resolve({ path: ["v1", "parking", "history"] }) });

    expect(response.headers.has("content-length")).toBe(false);
    expect(await response.json()).toEqual({ items: [1, 2, 3] });
  });

  test.each([
    { clientEncoding: "gzip", forwarded: "gzip", responseEncoding: "gzip" },
    { clientEncoding: "br", forwarded: "br", responseEncoding: "br" },
    { clientEncoding: "br, gzip;q=0", forwarded: "br", responseEncoding: "br" },
    { clientEncoding: "br, gzip", forwarded: "br, gzip", responseEncoding: "br" },
  ])("streams $clientEncoding full history without the JSON buffer limit", async ({ clientEncoding, forwarded, responseEncoding }) => {
    const uncompressed = JSON.stringify({ items: ["x".repeat(17 * 1024 * 1024)], next_cursor: null });
    const compressed = responseEncoding === "br" ? brotliCompressSync(uncompressed, {
      params: { [constants.BROTLI_PARAM_QUALITY]: 4 },
    }) : gzipSync(uncompressed);
    let forwardedEncoding: string | undefined;
    const server = createServer((upstreamRequest, response) => {
      forwardedEncoding = upstreamRequest.headers["accept-encoding"];
      response.writeHead(200, {
        "content-type": "application/json",
        "content-encoding": responseEncoding,
        "content-length": compressed.length,
      });
      response.end(compressed);
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    try {
      const address = server.address();
      if (!address || typeof address === "string") throw new Error("missing test server port");
      vi.stubEnv("BACKEND_INTERNAL_URL", `http://127.0.0.1:${address.port}`);
      const { GET } = await import("@/app/api/backend/[...path]/route");
      const request = new NextRequest("https://pr.digitie.mywire.org/api/backend/v1/parking/history?days=30", {
        headers: { "accept-encoding": clientEncoding },
      });
      const response = await GET(request, { params: Promise.resolve({ path: ["v1", "parking", "history"] }) });

      expect(response.status).toBe(200);
      expect(forwardedEncoding).toBe(forwarded);
      expect(response.headers.get("content-encoding")).toBe(responseEncoding);
      expect(response.headers.get("content-length")).toBe(String(compressed.length));
      const payload = Buffer.from(await response.arrayBuffer());
      expect((responseEncoding === "br" ? brotliDecompressSync(payload) : gunzipSync(payload)).toString()).toBe(uncompressed);
    } finally {
      await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    }
  });

  test("does not cut a progressing full-history stream at the ordinary JSON body deadline", async () => {
    vi.stubEnv("BACKEND_PROXY_BODY_TIMEOUT_MS", "1000");
    const server = createServer((_request, response) => {
      response.writeHead(200, { "content-type": "application/json" });
      response.write('{"items":[');
      setTimeout(() => response.end('1],"next_cursor":null}'), 1_100);
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    try {
      const address = server.address();
      if (!address || typeof address === "string") throw new Error("missing test server port");
      vi.stubEnv("BACKEND_INTERNAL_URL", `http://127.0.0.1:${address.port}`);
      const { GET } = await import("@/app/api/backend/[...path]/route");
      const request = new NextRequest("https://pr.digitie.mywire.org/api/backend/v1/parking/history?days=30");
      const response = await GET(request, { params: Promise.resolve({ path: ["v1", "parking", "history"] }) });

      expect(response.status).toBe(200);
      expect(await response.json()).toEqual({ items: [1], next_cursor: null });
    } finally {
      await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    }
  });

  test("waits for a full-history response header beyond the ordinary JSON deadline", async () => {
    vi.stubEnv("BACKEND_PROXY_TIMEOUT_MS", "1000");
    const server = createServer((_request, response) => {
      setTimeout(() => response.end('{"items":[],"next_cursor":null}'), 1_100);
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    try {
      const address = server.address();
      if (!address || typeof address === "string") throw new Error("missing test server port");
      vi.stubEnv("BACKEND_INTERNAL_URL", `http://127.0.0.1:${address.port}`);
      const { GET } = await import("@/app/api/backend/[...path]/route");
      const request = new NextRequest("https://pr.digitie.mywire.org/api/backend/v1/parking/history?days=30");
      const response = await GET(request, { params: Promise.resolve({ path: ["v1", "parking", "history"] }) });

      expect(response.status).toBe(200);
      expect(await response.json()).toEqual({ items: [], next_cursor: null });
    } finally {
      await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    }
  });

  test("bounds simultaneous full-history requests waiting for backend headers", async () => {
    const waitingResponses: import("node:http").ServerResponse[] = [];
    let allStarted!: () => void;
    const started = new Promise<void>((resolve) => { allStarted = resolve; });
    const server = createServer((_request, response) => {
      waitingResponses.push(response);
      if (waitingResponses.length === 8) allStarted();
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    try {
      const address = server.address();
      if (!address || typeof address === "string") throw new Error("missing test server port");
      vi.stubEnv("BACKEND_INTERNAL_URL", `http://127.0.0.1:${address.port}`);
      const { GET } = await import("@/app/api/backend/[...path]/route");
      const makeRequest = () => GET(
        new NextRequest("https://pr.digitie.mywire.org/api/backend/v1/parking/history?days=30"),
        { params: Promise.resolve({ path: ["v1", "parking", "history"] }) },
      );
      const waiting = Array.from({ length: 8 }, makeRequest);
      await started;
      const rejected = await makeRequest();
      expect(rejected.status).toBe(503);
      expect((await rejected.json()).code).toBe("backend_busy");
      waitingResponses.forEach((response) => response.end('{"items":[],"next_cursor":null}'));
      const completed = await Promise.all(waiting);
      expect(completed.every((response) => response.status === 200)).toBe(true);
      await Promise.all(completed.map((response) => response.json()));
    } finally {
      waitingResponses.forEach((response) => { if (!response.writableEnded) response.end(); });
      await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    }
  });

  test("releases full-history header slots when waiting clients abort", async () => {
    const waitingResponses: import("node:http").ServerResponse[] = [];
    let allStarted!: () => void;
    const started = new Promise<void>((resolve) => { allStarted = resolve; });
    const server = createServer((_request, response) => {
      waitingResponses.push(response);
      if (waitingResponses.length === 8) allStarted();
      if (waitingResponses.length === 9) response.end('{"items":[],"next_cursor":null}');
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    try {
      const address = server.address();
      if (!address || typeof address === "string") throw new Error("missing test server port");
      vi.stubEnv("BACKEND_INTERNAL_URL", `http://127.0.0.1:${address.port}`);
      const { GET } = await import("@/app/api/backend/[...path]/route");
      const makeRequest = (signal?: AbortSignal) => GET(
        new NextRequest("https://pr.digitie.mywire.org/api/backend/v1/parking/history?days=30", { signal }),
        { params: Promise.resolve({ path: ["v1", "parking", "history"] }) },
      );
      const controllers = Array.from({ length: 8 }, () => new AbortController());
      const waiting = controllers.map((controller) => makeRequest(controller.signal));
      await started;
      controllers.forEach((controller) => controller.abort());
      await Promise.all(waiting);
      const next = await makeRequest();
      expect(next.status).toBe(200);
      expect(await next.json()).toEqual({ items: [], next_cursor: null });
    } finally {
      waitingResponses.forEach((response) => { if (!response.writableEnded) response.end(); });
      await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    }
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
