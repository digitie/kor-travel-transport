"use client";
import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import { ArrowLeftRight, RefreshCw } from "lucide-react";
import { dateTime, money, seoulDate, serviceInstant, serviceTime, transportGet } from "@/lib/journey";
import { generalRailStations, type RailStation, type RailCatalog } from "@/lib/general-rail";
import { useSeoulToday } from "@/lib/journey-hooks";
import { MapFilterBar, MapFilterField } from "@kor-travel/ui/map-controls";
import { Button } from "./ui/button";
import { Input } from "@kor-travel/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@kor-travel/ui/select";
import { GeneralRailGuide, type GeneralRailStationIntent } from "./general-rail-guide";
import { RailStationPicker } from "./rail-station-picker";
import { EmptyState } from "./empty-state";
import { Alert, AlertDescription } from "./ui/alert";
const inlineLink = "rounded-control text-sm font-medium text-brand underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";
const departureRow = "departure-row grid gap-3 border-b border-border py-3 last:border-b-0 sm:grid-cols-[8rem_minmax(0,1fr)_auto] sm:items-center";

type Trips = { fetched_at:string; stale:boolean; service_date:string; total:number|null; truncated:boolean; items:{train_number:string|null;grade_name:string|null;departure_station_name:string|null;arrival_station_name:string|null;departure_planned_time:string|null;arrival_planned_time:string|null;adult_fare:number|null}[] };

type JourneyState = ReturnType<typeof useGeneralRailJourney>;
type JourneyProps = { initialDepartureName?: string; initialStationIntent?: GeneralRailStationIntent; compact?: boolean; mapWorkspace?: boolean };

export function GeneralRailJourney({ initialDepartureName = "", initialStationIntent, compact = false, mapWorkspace = false }: JourneyProps) {
  const state = useGeneralRailJourney({ initialDepartureName, initialStationIntent });
  const { requestStation, departure } = state;
  const compactQuery = new URLSearchParams({mode: "general", ...(initialStationIntent
    ? {guide_id: initialStationIntent.station.provider_id, guide_name: initialStationIntent.station.name, guide_role: initialStationIntent.role}
    : {departure: departure?.station_name ?? initialDepartureName})});
  return <section className={mapWorkspace ? "journey-workbench map-route" : "rail-timetable-page"} aria-label="일반철도 예정 시간표">
    {mapWorkspace ? <GeneralRailGuide onStationIntent={requestStation} timetableAnchor /> : null}
    <div id={mapWorkspace ? "general-rail-timetable" : undefined} className={mapWorkspace ? "journey-map-target map-route-followup flex flex-col gap-4" : "flex flex-col gap-4"} tabIndex={-1}>
      {mapWorkspace ? <a className={inlineLink} href="#general-rail-map">지도 작업면으로</a> : null}
      {!compact && !mapWorkspace ? <GeneralRailGuideToggle state={state} /> : null}
      <GeneralRailReference state={state} />
      <GeneralRailControls state={state} />
      {compact ? <Link className={inlineLink} href={"/rail/timetable?" + compactQuery}>전체 화면에서 시간표 조회</Link> : null}
      <p className="text-sm text-text-secondary">예정 시각·성인 요금 · 하루 1회 갱신한 저장본 · 실시간 지연·잔여 좌석은 제공하지 않습니다.</p>
      <GeneralRailResults state={state} />
    </div>
  </section>;
}

function GeneralRailGuideToggle({ state }: { state: JourneyState }) {
  const { guideOpen, setGuideOpen, requestStation } = state;
  return <><Button variant="outline" aria-expanded={guideOpen} onClick={() => setGuideOpen(value => !value)}>지도에서 역 선택</Button>{guideOpen ? <GeneralRailGuide onStationIntent={requestStation} /> : null}</>;
}

function GeneralRailReference({ state }: { state: JourneyState }) {
  const { referenceError, reference, setRevision, stationSearch } = state;
  return <>
    {referenceError ? <Alert variant="destructive"><AlertDescription>{referenceError} <Button variant="outline" size="sm" onClick={() => setRevision(v => v + 1)}>다시 조회</Button></AlertDescription></Alert> : !reference ? <p role="status" className="text-sm text-text-secondary">전체 역 목록을 불러오는 중…</p> : null}
    {reference?.stale ? <p className="text-sm text-text-secondary">이전 저장 역 목록입니다.</p> : null}
    {reference?.incomplete ? <p role="status" className="text-sm text-text-secondary">일부 지역 역 목록을 불러오지 못했습니다. 확인된 역만 표시합니다.</p> : null}
    {stationSearch.departure || stationSearch.arrival ? <p className="text-sm text-text-secondary">역 안내의 이름을 검색어로 전달했습니다. 지역과 시간표 역 후보를 직접 확인해 선택하세요.</p> : null}
  </>;
}

function GeneralRailControls({ state }: { state: JourneyState }) {
  const { id, reference, stationSearch, departure, arrival, chooseDeparture, chooseArrival, clearRequest, setDeparture, setArrival, setStationSearch, today, effectiveDate, setDate, grade, setGrade, loading, setResult, setRequest, key } = state;
  const swap = () => { clearRequest(); setDeparture(arrival); setArrival(departure); setStationSearch({}); };
  const load = () => { setResult({key: ""}); setRequest({key, revision: Date.now()}); };
  return <>
    <div className="journey-data-grid grid gap-4 lg:grid-cols-2"><RailStationPicker id={id + "-departure"} label="출발역" stations={reference?.stations ?? []} value={departure} onChange={chooseDeparture} searchRequest={stationSearch.departure} disabled={!reference} /><RailStationPicker id={id + "-arrival"} label="도착역" stations={reference?.stations ?? []} value={arrival} onChange={chooseArrival} searchRequest={stationSearch.arrival} disabled={!reference} /></div>
    <MapFilterBar>
      <Button variant="outline" aria-label="출발역 도착역 바꾸기" onClick={swap}><ArrowLeftRight aria-hidden="true" />바꾸기</Button>
      <MapFilterField label="출발일" htmlFor={id + "-date"}><Input id={id + "-date"} type="date" min={today} max={seoulDate(9)} value={effectiveDate} onChange={event => { clearRequest(); setDate(event.target.value); }} /></MapFilterField>
      <MapFilterField label="열차 종류" htmlFor={id + "-grade"}><Select value={grade || "all"} onValueChange={value => { clearRequest(); setGrade(value === "all" ? "" : value); }}><SelectTrigger id={id + "-grade"} aria-label="열차 종류"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">모든 열차</SelectItem>{reference?.catalog.train_classes.map(row => <SelectItem key={row.code} value={row.code}>{row.name}</SelectItem>)}</SelectContent></Select></MapFilterField>
      <Button disabled={!departure || !arrival || departure.station_id === arrival.station_id || !effectiveDate || loading} onClick={load}><RefreshCw aria-hidden="true" />{loading ? "조회 중…" : "예정 시간표 조회"}</Button>
    </MapFilterBar>
  </>;
}

function GeneralRailResults({ state }: { state: JourneyState }) {
  const { loading, current, view, setView, futureOnly, setFutureOnly, trips } = state;
  return <>
    {loading ? <p role="status" className="text-sm text-text-secondary">시간표를 조회하는 중입니다…</p> : current?.error ? <Alert variant="destructive"><AlertDescription>{current.error}</AlertDescription></Alert> : null}
    <div className="metro-timetable-actions flex flex-wrap gap-2"><Button variant={view === "all" ? "default" : "outline"} aria-pressed={view === "all"} onClick={() => setView("all")}>전체 시간표</Button><Button variant={view === "ends" ? "default" : "outline"} aria-pressed={view === "ends"} onClick={() => setView("ends")}>첫차·막차</Button></div>
    {view === "all" ? <label className="inline-checkbox flex items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-brand" checked={futureOnly} onChange={event => setFutureOnly(event.target.checked)} />지금 이후만</label> : null}
    {trips ? <GeneralRailTripList state={state} trips={trips} /> : !loading ? <p className="text-sm text-text-secondary">출발·도착역을 선택해 시간표를 조회하세요.</p> : null}
  </>;
}

function GeneralRailTripList({ state, trips }: { state: JourneyState; trips: Trips }) {
  const { view, departure, arrival, rows } = state;
  return <section className="flex flex-col gap-2" aria-label={view === "ends" ? "저장표 첫차 막차" : "전체 예정 시간표"}>
    <h3 className="text-sm font-semibold text-text-primary">{departure?.station_name} → {arrival?.station_name}</h3>
    <p className="text-sm text-text-secondary">{trips.service_date} · 저장 {dateTime(trips.fetched_at)}{trips.stale ? " · 이전 저장본" : ""}{trips.truncated ? " · 일부 결과" : ""}</p>
    {rows.map(row => <article className={departureRow} key={JSON.stringify([row.train_number, row.departure_planned_time, row.arrival_planned_time, row.departure_station_name, row.arrival_station_name])}><div className="flex flex-col gap-0.5"><strong className="text-base tabular-nums">{serviceTime(row.departure_planned_time, trips.service_date)}</strong><p className="text-sm text-text-secondary">{row.departure_station_name}</p></div><div className="flex flex-col gap-0.5"><strong className="text-sm">{row.grade_name ?? "종류 미제공"} {row.train_number}</strong><p className="text-sm text-text-secondary">{row.arrival_station_name} · {serviceTime(row.arrival_planned_time, row.departure_planned_time ?? trips.service_date)}</p></div><strong className="text-sm tabular-nums">{money(row.adult_fare)}</strong></article>)}
    {!rows.length ? <EmptyState size="sm" title={trips.items.length ? "지금 이후 예정편이 없습니다. 전체 시간표를 확인해 주세요." : "정상 응답에 운행편이 없습니다. 미운행 확정은 아닙니다."} /> : null}
  </section>;
}

function useGeneralRailJourney({ initialDepartureName, initialStationIntent }: { initialDepartureName: string; initialStationIntent?: GeneralRailStationIntent }) {
  const id=useId(), today=useSeoulToday();
  const [reference,setReference]=useState<{catalog:RailCatalog;stations:RailStation[];stale:boolean;incomplete:boolean}|null>(null);
  const intentRevision=useRef(1);
  const [guideOpen,setGuideOpen]=useState(false);
  // 초기 이름 채움은 검색어 전달이며, 명시적 역 지정만 자동 초점을 요청한다.
  const [stationSearch,setStationSearch]=useState<Partial<Record<"departure"|"arrival",{revision:number;text:string}>>>(()=>initialStationIntent?{[initialStationIntent.role]:{revision:1,text:initialStationIntent.station.name}}:initialDepartureName?{departure:{revision:0,text:initialDepartureName}}:{});
  const [referenceError,setReferenceError]=useState("");
  const [revision,setRevision]=useState(0);
  const [departure,setDeparture]=useState<RailStation|null>(null), [arrival,setArrival]=useState<RailStation|null>(null);
  const [date,setDate]=useState(seoulDate), [grade,setGrade]=useState("");
  const [futureOnly,setFutureOnly]=useState(true),[view,setView]=useState<"all"|"ends">("all");
  const [clock,setClock]=useState(()=>Date.now());
  const [request,setRequest]=useState<{key:string;revision:number}|null>(null);
  const [result,setResult]=useState<{key:string;data?:Trips;error?:string}>({key:""});
  function clearRequest(){setRequest(null);setResult({key:""});}
  function chooseDeparture(station:RailStation|null){clearRequest();setDeparture(station);}
  function chooseArrival(station:RailStation|null){clearRequest();setArrival(station);}
  function requestStation(intent:GeneralRailStationIntent){
    clearRequest();
    if(intent.role==="departure")setDeparture(null);else setArrival(null);
    const revision = ++intentRevision.current;
    setStationSearch(previous=>({...previous,[intent.role]:{revision,text:intent.station.name}}));
  }
  const effectiveDate=date&&date<today?today:date;
  const key=JSON.stringify([departure?.station_id,arrival?.station_id,effectiveDate,grade]);
  useEffect(()=>{
    const controller=new AbortController();
    generalRailStations(controller.signal).then(data=>{if(!controller.signal.aborted){setReference(data);setReferenceError("");}}).catch(reason=>{if(!controller.signal.aborted)setReferenceError(reason instanceof Error?reason.message:"역 목록 조회 실패");});
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

  return { id, today, reference, referenceError, setRevision, stationSearch, departure, arrival, chooseDeparture, chooseArrival, effectiveDate, setDate, grade, setGrade, loading, clearRequest, setDeparture, setArrival, setStationSearch, setResult, setRequest, key, view, setView, futureOnly, setFutureOnly, current, trips, rows, guideOpen, setGuideOpen, requestStation };
}
