import { PAGE_HEADINGS } from "@/components/admin-nav";
import { PageHeader } from "@/components/admin-shell";
import { HighwayStatistics } from "@/components/highway-statistics";
export default function Page() { return <><PageHeader {...PAGE_HEADINGS["/highways/statistics"]} /><HighwayStatistics /></>; }
