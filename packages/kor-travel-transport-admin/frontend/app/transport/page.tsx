import { PageHeader } from "@/components/admin-shell";
import { TransportDashboard } from "@/components/transport-dashboard";

export default function TransportPage() { return <><PageHeader title="교통 수집" description="provider 호출이 아니라 마지막으로 저장된 정규화 스냅샷을 조회합니다." /><TransportDashboard /></>; }
