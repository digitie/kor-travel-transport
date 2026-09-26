"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { placeKindLabel } from "@/lib/transport-presentation";

type PlaceKind = "rail_station" | "ferry_port";
type Place = { id: number; kind: PlaceKind; provider_id: string | null; name: string; subtitle: string | null; line_names: string[]; address: string | null; updated_at: string; location_point_count: number | null };
type FerryOperation = { vessel_name: string | null; departure_port_name: string | null; arrival_port_name: string | null; departure_planned_time: string | null; arrival_planned_time: string | null; fare: string | null };
const REFERENCE_LIMIT = 5_000;
const INITIAL_VISIBLE_COUNT = 60;

function updatedAt(value: string) { return new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Seoul" }).format(new Date(value)); }
function operationText(item: FerryOperation, portName: string) { return `${item.departure_planned_time ?? "—"} ${item.departure_port_name ?? portName} → ${item.arrival_planned_time ?? "—"} ${item.arrival_port_name ?? "—"}${item.vessel_name ? ` · ${item.vessel_name}` : ""}${item.fare ? ` · ${item.fare}원` : ""}`; }
function seoulDateValue(offsetDays = 0) { const date = new Date(Date.now() + (9 * 60 * 60 * 1000)); date.setUTCDate(date.getUTCDate() + offsetDays); return date.toISOString().slice(0, 10); }
export function effectiveFerryServiceDate(serviceDate: string, today = seoulDateValue()) { return serviceDate < today ? today : serviceDate; }

export function TransportReferenceList({ kind }: { kind: PlaceKind }) {
  const [items, setItems] = useState<Place[]>([]);
  const [query, setQuery] = useState("");
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE_COUNT);
  const [message, setMessage] = useState("저장된 기준정보를 읽는 중입니다…");
  const [selected, setSelected] = useState<Place | null>(null);
  const [operations, setOperations] = useState<string[]>([]);
  const [loadingTimetable, setLoadingTimetable] = useState(false);
  const [serviceDate, setServiceDate] = useState(() => seoulDateValue());
  const timetableController = useRef<AbortController | null>(null);
  const timetableRequest = useRef(0);

  useEffect(() => {
    let active = true;
    fetch(`/api/transport/transport/features/places?kind=${kind}&limit=${REFERENCE_LIMIT}`, { cache: "no-store" })
      .then(async (response) => response.ok ? response.json() : Promise.reject(new Error("저장된 기준정보를 불러오지 못했습니다.")))
      .then((payload: { items: Place[] }) => { if (active) { setItems(payload.items); setMessage(payload.items.length ? "" : "아직 저장된 기준정보가 없습니다."); } })
      .catch((reason: unknown) => { if (active) setMessage(reason instanceof Error ? reason.message : "저장된 기준정보를 불러오지 못했습니다."); });
    return () => { active = false; timetableRequest.current += 1; timetableController.current?.abort(); };
  }, [kind]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("ko-KR");
    return needle ? items.filter((item) => [item.name, item.subtitle, item.address, ...item.line_names].filter(Boolean).join(" ").toLocaleLowerCase("ko-KR").includes(needle)) : items;
  }, [items, query]);
  const visibleItems = filtered.slice(0, visibleCount);

  async function loadTimetable(port: Place) {
    if (!port.provider_id) return;
    // 화면을 자정 전에 연 뒤에도 API에는 항상 현재 KST 이후의 운항일만 보낸다.
    const todayAtRequest = seoulDateValue();
    const requestedServiceDate = effectiveFerryServiceDate(serviceDate, todayAtRequest);
    if (requestedServiceDate !== serviceDate) setServiceDate(requestedServiceDate);
    const request = ++timetableRequest.current;
    timetableController.current?.abort();
    const controller = new AbortController();
    timetableController.current = controller;
    setSelected(port);
    setOperations([]);
    setLoadingTimetable(true);
    try {
      const response = await fetch(`/api/transport/transport/ports/${encodeURIComponent(port.provider_id)}/timetable?date=${encodeURIComponent(requestedServiceDate)}`, { signal: controller.signal });
      if (!response.ok) {
        const body = await response.json().catch(() => null) as { detail?: string } | null;
        if (response.status === 429) {
          const retryAfter = response.headers.get("retry-after");
          throw new Error(retryAfter ? `요청이 많습니다. ${retryAfter}초 뒤에 다시 확인해 주세요.` : "요청이 많습니다. 잠시 뒤에 다시 확인해 주세요.");
        }
        throw new Error(body?.detail ?? "운항 정보를 불러오지 못했습니다.");
      }
      const payload = await response.json() as { items: FerryOperation[] };
      if (request === timetableRequest.current) setOperations(payload.items.map((item) => operationText(item, port.name)));
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      if (request === timetableRequest.current) setOperations([reason instanceof Error ? reason.message : "운항 정보를 불러오지 못했습니다."]);
    } finally {
      if (request === timetableRequest.current) setLoadingTimetable(false);
    }
  }

  const rail = kind === "rail_station";
  const today = seoulDateValue();
  const timetableLabel = serviceDate === today ? "오늘 운항" : `${serviceDate} 운항`;
  return <section className="reference-section">
    <div className="reference-toolbar"><label htmlFor={`${kind}-query`}>{rail ? "역 또는 노선 검색" : "항구 검색"}<input id={`${kind}-query`} onChange={(event) => { setQuery(event.target.value); setVisibleCount(INITIAL_VISIBLE_COUNT); }} placeholder={rail ? "예: 서울역, 1호선" : "예: 목포, 제주"} value={query} /></label>{!rail ? <label htmlFor="ferry-service-date">운항일<input id="ferry-service-date" max={seoulDateValue(9)} min={today} onChange={(event) => { setServiceDate(event.target.value); setSelected(null); setOperations([]); }} type="date" value={serviceDate} /></label> : null}<p className="quiet">{query.trim() ? `검색 결과 ${filtered.length.toLocaleString("ko-KR")}곳 · ` : ""}저장된 {placeKindLabel(kind)} {items.length.toLocaleString("ko-KR")}곳</p></div>
    {message ? <p className="loading">{message}</p> : <div className="reference-list">
      {visibleItems.map((item) => <article className="reference-card" key={item.id}>
        <p className="eyebrow">{placeKindLabel(kind)}</p><h2>{item.name}</h2>
        {item.subtitle ? <p>{item.subtitle}</p> : null}
        {item.line_names.length ? <p className="reference-lines">운행 노선: {item.line_names.join(", ")}</p> : null}
        {item.address ? <p className="quiet">{item.address}</p> : null}
        <p className="quiet">기준정보 반영: {updatedAt(item.updated_at)}</p>
        {kind === "ferry_port" ? <button className="button" disabled={loadingTimetable && selected?.id === item.id} onClick={() => void loadTimetable(item)} type="button">{loadingTimetable && selected?.id === item.id ? "운항 정보 확인 중…" : `${timetableLabel} 보기`}</button> : null}
      </article>)}
    </div>}
    {!message && visibleItems.length < filtered.length ? <button className="button reference-more" onClick={() => setVisibleCount((count) => count + INITIAL_VISIBLE_COUNT)} type="button">{Math.min(INITIAL_VISIBLE_COUNT, filtered.length - visibleItems.length).toLocaleString("ko-KR")}곳 더 보기</button> : null}
    {selected ? <section aria-live="polite" className="panel ferry-operations"><h2>{selected.name} {timetableLabel}</h2>{operations.length ? <ul className="row-list">{operations.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul> : loadingTimetable ? <p className="quiet">저장된 운항 정보를 확인하는 중입니다…</p> : <p className="quiet">{timetableLabel}이 없습니다.</p>}</section> : null}
  </section>;
}
