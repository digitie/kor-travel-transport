import { PageHeader } from "@/components/admin-shell";
import { CollectionStatus } from "@/components/collection-status";
export default function Page() { return <><PageHeader title="수집 상태" description="모든 제공기관의 연결·수집 상태와 Dagster 실행 기록을 확인합니다. 활성 설정과 실제 수집 성공을 구분합니다." /><CollectionStatus /></>; }
