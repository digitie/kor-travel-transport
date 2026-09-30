import { NextRequest, NextResponse } from "next/server";

import { hasAdminSession } from "@/lib/auth";
import { isAllowedOrigin } from "@/lib/origin";
import { boundedText, fetchNoStore } from "@/lib/upstream";

export async function POST(request: NextRequest) {
  if (!(await hasAdminSession(request))) return NextResponse.json({ detail: "로그인이 필요합니다." }, { status: 401 });
  if (!isAllowedOrigin(request)) return NextResponse.json({ detail: "허용되지 않은 요청입니다." }, { status: 403 });
  if (!request.headers.get("content-type")?.startsWith("application/json")) return NextResponse.json({ detail: "JSON 요청만 허용합니다." }, { status: 415 });
  const token = process.env.TRANSPORT_ADMIN_WRITE_TOKEN ?? "";
  if (token.length < 32) return NextResponse.json({ detail: "좌표 보정 기능이 설정되지 않았습니다." }, { status: 503 });
  const raw = await boundedText(request, 4096);
  if (raw === null) return NextResponse.json({ detail: "요청 본문이 너무 큽니다." }, { status: 413 });
  let body: Record<string, unknown> | null;
  try { body = JSON.parse(raw || "null") as Record<string, unknown> | null; }
  catch { return NextResponse.json({ detail: "JSON 본문을 확인해 주세요." }, { status: 422 }); }
  if (!body || typeof body !== "object" || !["ferry_port", "bus_terminal"].includes(String(body.kind))) {
    return NextResponse.json({ detail: "항구·버스터미널 좌표만 보정할 수 있습니다." }, { status: 422 });
  }
  try {
    const target = new URL("/v1/transport/admin/place-locations", process.env.TRANSPORT_API_INTERNAL_URL ?? "http://127.0.0.1:14001");
    const response = await fetchNoStore(target, { method: "POST", headers: { "content-type": "application/json", "x-transport-admin-token": token }, body: raw });
    return new NextResponse(response.body, { status: response.status, headers: { "cache-control": "no-store, private", "content-type": response.headers.get("content-type") ?? "application/json" } });
  } catch {
    return NextResponse.json({ detail: "좌표 보정 API에 연결하지 못했습니다." }, { status: 502 });
  }
}
