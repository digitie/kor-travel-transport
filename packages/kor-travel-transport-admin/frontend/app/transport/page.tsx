import { PageHeader } from "@/components/admin-shell";
import { TransportDashboard } from "@/components/transport-dashboard";

export default function TransportPage() { return <><PageHeader title="교통·유가 현황" description="고속도로와 유가의 마지막 저장 정보·통계를 한 화면에서 확인합니다." /><TransportDashboard /></>; }
