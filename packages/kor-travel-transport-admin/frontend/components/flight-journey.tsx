"use client";
import dynamic from "next/dynamic";
import { useEffect, useId, useState } from "react";
import { MapFilterBar, MapFilterField } from "@kor-travel/ui/map-controls";
import { dateTime, transportGet, type Place } from "@/lib/journey";
import { useSeoulToday } from "@/lib/journey-hooks";
import { StatStrip } from "./stat-strip";
import { SectionCard } from "./section-card";
import { Input } from "./ui/input";
const TransportMap = dynamic(() => import("./transport-map").then((module) => module.TransportMap), { ssr: false });

type Flight = { flight_number: string; direction: string; airline: string | null; scheduled_at: string; estimated_at: string | null; origin_airport: string; destination_airport: string; status: string | null };
type Flights = { items: Flight[]; status: string; error_message: string | null };
type Parking = { parking_lot_id: number; parking_lot_name: string; available_spaces: number; total_spaces: number; observed_at: string; terminal?: string | null };
type Resource<T> = { key: string; data?: T; error?: string };
const flightMoment = (row: Flight) => Date.parse(row.estimated_at ?? row.scheduled_at);
export function FlightJourney() {
  const id = useId();
  const today = useSeoulToday();
  const [items, setItems] = useState<Place[]>([]);
  const [selected, setSelected] = useState<Place | null>(null);
  const [catalogError, setCatalogError] = useState("");
  const [catalogLoaded, setCatalogLoaded] = useState(false);
  const [flightState, setFlights] = useState<Resource<Flights>>({ key: "" });
  const [parkingState, setParking] = useState<Resource<Parking[]>>({ key: "" });
  const [direction, setDirection] = useState("");
  const [filter, setFilter] = useState("");
  const [futureOnly, setFutureOnly] = useState(true);
  const [reload, setReload] = useState(0);
  const [clock, setClock] = useState(() => Date.now());
  const airport = selected?.provider_id ?? "";
  const key = `${airport}/${today}/${reload}`;
  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    transportGet<{ items: Place[] }>("transport/features/places?kind=airport&include_unlocated=true", controller.signal).then((data) => {
      if (controller.signal.aborted) return;
      setItems(data.items); setCatalogLoaded(true);
      let preferred = new URLSearchParams(window.location.search).get("airport");
      try { preferred ??= window.localStorage.getItem("transport-last-airport"); } catch { /* 저장소 접근은 선택 사항이다. */ }
      setSelected(data.items.find((item) => item.provider_id === preferred) ?? data.items.find((item) => item.provider_id === "GMP") ?? data.items[0] ?? null);
    }).catch(() => { if (!controller.signal.aborted) { setCatalogLoaded(true); setCatalogError("공항 목록을 불러오지 못했습니다."); } });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!airport) return;
    const controller = new AbortController();
    transportGet<{ items: Parking[] }>(`parking/current?airport_code=${encodeURIComponent(airport)}`, controller.signal)
      .then((data) => { if (!controller.signal.aborted) setParking({ key, data: data.items }); })
      .catch(() => { if (!controller.signal.aborted) setParking({ key, error: "주차 현황을 불러오지 못했습니다." }); });
    transportGet<Flights>(`flights/status?airport_code=${encodeURIComponent(airport)}&local_date=${today}`, controller.signal)
      .then((data) => { if (!controller.signal.aborted) setFlights({ key, data }); })
      .catch(() => { if (!controller.signal.aborted) setFlights({ key, error: "항공편 정보를 불러오지 못했습니다." }); });
    return () => controller.abort();
  }, [airport, today, key]);
  function select(place: Place) { setSelected(place); try { window.localStorage.setItem("transport-last-airport", place.provider_id ?? ""); } catch { /* 선택을 메모리에 유지한다. */ } }
  const unavailable = catalogError ? "공항 목록을 확인하지 못했습니다." : catalogLoaded ? "저장된 공항이 없습니다." : "공항 목록을 확인하는 중입니다…";
  const parking = parkingState.key === key ? parkingState.data : undefined;
  const flights = flightState.key === key ? flightState.data : undefined;
  const rows = flights?.items.filter((row) => (!direction || row.direction === direction) && (!futureOnly || flightMoment(row) >= clock) && [row.flight_number, row.airline, row.origin_airport, row.destination_airport].join(" ").toLocaleLowerCase().includes(filter.toLocaleLowerCase())).sort((a, b) => flightMoment(a) - flightMoment(b));
  const freshParking = parking?.filter((row) => clock - Date.parse(row.observed_at) >= 0 && clock - Date.parse(row.observed_at) <= 15 * 60_000);
  const errors = [catalogError, parkingState.key === key ? parkingState.error : null, flightState.key === key ? flightState.error : null].filter(Boolean);
  return <section className="journey-workbench flight-journey">
    <nav className="journey-shortcuts" aria-label="공항 화면 바로가기"><a href="#airport-map">공항 지도</a><a href="#airport-flights">이후 항공편</a></nav>
    <MapFilterBar><MapFilterField label="공항" htmlFor={`${id}-airport`}><select id={`${id}-airport`} value={selected?.id ?? ""} onChange={(event) => { const place = items.find((item) => item.id === Number(event.target.value)); if (place) select(place); }}>{!selected ? <option value="">공항 선택</option> : null}{items.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></MapFilterField><button type="button" className="secondary" onClick={() => setReload((value) => value + 1)}>주차·항공편 새로고침</button></MapFilterBar>
    {errors.map((error) => <p key={error} role="alert">{error}</p>)}
    <SectionCard title="지금 주차할 곳" description={`${selected?.name ?? "공항"} · 최근 15분 관측만 현재 잔여 합계에 포함합니다.`}>
      <StatStrip items={[
        { label: "확인된 잔여 주차면", value: freshParking?.length ? freshParking.reduce((sum, row) => sum + row.available_spaces, 0) : null, unit: "면", caption: freshParking ? `${freshParking.length}개 주차장 기준` : parkingState.key === key && parkingState.error ? "조회 실패" : airport ? "조회 중" : unavailable },
        { label: "오늘 이후 출발", value: flights && ["success", "sample"].includes(flights.status) ? flights.items.filter((row) => row.direction === "departure" && flightMoment(row) >= clock).length : null, unit: "편" },
        { label: "오늘 이후 도착", value: flights && ["success", "sample"].includes(flights.status) ? flights.items.filter((row) => row.direction === "arrival" && flightMoment(row) >= clock).length : null, unit: "편" },
      ]} />
      {parking ? parking.length ? <div className="parking-lots">{parking.map((row) => <article key={row.parking_lot_id}><strong>{row.parking_lot_name}</strong><span>{row.terminal}</span><p>잔여 <strong>{row.available_spaces.toLocaleString()}</strong> / {row.total_spaces.toLocaleString()}면</p><small>{clock - Date.parse(row.observed_at) > 15 * 60_000 ? "갱신 지연 · " : ""}{dateTime(row.observed_at)}</small></article>)}</div> : <p>저장된 주차 관측이 없습니다.</p> : parkingState.error && parkingState.key === key ? null : <p role="status">{airport ? "주차 현황을 확인하는 중입니다…" : unavailable}</p>}
    </SectionCard>
    <div id="airport-flights" className="journey-map-target"><SectionCard title="오늘 출도착 항공편" description="공항 선택 시 자동 조회합니다. 예정 시각보다 변경 예정 시각을 우선해 정렬합니다.">
      <MapFilterBar><MapFilterField label="방향" htmlFor={`${id}-direction`}><select id={`${id}-direction`} value={direction} onChange={(event) => setDirection(event.target.value)}><option value="">출발·도착 전체</option><option value="departure">출발</option><option value="arrival">도착</option></select></MapFilterField><MapFilterField label="항공편 검색" htmlFor={`${id}-flight`}><Input id={`${id}-flight`} type="search" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="편명·항공사·목적지" /></MapFilterField><label className="inline-checkbox"><input type="checkbox" checked={futureOnly} onChange={(event) => setFutureOnly(event.target.checked)} />지금 이후만</label></MapFilterBar>
      {flights?.status === "sample" ? <p role="status">예시 항공편 자료입니다. 실제 운항편이 아닙니다.</p> : null}
      {flights && (!["success", "sample"].includes(flights.status) || flights.error_message) ? <p role="alert">{{ disabled: "항공편 조회가 비활성화되어 있습니다.", config_error: "항공편 조회 설정을 확인해야 합니다.", rate_limited: "제공기관 호출 제한으로 조회를 보류했습니다.", upstream_error: "제공기관의 항공편 정보를 확인하지 못했습니다." }[flights.status] ?? "항공편 응답을 확인하지 못했습니다."}</p> : flights ? <div aria-live="polite">{rows?.map((row, index) => <article className="departure-row" key={index}><div className="departure-time"><strong>{new Date(row.estimated_at ?? row.scheduled_at).toLocaleTimeString("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hour12: false })}</strong><span>{row.flight_number} · {row.direction === "arrival" ? "도착" : "출발"}</span></div><div className="departure-route"><strong>{row.origin_airport} → {row.destination_airport}</strong><small>{row.airline}</small></div><div className="departure-meta"><strong>{row.status ?? "상태 미제공"}</strong><small>예정 {dateTime(row.scheduled_at)}</small></div></article>)}{!rows?.length ? <p className="empty-state">조건에 맞는 이후 항공편이 없습니다.</p> : null}</div> : flightState.key === key && flightState.error ? null : <p role="status">{airport ? "항공편을 확인하는 중입니다…" : unavailable}</p>}
    </SectionCard></div>
    <div id="airport-map" className="journey-map-target" tabIndex={-1}><TransportMap places={items} selectedPlace={selected} onSelectPlace={select} /></div>
  </section>;
}
