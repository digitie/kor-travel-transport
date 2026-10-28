"use client";
import { useEffect, useId, useRef, useState } from "react";
import { dateTime, money, seoulDate, serviceInstant, serviceTime, transportGet } from "@/lib/journey";
import { useSeoulToday } from "@/lib/journey-hooks";
import { MapFilterBar, MapFilterField } from "@kor-travel/ui/map-controls";
import { Input } from "./ui/input";
import { SectionCard } from "./section-card";
import { GeneralRailGuide, type GeneralRailStationIntent, type GeneralRailStationReference } from "./general-rail-guide";

type Code = { code: string; name: string };
type Station = { station_id: string; station_name: string };
type Catalog = { fetched_at: string; stale: boolean; cities: Code[]; train_classes: Code[] };
type Stations = { fetched_at: string; stale: boolean; city_code: string; items: Station[] };
type Trips = { fetched_at: string; stale: boolean; service_date: string; total: number | null; truncated: boolean; items: { train_number: string | null; grade_name: string | null; departure_station_name: string | null; arrival_station_name: string | null; departure_planned_time: string | null; arrival_planned_time: string | null; adult_fare: number | null }[] };
type StationSearchIntent = { revision: number; station: GeneralRailStationReference };

function StationSearch({ label, cities, value, onChange, request }: { label: string; cities: Code[]; value: Station | null; onChange: (value: Station | null) => void; request?: StationSearchIntent }) {
  const id = useId();
  const [city, setCity] = useState("");
  const [search, setSearch] = useState({ revision: 0, text: "" });
  const revision = request?.revision ?? 0;
  // 안내의 이름은 검색어일 뿐이다. 지역과 실제 TAGO station_id는 후보 클릭 전 확정하지 않는다.
  const query = search.revision === revision ? search.text : request?.station.name ?? "";
  const fieldset = useRef<HTMLFieldSetElement>(null);
  const cityInput = useRef<HTMLSelectElement>(null);
  const queryInput = useRef<HTMLInputElement>(null);
  const focusedRequest = useRef(0);
  const [response, setResponse] = useState<{ city: string; data?: Stations; error?: string }>({ city: "" });
  useEffect(() => {
    if (!city) return;
    const controller = new AbortController();
    transportGet<Stations>(`transport/rail/general/stations?city_code=${encodeURIComponent(city)}`, controller.signal)
      .then((data) => { if (!controller.signal.aborted) setResponse({ city, data }); })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setResponse({ city, error: reason instanceof Error ? reason.message : "역 목록 조회 실패" }); });
    return () => controller.abort();
  }, [city]);
  const current = response.city === city ? response : undefined;
  const ready = Boolean(current?.data);
  useEffect(() => {
    if (!revision) return;
    const freshRequest = focusedRequest.current !== revision;
    focusedRequest.current = revision;
    // 뒤늦은 목록 응답은 다른 쪽 역/날짜 등으로 옮긴 사용자의 초점을 빼앗지 않는다.
    if (!freshRequest && document.activeElement !== cityInput.current && document.activeElement !== queryInput.current) return;
    if (freshRequest) fieldset.current?.scrollIntoView?.({ block: "start" });
    (city && ready ? queryInput.current : cityInput.current)?.focus({ preventScroll: true });
  }, [revision, city, ready]);
  const results = query.trim() ? current?.data?.items.filter((station) => `${station.station_name} ${station.station_id}`.includes(query.trim())) ?? [] : [];
  return <fieldset ref={fieldset} className="train-station-search"><legend>{label}</legend>
    <MapFilterBar><MapFilterField label="지역" htmlFor={`${id}-city`}><select ref={cityInput} id={`${id}-city`} value={city} onChange={(event) => { setCity(event.target.value); setSearch({ revision, text: request?.station.name ?? "" }); onChange(null); }}><option value="">지역 선택</option>{cities.map((row) => <option key={row.code} value={row.code}>{row.name}</option>)}</select></MapFilterField><MapFilterField label={`${label} 검색`} htmlFor={`${id}-query`}><Input ref={queryInput} id={`${id}-query`} type="search" disabled={!ready} placeholder="역 이름·코드" value={query} onChange={(event) => setSearch({ revision, text: event.target.value })} /></MapFilterField></MapFilterBar>
    {request && !value ? <p className="quiet" role="status">{request.station.name} · {city ? "TAGO 후보를 확인해 선택하세요." : "지역을 선택한 뒤 TAGO 후보를 확인하세요."}</p> : null}
    {current?.error ? <p role="alert">{current.error}</p> : city && !current?.data ? <p role="status">역 목록 조회 중…</p> : null}
    {current?.data?.stale ? <p>갱신에 실패한 이전 역 목록입니다.</p> : null}
    {value ? <p><strong>{value.station_name}</strong> <small>{value.station_id}</small> <button type="button" className="inline-link" onClick={() => onChange(null)}>선택 해제</button></p> : null}
    {results.length ? <div className="station-results">{results.slice(0, 20).map((station) => <button type="button" key={station.station_id} aria-pressed={value?.station_id === station.station_id} onClick={() => onChange(station)}><strong>{station.station_name}</strong><small>{station.station_id}</small></button>)}</div> : ready && query.trim() ? <p className="quiet">조건에 맞는 역이 없습니다.</p> : null}
  </fieldset>;
}

export function GeneralRailJourney() {
  const id = useId();
  const today = useSeoulToday();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [catalogError, setCatalogError] = useState("");
  const [reload, setReload] = useState(0);
  const [departure, setDeparture] = useState<Station | null>(null);
  const [arrival, setArrival] = useState<Station | null>(null);
  const [stationRequests, setStationRequests] = useState<Partial<Record<GeneralRailStationIntent["role"], StationSearchIntent>>>({});
  const [grade, setGrade] = useState("");
  const [date, setDate] = useState(seoulDate);
  const [futureOnly, setFutureOnly] = useState(true);
  const [clock, setClock] = useState(() => Date.now());
  const [response, setResponse] = useState<{ key: string; data?: Trips; error?: string; pending?: boolean }>({ key: "" });
  const pending = useRef<AbortController | null>(null);
  const effectiveDate = date && date < today ? today : date;
  const key = `${departure?.station_id}/${arrival?.station_id}/${effectiveDate}/${grade}`;
  useEffect(() => {
    const controller = new AbortController();
    transportGet<Catalog>("transport/rail/general/catalog", controller.signal)
      .then((data) => { if (!controller.signal.aborted) { setCatalog(data); setCatalogError(""); } })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setCatalogError(reason instanceof Error ? reason.message : "철도 기준정보 조회 실패"); });
    return () => controller.abort();
  }, [reload]);
  useEffect(() => {
    pending.current?.abort(); pending.current = null;
    // 조건 변경으로 취소한 요청의 pending 상태가 같은 조건으로 복귀했을 때 살아나지 않게 한다.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setResponse((previous) => previous.pending ? { key: "" } : previous);
  }, [key]);
  useEffect(() => () => pending.current?.abort(), []);
  useEffect(() => { const timer = setInterval(() => setClock(Date.now()), 30_000); return () => clearInterval(timer); }, []);
  async function load() {
    if (!departure || !arrival || !effectiveDate) return;
    pending.current?.abort(); const controller = new AbortController(); pending.current = controller;
    setResponse({ key, pending: true });
    try {
      const data = await transportGet<Trips>(`transport/rail/general/timetable?${new URLSearchParams({ departure_station_id: departure.station_id, arrival_station_id: arrival.station_id, date: effectiveDate, ...(grade ? { train_grade_code: grade } : {}) })}`, controller.signal);
      if (!controller.signal.aborted) setResponse({ key, data });
    } catch (reason) { if (!controller.signal.aborted) setResponse({ key, error: reason instanceof Error ? reason.message : "열차 시간표 조회 실패" }); }
  }
  const current = response.key === key ? response : undefined;
  const trips = current?.data;
  const rows = trips?.items.filter((row) => !futureOnly || (serviceInstant(row.departure_planned_time, trips.service_date) ?? -Infinity) >= clock).sort((a, b) => (serviceInstant(a.departure_planned_time, trips!.service_date) ?? Infinity) - (serviceInstant(b.departure_planned_time, trips!.service_date) ?? Infinity));
  function requestStation({ role, station }: GeneralRailStationIntent) {
    if (role === "departure") setDeparture(null); else setArrival(null);
    setStationRequests((previous) => ({ ...previous, [role]: { revision: (previous[role]?.revision ?? 0) + 1, station } }));
  }
  return <section className="journey-workbench map-route">
    <GeneralRailGuide onStationIntent={requestStation} />
    <div id="general-rail-timetable" className="journey-map-target map-route-followup" tabIndex={-1}>
    <a className="inline-link" href="#general-rail-map">지도 작업면으로</a>
    {catalogError ? <p role="alert">{catalogError} <button type="button" className="inline-link" onClick={() => setReload((v) => v + 1)}>다시 조회</button></p> : !catalog ? <p role="status">열차 종류와 지역을 확인하는 중입니다…</p> : null}
    {catalog?.stale ? <p>갱신에 실패한 이전 기준정보입니다. 조회 기준 {dateTime(catalog.fetched_at)}</p> : null}
    <MapFilterBar><MapFilterField label="열차 종류" htmlFor={`${id}-grade`}><select id={`${id}-grade`} value={grade} onChange={(event) => setGrade(event.target.value)}><option value="">모든 열차</option>{catalog?.train_classes.map((row) => <option key={row.code} value={row.code}>{row.name}</option>)}</select></MapFilterField><MapFilterField label="출발일" htmlFor={`${id}-date`}><input id={`${id}-date`} type="date" min={today} max={seoulDate(9)} value={effectiveDate} onChange={(event) => setDate(event.target.value)} /></MapFilterField></MapFilterBar>
    <div className="journey-data-grid"><StationSearch label="출발역" cities={catalog?.cities ?? []} value={departure} onChange={setDeparture} request={stationRequests.departure} /><StationSearch label="도착역" cities={catalog?.cities ?? []} value={arrival} onChange={setArrival} request={stationRequests.arrival} /></div>
    <button type="button" className="button" onClick={() => void load()} disabled={!departure || !arrival || departure.station_id === arrival.station_id || !effectiveDate || current?.pending}>예정 운행편 조회</button>
    {current?.pending ? <p role="status">시간표를 조회하는 중입니다…</p> : current?.error ? <p role="alert">{current.error}</p> : null}
    <SectionCard title={`${departure?.station_name ?? "출발역"} → ${arrival?.station_name ?? "도착역"}`} description="예정 출발·도착 시각과 성인 요금을 비교합니다. 실시간 지연·잔여 좌석은 제공하지 않습니다.">
      <label className="inline-checkbox"><input type="checkbox" checked={futureOnly} onChange={(event) => setFutureOnly(event.target.checked)} />지금 이후만</label>
      {trips ? <><p className="quiet">{trips.service_date} · {dateTime(trips.fetched_at)} 조회{trips.stale ? " · 이전 저장 시간표" : ""}{trips.truncated ? " · 일부 결과" : ""}</p>{rows?.map((row, index) => <article className="departure-row" key={`${row.train_number}/${index}`}><div><strong>{serviceTime(row.departure_planned_time, trips.service_date)}</strong><p>{row.departure_station_name}</p></div><div><strong>{row.grade_name ?? "종류 미제공"} {row.train_number}</strong><p>{row.arrival_station_name} · 도착 {serviceTime(row.arrival_planned_time, row.departure_planned_time ?? trips.service_date)}</p></div><strong>{money(row.adult_fare)}</strong></article>)}{!rows?.length ? <p>{trips.items.length ? "지금 이후 조건에 맞는 운행편이 없습니다. 전체 시간표도 확인할 수 있습니다." : "정상 응답에 등록된 운행편이 없습니다. 미운행 확정은 아닙니다."}</p> : null}</> : <p className="quiet">출발·도착역을 선택하고 예정 운행편을 조회하세요.</p>}
    </SectionCard>
    </div>
  </section>;
}
