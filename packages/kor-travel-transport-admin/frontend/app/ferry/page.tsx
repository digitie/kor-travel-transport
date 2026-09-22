import { PageHeader } from "@/components/admin-shell";
import { TransportReferenceList } from "@/components/transport-reference-list";

export default function FerryPage() { return <><PageHeader title="배편" description="저장된 항구 기준정보를 먼저 조회하며, 시간표는 선택한 항구에 한해 실시간으로 확인합니다." /><TransportReferenceList kind="ferry_port" /></>; }
