import { PageHeader } from "@/components/admin-shell";
import { BusJourney } from "@/components/bus-journey";
export default function Page() { return <><PageHeader title="고속버스" description="터미널을 검색해 출발·도착 예정 시각과 등급별 요금을 비교합니다." /><BusJourney type="express" /></>; }
