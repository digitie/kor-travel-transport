import { NextRequest, NextResponse } from "next/server";

import { hasAdminSession } from "@/lib/auth";
import { isAllowedOrigin } from "@/lib/origin";
import { fetchNoStore, transportUpstreamUrl } from "@/lib/upstream";

export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  if (!(await hasAdminSession(request))) return NextResponse.json({ detail: "로그인이 필요합니다." }, { status: 401 });
  const { path } = await context.params; const target = transportUpstreamUrl(path, request.nextUrl.searchParams);
  if (!target) return NextResponse.json({ detail: "허용되지 않은 transport API 경로입니다." }, { status: 404 });
  try {
    const response = await fetchNoStore(target, { headers: { accept: request.headers.get("accept") ?? "application/json", "x-request-id": request.headers.get("x-request-id") ?? "" } });
    const retryAfter = response.headers.get("retry-after");
    return new NextResponse(response.body, { status: response.status, headers: { "cache-control": "no-store, private", "content-type": response.headers.get("content-type") ?? "application/json", "retry-after": retryAfter ?? "", "x-request-id": response.headers.get("x-request-id") ?? "" } });
  } catch { return NextResponse.json({ detail: "transport API에 연결하지 못했습니다." }, { status: 502, headers: { "cache-control": "no-store, private" } }); }
}

/** 요금 계산만 허용한다. 수집·DB 변경을 수행하는 admin POST는 중계하지 않는다. */
export async function POST(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const noStore = { "cache-control": "no-store, private" };
  if (!(await hasAdminSession(request))) return NextResponse.json({ detail: "로그인이 필요합니다." }, { status: 401, headers: noStore });
  const { path } = await context.params;
  if (path.join("/") !== "fees/calculate") return NextResponse.json({ detail: "허용되지 않은 transport API 경로입니다." }, { status: 404, headers: noStore });
  if (!isAllowedOrigin(request)) return NextResponse.json({ detail: "허용되지 않은 요청입니다." }, { status: 403, headers: noStore });
  if (request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") return NextResponse.json({ detail: "JSON 요청이 필요합니다." }, { status: 415, headers: noStore });
  // 계산 요청은 작고 정형화되어 있다. 크기는 선언값과 실제 스트림 모두 제한한다.
  const declared = Number(request.headers.get("content-length") ?? 0);
  if (declared > 4096) return NextResponse.json({ detail: "요청이 너무 큽니다." }, { status: 413, headers: noStore });
  const reader = request.body?.getReader();
  let size = 0; const chunks: Uint8Array[] = [];
  try {
    if (reader) while (true) {
      const { value, done } = await reader.read(); if (done) break;
      size += value.byteLength;
      if (size > 4096) { await reader.cancel(); return NextResponse.json({ detail: "요청이 너무 큽니다." }, { status: 413, headers: noStore }); }
      chunks.push(value);
    }
    const body = new Uint8Array(size); let offset = 0;
    for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
    JSON.parse(new TextDecoder().decode(body));
    // GET allowlist에 fees를 추가하지 않고, 이 단일 계산 경로만 같은 내부 origin에 연결한다.
    const base = transportUpstreamUrl(["airports"], new URLSearchParams());
    if (!base) throw new Error("설정 오류");
    const target = new URL("fees/calculate", base);
    const response = await fetchNoStore(target, { method: "POST", headers: { accept: "application/json", "content-type": "application/json" }, body });
    return new NextResponse(response.body, { status: response.status, headers: { ...noStore, "content-type": response.headers.get("content-type") ?? "application/json" } });
  } catch (error) {
    return NextResponse.json({ detail: error instanceof SyntaxError ? "유효한 JSON 요청이 필요합니다." : "transport API에 연결하지 못했습니다." }, { status: error instanceof SyntaxError ? 400 : 502, headers: noStore });
  } finally { reader?.releaseLock(); }
}
