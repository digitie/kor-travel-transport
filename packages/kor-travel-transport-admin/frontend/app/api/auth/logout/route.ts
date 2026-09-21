import { NextRequest, NextResponse } from "next/server";

import { isAllowedOrigin } from "@/lib/origin";
import { SESSION_COOKIE } from "@/lib/session";

export async function POST(request: NextRequest) {
  if (!isAllowedOrigin(request)) return NextResponse.json({ detail: "허용되지 않은 요청입니다." }, { status: 403 });
  const response = NextResponse.redirect(new URL("/login", request.url), 303);
  response.cookies.set(SESSION_COOKIE, "", { httpOnly: true, maxAge: 0, path: "/", sameSite: "strict", secure: process.env.NODE_ENV === "production" });
  return response;
}
