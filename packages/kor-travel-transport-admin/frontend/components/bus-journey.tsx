"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { dateTime, money, seoulDate, serviceTime, TransportError, transportGet } from "@/lib/journey";
import { MultiSearch } from "./journey-controls";

type Terminal = { terminal_id: string; terminal_name: string | null; city_name: string | null };
type Timetable = { fetched_at: string; total?: number | null; truncated?: boolean; items: { departure_planned_time: string | null; arrival_planned_time: string | null; departure_terminal_name: string | null; arrival_terminal_name: string | null; grade_name: string | null; adult_fare: number | null }[] };

function TerminalSearch({ type, label, selected, onSelect }: { type: string; label: string; selected: Terminal | null; onSelect: (value: Terminal | null) => void }) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<Terminal[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setLoading(true); setError("");
      transportGet<{ items: Terminal[] }>(`transport/bus/terminals?${new URLSearchParams({ service_type: type, query, limit: "100" })}`, controller.signal)
        .then((data) => { if (!controller.signal.aborted) setItems(data.items); })
        .catch(() => { if (!controller.signal.aborted) setError("터미널 검색에 실패했습니다. 검색어를 다시 입력해 주세요."); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [query, type]);
  return <><MultiSearch label={label} query={query} onQuery={setQuery} options={items.map((item) => ({ id: item.terminal_id, name: item.terminal_name ?? item.terminal_id, description: item.city_name ?? "지역 미제공" }))} selected={selected ? [{ id: selected.terminal_id, name: selected.terminal_name ?? selected.terminal_id }] : []} max={1} loading={loading} onSelect={(id) => onSelect(selected?.terminal_id === id ? null : items.find((item) => item.terminal_id === id) ?? null)} />{error ? <p className="error" role="alert">{error}</p> : null}</>;
}

export function BusJourney({ type }: { type: "express" | "intercity" }) {
  const [departure, setDeparture] = useState<Terminal | null>(null);
  const [arrival, setArrival] = useState<Terminal | null>(null);
  const [date, setDate] = useState(seoulDate);
  const [result, setResult] = useState<Timetable | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [retryAt, setRetryAt] = useState(0);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  function invalidate() { request.current?.abort(); setResult(null); setError(""); setLoading(false); }
  async function search() {
    if (!departure || !arrival) return;
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    setLoading(true); setError(""); setResult(null);
    try {
      const data = await transportGet<Timetable>(`transport/bus/timetable?${new URLSearchParams({ service_type: type, departure_terminal_id: departure.terminal_id, arrival_terminal_id: arrival.terminal_id, date: type === "intercity" ? seoulDate() : date })}`, controller.signal);
      if (!controller.signal.aborted) setResult(data);
    } catch (reason) {
      if (!controller.signal.aborted) {
        if (reason instanceof TransportError && reason.status === 429) { setRetryAt(Date.now() + reason.retryAfter * 1000); setError(`제공기관 호출 보호 중입니다. ${Math.ceil(reason.retryAfter / 60)}분 뒤 다시 조회할 수 있습니다. 터미널 검색은 계속 가능합니다.`); }
        else setError(reason instanceof Error ? reason.message : "운행편 조회에 실패했습니다.");
      }
    } finally { if (!controller.signal.aborted) setLoading(false); }
  }
  return <section className="journey-workbench">
    <nav className="transport-tabs" aria-label="버스 종류"><Link href="/bus/express" aria-current={type === "express" ? "page" : undefined}>고속버스</Link><Link href="/bus/intercity" aria-current={type === "intercity" ? "page" : undefined}>시외버스</Link></nav>
    <div className="journey-toolbar"><label>출발일<input type="date" min={seoulDate()} max={type === "intercity" ? seoulDate() : seoulDate(9)} value={type === "intercity" ? seoulDate() : date} disabled={type === "intercity"} onChange={(event) => { invalidate(); setDate(event.target.value); }} /></label><p className="quiet">{type === "intercity" ? "시외버스는 오늘 운행편만 제공합니다." : "고속버스 출발·도착 터미널을 선택하세요."} 검색·선택만으로 운행 API를 호출하지 않습니다.</p></div>
    <div className="bus-search-grid"><TerminalSearch type={type} label="출발 터미널" selected={departure} onSelect={(value) => { invalidate(); setDeparture(value); }} /><TerminalSearch type={type} label="도착 터미널" selected={arrival} onSelect={(value) => { invalidate(); setArrival(value); }} /></div>
    {departure && arrival && departure.terminal_id === arrival.terminal_id ? <p className="error">출발과 도착 터미널을 다르게 선택해 주세요.</p> : null}
    <button className="button" type="button" disabled={!departure || !arrival || departure.terminal_id === arrival.terminal_id || !date || loading} onClick={() => { if (retryAt > Date.now()) setError(`다음 조회 가능 시각은 ${dateTime(new Date(retryAt).toISOString())}입니다.`); else void search(); }}>{loading ? "운행편 확인 중…" : "운행편 조회"}</button>
    {error ? <p className="error" role="alert">{error}</p> : null}
    <section aria-live="polite" className="departures"><h2>{departure?.terminal_name ?? "출발지"} → {arrival?.terminal_name ?? "도착지"}</h2>
      {result ? <><p className="quiet">{dateTime(result.fetched_at)} 조회 · {result.items.length}편{result.truncated ? ` · 전체 ${result.total ?? "미확인"}편 중 일부 결과` : ""}</p>{result.items.map((row, index) => <article className="departure-row" key={index}><div className="departure-time"><strong>{serviceTime(row.departure_planned_time, date)}</strong><span>{row.departure_terminal_name ?? departure?.terminal_name}</span></div><div className="departure-route"><strong>{row.arrival_terminal_name ?? arrival?.terminal_name}</strong><span>도착 {serviceTime(row.arrival_planned_time, row.departure_planned_time && /^\d{8}/.test(row.departure_planned_time) ? row.departure_planned_time : date)}</span></div><div className="departure-meta"><strong>{row.grade_name ?? "등급 미제공"}</strong><span>{money(row.adult_fare)}</span></div></article>)}{!result.items.length ? <p className="empty-state">제공기관 응답에 등록된 운행편이 없습니다. 미운행 확정은 아니므로 터미널에 확인해 주세요.</p> : null}</> : <p className="quiet">터미널을 선택하고 운행편 조회를 누르면 예정 시각·등급·성인 요금을 확인할 수 있습니다.</p>}
    </section><p className="data-caveat">이 터미널 기준정보에는 좌표가 없어 지도 위치를 임의로 표시하지 않습니다. 시간표·요금은 예매 전 운송사에서 확인해 주세요.</p>
  </section>;
}
