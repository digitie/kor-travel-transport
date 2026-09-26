import { PageHeader } from "@/components/admin-shell";
import { BusJourney } from "@/components/bus-journey";
export default function Page() { return <><PageHeader title="시외버스" description="출발·도착 터미널을 검색하고 오늘의 운행편을 확인합니다." /><BusJourney type="intercity" /></>; }
