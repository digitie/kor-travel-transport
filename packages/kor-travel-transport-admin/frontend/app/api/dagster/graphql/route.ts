import { NextRequest, NextResponse } from "next/server";

import { hasAdminSession } from "@/lib/auth";
import { isAllowedOrigin } from "@/lib/origin";
import { boundedText, fetchNoStore } from "@/lib/upstream";

export async function POST(request: NextRequest) {
  if (!(await hasAdminSession(request))) return NextResponse.json({ errors: [{ message: "로그인이 필요합니다." }] }, { status: 401 });
  if (!isAllowedOrigin(request)) return NextResponse.json({ errors: [{ message: "허용되지 않은 요청입니다." }] }, { status: 403 });
  const body = await boundedText(request); if (body === null) return NextResponse.json({ errors: [{ message: "Dagster 요청이 너무 큽니다." }] }, { status: 413 });
  try {
    const base = (process.env.TRANSPORT_DAGSTER_INTERNAL_URL ?? "http://127.0.0.1:14004").replace(/\/$/, "");
    const response = await fetchNoStore(new URL(`${base}/graphql`), { method: "POST", headers: { accept: "application/json", "content-type": "application/json" }, body });
    return new NextResponse(response.body, { status: response.status, headers: { "cache-control": "no-store, private", "content-type": response.headers.get("content-type") ?? "application/json" } });
  } catch { return NextResponse.json({ errors: [{ message: "Dagster에 연결하지 못했습니다." }] }, { status: 502 }); }
}
