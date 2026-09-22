"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { placeKindLabel } from "@/lib/transport-presentation";

type PlaceKind = "rail_station" | "ferry_port";
type Place = { id: number; kind: PlaceKind; provider_id: string | null; name: string; subtitle: string | null; line_names: string[]; address: string | null; updated_at: string; location_point_count: number | null };
type FerryOperation = { vessel_name: string | null; departure_port_name: string | null; arrival_port_name: string | null; departure_planned_time: string | null; arrival_planned_time: string | null; fare: string | null };

function updatedAt(value: string) { return new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Seoul" }).format(new Date(value)); }
function operationText(item: FerryOperation, portName: string) { return `${item.departure_planned_time ?? "—"} ${item.departure_port_name ?? portName} → ${item.arrival_planned_time ?? "—"} ${item.arrival_port_name ?? "—"}${item.vessel_name ? ` · ${item.vessel_name}` : ""}${item.fare ? ` · ${item.fare}원` : ""}`; }

export function TransportReferenceList({ kind }: { kind: PlaceKind }) {
  const [items, setItems] = useState<Place[]>([]);
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState("저장된 기준정보를 읽는 중입니다…");
  const [selected, setSelected] = useState<Place | null>(null);
  const [operations, setOperations] = useState<string[]>([]);
  const [loadingTimetable, setLoadingTimetable] = useState(false);
  const timetableController = useRef<AbortController | null>(null);

  useEffect(() => {
    let active = true;
    fetch(`/api/transport/transport/features/places?kind=${kind}&limit=500`, { cache: "no-store" })
      .then(async (response) => response.ok ? response.json() : Promise.reject(new Error("저장된 기준정보를 불러오지 못했습니다.")))
      .then((payload: { items: Place[] }) => { if (active) { setItems(payload.items); setMessage(payload.items.length ? "" : "아직 저장된 기준정보가 없습니다."); } })
      .catch((reason: unknown) => { if (active) setMessage(reason instanceof Error ? reason.message : "저장된 기준정보를 불러오지 못했습니다."); });
    return () => { active = false; timetableController.current?.abort(); };
  }, [kind]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("ko-KR");
    return needle ? items.filter((item) => [item.name, item.subtitle, item.address, ...item.line_names].filter(Boolean).join(" ").toLocaleLowerCase("ko-KR").includes(needle)) : items;
  }, [items, query]);

  async function loadTimetable(port: Place) {
    if (!port.provider_id) return;
    timetableController.current?.abort();
    const controller = new AbortController();
    timetableController.current = controller;
    setSelected(port);
    setOperations([]);
    setLoadingTimetable(true);
    try {
      const response = await fetch(`/api/transport/transport/ports/${encodeURIComponent(port.provider_id)}/timetable`, { signal: controller.signal });
      if (!response.ok) {
        const body = await response.json().catch(() => null) as { detail?: string } | null;
        throw new Error(body?.detail ?? "오늘 운항 정보를 불러오지 못했습니다.");
      }
      const payload = await response.json() as { items: FerryOperation[] };
      setOperations(payload.items.map((item) => operationText(item, port.name)));
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setOperations([reason instanceof Error ? reason.message : "오늘 운항 정보를 불러오지 못했습니다."]);
    } finally {
      if (!controller.signal.aborted) setLoadingTimetable(false);
    }
  }

  const rail = kind === "rail_station";
  return <section className="reference-section">
    <div className="reference-toolbar"><label htmlFor={`${kind}-query`}>{rail ? "역 또는 노선 검색" : "항구 검색"}<input id={`${kind}-query`} onChange={(event) => setQuery(event.target.value)} placeholder={rail ? "예: 서울역, 1호선" : "예: 목포, 제주"} value={query} /></label><p className="quiet">저장된 {placeKindLabel(kind)} {filtered.length.toLocaleString("ko-KR")}곳</p></div>
    {message ? <p className="loading">{message}</p> : <div className="reference-list">
      {filtered.map((item) => <article className="reference-card" key={item.id}>
        <p className="eyebrow">{placeKindLabel(kind)}</p><h2>{item.name}</h2>
        {item.subtitle ? <p>{item.subtitle}</p> : null}
        {item.line_names.length ? <p className="reference-lines">운행 노선: {item.line_names.join(", ")}</p> : null}
        {item.address ? <p className="quiet">{item.address}</p> : null}
        <p className="quiet">기준정보 반영: {updatedAt(item.updated_at)}</p>
        {kind === "ferry_port" ? <button className="button" disabled={loadingTimetable && selected?.id === item.id} onClick={() => void loadTimetable(item)} type="button">{loadingTimetable && selected?.id === item.id ? "운항 정보 확인 중…" : "오늘 운항 보기"}</button> : null}
      </article>)}
    </div>}
    {selected ? <section aria-live="polite" className="panel ferry-operations"><h2>{selected.name} 오늘 운항</h2>{operations.length ? <ul className="row-list">{operations.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul> : loadingTimetable ? <p className="quiet">실시간 운항 정보를 확인하는 중입니다…</p> : <p className="quiet">오늘 등록된 운항 정보가 없습니다.</p>}</section> : null}
  </section>;
}
