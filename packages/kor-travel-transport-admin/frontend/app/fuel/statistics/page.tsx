import Link from "next/link";
import { PageHeader } from "@/components/admin-shell";
import { FuelStatisticsPage } from "@/components/fuel-statistics";

export default function Page() {
  return <><PageHeader title="유가 통계" description="수집 완료 시점의 지역·고속도로별 가격과 최근 7일 추이를 확인합니다." actions={<Link href="/fuel">유가 지도</Link>} /><FuelStatisticsPage /></>;
}
