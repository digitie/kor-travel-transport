import { PAGE_HEADINGS } from "@/components/admin-nav";
import { PageHeader } from "@/components/admin-shell";
import { RailTimetableWorkbench } from "@/components/rail-timetable-workbench";

export default async function Page({searchParams}:{searchParams:Promise<{mode?:string;station?:string;departure?:string;view?:string;guide_id?:string;guide_name?:string;guide_role?:string}>}) {
  const params=await searchParams;
  return <><PageHeader {...PAGE_HEADINGS["/rail/timetable"]}/><RailTimetableWorkbench mode={params.mode==="metro"?"metro":"general"} stationId={params.station} departureName={params.departure} initialStationIntent={params.guide_id&&params.guide_name&&(params.guide_role==="departure"||params.guide_role==="arrival")?{role:params.guide_role,station:{provider:"korail_public_guide",provider_id:params.guide_id,name:params.guide_name}}:undefined} initialView={params.view==="ends"?"ends":"all"}/></>;
}
