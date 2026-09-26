"use client";
import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import { dateTime, seoulDate, transportGet, type Place } from "@/lib/journey";
import { MultiSearch, PlaceDetails } from "./journey-controls";
const TransportMap = dynamic(() => import("./transport-map").then((module) => module.TransportMap), { ssr: false });
type Flight = { flight_number: string; direction: string; airline: string | null; scheduled_at: string; estimated_at: string | null; origin_airport: string; destination_airport: string; status: string | null };
type Parking = { parking_lot_name: string; available_spaces: number; total_spaces: number; observed_at: string };
export function FlightJourney() {
  const [items, setItems] = useState<Place[]>([]);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Place | null>(null);
  const [flights, setFlights] = useState<Flight[] | null>(null);
  const [parking, setParking] = useState<Parking[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [direction, setDirection] = useState("");
  const [filter, setFilter] = useState("");
  const request = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    transportGet<{ items: Place[] }>("transport/features/places?kind=airport&include_unlocated=true", controller.signal).then((data) => { if (!controller.signal.aborted) setItems(data.items); }).catch(() => { if (!controller.signal.aborted) setError("공항 목록을 불러오지 못했습니다."); });
    return () => { controller.abort(); request.current?.abort(); };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    if (selected?.provider_id) transportGet<{ items: Parking[] }>(`parking/current?airport_code=${encodeURIComponent(selected.provider_id)}`, controller.signal).then((data) => { if (!controller.signal.aborted) setParking(data.items); }).catch(() => { if (!controller.signal.aborted) setError("주차 현황을 불러오지 못했습니다."); });
    return () => controller.abort();
  }, [selected]);
  function select(place: Place | null) { request.current?.abort(); setLoading(false); setSelected(place); setFlights(null); setParking([]); setError(""); }
  async function load() {
    if (!selected?.provider_id) return;
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    setLoading(true); setError("");
    try {
      const data = await transportGet<{ items: Flight[]; status: string; error_message: string | null }>(`flights/status?airport_code=${encodeURIComponent(selected.provider_id)}&local_date=${seoulDate()}`, controller.signal);
      if (!controller.signal.aborted) { setFlights(data.items); if (data.error_message) setError("제공기관의 항공편 조회가 지연되거나 일부 자료가 없습니다. 잠시 후 다시 조회해 주세요."); }
    } catch { if (!controller.signal.aborted) setError("항공편 정보를 불러오지 못했습니다."); }
    finally { if (!controller.signal.aborted) setLoading(false); }
  }
  const rows = flights?.filter((row) => (!direction || row.direction === direction) && [row.flight_number, row.airline, row.origin_airport, row.destination_airport].join(" ").includes(filter));
  return <section className="journey-layout">
    <div className="journey-search"><MultiSearch label="공항 검색" query={query} onQuery={setQuery} options={items.filter((item) => item.name.includes(query)).map((item) => ({ id: String(item.id), name: item.name }))} selected={selected ? [{ id: String(selected.id), name: selected.name }] : []} max={1} onSelect={(id) => select(selected?.id === Number(id) ? null : items.find((item) => item.id === Number(id)) ?? null)} /></div>
    <div className="journey-inspector">{error ? <p className="error" role="alert">{error}</p> : null}{selected ? <><PlaceDetails place={selected} /><div className="journey-toolbar"><button type="button" className="button" disabled={loading} onClick={() => void load()}>{loading ? "항공편 확인 중…" : "오늘 출도착 조회"}</button><label>방향<select value={direction} onChange={(event) => setDirection(event.target.value)}><option value="">전체</option><option value="departure">출발</option><option value="arrival">도착</option></select></label><label>항공편 검색<input type="search" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="편명·항공사·목적지" /></label></div>
      <div aria-live="polite">{rows?.map((row, index) => <article className="departure-row" key={index}><div className="departure-time"><strong>{new Date(row.estimated_at ?? row.scheduled_at).toLocaleTimeString("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hour12: false })}</strong><span>{row.flight_number}</span></div><div className="departure-route"><strong>{row.origin_airport} → {row.destination_airport}</strong><small>{row.airline}</small></div><div className="departure-meta"><strong>{row.status ?? "상태 미제공"}</strong><small>예정 {dateTime(row.scheduled_at)}</small></div></article>)}{rows && !rows.length ? <p className="empty-state">조건에 맞는 등록 항공편이 없습니다.</p> : null}</div><h3>공항 주차 현황</h3>{parking.length ? parking.map((row) => <div className="departure-row" key={row.parking_lot_name}><strong>{row.parking_lot_name}</strong><span>여유 {row.available_spaces.toLocaleString()} / {row.total_spaces.toLocaleString()}면</span><small>{dateTime(row.observed_at)}</small></div>) : <p className="quiet">저장된 주차 관측이 없습니다.</p>}</> : <p className="empty-state">공항을 선택하면 주차 현황과 출도착 조회를 이용할 수 있습니다.</p>}</div>
    <div className="journey-map"><TransportMap places={items} selectedPlace={selected} onSelectPlace={select} /></div>
  </section>;
}
