import { PAGE_HEADINGS } from "@/components/admin-nav";
import { PageHeader } from "@/components/admin-shell";
import { TransportMap } from "@/components/transport-map";

export default function MapPage() { return <><PageHeader {...PAGE_HEADINGS["/map"]} /><TransportMap mode="transport" /></>; }
