import { PageHeader } from "@/components/admin-shell";
import { GeneralRailJourney } from "@/components/general-rail-journey";

export default function RailPage() { return <><PageHeader title="철도" description="지도에서 역을 선택하고 예정 시간표와 요금을 확인합니다." /><GeneralRailJourney mapWorkspace /></>; }
