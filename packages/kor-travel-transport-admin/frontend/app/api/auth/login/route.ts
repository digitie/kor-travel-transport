import { NextRequest, NextResponse } from "next/server";

import { isAllowedOrigin } from "@/lib/origin";
import { sanitizeLocalPath } from "@/lib/navigation";
import { clearFailedLogins, loginClientKey, loginRateLimited, recordFailedLogin } from "@/lib/rate-limit";
import { SESSION_COOKIE, SESSION_MAX_AGE, adminUsername, configuredPassword, createSessionValue, loginIsConfigured } from "@/lib/session";

function equal(left: string, right: string) {
  const a = new TextEncoder().encode(left); const b = new TextEncoder().encode(right); let difference = a.length ^ b.length;
  for (let index = 0; index < Math.max(a.length, b.length); index += 1) difference |= (a[index % a.length] ?? 0) ^ (b[index % b.length] ?? 0);
  return difference === 0;
}

export async function POST(request: NextRequest) {
  if (!isAllowedOrigin(request)) return NextResponse.json({ detail: "허용되지 않은 요청입니다." }, { status: 403 });
  if (!loginIsConfigured()) return NextResponse.json({ detail: "로그인 환경변수가 안전하게 설정되지 않았습니다." }, { status: 503 });
  const key = loginClientKey(request.headers);
  if (loginRateLimited(key)) return NextResponse.json({ detail: "로그인 시도가 너무 많습니다. 잠시 후 다시 시도하세요." }, { status: 429 });
  const body = await request.json().catch(() => null) as { username?: unknown; password?: unknown; next?: unknown } | null;
  const username = typeof body?.username === "string" ? body.username : ""; const password = typeof body?.password === "string" ? body.password : "";
  if (!equal(username, adminUsername()) || !equal(password, configuredPassword())) { recordFailedLogin(key); return NextResponse.json({ detail: "아이디 또는 비밀번호가 올바르지 않습니다." }, { status: 401 }); }
  clearFailedLogins(key);
  const next = sanitizeLocalPath(body?.next); const response = NextResponse.json({ next });
  response.cookies.set(SESSION_COOKIE, await createSessionValue(adminUsername()), { httpOnly: true, maxAge: SESSION_MAX_AGE, path: "/", sameSite: "strict", secure: process.env.NODE_ENV === "production" });
  return response;
}
