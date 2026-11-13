"use client";
import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import { dateTime, money, seoulDate, serviceInstant, serviceTime, TransportError, transportGet, type Place } from "@/lib/journey";
import { useNearbyPosition, useSeoulToday } from "@/lib/journey-hooks";
import { nearestPlaces } from "@/lib/nearby";
import { FilterActions, FilterBar, FilterField } from "@/components/filter-bar";
import { EmptyState } from "@/components/empty-state";
import { SectionCard } from "./section-card";
import { HelpTip } from "./help-tip";
import { Alert, AlertDescription } from "./ui/alert";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
const TransportMap = dynamic(() => import("./transport-map").then((m) => m.TransportMap), { ssr: false });
const inlineLink = "rounded-control text-sm font-medium text-brand underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";
const resultButton = "flex min-w-0 flex-col items-start gap-0.5 rounded-control border border-border bg-card px-3 py-2 text-left hover:bg-surface-subtle aria-pressed:border-brand aria-pressed:bg-brand-tint focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";
const departureRow = "departure-row grid gap-3 border-b border-border py-3 last:border-b-0 sm:grid-cols-[8rem_minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-center";

type Terminal = { id: number; terminal_id: string; terminal_name: string | null; city_name: string | null; latitude: number | null; longitude: number | null; updated_at: string; location_source?: string | null };
type Timetable = { service_date: string; fetched_at: string; total?: number | null; truncated?: boolean; stored?: boolean; stale?: boolean; refresh_status?: "stored_only" | "rate_limited" | "not_configured" | "upstream_error" | null; items: { departure_planned_time: string | null; arrival_planned_time: string | null; departure_terminal_name: string | null; arrival_terminal_name: string | null; grade_name: string | null; adult_fare: number | null }[] };

function TerminalSearch({ type, label, selected, other, terminals, catalogReady, catalogFailed, date, direction, onSelect }: { type: string; label: string; selected: Terminal | null; other: Terminal | null; terminals: Terminal[]; catalogReady: boolean; catalogFailed: boolean; date: string; direction: "departure" | "arrival"; onSelect: (value: Terminal | null) => void }) {
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
  const ready = other && !showAll ? current?.items !== undefined : catalogReady;
  const visible = query.trim() || other ? rows.slice(0, 20) : [];
  return <section className="terminal-search flex flex-col gap-3">
    <FilterBar><FilterField label={label} htmlFor={`bus-${label}`}><Input id={`bus-${label}`} type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="터미널 이름·지역·코드" /></FilterField></FilterBar>
    {selected ? <p className="text-sm"><strong>{selected.terminal_name ?? selected.terminal_id}</strong> <Button type="button" variant="link" size="sm" onClick={() => onSelect(null)}>선택 해제</Button></p> : null}
    {other ? <div className="flex flex-wrap items-center gap-2"><label className="flex items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-brand" checked={!showAll} onChange={(event) => setShowAll(!event.target.checked)} />{other.terminal_name}와 연결 확인된 터미널</label><HelpTip label="연결된 터미널">해당 운행일의 저장된 시간표로 확인된 연결입니다. 미조회 노선도 찾으려면 연결 확인 필터를 해제하고 전체 터미널을 검색하세요.</HelpTip></div> : null}
    {(!other || showAll) && !catalogReady && !catalogFailed ? <p role="status" className="text-sm text-text-secondary">터미널 목록 조회 중…</p> : null}
    {other && !showAll && !current ? <p role="status" className="text-sm text-text-secondary">연결된 터미널 확인 중…</p> : null}
    {current?.error && !showAll ? <Alert variant="destructive"><AlertDescription>연결 정보를 확인하지 못했습니다. 전체 터미널 검색을 이용해 주세요.</AlertDescription></Alert> : null}
    {visible.length ? <div className="station-results grid gap-2 sm:grid-cols-2">{visible.map((item) => <button type="button" className={resultButton} key={item.terminal_id} aria-pressed={item.terminal_id === selected?.terminal_id} onClick={() => onSelect(item)}><strong className="text-sm">{item.terminal_name ?? item.terminal_id}</strong><small className="text-xs text-text-secondary">{item.city_name} · {item.terminal_id}</small></button>)}</div> : ready && (query || other) ? <p className="text-sm text-text-secondary">조건에 맞는 터미널이 없습니다.</p> : null}
  </section>;
}

export function BusJourney({ type }: { type: "express" | "intercity" }) {
  const [terminals, setTerminals] = useState<Terminal[]>([]);
  const [catalogLoaded, setCatalogLoaded] = useState(false);
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
      if (!controller.signal.aborted) { setTerminals(items); setCatalogLoaded(true); if (offset !== null) setCatalogError("터미널 목록의 일부를 표시합니다."); }
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
  return <section className="journey-workbench flex flex-col gap-6">
    <nav aria-label="버스 화면 바로가기" className="flex flex-wrap items-center gap-x-4 gap-y-2"><a className={inlineLink} href="#bus-map">지도 보기</a><a className={inlineLink} href="#bus-departures">시간표 보기</a><HelpTip label="버스 시간표">시외버스는 오늘 운행편을 제공합니다. 터미널 선택 후 운행편을 조회하면 예정 시각과 요금을 확인할 수 있습니다.</HelpTip></nav>
    <FilterBar>
      <FilterField label="출발일" htmlFor="bus-service-date"><Input id="bus-service-date" type="date" min={today} max={type === "intercity" ? today : seoulDate(9)} value={effectiveDate} disabled={type === "intercity"} onChange={(event) => { invalidate(); setDate(event.target.value); }} /></FilterField>
      <FilterActions>
        <Button type="button" variant="outline" disabled={locating} onClick={locate}>{locating ? "위치 확인 중…" : "내 근처 터미널"}</Button>
        <Button type="button" variant="outline" disabled={!departure && !arrival} onClick={() => { invalidate(); setDeparture(arrival); setArrival(departure); }}>출발·도착 바꾸기</Button>
      </FilterActions>
    </FilterBar>

    {catalogError ? <Alert variant="destructive"><AlertDescription>{catalogError}</AlertDescription></Alert> : null}{positionError ? <Alert variant="destructive"><AlertDescription>{positionError}</AlertDescription></Alert> : null}
    {position ? <div className="grid gap-3"><p className="text-sm text-text-secondary">위치 오차 약 {Math.round(position.accuracy)}m · 직선 거리 순</p><div className="station-results grid gap-2 sm:grid-cols-2" aria-label="가까운 터미널">{nearby.map(({ place, distance }) => <button type="button" className={resultButton} key={place.terminal_id} onClick={() => setFocused(place)}><strong className="text-sm">{place.terminal_name}</strong><small className="text-xs text-text-secondary">{distance.toFixed(1)}km · {place.terminal_id}</small></button>)}</div>{!nearby.length ? <p className="text-sm">좌표가 등록된 터미널이 없습니다. 이름으로 검색해 주세요.</p> : null}</div> : null}
    <div className="grid gap-6 lg:grid-cols-2">
      <TerminalSearch type={type} label="출발 터미널" selected={departure} other={arrival} direction="arrival" terminals={terminals} catalogReady={catalogLoaded} catalogFailed={Boolean(catalogError) && !catalogLoaded} date={effectiveDate} onSelect={(value) => { invalidate(); setDeparture(value); setFocused(value); }} />
      <TerminalSearch type={type} label="도착 터미널" selected={arrival} other={departure} direction="departure" terminals={terminals} catalogReady={catalogLoaded} catalogFailed={Boolean(catalogError) && !catalogLoaded} date={effectiveDate} onSelect={(value) => { invalidate(); setArrival(value); setFocused(value); }} />
    </div>
    <div id="bus-map" className="scroll-mt-6" tabIndex={-1}>
      <TransportMap places={places} selectedPlace={focused ? asPlace(focused) : null} onSelectPlace={(place) => setFocused(terminals.find((row) => row.terminal_id === place.provider_id) ?? null)} onCloseDetails={() => setFocused(null)} details={focused ? <div className="grid gap-2"><h2 className="text-base font-semibold text-text-primary">{focused.terminal_name}</h2><p className="text-sm text-text-secondary">{focused.city_name} · {focused.terminal_id}</p><div className="flex flex-wrap gap-2"><Button type="button" onClick={() => { invalidate(); setDeparture(focused); }}>출발지로 선택</Button><Button type="button" variant="outline" onClick={() => { invalidate(); setArrival(focused); }}>도착지로 선택</Button></div></div> : undefined} />
    </div>
    {departure && arrival && departure.terminal_id === arrival.terminal_id ? <Alert variant="destructive"><AlertDescription>출발과 도착 터미널을 다르게 선택해 주세요.</AlertDescription></Alert> : null}
    <div><Button type="button" disabled={!departure || !arrival || departure.terminal_id === arrival.terminal_id || !effectiveDate || loading} onClick={() => void search()}>{loading ? "운행편 확인 중…" : "운행편 조회"}</Button></div>
    {result?.stored ? <p className="text-sm text-text-secondary">저장된 시간표입니다.{result.stale ? " 갱신 전 저장본입니다." : ""}</p> : null}
    {result?.refresh_status ? <p className="text-sm text-text-secondary">{{ stored_only: "제공기관을 호출하지 않고 저장본만 조회했습니다.", rate_limited: "제공기관 호출 보호로 저장본을 표시합니다.", not_configured: "제공기관 연결 설정이 없어 저장본을 표시합니다.", upstream_error: "제공기관 갱신에 실패하여 이전 저장본을 표시합니다." }[result.refresh_status]}</p> : null}
    {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
    <section id="bus-departures" aria-live="polite" className="scroll-mt-6">
      <SectionCard title={`${departure?.terminal_name ?? "출발지"} → ${arrival?.terminal_name ?? "도착지"}`}>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-brand" checked={futureOnly} onChange={(event) => setFutureOnly(event.target.checked)} />지금 이후만</label>
        {result ? <>
          <p className="text-sm text-text-secondary">{dateTime(result.fetched_at)} 조회 · {shown?.length}편 표시{result.truncated ? ` · 전체 ${result.total ?? "미확인"}편 중 일부 결과` : ""}</p>
          <div className="grid">{shown?.map((row, index) => <article className={departureRow} key={index}>
            <div className="flex flex-col gap-0.5"><strong className="text-base tabular-nums">{serviceTime(row.departure_planned_time, result.service_date)}</strong><span className="text-sm text-text-secondary">{row.departure_terminal_name ?? departure?.terminal_name}</span></div>
            <div className="flex flex-col gap-0.5"><strong className="text-sm">{row.arrival_terminal_name ?? arrival?.terminal_name}</strong><span className="text-sm text-text-secondary">도착 {serviceTime(row.arrival_planned_time, row.departure_planned_time && /^\d{8}/.test(row.departure_planned_time) ? row.departure_planned_time : result.service_date)}</span></div>
            <div className="flex flex-col gap-0.5"><strong className="text-sm">{row.grade_name ?? "등급 미제공"}</strong><span className="text-sm tabular-nums">{money(row.adult_fare)}</span></div>
          </article>)}</div>
          {!shown?.length ? <EmptyState size="sm" title={result.items.length ? "지금 이후 조건에 맞는 운행편이 없습니다." : "정상 응답에 등록된 운행편이 없습니다."} description={result.items.length ? "전체 시간표도 확인할 수 있습니다." : "미운행 확정은 아닙니다."} /> : null}
        </> : <p className="text-sm text-text-secondary">출발·도착지를 선택하고 운행편을 조회하세요.</p>}
      </SectionCard>
    </section>
  </section>;
}
