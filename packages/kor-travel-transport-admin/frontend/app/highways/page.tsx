import { PageHeader } from "@/components/admin-shell";
import { HighwayJourney } from "@/components/highway-journey";
export default function Page() { return <><PageHeader title="고속도로" description="ITS 도로별 속도 지도와 저장된 도로 돌발·통제, 운전 지표를 확인합니다." /><HighwayJourney /></>; }
