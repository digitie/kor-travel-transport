import { MapIcon } from "lucide-react";
import Link from "next/link";
import { PageHeader } from "@/components/admin-shell";
import { FuelStatisticsPage } from "@/components/fuel-statistics";
import { buttonVariants } from "@/components/ui/button-variants";

export default function Page() {
  return <><PageHeader title="유가 통계" description="수집 완료 시점의 지역·고속도로별 가격과 최근 30일 추이를 확인합니다." actions={<Link className={buttonVariants({ variant: "outline", size: "sm" })} href="/fuel"><MapIcon aria-hidden="true" data-icon="inline-start" /><span className="sr-only sm:not-sr-only">유가 지도</span></Link>} /><FuelStatisticsPage /></>;
}
