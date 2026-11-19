import { PAGE_HEADINGS } from "@/components/admin-nav";
import { PageHeader } from "@/components/admin-shell";
import { MetroJourney } from "@/components/metro-journey";
export default function Page() { return <><PageHeader {...PAGE_HEADINGS["/rail/metro"]} /><MetroJourney /></>; }
