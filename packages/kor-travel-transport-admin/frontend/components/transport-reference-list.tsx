"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSeoulToday } from "@/lib/journey-hooks";
import { dateTime, hasCoordinates, seoulDate, transportGet, type Place, type StoredFerry } from "@/lib/journey";
import { FerryDepartures, MultiSearch, PlaceDetails } from "./journey-controls";
import { RailTimetables } from "./rail-timetables";

const TransportMap = dynamic(() => import("./transport-map").then((module) => module.TransportMap), { ssr: false, loading: () => <p className="loading">지도를 준비하는 중입니다…</p> });
export function effectiveFerryServiceDate(serviceDate: string, today = seoulDate()) { return serviceDate < today ? today : serviceDate; }

export function TransportReferenceList({ kind }: { kind: "rail_station" | "ferry_port" }) {
  const [items, setItems] = useState<Place[]>([]);
  const [query, setQuery] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [activePlace, setActivePlace] = useState<Place | null>(null);
  const [message, setMessage] = useState("저장된 기준정보를 읽는 중입니다…");
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [serviceDate, setServiceDate] = useState(seoulDate);
  const [stored, setStored] = useState<StoredFerry | null>(null);
  const [loading, setLoading] = useState(false);
  const [routeQuery, setRouteQuery] = useState("");
  const [line, setLine] = useState("");
  const rail = kind === "rail_station";
  const restoredPort = useRef(false);
  const today = useSeoulToday();
  const effectiveDate = effectiveFerryServiceDate(serviceDate, today);
  useEffect(() => {
    const controller = new AbortController();
    transportGet<{ items: Place[] }>(`transport/features/places?kind=${kind}&include_unlocated=true&limit=5000`, controller.signal).then((payload) => {
      if (controller.signal.aborted) return;
      setError(""); setItems(payload.items); setMessage(payload.items.length ? "" : "아직 저장된 기준정보가 없습니다.");
      const port = new URLSearchParams(window.location.search).get("port");
      if (!restoredPort.current && port) {
        if (payload.items.some((item) => item.provider_id === port)) setSelectedIds([port]);
        else setError("링크의 항구 코드를 저장된 항구에서 찾을 수 없습니다. 항구를 다시 검색해 주세요.");
      }
      restoredPort.current = true;
    }).catch(() => { if (!controller.signal.aborted) { setMessage(""); setError("기준정보를 불러오지 못했습니다. 다시 조회해 주세요."); } });
    return () => controller.abort();
  }, [kind, reload]);

  const keyOf = (place: Place) => rail ? String(place.id) : place.provider_id ?? String(place.id);
  const selected = items.filter((item) => selectedIds.includes(keyOf(item)));
  const nameCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of items) counts.set(item.name, (counts.get(item.name) ?? 0) + 1);
    return counts;
  }, [items]);
  const displayName = (item: Pick<Place, "name" | "provider_id">) => !rail && (nameCounts.get(item.name) ?? 0) > 1
    ? `${item.name} · ${item.provider_id ?? "코드 미제공"} · 지역 미확인` : item.name;
  const selectedKey = selectedIds.join(",");
  useEffect(() => {
    if (rail || !selectedKey) {
      // 취소된 요청의 finally는 실행 상태를 바꾸지 않으므로 빈 선택을 여기서 초기화한다.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLoading(false); setStored(null);
      return;
    }
    const controller = new AbortController();
    const date = effectiveDate;
    // 선택 조건별 비동기 조회가 시작될 때 이전 운항일의 결과를 숨긴다.
    setLoading(true); setError(""); setStored(null);
    transportGet<StoredFerry>(`transport/ports/timetables?${new URLSearchParams({ port_ids: selectedKey, date })}`, controller.signal)
      .then((payload) => { if (!controller.signal.aborted) setStored(payload); })
      .catch(() => { if (!controller.signal.aborted) setError("저장된 운항 정보를 불러오지 못했습니다. 다시 조회해 주세요."); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [rail, selectedKey, effectiveDate, reload]);

  const lines = useMemo(() => [...new Set(items.flatMap((item) => item.line_names))].sort(), [items]);
  const filtered = useMemo(() => items.filter((item) => (!line || item.line_names.includes(line)) && query.trim().split(/\s+/).every((term) => [item.name, item.provider_id, item.subtitle, item.address, ...item.line_names].join(" ").includes(term))), [items, query, line]);
  function toggle(id: string) {
    setSelectedIds((current) => current.includes(id) ? current.filter((value) => value !== id) : current.length < 5 ? [...current, id] : current);
    setActivePlace(selectedIds.includes(id) ? null : items.find((item) => keyOf(item) === id) ?? null);
  }
  const mapItems = (selected.length ? selected : filtered).filter(hasCoordinates);
  return <section className="journey-workbench">
    <div className="journey-toolbar">
      {!rail ? <label htmlFor="ferry-service-date">운항일<input id="ferry-service-date" type="date" min={today} max={seoulDate(9)} value={effectiveDate} onChange={(event) => { if (event.target.value) setServiceDate(event.target.value); }} /></label> : <label>노선<select value={line} onChange={(event) => setLine(event.target.value)}><option value="">모든 노선</option>{lines.map((name) => <option key={name}>{name}</option>)}</select></label>}
      <p className="quiet">저장된 {rail ? "역" : "항구"} {items.length.toLocaleString("ko-KR")}곳 · 지도 좌표 {items.filter(hasCoordinates).length}곳</p>
      <button className="secondary" type="button" disabled={loading} onClick={() => setReload((value) => value + 1)}>저장 정보 새로고침</button>
    </div>
    {message ? <p role="status">{message}</p> : null}
    {error ? <p className="error" role="alert">{error}</p> : null}
    <div className="journey-layout">
      <div className="journey-search">
        <MultiSearch label={rail ? "역 또는 노선 검색" : "항구 검색"} query={query} onQuery={setQuery}
          options={filtered.map((item) => ({ id: keyOf(item), name: displayName(item), description: item.line_names.join(" · ") || [item.provider_id ? `항구 코드 ${item.provider_id}` : null, hasCoordinates(item) ? "지도 위치 제공" : "좌표 미등록 · 운항 검색 가능"].filter(Boolean).join(" · ") }))}
          selected={selected.map((item) => ({ id: keyOf(item), name: displayName(item) }))} onSelect={toggle} />
      </div>
      <div className="journey-inspector" aria-live="polite">
        {!selected.length ? <div className="empty-state"><h2>{rail ? "역·노선 비교" : "어디에서 출발하시나요?"}</h2><p>{rail ? "역을 선택하면 노선·주소·연락처를 비교할 수 있습니다." : "출발 항구를 최대 5곳 선택하세요. 선택 즉시 저장된 운항편을 비교합니다."}</p></div> : null}
        {!rail && selected.length ? <>
          <div className="journey-toolbar"><h2>{effectiveDate === today ? "오늘 운항" : `${effectiveDate} 운항`} 비교</h2><label>도착항·선박 검색<input type="search" value={routeQuery} onChange={(event) => setRouteQuery(event.target.value)} placeholder="예: 제주, 퀸" /></label></div>
          {loading ? <p role="status">저장된 운항 정보를 확인하는 중입니다…</p> : null}
          {(stored?.service_date === effectiveDate ? stored.items : []).map((table) => <FerryDepartures key={table.port_id} timetable={table} query={routeQuery} name={displayName(items.find((item) => item.provider_id === table.port_id) ?? { name: table.port_id, provider_id: table.port_id })} />)}
          {(stored?.service_date === effectiveDate ? stored.missing_port_ids : []).map((id) => <section className="empty-state" key={id}><h3>{displayName(items.find((item) => item.provider_id === id) ?? { name: id, provider_id: id })}</h3><p>이 날짜는 아직 수집 중입니다. 운항편이 없다는 뜻은 아닙니다. 정기 수집 후 저장 정보 새로고침으로 확인해 주세요.</p></section>)}
        </> : null}
        {rail && selected.length ? <RailTimetables placeIds={selected.map((place) => place.id)} /> : null}
        {rail ? selected.map((place) => <section className="reference-detail" key={place.id}><PlaceDetails place={place} showRailTimetable={false} /></section>) : null}
        {activePlace && !rail ? <details><summary>{displayName(activePlace)} 항구 상세</summary><PlaceDetails place={activePlace} /></details> : null}
      </div>
      <div className="journey-map"><TransportMap places={mapItems} selectedPlace={activePlace} onSelectPlace={(place) => { setActivePlace(place); if (!selectedIds.includes(keyOf(place)) && selectedIds.length < 5) setSelectedIds((current) => [...current, keyOf(place)]); }} />
        <p className="quiet">좌표가 없는 장소는 검색·선택 목록에 계속 표시됩니다. {stored?.items.length ? `저장본 최근 확인 ${dateTime(stored.items[0].fetched_at)}` : ""}</p>
      </div>
    </div>
  </section>;
}
