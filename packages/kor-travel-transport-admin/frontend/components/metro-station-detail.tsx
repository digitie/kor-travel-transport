"use client";

import { useEffect, useState } from "react";
import { dateTime, serviceTime, transportGet, type Place } from "@/lib/journey";
import { RefreshCw } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@kor-travel/ui/select";
import { Button } from "@kor-travel/ui/button";
import { clockSeconds, dayNames, metroDestinationGroups, type MetroTimetable, type MetroTimetableResponse } from "@/lib/metro-timetable";

type SummaryProps = {
  station: Place; data?: MetroTimetableResponse; loading?: boolean; failed?: boolean; refresh: () => void;
  period: string; onPeriod: (value: string) => void; timetablePage?: boolean; initialView?: "all" | "ends";
};
type DestinationGroup = ReturnType<typeof metroDestinationGroups>[number];

export function MetroStationSummary({ station, data, loading = false, failed = false, refresh, period, onPeriod, timetablePage = false, initialView = "all" }: SummaryProps) {
  const [expanded, setExpanded] = useState<"all" | "ends" | null>(timetablePage ? initialView : null);
  const table = data?.items.find(item => item.code_id === station.id);
  const groups = table ? metroDestinationGroups(table) : [];
  const local = data ? new Date(Date.parse(data.generated_at) + 9 * 3600000) : null;
  const seconds = local && Number.isFinite(local.getTime()) ? local.getUTCHours() * 3600 + local.getUTCMinutes() * 60 + local.getUTCSeconds() : 0;
  const canShowNext = !loading && !failed && data?.basis === "calendar" && !table?.stale && (!table?.collection_status || table.collection_status === "stored");
  return <section className="metro-station-sheet" aria-label={station.name + " 역 정보"} aria-busy={loading}>
    <header className="metro-station-heading"><span>{station.line_names.join(" · ")}</span><strong>{station.name}</strong><small>{station.subtitle}</small></header>
    <div className="metro-station-toolbar"><span className="metro-mode">예정 시간표</span><small>실시간 도착 정보가 아닙니다.</small><Button type="button" className="inline-link" disabled={loading} aria-label="역 시간표 새로고침" onClick={refresh}><RefreshCw aria-hidden="true" /></Button></div>
    <MetroDayControl period={period} onPeriod={onPeriod} dayCode={data?.day_code} />
    <MetroNotices loading={loading} failed={failed} data={data} table={table} />
    <div className="metro-destination-grid">{groups.map(group => <MetroDestinationCard key={group.name} group={group} canShowNext={canShowNext} seconds={seconds} />)}</div>
    <MetroScheduleActions station={station} timetablePage={timetablePage} expanded={expanded} setExpanded={setExpanded} />
    {expanded === "all" ? <MetroAllSchedule table={table} groups={groups} /> : null}
    {expanded === "ends" ? <MetroEndsSchedule groups={groups} /> : null}
    <MetroAmenities station={station} />
    <MetroSource station={station} table={table} />
  </section>;
}

function MetroDayControl({ period, onPeriod, dayCode }: Pick<SummaryProps, "period" | "onPeriod"> & { dayCode?: MetroTimetableResponse["day_code"] }) {
  return <div className="metro-day-select"><span>운행 기준</span><Select value={period || "today"} onValueChange={value => onPeriod(value === "today" ? "" : value)}><SelectTrigger aria-label="운행 기준"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="today">오늘</SelectItem><SelectItem value="8">평일</SelectItem><SelectItem value="7">토요일</SelectItem><SelectItem value="9">휴일</SelectItem></SelectContent></Select>{dayCode ? <small>{dayNames[dayCode]}</small> : null}</div>;
}

function MetroNotices({ loading, failed, data, table }: Pick<SummaryProps, "loading" | "failed" | "data"> & { table?: MetroTimetable }) {
  return <>
    {loading ? <p role="status">저장 시간표 조회 중…</p> : failed ? <p role="alert">시간표를 불러오지 못했습니다. 새로고침해 주세요.</p> : null}
    {data?.basis === "calendar_unavailable" ? <p className="quiet">공휴일 확인이 필요합니다. 운행 기준을 선택해 주세요.</p> : data?.basis === "overnight_unresolved" ? <p className="quiet">새벽 운행일은 확인이 필요합니다. 운행 기준을 선택해 주세요.</p> : null}
    {table?.stale ? <p className="quiet">24시간이 지난 저장본입니다. 이후 예정은 표시하지 않습니다.</p> : null}
    {table?.collection_status === "no_data" ? <p className="quiet">최근 조회에서 제공기관이 시간표를 제공하지 않았습니다. 이전 저장본이 있으면 아래에 표시합니다. 운행이 없다는 뜻은 아닙니다.</p> : table?.collection_status === "error" ? <p className="quiet">최근 수집에 실패했습니다. 이전 저장본을 참고해 주세요.</p> : table?.collection_status === "pending" ? <p className="quiet">최근 수집 결과가 아직 확정되지 않았습니다.</p> : null}
    {table && table.status !== "stored" ? <p className="quiet">{table.status === "day_unresolved" ? "선택한 운행 기준을 확인해 주세요." : "저장 시간표가 아직 없습니다. 운행이 없다는 뜻은 아닙니다."}</p> : null}
    {table?.status === "stored" && !table.items.length ? <p className="quiet">마지막 정상 응답에 시간표가 없습니다. 운행 중단을 의미하지 않습니다.</p> : null}
  </>;
}

function MetroDestinationCard({ group, canShowNext, seconds }: { group: DestinationGroup; canShowNext: boolean; seconds: number }) {
  const next = canShowNext ? group.rows.filter(row => { const time = clockSeconds(row.departure_time); return time !== null && time >= seconds && time >= 5 * 3600 && time < 24 * 3600; }).slice(0, 2) : [];
  return <section className="metro-destination" aria-label={group.name + " 예정 " + (group.arrivalOnly ? "도착" : "출발")}><h4>{group.name}{group.arrivalOnly ? " 도착" : group.name !== "행선지 미제공" ? "행" : ""}</h4>
    {next.length ? next.map(row => <div key={JSON.stringify(row)}><span>{serviceTime(row.departure_time)}</span><strong>{Math.ceil((clockSeconds(row.departure_time)! - seconds) / 60)}분 후 예정</strong></div>) : <p className="quiet">{group.arrivalOnly ? "아래 도착 시각 참고" : canShowNext ? "이후 예정 시각 없음" : "아래 저장 시간표 참고"}</p>}
  </section>;
}

function MetroScheduleActions({ station, timetablePage, expanded, setExpanded }: Pick<SummaryProps, "station" | "timetablePage"> & { expanded: "all" | "ends" | null; setExpanded: (value: "all" | "ends") => void }) {
  return <div className="metro-timetable-actions">{timetablePage ? <><Button type="button" aria-expanded={expanded === "all"} onClick={() => setExpanded("all")}>전체 시간표</Button><Button type="button" aria-expanded={expanded === "ends"} onClick={() => setExpanded("ends")}>첫차·막차</Button></> : <><a className="button secondary" href={"/rail/timetable?mode=metro&station=" + station.id}>전체 시간표</a><a className="button secondary" href={"/rail/timetable?mode=metro&station=" + station.id + "&view=ends"}>첫차·막차</a></>}</div>;
}

function MetroAllSchedule({ table, groups }: { table?: MetroTimetable; groups: DestinationGroup[] }) {
  return <section className="metro-expanded" aria-label="전체 예정 시간표"><h4>전체 예정 시간표</h4>{table?.items.length ? <div className="metro-all-timetable">{groups.map(group => <section key={group.name}><h5>{group.name}{group.arrivalOnly ? " 도착" : ""}</h5>{group.rows.map(row => <div className="metro-schedule-row" key={JSON.stringify(row)}><strong>{serviceTime(row.departure_time || row.arrival_time)}</strong><span>{row.departure_time ? "출발 · " : row.arrival_time ? "도착 · " : ""}{row.train_number ?? "열차번호 미제공"}</span></div>)}</section>)}</div> : <p className="quiet">표시할 저장 시간표가 없습니다.</p>}</section>;
}

function MetroEndsSchedule({ groups }: { groups: DestinationGroup[] }) {
  return <section className="metro-expanded" aria-label="저장표 첫차 막차"><h4>첫차·막차</h4><p className="quiet">저장표의 시각 순서입니다. 자정 이후 운행일 연장은 운영기관에 확인해 주세요.</p>{groups.map(group => {
    const valid = group.rows.filter(row => clockSeconds(row.departure_time || row.arrival_time) !== null);
    return <div className="metro-schedule-row" key={group.name}><span>{group.name}{group.arrivalOnly ? " · 도착 시각 범위" : ""}</span><strong>{valid.length ? serviceTime(valid[0].departure_time || valid[0].arrival_time) + " ~ " + serviceTime(valid.at(-1)?.departure_time || valid.at(-1)?.arrival_time) : "시각 미제공"}</strong></div>;
  })}</section>;
}

function MetroAmenities({ station }: Pick<SummaryProps, "station">) {
  return <section className="metro-information metro-amenities" aria-label="역 편의정보"><h3>역 편의정보</h3>
    {station.facilities.length ? <ul>{station.facilities.map(facility => <li key={facility}><span>{facility}</span><strong aria-label={facility + " 있음"}>O</strong></li>)}</ul> : <p className="quiet">편의시설 미제공</p>}
    <dl className="metro-station-contact"><div><dt>역 주소</dt><dd>{station.address || "미제공"}</dd></div><div><dt>역 연락처</dt><dd>{station.phone ? <a className="inline-link" href={"tel:" + station.phone.replace(/[^+\d]/g, "")}>{station.phone}</a> : "미제공"}</dd></div></dl>
  </section>;
}

function MetroSource({ station, table }: Pick<SummaryProps, "station"> & { table?: MetroTimetable }) {
  return <details className="metro-source"><summary>역 안내 · 출처</summary><p>KRIC 공식 코드 {station.provider_id}</p>{table?.source_name ? <p>시간표 {table.source_name}{table.time_precision === "minute" ? " · 분 단위 시각" : ""}</p> : null}{table?.collected_at ? <p>시간표 저장 {dateTime(table.collected_at)}</p> : null}<p>기준정보 {dateTime(station.updated_at)}</p></details>;
}

export function MetroStationDetail({station,timetablePage=false,initialView="all"}: {station:Place;timetablePage?:boolean;initialView?:"all"|"ends"}) {
  const [period,setPeriod]=useState(""); const [revision,setRevision]=useState(0);
  const key=`${station.id}/${period}/${revision}`;
  const [state,setState]=useState<{key:string;data?:MetroTimetableResponse;failed?:boolean}>({key:""});
  useEffect(()=>{
    const controller=new AbortController();const params=new URLSearchParams();if(period)params.set("day_code",period);
    transportGet<MetroTimetableResponse>(`transport/rail/stations/${station.id}/timetable?${params}`,controller.signal)
      .then(data=>{if(!controller.signal.aborted)setState({key,data});})
      .catch(()=>{if(!controller.signal.aborted)setState({key,failed:true});});
    return ()=>controller.abort();
  },[station.id,period,key]);
  useEffect(()=>{const timer=setInterval(()=>{if(document.visibilityState==="visible")setRevision(v=>v+1);},60_000);return()=>clearInterval(timer);},[]);
  const current=state.key===key?state:undefined;
  return <MetroStationSummary station={station} data={current?.data} failed={current?.failed} loading={!current} refresh={()=>setRevision(v=>v+1)} period={period} onPeriod={setPeriod} timetablePage={timetablePage} initialView={initialView}/>;
}
