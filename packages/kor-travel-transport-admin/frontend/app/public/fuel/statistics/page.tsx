import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PublicFuelStatisticsPage } from "@/components/public-fuel-statistics";
import { parseStatisticsView } from "@/lib/public-fuel-statistics";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: { absolute: "지역별 유가 통계" }, description: "전국·시도·시군구·고속도로 평균 유가와 기간별 추이",
  icons: { icon: [{ url: "/favicon.ico", sizes: "16x16 32x32 48x48", type: "image/x-icon" }] },
};

/** fuel 실행의 `/statistics`(proxy rewrite). 화면 상태는 URL query로 받아 첫 렌더부터 같은 화면을 그린다. */
export default async function PublicFuelStatisticsRoute({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  if (process.env.TRANSPORT_UI_MODE !== "fuel") notFound();
  return <PublicFuelStatisticsPage initialView={parseStatisticsView(await searchParams)} />;
}
