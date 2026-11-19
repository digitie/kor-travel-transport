import { PAGE_HEADINGS } from "@/components/admin-nav";
import { PageHeader } from "@/components/admin-shell";
import { CollectionStatus } from "@/components/collection-status";
export default function Page() { return <><PageHeader {...PAGE_HEADINGS["/collections"]} /><CollectionStatus /></>; }
