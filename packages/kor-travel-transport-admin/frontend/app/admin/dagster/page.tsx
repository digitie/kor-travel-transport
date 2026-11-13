import { PageHeader } from "@/components/admin-shell";
import { AddressRefresh } from "@/components/address-refresh";
import { DagsterOperations } from "@/components/dagster-operations";

export default function DagsterPage() {
  return <>
    <PageHeader title="Dagster" description="자동 수집 작업의 실행 기록과 스케줄을 확인합니다. 제공기관별 저장 범위는 수집 상태 메뉴에서 확인하세요." />
    <AddressRefresh />
    <DagsterOperations />
  </>;
}
