import Link from "next/link";
import { PAGE_HEADINGS } from "@/components/admin-nav";
import { PageHeader } from "@/components/admin-shell";
import { FuelStatisticsPage } from "@/components/fuel-statistics";
import { buttonVariants } from "@/components/ui/button-variants";

export default function Page() {
  return <><PageHeader {...PAGE_HEADINGS["/fuel/statistics"]} actions={<Link className={buttonVariants({ variant: "outline", size: "sm" })} href="/fuel">유가 지도</Link>} /><FuelStatisticsPage /></>;
}
