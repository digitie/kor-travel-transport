import { PageHeader } from "@/components/admin-shell";
import { MetroJourney } from "@/components/metro-journey";
export default function RailPage() { return <><PageHeader title="철도 역 찾기" description="현재 저장된 역·노선 위치와 연락처를 검색합니다. 간선열차 운행편은 일반철도 API 연동 후 제공하며, 예정 시간표는 연결된 도시철도 역만 표시됩니다." /><MetroJourney /></>; }
