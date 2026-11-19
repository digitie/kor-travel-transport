import { PAGE_HEADINGS } from "@/components/admin-nav";
import { PageHeader } from "@/components/admin-shell";
import { AddressRefresh } from "@/components/address-refresh";
import { DagsterOperations } from "@/components/dagster-operations";

export default function DagsterPage() {
  return <>
    <PageHeader {...PAGE_HEADINGS["/admin/dagster"]} />
    <AddressRefresh />
    <DagsterOperations />
  </>;
}
