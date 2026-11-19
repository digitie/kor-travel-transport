import { PAGE_HEADINGS } from "@/components/admin-nav";
import { PageHeader } from "@/components/admin-shell";
import { HighwayJourney } from "@/components/highway-journey";
export default function Page() { return <><PageHeader {...PAGE_HEADINGS["/highways"]} /><HighwayJourney /></>; }
