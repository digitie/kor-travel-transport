import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { PassThrough, type Readable, pipeline } from "node:stream";
import { createBrotliDecompress, createGunzip } from "node:zlib";

/**
 * 30일 전체 이력(`/v1/parking/history`, `limit` 없음) 프록시의 Node 수준 구현.
 *
 * 본문(운영 약 75MB JSON)은 16MiB JSON 버퍼를 피하려고 스트림으로 넘긴다. 공개 웹의 정본 경로는 pages API
 * (`src/pages/api/full-history.ts`, next.config rewrite)다 — Next(16.4)는 App Router route handler 응답의
 * `content-encoding`·`content-length`를 버리고(send-response FORBIDDEN_HEADERS) 서버 압축을 다시 걸어, backend가
 * 미리 만든 br·gzip 본문을 그대로 넘기면 이중 gzip이 됐다(2026-11-24 운영 검증). pages API는 Node 응답에 머리말을
 * 직접 쓰므로 backend 압축 본문을 그대로 넘기고, Next 압축은 이미 인코딩된 응답을 건너뛴다.
 * App Router fallback(`passthroughEncoding=false`)은 identity를 요청하고 압축 본문이 와도 풀어서 넘긴다.
 * 헤더 대기 상한(`pendingFullHistoryHeaders`)은 모듈 상태라 pages API와 App Router 번들이 따로 셀 수 있다(상한은 번들별).
 */

export const MAX_PENDING_FULL_HISTORY_HEADERS = 8;
let pendingFullHistoryHeaders = 0;

export const FORWARDED_RESPONSE_HEADERS = new Set([
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

export const NO_STORE = "no-store, max-age=0, must-revalidate";

export type FullHistoryOptions = {
  /** 클라이언트의 Accept-Encoding. passthrough일 때 backend에 그대로 협상한다(br·gzip만). */
  acceptEncoding: string | null;
  /** true면 backend 압축 본문과 content-encoding을 그대로 넘긴다(pages API). false면 identity로 맞춘다. */
  passthroughEncoding: boolean;
  forwardedHost: string;
  forwardedProto: string;
  accept: string | null;
  signal: AbortSignal;
  headerTimeoutMs: number;
  bodyIdleTimeoutMs: number;
};

export type FullHistoryResult =
  | { kind: "response"; status: number; headers: Record<string, string>; body: Readable }
  | { kind: "error"; status: 502 | 503 | 504; detail: string };

export function acceptsEncoding(header: string | null, encoding: string): boolean {
  return (header ?? "").split(",").some((entry) => {
    const [name, ...parameters] = entry.trim().toLowerCase().split(";").map((part) => part.trim());
    if (name !== encoding) return false;
    const quality = parameters.find((part) => part.startsWith("q="));
    return !quality || Number(quality.slice(2)) > 0;
  });
}

/** 압축 본문을 풀어 identity 스트림으로 만든다. 모르는 인코딩이면 null이다. */
export function decodedBody(incoming: Readable, encoding: string | undefined): Readable | null {
  const normalized = (encoding ?? "identity").trim().toLowerCase();
  if (!normalized || normalized === "identity") return incoming;
  const decoder = normalized === "gzip" || normalized === "x-gzip" ? createGunzip()
    : normalized === "br" ? createBrotliDecompress() : null;
  if (!decoder) return null;
  const output = new PassThrough();
  pipeline(incoming, decoder, output, () => {});
  return output;
}

export function openFullHistory(target: URL, options: FullHistoryOptions): Promise<FullHistoryResult> {
  if (pendingFullHistoryHeaders >= MAX_PENDING_FULL_HISTORY_HEADERS) {
    return Promise.resolve({ kind: "error", status: 503, detail: "전체 이력 조회가 많습니다. 잠시 후 다시 시도해 주세요." });
  }
  pendingFullHistoryHeaders += 1;
  return new Promise((resolve) => {
    let headerPending = true;
    const finishHeaderWait = () => {
      if (!headerPending) return;
      headerPending = false;
      pendingFullHistoryHeaders -= 1;
    };
    const send = target.protocol === "https:" ? httpsRequest : httpRequest;
    let timedOut = false;
    const offered = options.passthroughEncoding
      ? ["br", "gzip"].filter((encoding) => acceptsEncoding(options.acceptEncoding, encoding))
      : [];
    const headers: Record<string, string> = {
      "accept-encoding": offered.length ? offered.join(", ") : "identity",
      "x-forwarded-host": options.forwardedHost,
      "x-forwarded-proto": options.forwardedProto,
    };
    if (options.accept) headers.accept = options.accept;

    const abortUpstream = () => {
      finishHeaderWait();
      upstream.destroy(new Error("client aborted"));
    };
    const upstream = send(target, { method: "GET", headers }, (incoming) => {
      finishHeaderWait();
      clearTimeout(headerTimer);
      incoming.once("close", () => options.signal.removeEventListener("abort", abortUpstream));
      const responseHeaders: Record<string, string> = {};
      const passthroughHeaders = options.passthroughEncoding ? ["content-encoding", "content-length", "vary"] : [];
      for (const key of [...FORWARDED_RESPONSE_HEADERS, ...passthroughHeaders]) {
        const value = incoming.headers[key];
        if (value) responseHeaders[key] = Array.isArray(value) ? value.join(", ") : value;
      }
      responseHeaders["cache-control"] = NO_STORE;
      // 대용량 스트림은 전체 전송시간이 아니라 비활성 시간을 제한한다.
      // 헤더 뒤 슬롯 대기나 느린 클라이언트가 정상 본문을 10초에 절단하지 않게 한다.
      incoming.setTimeout(Math.max(options.bodyIdleTimeoutMs, 120_000), () => {
        incoming.destroy(new Error("backend response body idle timeout"));
      });
      const encoding = incoming.headers["content-encoding"];
      const body = options.passthroughEncoding
        ? incoming
        : decodedBody(incoming, Array.isArray(encoding) ? encoding.join(",") : encoding);
      if (!body) {
        incoming.destroy();
        options.signal.removeEventListener("abort", abortUpstream);
        resolve({ kind: "error", status: 502, detail: "백엔드 응답 형식을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요." });
        return;
      }
      resolve({ kind: "response", status: incoming.statusCode ?? 502, headers: responseHeaders, body });
    });
    // API가 앞선 대량 응답의 전송 슬롯을 기다릴 수 있으므로 일반 JSON의
    // 짧은 헤더 제한을 적용하지 않는다. 연결 자체가 멈춘 경우에는 종료한다.
    const headerTimer = setTimeout(() => {
      timedOut = true;
      upstream.destroy(new Error("backend response header timeout"));
    }, Math.max(options.headerTimeoutMs, 120_000));
    upstream.once("error", () => {
      finishHeaderWait();
      clearTimeout(headerTimer);
      options.signal.removeEventListener("abort", abortUpstream);
      resolve(timedOut
        ? { kind: "error", status: 504, detail: "백엔드 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요." }
        : { kind: "error", status: 502, detail: "백엔드에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요." });
    });
    options.signal.addEventListener("abort", abortUpstream, { once: true });
    if (options.signal.aborted) abortUpstream();
    else upstream.end();
  });
}

export function problemBody(status: 404 | 502 | 503 | 504, detail: string, instance: string) {
  const titles = { 404: "Not Found", 502: "Bad Gateway", 503: "Service Unavailable", 504: "Gateway Timeout" };
  // ADR-005의 오류 계약을 따르되 기존 클라이언트의 detail/code 호환성을 유지한다.
  return {
    type: "about:blank",
    title: titles[status],
    status,
    detail,
    instance,
    ...(status === 404 ? {} : { code: status === 504 ? "backend_timeout" : status === 503 ? "backend_busy" : "backend_unavailable" }),
  };
}
