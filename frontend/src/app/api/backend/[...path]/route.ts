import type { NextRequest } from "next/server";
import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { Readable } from "node:stream";

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
// JSON 버퍼가 요청별로 무제한 증가하지 않도록 실제 수신 바이트를 제한한다.
const MAX_JSON_BODY_BYTES = 16 * 1024 * 1024;
const MAX_PENDING_FULL_HISTORY_HEADERS = 8;
let pendingFullHistoryHeaders = 0;
const FORWARDED_REQUEST_HEADERS = new Set(["accept", "content-type"]);
const FORWARDED_RESPONSE_HEADERS = new Set([
  "cache-control",
  "content-disposition",
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
  return false;
}

// 2026-10-02 공개 백업 노출 사고(docs/adr/012-*.md): 공개 웹 앱은 어떤 관리 기능도 중계하지
// 않는다. 백업·복원·수동 수집은 관리자 토큰을 아는 운영자만 호스트에서 직접 호출한다.
// Next는 catch-all 세그먼트를 디코드해 넘기므로(`back%75ps` → `backups`, `%2F` → `/` 포함 세그먼트),
// 빈 세그먼트·점 세그먼트·구분자를 품은 세그먼트는 경로 정규화 우회를 막기 위해 통째로 거부한다.
function hasUnsafeSegment(segments: string[]): boolean {
  return segments.some((segment) =>
    segment === "" || segment === "." || segment === ".." || /[\\/%\u0000-\u001f]/.test(segment)
  );
}

function isAdminOperationPath(path: string): boolean {
  const lowered = path.toLowerCase();
  return (
    lowered.includes("admin/backup") ||
    (lowered.startsWith("v1/admin/") && lowered !== "v1/admin/collector-status") ||
    // 관리자 BFF 전용 좌표 보정 경로. 백엔드도 토큰 없이 404지만 공개 프록시는 아예 중계하지 않는다.
    lowered.startsWith("v1/transport/admin/")
  );
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

function acceptsEncoding(header: string | null, encoding: string): boolean {
  return (header ?? "").split(",").some((entry) => {
    const [name, ...parameters] = entry.trim().toLowerCase().split(";").map((part) => part.trim());
    if (name !== encoding) return false;
    const quality = parameters.find((part) => part.startsWith("q="));
    return !quality || Number(quality.slice(2)) > 0;
  });
}

// fetch()는 gzip을 자동 해제한다. 30일 전체 이력을 통과시키는 경로에서는
// 압축된 원본 스트림을 그대로 전달해 16MiB JSON 버퍼와 이중 전송을 피한다.
function proxyFullHistory(request: NextRequest, targetUrl: string, timeoutMs: number, bodyTimeoutMs: number): Promise<Response> {
  if (pendingFullHistoryHeaders >= MAX_PENDING_FULL_HISTORY_HEADERS) {
    return Promise.resolve(buildProxyErrorResponse(request, 503,
      "전체 이력 조회가 많습니다. 잠시 후 다시 시도해 주세요."));
  }
  pendingFullHistoryHeaders += 1;
  return new Promise((resolve) => {
    let headerPending = true;
    const finishHeaderWait = () => {
      if (!headerPending) return;
      headerPending = false;
      pendingFullHistoryHeaders -= 1;
    };
    const url = new URL(targetUrl);
    const send = url.protocol === "https:" ? httpsRequest : httpRequest;
    let timedOut = false;
    const supportedEncodings = ["br", "gzip"].filter((encoding) =>
      acceptsEncoding(request.headers.get("accept-encoding"), encoding)
    );
    const headers: Record<string, string> = {
      "accept-encoding": supportedEncodings.length ? supportedEncodings.join(", ") : "identity",
      "x-forwarded-host": request.headers.get("host") ?? "",
      "x-forwarded-proto": request.headers.get("x-forwarded-proto") ?? request.nextUrl.protocol.replace(":", ""),
    };
    const accept = request.headers.get("accept");
    if (accept) headers.accept = accept;

    const upstream = send(url, { method: "GET", headers }, (incoming) => {
      finishHeaderWait();
      clearTimeout(headerTimer);
      incoming.once("close", () => request.signal.removeEventListener("abort", abortUpstream));
      const responseHeaders = new Headers();
      for (const key of FORWARDED_RESPONSE_HEADERS) {
        const value = incoming.headers[key];
        if (value) responseHeaders.set(key, Array.isArray(value) ? value.join(", ") : value);
      }
      for (const key of ["content-encoding", "content-length", "vary"]) {
        const value = incoming.headers[key];
        if (value) responseHeaders.set(key, Array.isArray(value) ? value.join(", ") : value);
      }
      responseHeaders.set("cache-control", "no-store, max-age=0, must-revalidate");
      // 대용량 스트림은 전체 전송시간이 아니라 비활성 시간을 제한한다.
      // 헤더 뒤 슬롯 대기나 느린 클라이언트가 정상 본문을 10초에 절단하지 않게 한다.
      incoming.setTimeout(Math.max(bodyTimeoutMs, 120_000), () => {
        incoming.destroy(new Error("backend response body idle timeout"));
      });
      resolve(new Response(Readable.toWeb(incoming) as ReadableStream<Uint8Array>, {
        status: incoming.statusCode ?? 502,
        headers: responseHeaders,
      }));
    });
    // API가 앞선 대량 응답의 전송 슬롯을 기다릴 수 있으므로 일반 JSON의
    // 짧은 헤더 제한을 적용하지 않는다. 연결 자체가 멈춘 경우에는 종료한다.
    const headerTimer = setTimeout(() => {
      timedOut = true;
      upstream.destroy(new Error("backend response header timeout"));
    }, Math.max(timeoutMs, 120_000));
    const abortUpstream = () => {
      finishHeaderWait();
      upstream.destroy(new Error("client aborted"));
    };
    upstream.once("error", () => {
      finishHeaderWait();
      clearTimeout(headerTimer);
      request.signal.removeEventListener("abort", abortUpstream);
      resolve(buildProxyErrorResponse(request, timedOut ? 504 : 502,
        timedOut ? "백엔드 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요."
          : "백엔드에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요."));
    });
    request.signal.addEventListener("abort", abortUpstream, { once: true });
    if (request.signal.aborted) abortUpstream();
    else upstream.end();
  });
}

function buildProxyErrorResponse(request: NextRequest, status: 404 | 502 | 503 | 504, detail: string): Response {
  const titles = { 404: "Not Found", 502: "Bad Gateway", 503: "Service Unavailable", 504: "Gateway Timeout" };

  // ADR-005의 오류 계약을 따르되 기존 클라이언트의 detail/code 호환성을 유지한다.
  return Response.json(
    {
      type: "about:blank",
      title: titles[status],
      status,
      detail,
      instance: request.nextUrl.pathname,
      ...(status === 404 ? {} : { code: status === 504 ? "backend_timeout" : status === 503 ? "backend_busy" : "backend_unavailable" }),
    },
    {
      status,
      headers: {
        "content-type": "application/problem+json",
        "cache-control": "no-store, max-age=0, must-revalidate",
      },
    }
  );
}

async function bufferJsonBody(
  body: ReadableStream<Uint8Array> | null,
  timeoutMs: number,
): Promise<Uint8Array<ArrayBuffer> | null> {
  if (!body) {
    return null;
  }

  const reader = body.getReader();
  let timeoutId: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      (async () => {
        const chunks: Uint8Array[] = [];
        let size = 0;
        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            break;
          }
          size += value.byteLength;
          if (size > MAX_JSON_BODY_BYTES) {
            throw new Error("backend JSON response body exceeds size limit");
          }
          chunks.push(value);
        }
        const bytes = new Uint8Array(size);
        let offset = 0;
        for (const chunk of chunks) {
          bytes.set(chunk, offset);
          offset += chunk.byteLength;
        }
        return bytes;
      })(),
      new Promise<never>((_resolve, reject) => {
        // 청크가 조금씩 계속 도착해도 전체 본문 수신 기한은 연장하지 않는다.
        timeoutId = setTimeout(() => {
          reject(new DOMException("backend response body timeout", "TimeoutError"));
        }, timeoutMs);
      }),
    ]);
  } catch (error) {
    // 취소 처리가 멈춰도 클라이언트 오류 응답은 즉시 반환한다.
    void reader.cancel(error).catch(() => undefined);
    throw error;
  } finally {
    clearTimeout(timeoutId);
    reader.releaseLock();
  }
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
  const segments = params.path ?? [];
  const backendPath = segments.join("/");
  const method = request.method.toUpperCase();

  if (hasUnsafeSegment(segments) || isAdminOperationPath(backendPath) || !isAllowedBackendRequest(backendPath, method)) {
    return buildProxyErrorResponse(request, 404, "Not found");
  }

  // Backend routes live under `/v1` (ADR-005) except `/health`, which stays
  // unversioned. `api.ts` already includes `v1/` in every path it builds (so
  // that direct-to-backend usage, bypassing this proxy, also gets the
  // correct versioned path) -- this proxy just forwards the path as-is.
  const targetUrl = `${BACKEND_INTERNAL_URL}/${segments.map(encodeURIComponent).join("/")}${request.nextUrl.search}`;
  const requestTimeoutMs = BACKEND_PROXY_TIMEOUT_MS;
  const bodyTimeoutMs = BACKEND_PROXY_BODY_TIMEOUT_MS;
  if (backendPath === "v1/parking/history" && method === "GET" && !request.nextUrl.searchParams.has("limit")) {
    return proxyFullHistory(request, targetUrl, requestTimeoutMs, bodyTimeoutMs);
  }
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
    clearTimeout(timeoutId);

    const mediaType = upstreamResponse.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase() ?? "";
    const isJson = mediaType === "application/json" || mediaType.endsWith("+json");
    // JSON은 완료 전까지 헤더를 보내지 않아 본문 timeout도 RFC7807 504로 반환한다.
    // JSON이 아닌 스트리밍 응답은 전송 시작 후 오류를 504로 바꿀 수 없으며 읽기가 실패한다.
    const responseBody = isJson
      ? await bufferJsonBody(upstreamResponse.body, bodyTimeoutMs)
      : streamWithReadTimeout(upstreamResponse.body, bodyTimeoutMs);

    return new Response(responseBody, {
      status: upstreamResponse.status,
      statusText: upstreamResponse.statusText,
      headers: buildResponseHeaders(upstreamResponse),
    });
  } catch (caughtError) {
    if (caughtError instanceof DOMException && (caughtError.name === "AbortError" || caughtError.name === "TimeoutError")) {
      return buildProxyErrorResponse(request, 504, "백엔드 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.");
    }
    return buildProxyErrorResponse(request, 502, "백엔드에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.");
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
