import type { NextRequest } from "next/server";

import { SESSION_COOKIE, verifySessionValue } from "./session";

export async function hasAdminSession(request: NextRequest) {
  return verifySessionValue(request.cookies.get(SESSION_COOKIE)?.value);
}
