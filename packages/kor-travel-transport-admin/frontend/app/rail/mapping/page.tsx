import { PAGE_HEADINGS } from "@/components/admin-nav";
import { PageHeader } from "@/components/admin-shell";
import { RailStationMapping } from "@/components/rail-station-mapping";

export default function RailMappingPage() {
  return <><PageHeader {...PAGE_HEADINGS["/rail/mapping"]} /><RailStationMapping /></>;
}
