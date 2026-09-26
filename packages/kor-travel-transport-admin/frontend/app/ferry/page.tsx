import { PageHeader } from "@/components/admin-shell";
import { TransportReferenceList } from "@/components/transport-reference-list";

export default function FerryPage() { return <><PageHeader title="배편" description="항구를 여러 곳 선택해 오늘부터 10일간의 저장 운항편을 비교합니다. 검색은 외부 API를 호출하지 않습니다." /><TransportReferenceList kind="ferry_port" /></>; }
