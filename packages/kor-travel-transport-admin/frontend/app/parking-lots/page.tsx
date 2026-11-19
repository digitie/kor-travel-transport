import { PAGE_HEADINGS } from "@/components/admin-nav";
import { PageHeader } from "@/components/admin-shell";
import { PublicParkingLots } from "@/components/public-parking-lots";

export default function ParkingLotsPage() {
  return <><PageHeader {...PAGE_HEADINGS["/parking-lots"]} /><PublicParkingLots /></>;
}
