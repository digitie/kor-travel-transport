import { PageHeader } from "@/components/admin-shell";
import { FlightJourney } from "@/components/flight-journey";
export default function Page() { return <><PageHeader title="비행·공항" description="공항 위치, 오늘의 출도착 예정과 저장된 주차 현황을 확인합니다." /><FlightJourney /></>; }
