import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE } from "@/lib/session";

const PUBLIC_PATHS = new Set(["/login"]);

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (process.env.TRANSPORT_UI_MODE === "fuel") {
    const api = pathname.startsWith("/api/public/fuel/");
    const allowed = pathname === "/" || pathname === "/public/fuel" || pathname === "/statistics" || pathname === "/public/fuel/statistics" || api
      || pathname.startsWith("/_next/") || pathname.startsWith("/maplibre/")
      || pathname.startsWith("/fuel-brands/") || pathname === "/favicon.ico";
    if (!allowed) return new NextResponse(null, { status: 404 });
    const methods = pathname === "/api/public/fuel/refresh" ? ["POST", "OPTIONS"] : ["GET", "HEAD", ...(api ? ["OPTIONS"] : [])];
    if (!methods.includes(request.method)) {
      return new NextResponse(null, { status: 405, headers: { Allow: methods.join(", ") } });
    }
    // 공개 주소는 `/`(지도)와 `/statistics`(지역별 통계)다. 실제 page는 /public/fuel 아래에 있다.
    if (pathname === "/" || pathname === "/statistics") {
      const target = request.nextUrl.clone(); target.pathname = pathname === "/" ? "/public/fuel" : "/public/fuel/statistics";
      return NextResponse.rewrite(target);
    }
    return NextResponse.next();
  }
  if (pathname.startsWith("/api/") || pathname.startsWith("/_next/") || PUBLIC_PATHS.has(pathname)) {
    return NextResponse.next();
  }
  if (request.cookies.has(SESSION_COOKIE)) return NextResponse.next();
  const loginUrl = new URL("/login", request.url);
  loginUrl.searchParams.set("next", `${pathname}${request.nextUrl.search}`);
  return NextResponse.redirect(loginUrl);
}

export const config = { matcher: ["/((?!favicon.ico).*)"] };
