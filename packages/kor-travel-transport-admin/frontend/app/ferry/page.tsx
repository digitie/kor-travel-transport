import { PAGE_HEADINGS } from "@/components/admin-nav";
import { PageHeader } from "@/components/admin-shell";
import { TransportReferenceList } from "@/components/transport-reference-list";
import { FerryReference } from "@/components/ferry-reference";

export default function FerryPage() { return <><PageHeader {...PAGE_HEADINGS["/ferry"]} /><TransportReferenceList kind="ferry_port"><FerryReference /></TransportReferenceList></>; }
