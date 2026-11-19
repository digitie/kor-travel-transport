import { PAGE_HEADINGS } from "@/components/admin-nav";
import { PageHeader } from "@/components/admin-shell";
import { FlightJourney } from "@/components/flight-journey";
export default function Page() { return <><PageHeader {...PAGE_HEADINGS["/flights"]} /><FlightJourney /></>; }
