import { PageHeader } from "@/components/admin-shell";
import { TransportMap } from "@/components/transport-map";

export default function MapPage() { return <><PageHeader title="교통 지도" description="저장된 주유소·철도역·항구 위치와 여행 이동 정보를 지도에서 확인합니다." /><TransportMap /></>; }
