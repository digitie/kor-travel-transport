import { NextRequest, NextResponse } from "next/server";

import { hasAdminSession } from "@/lib/auth";

export const dynamic = "force-dynamic";

// 배포 candidate와 실제 실행 이미지를 대조하는 live E2E 전용 인증 API다.
export async function GET(request: NextRequest) {
  if (!(await hasAdminSession(request))) {
    return NextResponse.json({ detail: "로그인이 필요합니다." }, { status: 401 });
  }
  return NextResponse.json({ releaseSha: process.env.TRANSPORT_ADMIN_RELEASE_SHA ?? "unknown" }, {
    headers: { "cache-control": "no-store, private" },
  });
}
