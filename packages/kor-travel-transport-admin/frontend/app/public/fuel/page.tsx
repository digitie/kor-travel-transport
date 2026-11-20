import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PublicFuelMap } from "@/components/public-fuel-map";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: { absolute: "주변 유가 지도" }, description: "현재 지도 범위와 내 위치 주변의 주유소 가격을 확인합니다." };
export default function PublicFuelPage() {
  if (process.env.TRANSPORT_UI_MODE !== "fuel") notFound();
  return <PublicFuelMap />;
}
