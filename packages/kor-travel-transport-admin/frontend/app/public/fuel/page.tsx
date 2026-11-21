import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PublicFuelMap } from "@/components/public-fuel-map";
import { publicFuelRefreshConfiguration } from "@/lib/public-fuel-proxy";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: { absolute: "주변 유가 지도" }, description: "주변 주유소 유가 지도" };
export default function PublicFuelPage() {
  if (process.env.TRANSPORT_UI_MODE !== "fuel") notFound();
  return <PublicFuelMap refreshEnabled={Boolean(publicFuelRefreshConfiguration())} />;
}
