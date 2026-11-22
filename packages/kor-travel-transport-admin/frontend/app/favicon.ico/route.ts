import { PUBLIC_FUEL_FAVICON_BASE64 } from "@/lib/public-fuel-favicon";

// /favicon.ico: 공개 유가(fuel-web)만 아이콘을 낸다. 관리 화면은 예전처럼 404다(관리 화면 무변경).
const icon = Buffer.from(PUBLIC_FUEL_FAVICON_BASE64, "base64");

export function GET() {
  if (process.env.TRANSPORT_UI_MODE !== "fuel") return new Response(null, { status: 404 });
  return new Response(new Uint8Array(icon), {
    headers: { "Content-Type": "image/x-icon", "Cache-Control": "public, max-age=86400" },
  });
}

export const dynamic = "force-dynamic";
