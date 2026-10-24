import { PageHeader } from "@/components/admin-shell";
import { GeneralRailJourney } from "@/components/general-rail-journey";

export default function RailPage() { return <><PageHeader title="철도" description="열차 종류와 출발·도착역을 선택해 일반철도 예정 시간표와 요금을 확인합니다." /><GeneralRailJourney /></>; }
