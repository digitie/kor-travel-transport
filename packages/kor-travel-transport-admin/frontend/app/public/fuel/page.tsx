import type { Metadata } from "next";
import { Suspense } from "react";
import { notFound } from "next/navigation";
import { PublicFuelMap } from "@/components/public-fuel-map";
import { publicFuelRefreshConfiguration } from "@/lib/public-fuel-proxy";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: { absolute: "주변 유가 지도" }, description: "주변 주유소 유가 지도",
  // app/favicon.ico/route.ts가 fuel 모드에서만 내는 주유기 아이콘.
  icons: { icon: [{ url: "/favicon.ico", sizes: "16x16 32x32 48x48", type: "image/x-icon" }] },
};
export default function PublicFuelPage() {
  if (process.env.TRANSPORT_UI_MODE !== "fuel") notFound();
  // 지도는 주소의 유종(`?product=`)을 useSearchParams로 읽는다. 요청마다 그리는 화면(force-dynamic)이라 서버 렌더에서 멈추지 않는다.
  return <Suspense fallback={null}><PublicFuelMap refreshEnabled={Boolean(publicFuelRefreshConfiguration())} /></Suspense>;
}
