import { PageHeader } from "@/components/admin-shell";
import { TransportDashboard } from "@/components/transport-dashboard";

export default function FuelPage() { return <><PageHeader title="교통·유가 현황" description="이전 유가 주소도 통합 교통·유가 화면을 유지합니다." /><TransportDashboard /></>; }
