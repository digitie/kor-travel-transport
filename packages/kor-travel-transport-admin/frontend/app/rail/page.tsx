import { PAGE_HEADINGS } from "@/components/admin-nav";
import { PageHeader } from "@/components/admin-shell";
import { GeneralRailJourney } from "@/components/general-rail-journey";

export default function RailPage() { return <><PageHeader {...PAGE_HEADINGS["/rail"]} /><GeneralRailJourney mapWorkspace /></>; }
