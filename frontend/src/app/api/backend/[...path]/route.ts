import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ path?: string[] }>;
};

const BACKEND_INTERNAL_URL = (process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000").replace(/\/$/, "");
const BACKEND_PROXY_TIMEOUT_MS = Math.max(1_000, Number(process.env.BACKEND_PROXY_TIMEOUT_MS ?? 10_000) || 10_000);
const BACKEND_PROXY_BODY_TIMEOUT_MS = Math.max(
  1_000,
  Number(process.env.BACKEND_PROXY_BODY_TIMEOUT_MS ?? BACKEND_PROXY_TIMEOUT_MS) || BACKEND_PROXY_TIMEOUT_MS
);
const BACKUP_PROXY_TIMEOUT_MS = Math.max(1_000, Number(process.env.BACKUP_PROXY_TIMEOUT_MS ?? 900_000) || 900_000);
const BACKUP_PROXY_BODY_TIMEOUT_MS = Math.max(
  1_000,
  Number(process.env.BACKUP_PROXY_BODY_TIMEOUT_MS ?? BACKUP_PROXY_TIMEOUT_MS) || BACKUP_PROXY_TIMEOUT_MS
);
const FORWARDED_REQUEST_HEADERS = new Set(["accept", "content-type"]);
const FORWARDED_RESPONSE_HEADERS = new Set([
  "cache-control",
  "content-disposition",
  "content-length",
  "content-type",
  "expires",
  "pragma",
  "permissions-policy",
  "referrer-policy",
  "strict-transport-security",
  "x-content-type-options",
  "x-frame-options",
]);

function isAllowedBackendRequest(path: string, method: string): boolean {
  // `/health` stays unversioned (ADR-005); everything else lives under `/v1`.
  if (path === "health" && method === "GET") {
    return true;
  }
  if (!path.startsWith("v1/")) {
    return false;
  }
  const versioned = path.slice("v1/".length);
  if (versioned === "airports" && method === "GET") {
    return true;
  }
  if (versioned.startsWith("parking/") && method === "GET") {
    return true;
  }
  if (versioned.startsWith("holidays/") && method === "GET") {
    return true;
  }
  if (versioned.startsWith("transport/") && method === "GET") {
    return true;
  }
  if (versioned === "flights/status" && method === "GET") {
    return true;
  }
  if (versioned === "fees/calculate" && method === "POST") {
    return true;
  }
  if (versioned === "admin/collector-status" && method === "GET") {
    return true;
  }
  if ((versioned === "dashboard/bootstrap" || versioned === "dashboard/analytics") && method === "GET") {
    return true;
  }
  if (versioned === "admin/backups" && (method === "GET" || method === "POST")) {
    return true;
  }
  if (versioned === "admin/backups/restore" && method === "POST") {
    return true;
  }
  if (/^admin\/backups\/[^/]+$/.test(versioned) && method === "GET") {
    return true;
  }
  return false;
}

function buildForwardHeaders(request: NextRequest): Headers {
  const headers = new Headers();

  for (const [key, value] of request.headers.entries()) {
    if (FORWARDED_REQUEST_HEADERS.has(key.toLowerCase())) {
      headers.set(key, value);
    }
  }

  headers.set("x-forwarded-host", request.headers.get("host") ?? "");
  headers.set("x-forwarded-proto", request.headers.get("x-forwarded-proto") ?? request.nextUrl.protocol.replace(":", ""));
  return headers;
}

function buildResponseHeaders(upstreamResponse: Response): Headers {
  const headers = new Headers();

  for (const [key, value] of upstreamResponse.headers.entries()) {
    if (FORWARDED_RESPONSE_HEADERS.has(key.toLowerCase())) {
      headers.set(key, value);
    }
  }

  headers.set("cache-control", "no-store, max-age=0, must-revalidate");
  return headers;
}

function buildProxyErrorResponse(status: 502 | 504, detail: string): Response {
  return Response.json(
    { detail, code: status === 504 ? "backend_timeout" : "backend_unavailable" },
    {
      status,
      headers: { "cache-control": "no-store, max-age=0, must-revalidate" },
    }
  );
}

function streamWithReadTimeout(
  body: ReadableStream<Uint8Array> | null,
  timeoutMs: number,
): ReadableStream<Uint8Array> | null {
  if (!body) {
    return null;
  }

  const reader = body.getReader();
  let closed = false;

  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      let timer: ReturnType<typeof setTimeout> | null = null;
      let settled = false;
      try {
        const nextChunk = new Promise<ReadableStreamReadResult<Uint8Array>>((resolve, reject) => {
          timer = setTimeout(() => {
            if (settled) {
              return;
            }
            settled = true;
            void reader.cancel("backend response body timeout").catch(() => undefined);
            reject(new Error("backend response body timeout"));
          }, timeoutMs);
          reader.read().then(
            (result) => {
              if (!settled) {
                settled = true;
                resolve(result);
              }
            },
            (error: unknown) => {
              if (!settled) {
                settled = true;
                reject(error);
              }
            }
          );
        });
        const result = await nextChunk;
        if (timer) {
          clearTimeout(timer);
        }
        if (result.done) {
          closed = true;
          controller.close();
        } else {
          controller.enqueue(result.value);
        }
      } catch (error) {
        if (timer) {
          clearTimeout(timer);
        }
        controller.error(error);
      }
    },
    async cancel(reason) {
      if (!closed) {
        await reader.cancel(reason);
      }
    },
  });
}

async function proxyToBackend(request: NextRequest, context: RouteContext): Promise<Response> {
  const params = await context.params;
  const backendPath = (params.path ?? []).join("/");
  const method = request.method.toUpperCase();

  if (!isAllowedBackendRequest(backendPath, method)) {
    return Response.json({ detail: "Not found" }, { status: 404 });
  }

  // Backend routes live under `/v1` (ADR-005) except `/health`, which stays
  // unversioned. `api.ts` already includes `v1/` in every path it builds (so
  // that direct-to-backend usage, bypassing this proxy, also gets the
  // correct versioned path) -- this proxy just forwards the path as-is.
  const targetUrl = `${BACKEND_INTERNAL_URL}/${backendPath}${request.nextUrl.search}`;
  const isBackupRequest = backendPath.startsWith("v1/admin/backups");
  const requestTimeoutMs = isBackupRequest ? BACKUP_PROXY_TIMEOUT_MS : BACKEND_PROXY_TIMEOUT_MS;
  const bodyTimeoutMs = isBackupRequest ? BACKUP_PROXY_BODY_TIMEOUT_MS : BACKEND_PROXY_BODY_TIMEOUT_MS;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), requestTimeoutMs);
  const requestBody = method === "GET" || method === "HEAD" ? undefined : request.body;

  try {
    const upstreamResponse = await fetch(targetUrl, {
      method,
      headers: buildForwardHeaders(request),
      body: requestBody,
      cache: "no-store",
      redirect: "manual",
      signal: controller.signal,
      ...(requestBody ? { duplex: "half" as const } : {}),
    });

    return new Response(streamWithReadTimeout(upstreamResponse.body, bodyTimeoutMs), {
      status: upstreamResponse.status,
      statusText: upstreamResponse.statusText,
      headers: buildResponseHeaders(upstreamResponse),
    });
  } catch (caughtError) {
    if (caughtError instanceof DOMException && caughtError.name === "AbortError") {
      return buildProxyErrorResponse(504, "백엔드 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.");
    }
    return buildProxyErrorResponse(502, "백엔드에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.");
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function GET(request: NextRequest, context: RouteContext): Promise<Response> {
  return proxyToBackend(request, context);
}

export async function POST(request: NextRequest, context: RouteContext): Promise<Response> {
  return proxyToBackend(request, context);
}
