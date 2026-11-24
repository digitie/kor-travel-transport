import { createServer, request as httpRequest, type IncomingMessage, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { brotliCompressSync, brotliDecompressSync, constants, gunzipSync, gzipSync } from "node:zlib";

import nextConfig from "../next.config";

// 30일 전체 이력의 공개 정본 경로(pages API). App Router 응답은 content-encoding을 잃어 이중 gzip이 됐다(2026-11-24).
// pages API는 backend 압축 본문과 머리말을 그대로 넘긴다.

async function listen(server: Server): Promise<string> {
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  return `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
}

async function close(server: Server) {
  await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
}

function rawGet(url: string, headers: Record<string, string>, method = "GET") {
  return new Promise<{ response: IncomingMessage; body: Buffer }>((resolve, reject) => {
    const req = httpRequest(url, { method, headers }, (response) => {
      const chunks: Buffer[] = [];
      response.on("data", (chunk: Buffer) => chunks.push(chunk));
      response.on("end", () => resolve({ response, body: Buffer.concat(chunks) }));
      response.on("error", reject);
    });
    req.on("error", reject);
    req.end();
  });
}

describe("full history pages route", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
  });

  test.each([
    { clientEncoding: "br, gzip", offered: "br, gzip", responseEncoding: "br" },
    { clientEncoding: "gzip", offered: "gzip", responseEncoding: "gzip" },
    { clientEncoding: "br, gzip;q=0", offered: "br", responseEncoding: "br" },
    { clientEncoding: "identity", offered: "identity", responseEncoding: "identity" },
  ])("passes the backend $responseEncoding body through unchanged", async ({ clientEncoding, offered, responseEncoding }) => {
    const uncompressed = JSON.stringify({ items: ["x".repeat(17 * 1024 * 1024)], next_cursor: null });
    const payload = responseEncoding === "br"
      ? brotliCompressSync(uncompressed, { params: { [constants.BROTLI_PARAM_QUALITY]: 4 } })
      : responseEncoding === "gzip" ? gzipSync(uncompressed) : Buffer.from(uncompressed);
    let forwarded: { encoding?: string; url?: string } = {};
    const backend = createServer((request, response) => {
      forwarded = { encoding: request.headers["accept-encoding"], url: request.url };
      response.writeHead(200, {
        "content-type": "application/json",
        ...(responseEncoding === "identity" ? {} : { "content-encoding": responseEncoding }),
        "content-length": payload.length,
        vary: "Accept-Encoding",
      });
      response.end(payload);
    });
    const backendUrl = await listen(backend);
    vi.stubEnv("BACKEND_INTERNAL_URL", backendUrl);
    const { default: handler } = await import("@/pages/api/full-history");
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const front = createServer((req, res) => void handler(req as any, res as any));
    const frontUrl = await listen(front);
    try {
      const { response, body } = await rawGet(`${frontUrl}/api/full-history?days=30`, { "accept-encoding": clientEncoding });
      expect(response.statusCode).toBe(200);
      expect(forwarded).toEqual({ encoding: offered, url: "/v1/parking/history?days=30" });
      expect(response.headers["content-encoding"]).toBe(responseEncoding === "identity" ? undefined : responseEncoding);
      expect(response.headers["content-length"]).toBe(String(payload.length));
      expect(response.headers["cache-control"]).toBe("no-store, max-age=0, must-revalidate");
      const decoded = responseEncoding === "br" ? brotliDecompressSync(body)
        : responseEncoding === "gzip" ? gunzipSync(body) : body;
      expect(decoded.toString()).toBe(uncompressed);
    } finally {
      await close(front);
      await close(backend);
    }
  });

  test("rejects other methods so the rewrite target does not widen the public surface", async () => {
    vi.stubEnv("BACKEND_INTERNAL_URL", "http://127.0.0.1:9");
    const { default: handler } = await import("@/pages/api/full-history");
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const front = createServer((req, res) => void handler(req as any, res as any));
    const frontUrl = await listen(front);
    try {
      const posted = await rawGet(`${frontUrl}/api/full-history`, {}, "POST");
      expect(posted.response.statusCode).toBe(404);
      expect(posted.response.headers["content-type"]).toBe("application/problem+json");
    } finally {
      await close(front);
    }
  });

  test("maps an unreachable backend to the problem+json 502 contract", async () => {
    const closed = createServer();
    const closedUrl = await listen(closed);
    await close(closed);
    vi.stubEnv("BACKEND_INTERNAL_URL", closedUrl);
    const { default: handler } = await import("@/pages/api/full-history");
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const front = createServer((req, res) => void handler(req as any, res as any));
    const frontUrl = await listen(front);
    try {
      const { response, body } = await rawGet(`${frontUrl}/api/full-history?days=30`, {});
      expect(response.statusCode).toBe(502);
      expect(JSON.parse(body.toString())).toMatchObject({
        status: 502, code: "backend_unavailable", instance: "/api/backend/v1/parking/history",
      });
    } finally {
      await close(front);
    }
  });

  test("routes only unpaged full history to the pages API", async () => {
    const rewrites = await nextConfig.rewrites?.();
    expect(rewrites).toEqual({
      beforeFiles: [{
        source: "/api/backend/v1/parking/history",
        missing: [{ type: "query", key: "limit" }],
        destination: "/api/full-history",
      }],
    });
  });
});
