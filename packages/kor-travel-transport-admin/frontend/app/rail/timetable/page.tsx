import { PageHeader } from "@/components/admin-shell";
import { RailTimetableWorkbench } from "@/components/rail-timetable-workbench";

export default async function Page({searchParams}:{searchParams:Promise<{mode?:string;station?:string;departure?:string;view?:string}>}) {
  const params=await searchParams;
  return <><PageHeader title="시간표 조회" description="역과 운행 기준을 선택하고 예정 출발·도착, 첫차·막차를 확인하세요."/><RailTimetableWorkbench mode={params.mode==="metro"?"metro":"general"} stationId={params.station} departureName={params.departure} initialView={params.view==="ends"?"ends":"all"}/></>;
}
