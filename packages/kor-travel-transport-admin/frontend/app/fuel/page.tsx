import { PageHeader } from "@/components/admin-shell";
import { TransportDashboard } from "@/components/transport-dashboard";

export default function FuelPage() { return <><PageHeader title="유가 수집" description="최신 python-opinet-api Playwright 수집 결과의 저장 상태를 확인합니다." /><TransportDashboard /></>; }
