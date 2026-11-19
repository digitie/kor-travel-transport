import Link from "next/link";
import { PAGE_HEADINGS } from "@/components/admin-nav";
import { PageHeader } from "@/components/admin-shell";
import { TransportMap } from "@/components/transport-map";
import { buttonVariants } from "@/components/ui/button-variants";

export default function FuelPage() { return <><PageHeader {...PAGE_HEADINGS["/fuel"]} actions={<Link className={buttonVariants({ variant: "outline", size: "sm" })} href="/fuel/statistics">유가 통계</Link>} /><TransportMap mode="fuel" /></>; }
