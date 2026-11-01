"use client";
import { useEffect, useId, useState } from "react";
import { transportGet, type Place } from "@/lib/journey";
import { GeneralRailJourney } from "./general-rail-journey";
import { MetroStationDetail } from "./metro-station-detail";
import { RailStationPicker } from "./rail-station-picker";
import { Button } from "./ui/button";

export function RailTimetableWorkbench({mode,stationId,departureName,initialView}:{mode:"general"|"metro";stationId?:string;departureName?:string;initialView:"all"|"ends"}) {
  const id=useId();
  const [stations,setStations]=useState<Place[]|null>(null),[failed,setFailed]=useState(false),[revision,setRevision]=useState(0);
  const [selectedId,setSelectedId]=useState(stationId??"");
  useEffect(()=>{
    if(mode!=="metro")return;
    const controller=new AbortController();
    transportGet<{items:Place[]}>("transport/rail/stations",controller.signal).then(data=>{if(!controller.signal.aborted){setStations(data.items);setFailed(false);}}).catch(()=>{if(!controller.signal.aborted)setFailed(true);});
    return()=>controller.abort();
  },[mode,revision]);
  const selected=stations?.find(row=>String(row.id)===selectedId);
  return <div className="rail-timetable-page">
    <nav className="rail-timetable-nav" aria-label="시간표 종류"><a className="button secondary" aria-current={mode==="general"?"page":undefined} href="/rail/timetable?mode=general">철도</a><a className="button secondary" aria-current={mode==="metro"?"page":undefined} href="/rail/timetable?mode=metro">도시철도</a><a className="inline-link" href={mode==="general"?"/rail":"/rail/metro"}>역 지도</a></nav>
    {mode==="general"?<GeneralRailJourney initialDepartureName={departureName}/>:<>
      <RailStationPicker id={`${id}-station`} label="역·노선" stations={(stations??[]).map(row=>({station_id:String(row.id),station_name:`${row.name} · ${row.line_names.join(" · ")} · ${row.subtitle??""}`}))} value={selected?{station_id:String(selected.id),station_name:selected.name}:null} onChange={station=>setSelectedId(station?.station_id??"")} disabled={!stations}/>
      {failed?<p role="alert">역 목록 조회 실패 <Button variant="outline" onClick={()=>setRevision(v=>v+1)}>다시 조회</Button></p>:!stations?<p role="status">역 목록 조회 중…</p>:selected?<MetroStationDetail key={selected.id} station={selected} timetablePage initialView={initialView}/>:<p className="quiet">역을 선택해 저장 시간표를 확인하세요.</p>}
    </>}
  </div>;
}
