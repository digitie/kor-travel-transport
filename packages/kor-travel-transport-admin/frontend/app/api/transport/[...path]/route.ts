import { NextRequest, NextResponse } from "next/server";

import { hasAdminSession } from "@/lib/auth";
import { fetchNoStore, transportUpstreamUrl } from "@/lib/upstream";

export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  if (!(await hasAdminSession(request))) return NextResponse.json({ detail: "로그인이 필요합니다." }, { status: 401 });
  const { path } = await context.params; const target = transportUpstreamUrl(path, request.nextUrl.searchParams);
  if (!target) return NextResponse.json({ detail: "허용되지 않은 transport API 경로입니다." }, { status: 404 });
  try {
    const response = await fetchNoStore(target, { headers: { accept: request.headers.get("accept") ?? "application/json", "x-request-id": request.headers.get("x-request-id") ?? "" } });
    return new NextResponse(response.body, { status: response.status, headers: { "cache-control": "no-store, private", "content-type": response.headers.get("content-type") ?? "application/json", "x-request-id": response.headers.get("x-request-id") ?? "" } });
  } catch { return NextResponse.json({ detail: "transport API에 연결하지 못했습니다." }, { status: 502, headers: { "cache-control": "no-store, private" } }); }
}
