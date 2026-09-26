import { PageHeader } from "@/components/admin-shell";
import { TransportReferenceList } from "@/components/transport-reference-list";

export default function FerryPage() { return <><PageHeader title="배편" description="저장된 항구 기준정보와 오늘 포함 10일 운항시간표를 조회합니다. 누락된 항구·운항일만 provider에서 보충합니다." /><TransportReferenceList kind="ferry_port" /></>; }
