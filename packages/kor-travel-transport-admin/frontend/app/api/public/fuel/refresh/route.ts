import { NextRequest, NextResponse } from "next/server";

import { isAllowedOrigin } from "@/lib/origin";
import { publicFuelRefreshConfiguration } from "@/lib/public-fuel-proxy";

const NO_STORE = { "cache-control": "no-store" };
const MAX_REQUEST_BYTES = 4 * 1024;

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
  try {
    const body = await readRefreshRequest(request);
    if (!body?.length) return new NextResponse(null, { status: 400 });
    const response = await fetch(config.target, {
      method: "POST",
      headers: { authorization: `Bearer ${config.token}`, "content-type": "application/json", accept: "application/json" },
      body: body.toString("utf8"),
      cache: "no-store",
      credentials: "omit",
      redirect: "error",
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(35_000)]),
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
