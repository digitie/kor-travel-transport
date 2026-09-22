import { PageHeader } from "@/components/admin-shell";
import { TransportReferenceList } from "@/components/transport-reference-list";

export default function RailPage() { return <><PageHeader title="열차·도시철도" description="KRIC 파일 수집으로 저장한 역 위치와 운영 노선을 조회합니다." /><TransportReferenceList kind="rail_station" /></>; }
