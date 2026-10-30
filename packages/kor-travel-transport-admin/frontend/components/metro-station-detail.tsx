"use client";

import { useEffect, useState } from "react";
import { dateTime, serviceTime, transportGet, type Place } from "@/lib/journey";

export type MetroDeparture = { train_number: string | null; departure_time: string | null; arrival_time: string | null; origin_name: string | null; destination_name: string | null };
export type MetroTimetable = { place_id: number | null; code_id?: number | null; station_name: string; line_name: string | null; status: "stored" | "unlinked" | "not_collected" | "day_unresolved"; collected_at: string | null; stale: boolean; items: MetroDeparture[] };
export type MetroTimetableResponse = { generated_at: string; day_code: "7" | "8" | "9" | null; basis: "calendar" | "selected_period" | "calendar_unavailable" | "overnight_unresolved"; items: MetroTimetable[] };
const dayNames = { "7": "토요일", "8": "평일", "9": "휴일" };
function clockSeconds(value: string | null) {
  if (!value || !/^[0-2][0-9][0-5][0-9][0-5][0-9]$/.test(value)) return null;
  return Number(value.slice(0, 2)) * 3600 + Number(value.slice(2, 4)) * 60 + Number(value.slice(4));
}
export function metroDestinationGroups(table: MetroTimetable) {
  const groups = new Map<string, MetroDeparture[]>();
  for (const row of table.items) {
    const name = row.destination_name || "행선지 미제공";
    const group = groups.get(name) ?? []; group.push(row); groups.set(name, group);
  }
  return [...groups].map(([name, rows]) => ({name, rows: rows.sort((a,b) => (clockSeconds(a.departure_time) ?? Infinity) - (clockSeconds(b.departure_time) ?? Infinity))}));
}

export function MetroStationSummary({ station, data, loading = false, failed = false, refresh, period, onPeriod }: {
  station: Place; data?: MetroTimetableResponse; loading?: boolean; failed?: boolean; refresh: () => void;
  period: string; onPeriod: (value: string) => void;
}) {
  const [expanded, setExpanded] = useState<"all" | "ends" | null>(null);
  const table = data?.items.find(item => item.code_id === station.id);
  const groups = table ? metroDestinationGroups(table) : [];
  const local = data ? new Date(Date.parse(data.generated_at) + 9 * 3600000) : null;
  const seconds = local && Number.isFinite(local.getTime()) ? local.getUTCHours()*3600 + local.getUTCMinutes()*60 + local.getUTCSeconds() : 0;
  const canShowNext = !loading && !failed && data?.basis === "calendar" && !table?.stale;
  return <section className="metro-station-sheet" aria-label={`${station.name} 역 정보`} aria-busy={loading}>
    <header className="metro-station-heading"><span>{station.line_names.join(" · ")}</span><strong>{station.name}</strong><small>{station.subtitle}</small></header>
    <div className="metro-station-toolbar"><span className="metro-mode">예정 시간표</span><small>실시간 도착 정보가 아닙니다.</small><button type="button" className="inline-link" disabled={loading} aria-label="역 시간표 새로고침" onClick={refresh}>↻</button></div>
    <label className="metro-day-select">운행 기준 <select value={period} onChange={e => onPeriod(e.target.value)}><option value="">오늘</option><option value="8">평일</option><option value="7">토요일</option><option value="9">휴일</option></select>{data?.day_code ? <small>{dayNames[data.day_code]}</small> : null}</label>
    {loading ? <p role="status">저장 시간표 조회 중…</p> : failed ? <p role="alert">시간표를 불러오지 못했습니다. 새로고침해 주세요.</p> : null}
    {data?.basis === "calendar_unavailable" ? <p className="quiet">공휴일 확인이 필요합니다. 운행 기준을 선택해 주세요.</p> : data?.basis === "overnight_unresolved" ? <p className="quiet">새벽 운행일은 확인이 필요합니다. 운행 기준을 선택해 주세요.</p> : null}
    {table?.stale ? <p className="quiet">48시간이 지난 저장본입니다. 이후 예정은 표시하지 않습니다.</p> : null}
    {table && table.status !== "stored" ? <p className="quiet">{table.status === "day_unresolved" ? "선택한 운행 기준을 확인해 주세요." : "저장 시간표가 아직 없습니다. 운행이 없다는 뜻은 아닙니다."}</p> : null}
    <div className="metro-destination-grid">{groups.map(group => {
      const next = canShowNext ? group.rows.filter(row => {const time=clockSeconds(row.departure_time);return time !== null && time >= seconds && time >= 5*3600 && time < 24*3600;}).slice(0,2) : [];
      return <section className="metro-destination" key={group.name} aria-label={`${group.name} 예정 출발`}><h4>{group.name}{group.name !== "행선지 미제공" ? "행" : ""}</h4>{next.length ? next.map((row,i) => <div key={`${row.train_number}/${i}`}><span>{serviceTime(row.departure_time)}</span><strong>{Math.ceil((clockSeconds(row.departure_time)!-seconds)/60)}분 후 예정</strong></div>) : <p className="quiet">{canShowNext ? "이후 예정 시각 없음" : "아래 저장 시간표 참고"}</p>}</section>;
    })}</div>
    {table?.status === "stored" && !table.items.length ? <p className="quiet">마지막 정상 응답에 시간표가 없습니다. 운행 중단을 의미하지 않습니다.</p> : null}
    <div className="metro-timetable-actions"><button type="button" aria-expanded={expanded==="all"} onClick={()=>setExpanded(expanded==="all"?null:"all")}>◷ 전체 시간표</button><button type="button" aria-expanded={expanded==="ends"} onClick={()=>setExpanded(expanded==="ends"?null:"ends")}>첫차·막차</button></div>
    {expanded === "all" ? <section className="metro-expanded" aria-label="전체 예정 시간표"><h4>전체 예정 시간표</h4>{table?.items.length ? <div className="metro-all-timetable">{groups.map(group=><section key={group.name}><h5>{group.name}</h5>{group.rows.map((row,i)=><div className="metro-schedule-row" key={`${row.train_number}/${i}`}><strong>{serviceTime(row.departure_time)}</strong><span>{row.train_number ?? "열차번호 미제공"}</span></div>)}</section>)}</div> : <p className="quiet">표시할 저장 시간표가 없습니다.</p>}</section> : null}
    {expanded === "ends" ? <section className="metro-expanded" aria-label="저장표 첫차 막차"><h4>첫차·막차</h4><p className="quiet">저장표의 시각 순서입니다. 자정 이후 운행일 연장은 운영기관에 확인해 주세요.</p>{groups.map(group => {const valid=group.rows.filter(row=>clockSeconds(row.departure_time)!==null);return <div className="metro-schedule-row" key={group.name}><span>{group.name}</span><strong>{serviceTime(valid[0]?.departure_time)} ~ {serviceTime(valid.at(-1)?.departure_time)}</strong></div>;})}</section> : null}
    <section className="metro-information"><h3>노선도</h3><p className="quiet">제공기관의 노선 순서 자료가 아직 없습니다.</p></section>
    <section className="metro-information"><h3>출구정보</h3><p className="quiet">출구별 안내 자료가 아직 없습니다.</p></section>
    <details className="metro-source"><summary>역 안내 · 출처</summary>{station.address ? <p>{station.address}</p> : null}{station.phone ? <a href={`tel:${station.phone.replace(/[^+\d]/g, "")}`}>{station.phone}</a> : null}<p>KRIC 공식 코드 {station.provider_id}</p>{table?.collected_at ? <p>시간표 저장 {dateTime(table.collected_at)}</p> : null}<p>기준정보 {dateTime(station.updated_at)}</p></details>
  </section>;
}

export function MetroStationDetail({station}: {station:Place}) {
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
  return <MetroStationSummary station={station} data={current?.data} failed={current?.failed} loading={!current} refresh={()=>setRevision(v=>v+1)} period={period} onPeriod={setPeriod}/>;
}
