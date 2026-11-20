import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE } from "@/lib/session";

const PUBLIC_PATHS = new Set(["/login"]);

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (process.env.TRANSPORT_UI_MODE === "fuel") {
    const api = pathname.startsWith("/api/public/fuel/");
    const allowed = pathname === "/" || pathname === "/public/fuel" || api
      || pathname.startsWith("/_next/") || pathname.startsWith("/maplibre/")
      || pathname.startsWith("/fuel-brands/") || pathname === "/favicon.ico";
    if (!allowed) return new NextResponse(null, { status: 404 });
    if (!["GET", "HEAD", ...(api ? ["OPTIONS"] : [])].includes(request.method)) {
      return new NextResponse(null, { status: 405, headers: { Allow: api ? "GET, HEAD, OPTIONS" : "GET, HEAD" } });
    }
    if (pathname === "/") {
      const target = request.nextUrl.clone(); target.pathname = "/public/fuel";
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
