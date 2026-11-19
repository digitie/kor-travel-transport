import { MapIcon } from "lucide-react";
import Link from "next/link";
import { PAGE_HEADINGS } from "@/components/admin-nav";
import { PageHeader } from "@/components/admin-shell";
import { FuelStatisticsPage } from "@/components/fuel-statistics";
import { buttonVariants } from "@/components/ui/button-variants";

export default function Page() {
  return <><PageHeader {...PAGE_HEADINGS["/fuel/statistics"]} actions={<Link className={buttonVariants({ variant: "outline", size: "sm" })} href="/fuel"><MapIcon aria-hidden="true" data-icon="inline-start" /><span className="sr-only sm:not-sr-only">유가 지도</span></Link>} /><FuelStatisticsPage /></>;
}
