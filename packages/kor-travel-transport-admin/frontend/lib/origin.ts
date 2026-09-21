import type { NextRequest } from "next/server";

function normalizeOrigin(value: string) {
  try {
    const parsed = new URL(value);
    if (parsed.username || parsed.password || parsed.pathname !== "/" || parsed.search || parsed.hash) return null;
    return parsed.origin;
  } catch {
    return null;
  }
}

export function isAllowedOrigin(request: NextRequest) {
  const origin = normalizeOrigin(request.headers.get("origin") ?? "");
  if (!origin) return false;
  const configured = (process.env.TRANSPORT_UI_PUBLIC_ORIGINS ?? process.env.TRANSPORT_UI_PUBLIC_ORIGIN ?? "")
    .split(",")
    .map((value) => normalizeOrigin(value.trim()))
    .filter((value): value is string => Boolean(value));
  return configured.length ? configured.includes(origin) : process.env.NODE_ENV !== "production" && origin === request.nextUrl.origin;
}
