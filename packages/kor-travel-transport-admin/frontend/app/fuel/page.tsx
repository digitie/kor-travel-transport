import { ChartNoAxesCombinedIcon } from "lucide-react";
import Link from "next/link";
import { PAGE_HEADINGS } from "@/components/admin-nav";
import { PageHeader } from "@/components/admin-shell";
import { TransportMap } from "@/components/transport-map";
import { buttonVariants } from "@/components/ui/button-variants";

export default function FuelPage() { return <><PageHeader {...PAGE_HEADINGS["/fuel"]} actions={<Link className={buttonVariants({ variant: "outline", size: "sm" })} href="/fuel/statistics"><ChartNoAxesCombinedIcon aria-hidden="true" data-icon="inline-start" /><span className="sr-only sm:not-sr-only">유가 통계</span></Link>} /><TransportMap mode="fuel" /></>; }
