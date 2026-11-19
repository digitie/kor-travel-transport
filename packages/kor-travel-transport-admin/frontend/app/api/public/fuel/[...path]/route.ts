import { NextRequest, NextResponse } from "next/server";

import { publicFuelUpstreamUrl } from "@/lib/public-fuel-proxy";

const NO_STORE = { "cache-control": "no-store" };
const MAX_BYTES = 16 * 1024 * 1024;

export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  if (process.env.TRANSPORT_UI_MODE !== "fuel") return new NextResponse(null, { status: 404 });
  const { path } = await context.params;
  try {
    const target = publicFuelUpstreamUrl(path, request.nextUrl.searchParams);
    if (!target) return new NextResponse(null, { status: 404 });
    const headers = new Headers({ accept: "application/json" });
    const etag = request.headers.get("if-none-match");
    if (etag) headers.set("if-none-match", etag);
    const response = await fetch(target, { method: "GET", headers, cache: "no-store", credentials: "omit",
      redirect: "error", signal: AbortSignal.any([request.signal, AbortSignal.timeout(30_000)]) });
    const outputHeaders = new Headers(NO_STORE);
    for (const name of ["content-type", "etag", "retry-after"]) {
      const value = response.headers.get(name); if (value !== null) outputHeaders.set(name, value);
    }
    if (response.status === 304 || response.status === 204) {
      return new NextResponse(null, { status: response.status, headers: outputHeaders });
    }
    const reader = response.body?.getReader();
    const chunks: Uint8Array[] = []; let size = 0;
    try {
      if (reader) while (true) {
        const { done, value } = await reader.read(); if (done) break;
        size += value.byteLength;
        if (size > MAX_BYTES) { await reader.cancel(); throw new Error("응답 크기 초과"); }
        chunks.push(value);
      }
    } finally { reader?.releaseLock(); }
    const body = new Uint8Array(size); let offset = 0;
    for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
    return new NextResponse(body, { status: response.status, headers: outputHeaders });
  } catch {
    return NextResponse.json({ detail: "유가 API에 연결하지 못했습니다." }, { status: 502, headers: NO_STORE });
  }
}
