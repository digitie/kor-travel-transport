"use client";
import { useEffect, useId, useRef, useState } from "react";
import { dateTime, money, seoulDate, serviceInstant, serviceTime, transportGet } from "@/lib/journey";
import { useSeoulToday } from "@/lib/journey-hooks";
import { FilterBar, FilterField } from "@/components/filter-bar";
import { EmptyState } from "@/components/empty-state";
import { SectionCard } from "./section-card";
import { GeneralRailGuide } from "./general-rail-guide";
import { Alert, AlertDescription } from "./ui/alert";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { NativeSelect } from "./ui/native-select";
import { NativeSelectOption } from "./ui/native-select-option";

type Code = { code: string; name: string };
type Station = { station_id: string; station_name: string };
type Catalog = { fetched_at: string; stale: boolean; cities: Code[]; train_classes: Code[] };
type Stations = { fetched_at: string; stale: boolean; city_code: string; items: Station[] };
type Trips = { fetched_at: string; stale: boolean; service_date: string; total: number | null; truncated: boolean; items: { train_number: string | null; grade_name: string | null; departure_station_name: string | null; arrival_station_name: string | null; departure_planned_time: string | null; arrival_planned_time: string | null; adult_fare: number | null }[] };
const resultButton = "flex min-w-0 flex-col items-start gap-0.5 rounded-control border border-border bg-card px-3 py-2 text-left hover:bg-surface-subtle aria-pressed:border-brand aria-pressed:bg-brand-tint focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

function StationSearch({ label, cities, value, onChange }: { label: string; cities: Code[]; value: Station | null; onChange: (value: Station | null) => void }) {
  const id = useId();
  const [city, setCity] = useState("");
  const [query, setQuery] = useState("");
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
  const results = query.trim() ? current?.data?.items.filter((station) => `${station.station_name} ${station.station_id}`.includes(query.trim())) ?? [] : [];
  return <fieldset className="grid gap-3 rounded-panel border border-border p-4"><legend className="px-1 text-sm font-semibold text-text-primary">{label}</legend>
    <FilterBar>
      <FilterField label="지역" htmlFor={`${id}-city`}><NativeSelect id={`${id}-city`} value={city} onChange={(event) => { setCity(event.target.value); setQuery(""); onChange(null); }}><NativeSelectOption value="">지역 선택</NativeSelectOption>{cities.map((row) => <NativeSelectOption key={row.code} value={row.code}>{row.name}</NativeSelectOption>)}</NativeSelect></FilterField>
      <FilterField label={`${label} 검색`} htmlFor={`${id}-query`}><Input id={`${id}-query`} type="search" disabled={!current?.data} placeholder="역 이름·코드" value={query} onChange={(event) => setQuery(event.target.value)} /></FilterField>
    </FilterBar>
    {current?.error ? <Alert variant="destructive"><AlertDescription>{current.error}</AlertDescription></Alert> : city && !current?.data ? <p role="status" className="text-sm text-text-secondary">역 목록 조회 중…</p> : null}
    {current?.data?.stale ? <p className="text-sm text-text-secondary">갱신에 실패한 이전 역 목록입니다.</p> : null}
    {value ? <p className="flex flex-wrap items-center gap-2 text-sm"><strong>{value.station_name}</strong> <small className="text-text-secondary">{value.station_id}</small> <Button type="button" variant="link" size="sm" onClick={() => onChange(null)}>선택 해제</Button></p> : null}
    {results.length ? <div className="station-results grid gap-2 sm:grid-cols-2">{results.slice(0, 20).map((station) => <button type="button" className={resultButton} key={station.station_id} aria-pressed={value?.station_id === station.station_id} onClick={() => onChange(station)}><strong className="text-sm">{station.station_name}</strong><small className="text-xs text-text-secondary">{station.station_id}</small></button>)}</div> : query ? <p className="text-sm text-text-secondary">조건에 맞는 역이 없습니다.</p> : null}
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
  return <section className="journey-workbench flex flex-col gap-6">
    <GeneralRailGuide />
    <div id="general-rail-timetable" className="scroll-mt-6" tabIndex={-1} />
    {catalogError ? <Alert variant="destructive"><AlertDescription>{catalogError} <Button type="button" variant="link" size="sm" onClick={() => setReload((v) => v + 1)}>다시 조회</Button></AlertDescription></Alert> : !catalog ? <p role="status" className="text-sm text-text-secondary">열차 종류와 지역을 확인하는 중입니다…</p> : null}
    {catalog?.stale ? <p className="text-sm text-text-secondary">갱신에 실패한 이전 기준정보입니다. 조회 기준 {dateTime(catalog.fetched_at)}</p> : null}
    <FilterBar>
      <FilterField label="열차 종류" htmlFor={`${id}-grade`}>
        <NativeSelect id={`${id}-grade`} value={grade} onChange={(event) => setGrade(event.target.value)}>
          <NativeSelectOption value="">모든 열차</NativeSelectOption>
          {catalog?.train_classes.map((row) => <NativeSelectOption key={row.code} value={row.code}>{row.name}</NativeSelectOption>)}
        </NativeSelect>
      </FilterField>
      <FilterField label="출발일" htmlFor={`${id}-date`}>
        <Input id={`${id}-date`} type="date" min={today} max={seoulDate(9)} value={effectiveDate} onChange={(event) => setDate(event.target.value)} />
      </FilterField>
    </FilterBar>
    <div className="grid gap-4 lg:grid-cols-2">
      <StationSearch label="출발역" cities={catalog?.cities ?? []} value={departure} onChange={setDeparture} />
      <StationSearch label="도착역" cities={catalog?.cities ?? []} value={arrival} onChange={setArrival} />
    </div>
    <div>
      <Button type="button" onClick={() => void load()} disabled={!departure || !arrival || departure.station_id === arrival.station_id || !effectiveDate || current?.pending}>예정 운행편 조회</Button>
    </div>
    {current?.pending ? <p role="status" className="text-sm text-text-secondary">시간표를 조회하는 중입니다…</p> : current?.error ? <Alert variant="destructive"><AlertDescription>{current.error}</AlertDescription></Alert> : null}
    <SectionCard title={`${departure?.station_name ?? "출발역"} → ${arrival?.station_name ?? "도착역"}`} description="예정 출발·도착 시각과 성인 요금을 비교합니다. 실시간 지연·잔여 좌석은 제공하지 않습니다.">
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-brand" checked={futureOnly} onChange={(event) => setFutureOnly(event.target.checked)} />지금 이후만</label>
      {trips ? <>
        <p className="text-sm text-text-secondary">{trips.service_date} · {dateTime(trips.fetched_at)} 조회{trips.stale ? " · 이전 저장 시간표" : ""}{trips.truncated ? " · 일부 결과" : ""}</p>
        <div className="grid">
          {rows?.map((row, index) => <article className="departure-row grid gap-3 border-b border-border py-3 last:border-b-0 sm:grid-cols-[8rem_minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-center" key={`${row.train_number}/${index}`}>
            <div className="flex flex-col gap-0.5"><strong className="text-base tabular-nums">{serviceTime(row.departure_planned_time, trips.service_date)}</strong><p className="text-sm text-text-secondary">{row.departure_station_name}</p></div>
            <div className="flex flex-col gap-0.5"><strong className="text-sm">{row.grade_name ?? "종류 미제공"} {row.train_number}</strong><p className="text-sm text-text-secondary">{row.arrival_station_name} · 도착 {serviceTime(row.arrival_planned_time, row.departure_planned_time ?? trips.service_date)}</p></div>
            <strong className="text-sm tabular-nums">{money(row.adult_fare)}</strong>
          </article>)}
        </div>
        {!rows?.length ? <EmptyState size="sm" title={trips.items.length ? "지금 이후 조건에 맞는 운행편이 없습니다." : "정상 응답에 등록된 운행편이 없습니다."} description={trips.items.length ? "전체 시간표도 확인할 수 있습니다." : "미운행 확정은 아닙니다."} /> : null}
      </> : <p className="text-sm text-text-secondary">출발·도착역을 선택하고 예정 운행편을 조회하세요.</p>}
    </SectionCard>
  </section>;
}
