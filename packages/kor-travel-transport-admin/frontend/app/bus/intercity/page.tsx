import { PAGE_HEADINGS } from "@/components/admin-nav";
import { PageHeader } from "@/components/admin-shell";
import { BusJourney } from "@/components/bus-journey";
export default function Page() { return <><PageHeader {...PAGE_HEADINGS["/bus/intercity"]} /><BusJourney type="intercity" /></>; }
