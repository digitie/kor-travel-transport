import { PageHeader } from "@/components/admin-shell";
import { HighwayJourney } from "@/components/highway-journey";
export default function Page() { return <><PageHeader title="고속도로" description="노선을 검색해 저장된 구간 속도와 도로 돌발·통제 정보를 비교합니다." /><HighwayJourney /></>; }
