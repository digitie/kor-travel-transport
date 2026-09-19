import { NextRequest } from "next/server";

describe("프록시 응답 본문 계약", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.useFakeTimers();
    vi.stubEnv("BACKEND_INTERNAL_URL", "http://test-backend:8000");
    vi.stubEnv("BACKEND_PROXY_TIMEOUT_MS", "1000");
    vi.stubEnv("BACKEND_PROXY_BODY_TIMEOUT_MS", "1000");
    vi.stubEnv("BACKUP_PROXY_TIMEOUT_MS", "1000");
    vi.stubEnv("BACKUP_PROXY_BODY_TIMEOUT_MS", "2000");
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  test.each([
    { contentType: "application/json", partial: false, path: "health", status: 200, timeoutMs: 1000 },
    { contentType: "Application/JSON; charset=utf-8", partial: true, path: "health", status: 200, timeoutMs: 1000 },
    { contentType: "application/problem+json", partial: true, path: "health", status: 502, timeoutMs: 1000 },
    { contentType: "application/json", partial: true, path: "v1/admin/backups", status: 200, timeoutMs: 2000 },
    { contentType: "application/problem+json", partial: true, path: "v1/admin/backups/test.dump", status: 404, timeoutMs: 2000 },
  ])("$path의 $contentType 본문이 멈추면 기존 $status 대신 504를 반환한다", async ({ contentType, partial, path, status, timeoutMs }) => {
    // 취소 자체가 끝나지 않는 소스도 오류 응답을 지연시키면 안 된다.
    const cancel = vi.fn(() => new Promise<void>(() => undefined));
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        if (partial) {
          controller.enqueue(new TextEncoder().encode('{"data":'));
        }
      },
      cancel,
    });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, {
      status,
      headers: { "content-type": contentType, "content-length": "999", "content-disposition": "attachment" },
    })));
    const { GET } = await import("@/app/api/backend/[...path]/route");
    const pending = GET(new NextRequest(`https://proxy.test/api/backend/${path}`), {
      params: Promise.resolve({ path: path.split("/") }),
    });
    const settled = vi.fn();
    void pending.then(settled);

    await vi.advanceTimersByTimeAsync(timeoutMs - 1);
    expect(settled).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    const response = await pending;

    expect(response.status).toBe(504);
    expect(response.headers.get("content-type")).toBe("application/problem+json");
    expect(response.headers.get("content-length")).toBeNull();
    expect(response.headers.get("content-disposition")).toBeNull();
    expect(await response.json()).toEqual({
      type: "about:blank",
      title: "Gateway Timeout",
      status: 504,
      detail: "백엔드 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.",
      instance: `/api/backend/${path}`,
      code: "backend_timeout",
    });
    expect(cancel).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  test("본문 수신 기한 안의 JSON은 헤더 대기 기한을 지나도 바이트와 상태를 그대로 전달한다", async () => {
    vi.stubEnv("BACKEND_PROXY_BODY_TIMEOUT_MS", "2000");
    const text = '{ "detail": "백엔드 오류", "status": 502 }';
    const bytes = new TextEncoder().encode(text);
    let source: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({ start(controller) { source = controller; } });
    let signal: AbortSignal | null | undefined;
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
      signal = init?.signal;
      signal?.addEventListener("abort", () => source.error(new DOMException("Aborted", "AbortError")));
      return new Response(body, {
        status: 502,
        headers: { "content-type": "application/problem+json", "content-length": String(bytes.length) },
      });
    }));
    const { GET } = await import("@/app/api/backend/[...path]/route");
    const pending = GET(new NextRequest("https://proxy.test/api/backend/health"), {
      params: Promise.resolve({ path: ["health"] }),
    });
    const settled = vi.fn();
    void pending.then(settled);
    await vi.advanceTimersByTimeAsync(1000);
    expect(signal?.aborted).toBe(false);
    // 멀티바이트 문자가 청크 경계에 걸려도 재인코딩 없이 전달한다.
    source!.enqueue(bytes.slice(0, 15));
    await vi.advanceTimersByTimeAsync(500);
    expect(settled).not.toHaveBeenCalled();
    source!.enqueue(bytes.slice(15));
    source!.close();
    const response = await pending;

    expect(response.status).toBe(502);
    expect(response.headers.get("content-type")).toBe("application/problem+json");
    expect(response.headers.get("content-length")).toBe(String(bytes.length));
    expect(await response.text()).toBe(text);
    expect(vi.getTimerCount()).toBe(0);
  });

  test("조금씩 도착하는 JSON도 전체 본문 수신 기한을 연장하지 않는다", async () => {
    let source: ReadableStreamDefaultController<Uint8Array>;
    const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({ start(controller) { source = controller; }, cancel });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, {
      headers: { "content-type": "application/json" },
    })));
    const { GET } = await import("@/app/api/backend/[...path]/route");
    const pending = GET(new NextRequest("https://proxy.test/api/backend/health"), {
      params: Promise.resolve({ path: ["health"] }),
    });
    await vi.advanceTimersByTimeAsync(400);
    source!.enqueue(new TextEncoder().encode("["));
    await vi.advanceTimersByTimeAsync(400);
    source!.enqueue(new TextEncoder().encode("1,"));
    await vi.advanceTimersByTimeAsync(200);

    expect((await pending).status).toBe(504);
    expect(cancel).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  test.each([undefined, "1"])("Content-Length=%s라도 실제 JSON 크기가 16 MiB를 넘으면 502와 취소를 반환한다", async (contentLength) => {
    const cancel = vi.fn();
    const chunk = new Uint8Array(1024 * 1024);
    const body = new ReadableStream<Uint8Array>({ pull(controller) { controller.enqueue(chunk); }, cancel });
    const headers = new Headers({ "content-type": "application/json" });
    if (contentLength) {
      headers.set("content-length", contentLength);
    }
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { headers })));
    const { GET } = await import("@/app/api/backend/[...path]/route");
    const response = await GET(new NextRequest("https://proxy.test/api/backend/health"), {
      params: Promise.resolve({ path: ["health"] }),
    });

    expect(response.status).toBe(502);
    expect(response.headers.get("content-type")).toBe("application/problem+json");
    expect(response.headers.get("content-length")).toBeNull();
    expect(await response.json()).toMatchObject({ status: 502, code: "backend_unavailable" });
    expect(cancel).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  test("정확히 16 MiB인 JSON은 허용한다", async () => {
    const bytes = new Uint8Array(16 * 1024 * 1024).fill(32);
    bytes[0] = 91;
    bytes[bytes.length - 1] = 93;
    vi.stubGlobal("fetch", vi.fn(async () => new Response(bytes, {
      headers: { "content-type": "application/json" },
    })));
    const { GET } = await import("@/app/api/backend/[...path]/route");
    const response = await GET(new NextRequest("https://proxy.test/api/backend/health"), {
      params: Promise.resolve({ path: ["health"] }),
    });

    expect(response.status).toBe(200);
    expect((await response.arrayBuffer()).byteLength).toBe(bytes.byteLength);
    expect(vi.getTimerCount()).toBe(0);
  });

  test("JSON 본문 수신 오류는 전송 시작 전에 502 문제 응답으로 변환한다", async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(new TextEncoder().encode("[")); },
      pull(controller) { controller.error(new Error("upstream body failed")); },
    });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, {
      headers: { "content-type": "application/json" },
    })));
    const { GET } = await import("@/app/api/backend/[...path]/route");
    const response = await GET(new NextRequest("https://proxy.test/api/backend/health"), {
      params: Promise.resolve({ path: ["health"] }),
    });

    expect(response.status).toBe(502);
    expect(response.headers.get("content-type")).toBe("application/problem+json");
    expect(await response.json()).toMatchObject({ status: 502, code: "backend_unavailable" });
    expect(vi.getTimerCount()).toBe(0);
  });

  test("본문 없는 응답은 원래 상태를 유지한다", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, {
      status: 204,
      headers: { "content-type": "application/json" },
    })));
    const { GET } = await import("@/app/api/backend/[...path]/route");
    const response = await GET(new NextRequest("https://proxy.test/api/backend/health"), {
      params: Promise.resolve({ path: ["health"] }),
    });

    expect(response.status).toBe(204);
    expect(response.body).toBeNull();
    expect(vi.getTimerCount()).toBe(0);
  });

  test("백업 파일은 크기 제한 없이 즉시 스트리밍하고 이후 timeout은 본문 읽기 오류로 남는다", async () => {
    const cancel = vi.fn();
    const chunk = new Uint8Array(17 * 1024 * 1024);
    const body = new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(chunk); },
      cancel,
    });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, {
      headers: {
        "content-type": "application/octet-stream",
        "content-disposition": 'attachment; filename="test.dump"',
      },
    })));
    const { GET } = await import("@/app/api/backend/[...path]/route");
    const response = await GET(new NextRequest("https://proxy.test/api/backend/v1/admin/backups/test.dump"), {
      params: Promise.resolve({ path: ["v1", "admin", "backups", "test.dump"] }),
    });
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("application/octet-stream");
    expect(response.headers.get("content-disposition")).toBe('attachment; filename="test.dump"');
    const reader = response.body!.getReader();
    expect((await reader.read()).value?.byteLength).toBe(chunk.byteLength);
    const bodyFailure = expect(reader.read()).rejects.toThrow("backend response body timeout");
    await vi.advanceTimersByTimeAsync(2000);
    await bodyFailure;
    expect(response.status).toBe(200);
    expect(cancel).toHaveBeenCalledOnce();
    reader.releaseLock();
    expect(vi.getTimerCount()).toBe(0);
  });
});
