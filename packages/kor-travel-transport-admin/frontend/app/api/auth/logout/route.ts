import { NextRequest, NextResponse } from "next/server";

import { isAllowedOrigin } from "@/lib/origin";
import { SESSION_COOKIE } from "@/lib/session";

export async function POST(request: NextRequest) {
  if (!isAllowedOrigin(request)) return NextResponse.json({ detail: "허용되지 않은 요청입니다." }, { status: 403 });
  // TLS는 앞단에서 종료된다. request.url의 scheme을 그대로 사용하면 public HTTPS
  // 요청이 내부 HTTP URL로 redirect될 수 있으므로, 브라우저가 현재 origin을 유지하는
  // 상대 Location을 반환한다.
  const response = new NextResponse(null, { status: 303, headers: { Location: "/login" } });
  response.cookies.set(SESSION_COOKIE, "", { httpOnly: true, maxAge: 0, path: "/", sameSite: "strict", secure: process.env.NODE_ENV === "production" });
  return response;
}
