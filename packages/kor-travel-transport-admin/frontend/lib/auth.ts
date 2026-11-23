import type { NextRequest } from "next/server";

import { SESSION_COOKIE, verifiedSessionUser, verifySessionValue } from "./session";

export async function hasAdminSession(request: NextRequest) {
  return verifySessionValue(request.cookies.get(SESSION_COOKIE)?.value);
}

/** 검증된 관리자 세션의 사용자 이름(감사 기록용). 세션이 없거나 무효면 null. */
export async function adminSessionUser(request: NextRequest) {
  return verifiedSessionUser(request.cookies.get(SESSION_COOKIE)?.value);
}
