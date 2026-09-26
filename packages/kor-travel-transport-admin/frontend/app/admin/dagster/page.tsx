import { PageHeader } from "@/components/admin-shell";
import { CollectionStatus } from "@/components/collection-status";
export default function DagsterPage() { return <><PageHeader title="Dagster" description="제공기관별 수집 상태, 실행 기록, 스케줄을 확인합니다." /><CollectionStatus /></>; }
