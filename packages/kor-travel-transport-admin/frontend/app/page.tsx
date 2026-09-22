import { PageHeader } from "@/components/admin-shell";
import { TransportDashboard } from "@/components/transport-dashboard";

export default function HomePage() { return <><PageHeader title="통합 교통정보 현황" description="PostgreSQL에 저장된 고속도로·유가 수집 결과와 Dagster 예약 상태입니다." /><TransportDashboard /></>; }
