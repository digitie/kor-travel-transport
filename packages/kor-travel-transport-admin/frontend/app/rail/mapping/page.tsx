import { PageHeader } from "@/components/admin-shell";
import { RailStationMapping } from "@/components/rail-station-mapping";

export default function RailMappingPage() {
  return <><PageHeader title="지하철역 코드 매핑" description="KRIC 역 코드와 저장된 역 기준정보를 대조하고, 미연결 항목을 수동으로 보정합니다." /><RailStationMapping /></>;
}
