import type { NextApiRequest, NextApiResponse } from "next";
import { pipeline } from "node:stream";

import { NO_STORE, openFullHistory, problemBody } from "@/lib/full-history-proxy";

/**
 * 30일 전체 이력(`GET /api/backend/v1/parking/history`, `limit` 없음)의 공개 프록시.
 *
 * next.config `rewrites`가 이 경로로 보낸다. App Router route handler는 응답의 `content-encoding`을 버려 backend가 미리 만든
 * br·gzip 본문을 넘길 수 없다(이중 gzip, 2026-11-24). pages API는 Node 응답에 머리말을 직접 써 압축 본문을 그대로 넘기고,
 * Next 서버 압축은 이미 인코딩된 응답을 건너뛴다. 그 밖의 이력 요청(`limit`·커서)은 App Router 프록시가 맡는다.
 */
export const config = { api: { responseLimit: false, bodyParser: false, externalResolver: true } };

const PUBLIC_PATH = "/api/backend/v1/parking/history";
const BACKEND_INTERNAL_URL = (process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000").replace(/\/$/, "");
const BACKEND_PROXY_TIMEOUT_MS = Math.max(1_000, Number(process.env.BACKEND_PROXY_TIMEOUT_MS ?? 10_000) || 10_000);
const BACKEND_PROXY_BODY_TIMEOUT_MS = Math.max(
  1_000,
  Number(process.env.BACKEND_PROXY_BODY_TIMEOUT_MS ?? BACKEND_PROXY_TIMEOUT_MS) || BACKEND_PROXY_TIMEOUT_MS
);

function header(req: NextApiRequest, name: string): string | null {
  const value = req.headers[name];
  return Array.isArray(value) ? value.join(", ") : value ?? null;
}

function sendProblem(res: NextApiResponse, status: 404 | 502 | 503 | 504, detail: string) {
  res.statusCode = status;
  res.setHeader("content-type", "application/problem+json");
  res.setHeader("cache-control", NO_STORE);
  res.end(JSON.stringify(problemBody(status, detail, PUBLIC_PATH)));
}

export default async function fullHistory(req: NextApiRequest, res: NextApiResponse): Promise<void> {
  const url = new URL(req.url ?? "/", "http://internal");
  const method = (req.method ?? "GET").toUpperCase();
  // 같은 backend 경로의 GET만 중계한다. `?limit=`(빈 값)은 rewrite의 `missing`을 통과하므로 여기 온다 — backend의
  // 응답(422)을 그대로 넘긴다(App Router 경로와 같은 결과).
  if (method !== "GET" && method !== "HEAD") {
    sendProblem(res, 404, "Not found");
    return;
  }
  const controller = new AbortController();
  res.once("close", () => {
    if (!res.writableFinished) controller.abort();
  });
  const result = await openFullHistory(new URL(`${BACKEND_INTERNAL_URL}/v1/parking/history${url.search}`), {
    acceptEncoding: header(req, "accept-encoding"),
    passthroughEncoding: true,
    forwardedHost: header(req, "host") ?? "",
    forwardedProto: header(req, "x-forwarded-proto") ?? "http",
    accept: header(req, "accept"),
    signal: controller.signal,
    headerTimeoutMs: BACKEND_PROXY_TIMEOUT_MS,
    bodyIdleTimeoutMs: BACKEND_PROXY_BODY_TIMEOUT_MS,
  });
  if (result.kind === "error") {
    if (!res.headersSent && !res.destroyed) sendProblem(res, result.status, result.detail);
    return;
  }
  res.statusCode = result.status;
  for (const [key, value] of Object.entries(result.headers)) res.setHeader(key, value);
  if (method === "HEAD") {
    result.body.destroy();
    res.end();
    return;
  }
  // 오류·중단 시 pipeline이 양쪽을 정리한다(헤더 뒤 실패는 연결을 끊어 잘린 본문이 성공처럼 보이지 않게 한다).
  pipeline(result.body, res, () => {});
}
