"use client";

import { useEffect, useState } from "react";
import { dateTime, serviceTime, transportGet } from "@/lib/journey";

type Departure = { train_number: string | null; departure_time: string | null; arrival_time: string | null; origin_name: string | null; destination_name: string | null };
type Table = { place_id: number; station_name: string; line_name: string | null; status: "unlinked" | "not_collected" | "stored"; collected_at: string | null; stale: boolean; next_departure: Departure | null; items: Departure[] };
type Response = { generated_at: string; day_code: "7" | "8" | "9" | null; basis: "calendar" | "selected_period" | "calendar_unavailable" | "overnight_unresolved"; items: Table[] };
const dayNames = { "7": "토요일", "8": "평일", "9": "휴일" };

export function RailTimetables({ placeIds }: { placeIds: number[] }) {
  const ids = placeIds.join(",");
  const [period, setPeriod] = useState("");
  const [reload, setReload] = useState(0);
  const [state, setState] = useState<{ key: string; data?: Response; error?: boolean }>({ key: "" });
  const key = `${ids}/${period}/${reload}`;
  useEffect(() => {
    if (!ids) return;
    const controller = new AbortController();
    const params = new URLSearchParams({ place_ids: ids });
    if (period) params.set("day_code", period);
    transportGet<Response>(`transport/rail/timetables?${params}`, controller.signal)
      .then((data) => { if (!controller.signal.aborted) setState({ key, data }); })
      .catch(() => { if (!controller.signal.aborted) setState({ key, error: true }); });
    return () => controller.abort();
  }, [ids, period, key]);
  // 다음 예정은 저장 시간표를 현재 시각과 비교한 값이다. 외부 KRIC 호출은 발생하지 않는다.
  useEffect(() => {
    const timer = setInterval(() => { if (document.visibilityState === "visible") setReload((value) => value + 1); }, 60_000);
    return () => clearInterval(timer);
  }, []);
  if (!ids) return null;
  const current = state.key === key ? state : null;
  const data = current?.data;
  return <section aria-label="도시철도 예정 시간표">
    <div className="journey-toolbar"><h3>예정 시간표</h3><label>시간표 기준<select value={period} onChange={(event) => setPeriod(event.target.value)}><option value="">오늘 · 공휴일 확인</option><option value="8">평일</option><option value="7">토요일</option><option value="9">휴일</option></select></label>
      <button type="button" className="secondary" disabled={!current} onClick={() => setReload((value) => value + 1)}>시간표 새로고침</button></div>
    {!current ? <p role="status">저장된 예정 시간표를 확인하는 중입니다…</p> : null}
    {current?.error ? <p className="error" role="alert">시간표를 불러오지 못했습니다. 시간표 새로고침으로 다시 확인해 주세요.</p> : null}
    {data?.basis === "calendar_unavailable" ? <p className="data-caveat">공휴일을 확인하지 못했습니다. 평일·토요일·휴일을 직접 선택해 저장 시간표를 확인해 주세요.</p> : null}
    {data?.basis === "overnight_unresolved" ? <p className="data-caveat">새벽 운행일은 확인이 필요합니다. 평일·토요일·휴일 시간표를 선택해 참고해 주세요.</p> : null}
    {data?.items.map((table) => <section className="departures" key={table.place_id} aria-label={`${table.station_name} 예정 출발`}>
      <header><h4>{table.station_name} · {table.line_name}</h4><p className="quiet">{data.day_code ? dayNames[data.day_code] : "운행일 미확정"} 기준 · 실시간 도착 정보가 아닙니다.</p></header>
      {table.status === "unlinked" ? <p className="empty-state">공식 역사 코드와 위치 정보가 아직 연결되지 않았습니다. 역명만으로 시간표를 추정하지 않습니다.</p> : table.status === "not_collected" ? <p className="empty-state">선택한 기준의 저장 시간표가 아직 없습니다. 운행편이 없다는 뜻은 아닙니다.</p> : <>
        {table.stale ? <p className="data-caveat">48시간이 지난 저장본입니다. 다음 열차로 표시하지 않으며 아래 계획 시간표만 제공합니다.</p> : null}
        {table.next_departure ? <div className="departure-row"><strong>다음 예정 {serviceTime(table.next_departure.departure_time)}</strong><span>{table.next_departure.destination_name ? `${table.next_departure.destination_name}행` : "행선지 미제공"}</span><span>{table.next_departure.train_number} 열차</span></div> : data.basis === "calendar" && !table.stale && table.items.length ? <p className="quiet">지금 이후의 당일 예정 시각이 확인되지 않습니다. 막차 운행 여부는 운영기관에 확인해 주세요.</p> : null}
        {!table.items.length ? <p className="empty-state">제공기관의 마지막 정상 응답에 시간표가 없습니다. 운행 중단을 의미하지 않습니다.</p> : <details><summary>전체 예정 시간표 {table.items.length}편</summary>{table.items.map((row, index) => <article className="departure-row" key={`${row.train_number}/${index}`}><div className="departure-time"><strong>{serviceTime(row.departure_time)}</strong><span>{row.train_number ?? "열차번호 미제공"}</span></div><div className="departure-route"><strong>{row.destination_name ? `${row.destination_name}행` : "행선지 미제공"}</strong><small>{row.origin_name ? `${row.origin_name} 출발 열차` : "기점 미제공"}</small></div></article>)}</details>}
        <p className="quiet">저장 시각 {dateTime(table.collected_at)}</p>
      </>}
    </section>)}
    {data ? <p className="quiet">조회 {dateTime(data.generated_at)} · KRIC 제공 예정 시각이며 변경·지연은 반영되지 않을 수 있습니다.</p> : null}
  </section>;
}
