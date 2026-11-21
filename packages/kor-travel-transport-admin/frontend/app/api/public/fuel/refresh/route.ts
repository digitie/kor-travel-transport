import { NextRequest, NextResponse } from "next/server";

import { isAllowedOrigin } from "@/lib/origin";
import { publicFuelRefreshConfiguration } from "@/lib/public-fuel-proxy";

const NO_STORE = { "cache-control": "no-store" };
const MAX_REQUEST_BYTES = 4 * 1024;
// 백엔드의 75초 조회 뒤 브라우저와 DB 정리를 기다린다.
const UPSTREAM_TIMEOUT_MS = 90_000;
const FIRST_HEARTBEAT_MS = 15_000;
const HEARTBEAT_INTERVAL_MS = 10_000;

async function readRefreshRequest(request: NextRequest) {
  const reader = request.body?.getReader();
  if (!reader) return null;
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return Buffer.concat(chunks, size);
      size += value.byteLength;
      if (size > MAX_REQUEST_BYTES) {
        await reader.cancel();
        return null;
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
}

export async function POST(request: NextRequest) {
  if (process.env.TRANSPORT_UI_MODE !== "fuel") return new NextResponse(null, { status: 404 });
  const config = publicFuelRefreshConfiguration();
  if (!config) return NextResponse.json({ detail: "수동 유가 갱신을 사용할 수 없습니다." }, { status: 503, headers: NO_STORE });
  if (!isAllowedOrigin(request, config.origin)) return new NextResponse(null, { status: 403 });
  if (request.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase() !== "application/json") {
    return new NextResponse(null, { status: 415 });
  }
  let body: Buffer | null;
  try {
    body = await readRefreshRequest(request);
  } catch {
    return new NextResponse(null, { status: 400 });
  }
  if (!body?.length) return new NextResponse(null, { status: 400 });

  const controller = new AbortController();
  const signal = AbortSignal.any([request.signal, controller.signal, AbortSignal.timeout(UPSTREAM_TIMEOUT_MS)]);
  const upstream = fetchRefresh(config, body.toString("utf8"), signal);
  let timer: ReturnType<typeof setTimeout> | undefined;
  const fastResponse = await Promise.race([
    upstream,
    new Promise<undefined>(resolve => { timer = setTimeout(resolve, FIRST_HEARTBEAT_MS); }),
  ]);
  clearTimeout(timer);
  return fastResponse ?? streamRefresh(upstream, controller);
}

async function fetchRefresh(
  config: NonNullable<ReturnType<typeof publicFuelRefreshConfiguration>>, body: string, signal: AbortSignal,
) {
  try {
    const response = await fetch(config.target, {
      method: "POST",
      headers: { authorization: `Bearer ${config.token}`, "content-type": "application/json", accept: "application/json" },
      body,
      cache: "no-store",
      credentials: "omit",
      redirect: "error",
      signal,
    });
    if (response.ok) return NextResponse.json(await response.json(), { headers: NO_STORE });
    if (response.status === 429) {
      const headers = new Headers(NO_STORE);
      const retryAfter = response.headers.get("retry-after");
      if (retryAfter) headers.set("retry-after", retryAfter);
      return NextResponse.json({ detail: "잠시 뒤 다시 시도해 주세요." }, { status: 429, headers });
    }
    if ([400, 404, 409, 422, 503].includes(response.status)) {
      return NextResponse.json({ detail: "이 범위의 유가를 갱신할 수 없습니다." }, { status: response.status, headers: NO_STORE });
    }
  } catch { /* 업스트림 상세 오류를 공개 응답에 포함하지 않는다. */ }
  return NextResponse.json({ detail: "유가 업데이트에 실패했습니다." }, { status: 502, headers: NO_STORE });
}

// JSON 값 앞의 공백이 프록시의 유휴 시간을 초기화한다. 빠른 응답은 기존 HTTP 상태를 유지한다.
function streamRefresh(upstream: Promise<NextResponse>, abort: AbortController) {
  const encoder = new TextEncoder();
  const heartbeat = encoder.encode(" ".repeat(1024));
  let timer: ReturnType<typeof setInterval> | undefined;
  let closed = false;
  return new NextResponse(new ReadableStream<Uint8Array>({
    start(stream) {
      const finish = (body: string) => {
        if (closed) return;
        closed = true;
        clearInterval(timer);
        stream.enqueue(encoder.encode(body));
        stream.close();
      };
      stream.enqueue(heartbeat);
      timer = setInterval(() => stream.enqueue(heartbeat), HEARTBEAT_INTERVAL_MS);
      void upstream.then(async response => {
        finish(response.ok ? await response.text() : JSON.stringify({ error_status: response.status }));
      }).catch(() => finish(JSON.stringify({ error_status: 502 })));
    },
    cancel() {
      closed = true;
      clearInterval(timer);
      abort.abort();
    },
  }), { headers: {
    ...NO_STORE,
    "content-type": "application/json",
    "content-encoding": "identity",
    "x-accel-buffering": "no",
  } });
}
