import type { Metadata } from "next";
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
  return <PublicFuelMap refreshEnabled={Boolean(publicFuelRefreshConfiguration())} />;
}
