"use client";
import dynamic from "next/dynamic";
import { useEffect, useId, useState } from "react";
import { dateTime, transportGet, type Place } from "@/lib/journey";
import { useSeoulToday } from "@/lib/journey-hooks";
import { FilterActions, FilterBar, FilterField } from "@/components/filter-bar";
import { EmptyState } from "@/components/empty-state";
import { StatStrip } from "./stat-strip";
import { SectionCard } from "./section-card";
import { Alert, AlertDescription } from "./ui/alert";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { NativeSelect } from "./ui/native-select";
import { NativeSelectOption } from "./ui/native-select-option";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "./ui/table";
const TransportMap = dynamic(() => import("./transport-map").then((module) => module.TransportMap), { ssr: false });
const inlineLink = "rounded-control text-sm font-medium text-brand underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";
const departureRow = "departure-row grid gap-3 border-b border-border py-3 last:border-b-0 sm:grid-cols-[8rem_minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-center";

type Flight = { flight_number: string; direction: string; airline: string | null; scheduled_at: string; estimated_at: string | null; origin_airport: string; destination_airport: string; status: string | null };
type Flights = { items: Flight[]; status: string; error_message: string | null };
type Parking = { parking_lot_id: number; parking_lot_name: string; available_spaces: number; total_spaces: number; observed_at: string; terminal?: string | null };
type Outlook = { generated_at: string; weekday: number; hour: number; items: { parking_lot_id: number; parking_lot_name: string; sample_days: number; observations: number; average_available_spaces: number; minimum_available_spaces: number; maximum_available_spaces: number; full_days: number; full_day_ratio: number; minimum_capacity: number; maximum_capacity: number; latest_observed_at: string }[] };
type Resource<T> = { key: string; data?: T; error?: string };
const plannedClock = () => new Date(Date.now() + 9 * 3600_000).toISOString().slice(0, 16);
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
  const [outlookState, setOutlook] = useState<Resource<Outlook>>({ key: "" });
  const [direction, setDirection] = useState("");
  const [filter, setFilter] = useState("");
  const [futureOnly, setFutureOnly] = useState(true);
  const [arrival, setArrival] = useState(plannedClock);
  const [reload, setReload] = useState(0);
  const [clock, setClock] = useState(() => Date.now());
  const airport = selected?.provider_id ?? "";
  const key = `${airport}/${today}/${reload}`;
  const outlookKey = `${airport}/${arrival}/${reload}`;
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
  useEffect(() => {
    if (!airport || !arrival || !Number.isFinite(Date.parse(`${arrival}:00+09:00`))) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      transportGet<Outlook>(`parking/outlook?${new URLSearchParams({ airport_code: airport, arrival_at: `${arrival}:00+09:00`, days: "28" })}`, controller.signal)
        .then((data) => { if (!controller.signal.aborted) setOutlook({ key: outlookKey, data }); })
        .catch(() => { if (!controller.signal.aborted) setOutlook({ key: outlookKey, error: "과거 주차 패턴을 불러오지 못했습니다." }); });
    }, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [airport, arrival, outlookKey]);
  function select(place: Place) { setSelected(place); try { window.localStorage.setItem("transport-last-airport", place.provider_id ?? ""); } catch { /* 선택을 메모리에 유지한다. */ } }
  const unavailable = catalogError ? "공항 목록을 확인하지 못했습니다." : catalogLoaded ? "저장된 공항이 없습니다." : "공항 목록을 확인하는 중입니다…";
  const parking = parkingState.key === key ? parkingState.data : undefined;
  const flights = flightState.key === key ? flightState.data : undefined;
  const outlook = outlookState.key === outlookKey ? outlookState.data : undefined;
  const rows = flights?.items.filter((row) => (!direction || row.direction === direction) && (!futureOnly || flightMoment(row) >= clock) && [row.flight_number, row.airline, row.origin_airport, row.destination_airport].join(" ").toLocaleLowerCase().includes(filter.toLocaleLowerCase())).sort((a, b) => flightMoment(a) - flightMoment(b));
  const freshParking = parking?.filter((row) => clock - Date.parse(row.observed_at) >= 0 && clock - Date.parse(row.observed_at) <= 15 * 60_000);
  const errors = [catalogError, parkingState.key === key ? parkingState.error : null, flightState.key === key ? flightState.error : null, outlookState.key === outlookKey ? outlookState.error : null].filter(Boolean);
  return <section className="journey-workbench flex flex-col gap-6">
    <nav aria-label="공항 화면 바로가기" className="flex flex-wrap items-center gap-x-4 gap-y-2"><a className={inlineLink} href="#airport-map">공항 지도</a><a className={inlineLink} href="#airport-flights">이후 항공편</a><a className={inlineLink} href="#parking-pattern">주차 패턴</a></nav>
    <FilterBar>
      <FilterField label="공항" htmlFor={`${id}-airport`}>
        <NativeSelect id={`${id}-airport`} value={selected?.id ?? ""} onChange={(event) => { const place = items.find((item) => item.id === Number(event.target.value)); if (place) select(place); }}>
          {!selected ? <NativeSelectOption value="">공항 선택</NativeSelectOption> : null}
          {items.map((item) => <NativeSelectOption key={item.id} value={item.id}>{item.name}</NativeSelectOption>)}
        </NativeSelect>
      </FilterField>
      <FilterActions><Button type="button" variant="outline" onClick={() => setReload((value) => value + 1)}>주차·항공편 새로고침</Button></FilterActions>
    </FilterBar>
    {errors.map((error) => <Alert variant="destructive" key={error}><AlertDescription>{error}</AlertDescription></Alert>)}
    <SectionCard title="지금 주차할 곳" description={`${selected?.name ?? "공항"} · 최근 15분 관측만 현재 잔여 합계에 포함합니다.`}>
      <StatStrip items={[
        { label: "확인된 잔여 주차면", value: freshParking?.length ? freshParking.reduce((sum, row) => sum + row.available_spaces, 0) : null, unit: "면", caption: freshParking ? `${freshParking.length}개 주차장 기준` : parkingState.key === key && parkingState.error ? "조회 실패" : airport ? "조회 중" : unavailable },
        { label: "오늘 이후 출발", value: flights && ["success", "sample"].includes(flights.status) ? flights.items.filter((row) => row.direction === "departure" && flightMoment(row) >= clock).length : null, unit: "편" },
        { label: "오늘 이후 도착", value: flights && ["success", "sample"].includes(flights.status) ? flights.items.filter((row) => row.direction === "arrival" && flightMoment(row) >= clock).length : null, unit: "편" },
      ]} />
      {parking ? parking.length ? <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{parking.map((row) => <article className="flex flex-col gap-1 rounded-panel border border-border bg-card p-4" key={row.parking_lot_id}><strong className="text-sm">{row.parking_lot_name}</strong><span className="text-xs text-text-secondary">{row.terminal}</span><p className="text-sm">잔여 <strong>{row.available_spaces.toLocaleString()}</strong> / {row.total_spaces.toLocaleString()}면</p><small className="text-xs text-text-secondary">{clock - Date.parse(row.observed_at) > 15 * 60_000 ? "갱신 지연 · " : ""}{dateTime(row.observed_at)}</small></article>)}</div> : <p className="text-sm text-text-secondary">저장된 주차 관측이 없습니다.</p> : parkingState.error && parkingState.key === key ? null : <p role="status" className="text-sm text-text-secondary">{airport ? "주차 현황을 확인하는 중입니다…" : unavailable}</p>}
    </SectionCard>
    <div id="airport-flights" className="scroll-mt-6"><SectionCard title="오늘 출도착 항공편" description="공항 선택 시 자동 조회합니다. 예정 시각보다 변경 예정 시각을 우선해 정렬합니다.">
      <FilterBar>
        <FilterField label="방향" htmlFor={`${id}-direction`}>
          <NativeSelect id={`${id}-direction`} value={direction} onChange={(event) => setDirection(event.target.value)}>
            <NativeSelectOption value="">출발·도착 전체</NativeSelectOption>
            <NativeSelectOption value="departure">출발</NativeSelectOption>
            <NativeSelectOption value="arrival">도착</NativeSelectOption>
          </NativeSelect>
        </FilterField>
        <FilterField label="항공편 검색" htmlFor={`${id}-flight`}><Input id={`${id}-flight`} type="search" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="편명·항공사·목적지" /></FilterField>
        <label className="flex items-center gap-2 pb-2 text-sm"><input type="checkbox" className="size-4 accent-brand" checked={futureOnly} onChange={(event) => setFutureOnly(event.target.checked)} />지금 이후만</label>
      </FilterBar>
      {flights?.status === "sample" ? <p role="status" className="text-sm text-text-secondary">예시 항공편 자료입니다. 실제 운항편이 아닙니다.</p> : null}
      {flights && (!["success", "sample"].includes(flights.status) || flights.error_message) ? <Alert variant="destructive"><AlertDescription>{{ disabled: "항공편 조회가 비활성화되어 있습니다.", config_error: "항공편 조회 설정을 확인해야 합니다.", rate_limited: "제공기관 호출 제한으로 조회를 보류했습니다.", upstream_error: "제공기관의 항공편 정보를 확인하지 못했습니다." }[flights.status] ?? "항공편 응답을 확인하지 못했습니다."}</AlertDescription></Alert> : flights ? <div aria-live="polite" className="grid">{rows?.map((row, index) => <article className={departureRow} key={index}>
        <div className="flex flex-col gap-0.5"><strong className="text-base tabular-nums">{new Date(row.estimated_at ?? row.scheduled_at).toLocaleTimeString("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hour12: false })}</strong><span className="text-sm text-text-secondary">{row.flight_number} · {row.direction === "arrival" ? "도착" : "출발"}</span></div>
        <div className="flex flex-col gap-0.5"><strong className="text-sm">{row.origin_airport} → {row.destination_airport}</strong><small className="text-xs text-text-secondary">{row.airline}</small></div>
        <div className="flex flex-col gap-0.5"><strong className="text-sm">{row.status ?? "상태 미제공"}</strong><small className="text-xs text-text-secondary">예정 {dateTime(row.scheduled_at)}</small></div>
      </article>)}{!rows?.length ? <EmptyState size="sm" title="조건에 맞는 이후 항공편이 없습니다." /> : null}</div> : flightState.key === key && flightState.error ? null : <p role="status" className="text-sm text-text-secondary">{airport ? "항공편을 확인하는 중입니다…" : unavailable}</p>}
    </SectionCard></div>
    <div id="parking-pattern" className="scroll-mt-6"><SectionCard title="입차 예정 시각의 과거 패턴" description="최근 28일의 같은 요일·시간대 관측입니다. 평균은 날짜별 평균의 동일 비중 평균입니다. 만차 관측일은 잔여 0면이 한 번 이상 기록된 날이며, 관측이 없는 날은 제외합니다. 오늘의 입차 가능성을 보장하는 예측값은 아닙니다.">
      <FilterBar><FilterField label="주차장 도착 예정(KST)" htmlFor={`${id}-arrival`}><Input id={`${id}-arrival`} type="datetime-local" value={arrival} onChange={(event) => setArrival(event.target.value)} /></FilterField></FilterBar>
      {outlook ? <><div className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>주차장</TableHead><TableHead>평균 잔여</TableHead><TableHead>최소~최대</TableHead><TableHead>만차 관측일</TableHead><TableHead>표본</TableHead></TableRow></TableHeader><TableBody>{outlook.items.map((row) => <TableRow key={row.parking_lot_id}><TableCell className="font-medium">{row.parking_lot_name}{row.minimum_capacity !== row.maximum_capacity ? <small className="text-xs text-text-secondary"> · 수용 규모 변경 있음</small> : null}</TableCell><TableCell className="tabular-nums">{row.average_available_spaces.toLocaleString()}면</TableCell><TableCell className="tabular-nums">{row.minimum_available_spaces}~{row.maximum_available_spaces}면</TableCell><TableCell className="tabular-nums">{row.full_days}/{row.sample_days}일 ({row.full_day_ratio}%)</TableCell><TableCell className="tabular-nums">{row.observations}건{row.sample_days < 3 ? " · 표본 부족" : ""}</TableCell></TableRow>)}</TableBody></Table></div>{!outlook.items.length ? <EmptyState size="sm" title="같은 요일·시간대의 과거 관측이 없습니다." /> : null}<small className="text-xs text-text-secondary">{dateTime(outlook.generated_at)} 조회</small></> : outlookState.key === outlookKey && outlookState.error ? null : !airport ? <p role="status" className="text-sm text-text-secondary">{unavailable}</p> : arrival ? <p role="status" className="text-sm text-text-secondary">주차 패턴을 확인하는 중입니다…</p> : <p className="text-sm text-text-secondary">입차 예정 시각을 선택하세요.</p>}
    </SectionCard></div>
    <div id="airport-map" className="scroll-mt-6" tabIndex={-1}><TransportMap places={items} selectedPlace={selected} onSelectPlace={select} /></div>
  </section>;
}
