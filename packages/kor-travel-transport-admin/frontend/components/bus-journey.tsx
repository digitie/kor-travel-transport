"use client";
import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import { dateTime, money, seoulDate, serviceInstant, serviceTime, TransportError, transportGet, type Place } from "@/lib/journey";
import { useNearbyPosition, useSeoulToday } from "@/lib/journey-hooks";
import { nearestPlaces } from "@/lib/nearby";
import { MapFilterBar, MapFilterField } from "@kor-travel/ui/map-controls";
import { InfoButton } from "./info-button";
import { Input } from "./ui/input";
const TransportMap = dynamic(() => import("./transport-map").then((m) => m.TransportMap), { ssr: false });

type Terminal = { id: number; terminal_id: string; terminal_name: string | null; city_name: string | null; latitude: number | null; longitude: number | null; updated_at: string; location_source?: string | null };
type Timetable = { service_date: string; fetched_at: string; total?: number | null; truncated?: boolean; stored?: boolean; stale?: boolean; refresh_status?: "stored_only" | "rate_limited" | "not_configured" | "upstream_error" | null; items: { departure_planned_time: string | null; arrival_planned_time: string | null; departure_terminal_name: string | null; arrival_terminal_name: string | null; grade_name: string | null; adult_fare: number | null }[] };

function TerminalSearch({ type, label, selected, other, terminals, date, direction, onSelect }: { type: string; label: string; selected: Terminal | null; other: Terminal | null; terminals: Terminal[]; date: string; direction: "departure" | "arrival"; onSelect: (value: Terminal | null) => void }) {
  const [query, setQuery] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [response, setResponse] = useState<{ key: string; items?: Terminal[]; error?: boolean }>({ key: "" });
  const key = `${type}/${other?.terminal_id}/${date}/${direction}`;
  useEffect(() => {
    if (!other || !date) return;
    const controller = new AbortController();
    transportGet<{ items: Terminal[] }>(`transport/bus/connections?${new URLSearchParams({ service_type: type, terminal_id: other.terminal_id, date, direction })}`, controller.signal)
      .then((data) => { if (!controller.signal.aborted) setResponse({ key, items: data.items }); })
      .catch(() => { if (!controller.signal.aborted) setResponse({ key, error: true }); });
    return () => controller.abort();
  }, [key, other, date, type, direction]);
  const current = response.key === key ? response : undefined;
  const options = other && !showAll ? current?.items ?? [] : terminals;
  const rows = options.filter((item) => item.terminal_id !== other?.terminal_id && (!query.trim() || [item.terminal_name, item.city_name, item.terminal_id].join(" ").includes(query.trim())));
  const visible = query.trim() || other ? rows.slice(0, 20) : [];
  return <section className="terminal-search"><MapFilterBar><MapFilterField htmlFor={`bus-${label}`} label={label}><Input id={`bus-${label}`} type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="터미널 이름·지역·코드" /></MapFilterField></MapFilterBar>
    {selected ? <p><strong>{selected.terminal_name ?? selected.terminal_id}</strong> <button type="button" className="inline-link" onClick={() => onSelect(null)}>선택 해제</button></p> : null}
    {other ? <><label className="inline-checkbox"><input type="checkbox" checked={!showAll} onChange={(event) => setShowAll(!event.target.checked)} />{other.terminal_name}와 연결 확인된 터미널</label><InfoButton label="연결된 터미널">해당 운행일의 저장된 시간표로 확인된 연결입니다. 미조회 노선도 찾으려면 연결 확인 필터를 해제하고 전체 터미널을 검색하세요.</InfoButton></> : null}
    {other && !showAll && !current ? <p role="status">연결된 터미널 확인 중…</p> : null}
    {current?.error && !showAll ? <p role="alert">연결 정보를 확인하지 못했습니다. 전체 터미널 검색을 이용해 주세요.</p> : null}
    {visible.length ? <div className="station-results">{visible.map((item) => <button type="button" key={item.terminal_id} aria-pressed={item.terminal_id === selected?.terminal_id} onClick={() => onSelect(item)}><strong>{item.terminal_name ?? item.terminal_id}</strong><small>{item.city_name} · {item.terminal_id}</small></button>)}</div> : query || other && current ? <p className="quiet">조건에 맞는 저장 연결이 없습니다.</p> : null}
  </section>;
}

export function BusJourney({ type }: { type: "express" | "intercity" }) {
  const [terminals, setTerminals] = useState<Terminal[]>([]);
  const [catalogError, setCatalogError] = useState("");
  const [departure, setDeparture] = useState<Terminal | null>(null);
  const [arrival, setArrival] = useState<Terminal | null>(null);
  const [focused, setFocused] = useState<Terminal | null>(null);
  const { position, positionError, locating, locate } = useNearbyPosition();
  const today = useSeoulToday();
  const [date, setDate] = useState(seoulDate);
  const effectiveDate = type === "intercity" || (date !== "" && date < today) ? today : date;
  const [result, setResult] = useState<Timetable | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [retryAt, setRetryAt] = useState(0);
  const [futureOnly, setFutureOnly] = useState(true);
  const [clock, setClock] = useState(() => Date.now());
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      const items: Terminal[] = [];
      let offset: number | null = 0;
      while (offset !== null && items.length < 10000) {
        const data: { items: Terminal[]; next_offset: number | null } = await transportGet(`transport/bus/terminals?${new URLSearchParams({ service_type: type, limit: "1000", offset: String(offset) })}`, controller.signal);
        items.push(...data.items);
        if (data.next_offset !== null && data.next_offset <= offset) throw new Error("터미널 목록 페이지를 확인하지 못했습니다.");
        offset = data.next_offset;
      }
      if (!controller.signal.aborted) { setTerminals(items); if (offset !== null) setCatalogError("터미널 목록의 일부를 표시합니다."); }
    }
    void load().catch(() => { if (!controller.signal.aborted) setCatalogError("터미널 목록을 불러오지 못했습니다."); });
    return () => controller.abort();
  }, [type]);
  useEffect(() => { const timer = setInterval(() => setClock(Date.now()), 30_000); return () => clearInterval(timer); }, []);
  useEffect(() => {
    request.current?.abort();
    // 날짜가 바뀌면 이전 날짜의 결과와 진행 중인 요청을 버린다.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setResult(null); setLoading(false); setError("");
  }, [effectiveDate]);
  function invalidate() { request.current?.abort(); setResult(null); setError(""); setLoading(false); }
  async function search() {
    if (!departure || !arrival) return;
    const currentToday = seoulDate();
    const requestDate = type === "intercity" || (date !== "" && date < currentToday) ? currentToday : date;
    if (!requestDate) return;
    if (currentToday !== today) {
      invalidate();
      setError("한국 날짜가 변경되었습니다. 날짜 동기화 후 출발일을 확인하고 다시 조회해 주세요.");
      return;
    }
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    setLoading(true); setError(""); setResult(null);
    try {
      const data = await transportGet<Timetable>(`transport/bus/timetable?${new URLSearchParams({ service_type: type, departure_terminal_id: departure.terminal_id, arrival_terminal_id: arrival.terminal_id, date: requestDate, ...(retryAt > Date.now() ? { stored_only: "true" } : {}) })}`, controller.signal);
      if (!controller.signal.aborted) setResult(data);
    } catch (reason) {
      if (!controller.signal.aborted) {
        if (reason instanceof TransportError && reason.status === 429) { setRetryAt(Date.now() + reason.retryAfter * 1000); setError(`제공기관 호출 보호 중입니다. 신규 갱신은 ${Math.ceil(reason.retryAfter / 60)}분 뒤 가능합니다. 다른 노선의 DB 저장본은 운행편 조회로 계속 확인할 수 있습니다.`); }
        else setError(reason instanceof Error ? reason.message : "운행편 조회에 실패했습니다.");
      }
    } finally { if (!controller.signal.aborted) setLoading(false); }
  }
  const nearby = position ? nearestPlaces(terminals, position).slice(0, 10) : [];
  const asPlace = (terminal: Terminal): Place => ({ id: terminal.id, kind: "bus_terminal", source: "data_go_kr_tago", provider_id: terminal.terminal_id, name: terminal.terminal_name ?? terminal.terminal_id, city_name: terminal.city_name, latitude: terminal.latitude, longitude: terminal.longitude, updated_at: terminal.updated_at, location_source: terminal.location_source, facilities: [], prices: [], line_names: [] });
  const places = (position ? nearby.map((row) => row.place) : terminals).map(asPlace);
  const shown = result?.items.filter((row) => !futureOnly || (serviceInstant(row.departure_planned_time, result.service_date) ?? -Infinity) >= clock).sort((a, b) => (serviceInstant(a.departure_planned_time, result!.service_date) ?? Infinity) - (serviceInstant(b.departure_planned_time, result!.service_date) ?? Infinity));
  return <section className="journey-workbench bus-journey">
    <nav className="journey-shortcuts" aria-label="버스 화면 바로가기"><a href="#bus-map">지도 보기</a><a href="#bus-departures">시간표 보기</a><InfoButton label="버스 시간표">시외버스는 오늘 운행편을 제공합니다. 터미널 선택 후 운행편을 조회하면 예정 시각과 요금을 확인할 수 있습니다.</InfoButton></nav>
    <MapFilterBar><MapFilterField label="출발일" htmlFor="bus-service-date"><input id="bus-service-date" type="date" min={today} max={type === "intercity" ? today : seoulDate(9)} value={effectiveDate} disabled={type === "intercity"} onChange={(event) => { invalidate(); setDate(event.target.value); }} /></MapFilterField><button type="button" className="secondary" disabled={locating} onClick={locate}>{locating ? "위치 확인 중…" : "내 근처 터미널"}</button><button type="button" className="secondary" disabled={!departure && !arrival} onClick={() => { invalidate(); setDeparture(arrival); setArrival(departure); }}>출발·도착 바꾸기</button></MapFilterBar>

    {catalogError ? <p role="alert">{catalogError}</p> : null}{positionError ? <p role="alert">{positionError}</p> : null}
    {position ? <><p className="quiet">위치 오차 약 {Math.round(position.accuracy)}m · 직선 거리 순</p><div className="station-results" aria-label="가까운 터미널">{nearby.map(({ place, distance }) => <button type="button" key={place.terminal_id} onClick={() => setFocused(place)}><strong>{place.terminal_name}</strong><small>{distance.toFixed(1)}km · {place.terminal_id}</small></button>)}</div>{!nearby.length ? <p>좌표가 등록된 터미널이 없습니다. 이름으로 검색해 주세요.</p> : null}</> : null}
    <div className="journey-data-grid"><TerminalSearch type={type} label="출발 터미널" selected={departure} other={arrival} direction="arrival" terminals={terminals} date={effectiveDate} onSelect={(value) => { invalidate(); setDeparture(value); setFocused(value); }} /><TerminalSearch type={type} label="도착 터미널" selected={arrival} other={departure} direction="departure" terminals={terminals} date={effectiveDate} onSelect={(value) => { invalidate(); setArrival(value); setFocused(value); }} /></div>
    <div id="bus-map" className="journey-map-target" tabIndex={-1}>
    <TransportMap places={places} selectedPlace={focused ? asPlace(focused) : null} onSelectPlace={(place) => setFocused(terminals.find((row) => row.terminal_id === place.provider_id) ?? null)} onCloseDetails={() => setFocused(null)} details={focused ? <div><h2>{focused.terminal_name}</h2><p className="quiet">{focused.city_name} · {focused.terminal_id}</p><div className="journey-toolbar"><button type="button" className="button" onClick={() => { invalidate(); setDeparture(focused); }}>출발지로 선택</button><button type="button" className="secondary" onClick={() => { invalidate(); setArrival(focused); }}>도착지로 선택</button></div></div> : undefined} />
    </div>
    {departure && arrival && departure.terminal_id === arrival.terminal_id ? <p role="alert">출발과 도착 터미널을 다르게 선택해 주세요.</p> : null}
    <button className="button" type="button" disabled={!departure || !arrival || departure.terminal_id === arrival.terminal_id || !effectiveDate || loading} onClick={() => void search()}>{loading ? "운행편 확인 중…" : "운행편 조회"}</button>
    {result?.stored ? <p className="quiet">저장된 시간표입니다.{result.stale ? " 갱신 전 저장본입니다." : ""}</p> : null}
    {result?.refresh_status ? <p className="quiet">{{ stored_only: "제공기관을 호출하지 않고 저장본만 조회했습니다.", rate_limited: "제공기관 호출 보호로 저장본을 표시합니다.", not_configured: "제공기관 연결 설정이 없어 저장본을 표시합니다.", upstream_error: "제공기관 갱신에 실패하여 이전 저장본을 표시합니다." }[result.refresh_status]}</p> : null}
    {error ? <p className="error" role="alert">{error}</p> : null}
    <section id="bus-departures" aria-live="polite" className="departures"><h2>{departure?.terminal_name ?? "출발지"} → {arrival?.terminal_name ?? "도착지"}</h2><label className="inline-checkbox"><input type="checkbox" checked={futureOnly} onChange={(event) => setFutureOnly(event.target.checked)} />지금 이후만</label>
      {result ? <><p className="quiet">{dateTime(result.fetched_at)} 조회 · {shown?.length}편 표시{result.truncated ? ` · 전체 ${result.total ?? "미확인"}편 중 일부 결과` : ""}</p>{shown?.map((row, index) => <article className="departure-row" key={index}><div className="departure-time"><strong>{serviceTime(row.departure_planned_time, result.service_date)}</strong><span>{row.departure_terminal_name ?? departure?.terminal_name}</span></div><div className="departure-route"><strong>{row.arrival_terminal_name ?? arrival?.terminal_name}</strong><span>도착 {serviceTime(row.arrival_planned_time, row.departure_planned_time && /^\d{8}/.test(row.departure_planned_time) ? row.departure_planned_time : result.service_date)}</span></div><div className="departure-meta"><strong>{row.grade_name ?? "등급 미제공"}</strong><span>{money(row.adult_fare)}</span></div></article>)}{!shown?.length ? <p className="empty-state">{result.items.length ? "지금 이후 조건에 맞는 운행편이 없습니다. 전체 시간표도 확인할 수 있습니다." : "정상 응답에 등록된 운행편이 없습니다. 미운행 확정은 아닙니다."}</p> : null}</> : <p className="quiet">출발·도착지를 선택하고 운행편을 조회하세요.</p>}
    </section>

  </section>;
}
