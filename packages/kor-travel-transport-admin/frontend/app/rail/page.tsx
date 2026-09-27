import { PageHeader } from "@/components/admin-shell";
import { TransportReferenceList } from "@/components/transport-reference-list";

export default function RailPage() { return <><PageHeader title="열차·도시철도" description="저장된 역·노선과 도시철도 예정 시간표를 비교합니다. 일반철도 운행편은 별도 연동 대상입니다." /><TransportReferenceList kind="rail_station" /></>; }
