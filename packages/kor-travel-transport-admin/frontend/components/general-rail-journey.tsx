"use client";
import { useEffect, useId, useState } from "react";
import { ArrowLeftRight, RefreshCw } from "lucide-react";
import { dateTime, money, seoulDate, serviceInstant, serviceTime, transportGet } from "@/lib/journey";
import { generalRailStations, uniqueStationByName, type RailStation, type RailCatalog } from "@/lib/general-rail";
import { useSeoulToday } from "@/lib/journey-hooks";
import { MapFilterBar, MapFilterField } from "@kor-travel/ui/map-controls";
import { Button } from "./ui/button";
import { RailStationPicker } from "./rail-station-picker";

type Trips = { fetched_at:string; stale:boolean; service_date:string; total:number|null; truncated:boolean; items:{train_number:string|null;grade_name:string|null;departure_station_name:string|null;arrival_station_name:string|null;departure_planned_time:string|null;arrival_planned_time:string|null;adult_fare:number|null}[] };

export function GeneralRailJourney({initialDepartureName="",compact=false}:{initialDepartureName?:string;compact?:boolean}) {
  const id=useId(), today=useSeoulToday();
  const [reference,setReference]=useState<{catalog:RailCatalog;stations:RailStation[];stale:boolean;incomplete:boolean}|null>(null);
  const [referenceError,setReferenceError]=useState("");
  const [revision,setRevision]=useState(0);
  const [departure,setDeparture]=useState<RailStation|null>(null), [arrival,setArrival]=useState<RailStation|null>(null);
  const [date,setDate]=useState(seoulDate), [grade,setGrade]=useState("");
  const [futureOnly,setFutureOnly]=useState(true),[view,setView]=useState<"all"|"ends">("all");
  const [clock,setClock]=useState(()=>Date.now());
  const [request,setRequest]=useState<{key:string;revision:number}|null>(null);
  const [result,setResult]=useState<{key:string;data?:Trips;error?:string}>({key:""});
  const effectiveDate=date&&date<today?today:date;
  const key=JSON.stringify([departure?.station_id,arrival?.station_id,effectiveDate,grade]);
  useEffect(()=>{
    const controller=new AbortController();
    generalRailStations(controller.signal).then(data=>{if(!controller.signal.aborted){setReference(data);setReferenceError("");if(initialDepartureName)setDeparture(uniqueStationByName(data.stations,initialDepartureName));}}).catch(reason=>{if(!controller.signal.aborted)setReferenceError(reason instanceof Error?reason.message:"역 목록 조회 실패");});
    return()=>controller.abort();
  },[revision,initialDepartureName]);
  useEffect(()=>{
    if(!request||request.key!==key||!departure||!arrival)return;
    const controller=new AbortController();
    const params=new URLSearchParams({departure_station_id:departure.station_id,arrival_station_id:arrival.station_id,date:effectiveDate,...(grade?{train_grade_code:grade}:{})});
    transportGet<Trips>(`transport/rail/general/timetable?${params}`,controller.signal).then(data=>{if(!controller.signal.aborted)setResult({key,data});}).catch(reason=>{if(!controller.signal.aborted)setResult({key,error:reason instanceof Error?reason.message:"시간표 조회 실패"});});
    return()=>controller.abort();
  },[request,key,departure,arrival,effectiveDate,grade]);
  useEffect(()=>{const timer=setInterval(()=>setClock(Date.now()),30_000);return()=>clearInterval(timer);},[]);
  const current=result.key===key?result:undefined;
  const loading=Boolean(request?.key===key&&!current);
  const trips=current?.data;
  const sorted=[...(trips?.items??[])].sort((a,b)=>(serviceInstant(a.departure_planned_time,trips!.service_date)??Infinity)-(serviceInstant(b.departure_planned_time,trips!.service_date)??Infinity));
  const filtered=sorted.filter(row=>!futureOnly||(serviceInstant(row.departure_planned_time,trips!.service_date)??-Infinity)>=clock);
  const timed=sorted.filter(row=>serviceInstant(row.departure_planned_time,trips!.service_date)!==null);
  const rows=view==="ends"?(timed.length>1?[timed[0],timed[timed.length-1]]:timed):filtered;
  return <section className="rail-timetable-page" aria-label="일반철도 예정 시간표">
    {referenceError?<p role="alert">{referenceError} <Button variant="outline" onClick={()=>setRevision(v=>v+1)}>다시 조회</Button></p>:!reference?<p role="status">전체 역 목록을 불러오는 중…</p>:null}
    {reference?.stale?<p className="quiet">이전 저장 역 목록입니다.</p>:null}
    {reference?.incomplete?<p role="status">일부 지역 역 목록을 불러오지 못했습니다. 확인된 역만 표시합니다.</p>:null}
    <div className="journey-data-grid"><RailStationPicker id={`${id}-departure`} label="출발역" stations={reference?.stations??[]} value={departure} onChange={setDeparture} disabled={!reference}/><RailStationPicker id={`${id}-arrival`} label="도착역" stations={reference?.stations??[]} value={arrival} onChange={setArrival} disabled={!reference}/></div>
    <MapFilterBar><Button variant="outline" aria-label="출발역 도착역 바꾸기" onClick={()=>{setDeparture(arrival);setArrival(departure);}}><ArrowLeftRight aria-hidden="true"/>바꾸기</Button><MapFilterField label="출발일" htmlFor={`${id}-date`}><input id={`${id}-date`} type="date" min={today} max={seoulDate(9)} value={effectiveDate} onChange={event=>setDate(event.target.value)}/></MapFilterField><MapFilterField label="열차 종류" htmlFor={`${id}-grade`}><select id={`${id}-grade`} value={grade} onChange={event=>setGrade(event.target.value)}><option value="">모든 열차</option>{reference?.catalog.train_classes.map(row=><option key={row.code} value={row.code}>{row.name}</option>)}</select></MapFilterField><Button disabled={!departure||!arrival||departure.station_id===arrival.station_id||!effectiveDate||loading} onClick={()=>{setResult({key:""});setRequest({key,revision:Date.now()});}}><RefreshCw aria-hidden="true"/>{loading?"조회 중…":"예정 시간표 조회"}</Button></MapFilterBar>
    {compact?<a className="inline-link" href={`/rail/timetable?mode=general&departure=${encodeURIComponent(departure?.station_name??initialDepartureName)}`}>전체 화면에서 시간표 조회</a>:null}
    <p className="quiet">예정 시각·성인 요금 · 하루 1회 갱신한 저장본 · 실시간 지연·잔여 좌석은 제공하지 않습니다.</p>
    {loading?<p role="status">시간표를 조회하는 중입니다…</p>:current?.error?<p role="alert">{current.error}</p>:null}
    <div className="metro-timetable-actions"><Button variant={view==="all"?"default":"outline"} aria-pressed={view==="all"} onClick={()=>setView("all")}>전체 시간표</Button><Button variant={view==="ends"?"default":"outline"} aria-pressed={view==="ends"} onClick={()=>setView("ends")}>첫차·막차</Button></div>
    {view==="all"?<label className="inline-checkbox"><input type="checkbox" checked={futureOnly} onChange={event=>setFutureOnly(event.target.checked)}/>지금 이후만</label>:null}
    {trips?<section aria-label={view==="ends"?"저장표 첫차 막차":"전체 예정 시간표"}><h3>{departure?.station_name} → {arrival?.station_name}</h3><p className="quiet">{trips.service_date} · 저장 {dateTime(trips.fetched_at)}{trips.stale?" · 이전 저장본": ""}{trips.truncated?" · 일부 결과":""}</p>{rows.map((row,index)=><article className="departure-row" key={`${row.train_number}/${index}`}><div><strong>{serviceTime(row.departure_planned_time,trips.service_date)}</strong><p>{row.departure_station_name}</p></div><div><strong>{row.grade_name??"종류 미제공"} {row.train_number}</strong><p>{row.arrival_station_name} · {serviceTime(row.arrival_planned_time,row.departure_planned_time??trips.service_date)}</p></div><strong>{money(row.adult_fare)}</strong></article>)}{!rows.length?<p className="quiet">{trips.items.length?"지금 이후 예정편이 없습니다. 전체 시간표를 확인해 주세요.":"정상 응답에 운행편이 없습니다. 미운행 확정은 아닙니다."}</p>:null}</section>:!loading?<p className="quiet">출발·도착역을 선택해 시간표를 조회하세요.</p>:null}
  </section>;
}
