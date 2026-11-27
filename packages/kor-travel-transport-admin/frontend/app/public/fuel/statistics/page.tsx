import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PublicFuelStatisticsPage } from "@/components/public-fuel-statistics";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: { absolute: "지역별 유가 통계" }, description: "전국·시도·시군구·고속도로 평균 유가와 기간별 변화",
  icons: { icon: [{ url: "/favicon.ico", sizes: "16x16 32x32 48x48", type: "image/x-icon" }] },
};

/**
 * fuel 실행의 `/statistics`(proxy rewrite). 화면 상태는 URL query(`useSearchParams`)에서 읽는다 — 서버 렌더와 뒤로 가기로
 * 돌아온 화면 모두 현재 주소의 조건을 그린다(첫 요청의 props로 고정하지 않는다).
 */
export default function PublicFuelStatisticsRoute() {
  if (process.env.TRANSPORT_UI_MODE !== "fuel") notFound();
  return <PublicFuelStatisticsPage />;
}
