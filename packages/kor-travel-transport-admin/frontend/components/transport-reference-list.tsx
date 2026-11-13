"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { FilterActions, FilterBar, FilterField } from "@/components/filter-bar";
import { SectionCard } from "@/components/section-card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { useSeoulToday } from "@/lib/journey-hooks";
import { dateTime, hasCoordinates, seoulDate, transportGet, type Place, type StoredFerry } from "@/lib/journey";
import { FerryDepartures, MultiSearch, PlaceDetails } from "./journey-controls";
import { RailTimetables } from "./rail-timetables";

const TransportMap = dynamic(() => import("./transport-map").then((module) => module.TransportMap), { ssr: false, loading: () => <p className="py-11 text-xs text-text-secondary">지도를 준비하는 중입니다…</p> });
export function effectiveFerryServiceDate(serviceDate: string, today = seoulDate()) { return serviceDate < today ? today : serviceDate; }
export function referenceDescription(item: Pick<Place, "line_names" | "provider_id" | "latitude" | "longitude">, rail: boolean) {
  return item.line_names.join(" · ") || [
    item.provider_id ? `${rail ? "역" : "항구"} 코드 ${item.provider_id}` : null,
    hasCoordinates(item) ? "지도 위치 제공" : rail ? "좌표 미등록" : "좌표 미등록 · 운항 검색 가능",
  ].filter(Boolean).join(" · ");
}

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
  return <div className="flex min-w-0 flex-col gap-4">
    <FilterBar>
      {!rail ? <FilterField htmlFor="ferry-service-date" label="운항일">
        <Input id="ferry-service-date" type="date" min={today} max={seoulDate(9)} value={effectiveDate} onChange={(event) => { if (event.target.value) setServiceDate(event.target.value); }} />
      </FilterField> : <FilterField htmlFor="rail-line-filter" label="노선">
        <NativeSelect id="rail-line-filter" value={line} onChange={(event) => setLine(event.target.value)}>
          <NativeSelectOption value="">모든 노선</NativeSelectOption>
          {lines.map((name) => <NativeSelectOption key={name} value={name}>{name}</NativeSelectOption>)}
        </NativeSelect>
      </FilterField>}
      <FilterActions>
        <Button loading={loading} type="button" variant="outline" onClick={() => setReload((value) => value + 1)}>저장 정보 새로고침</Button>
      </FilterActions>
    </FilterBar>
    <p className="text-xs text-text-secondary">저장된 {rail ? "역" : "항구"} {items.length.toLocaleString("ko-KR")}곳 · 지도 좌표 {items.filter(hasCoordinates).length}곳</p>
    {message ? <p className="text-xs text-text-secondary" role="status">{message}</p> : null}
    {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
    <div className="grid min-w-0 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
      <div className="flex min-w-0 flex-col gap-6">
        <MultiSearch label={rail ? "역 또는 노선 검색" : "항구 검색"} query={query} onQuery={setQuery}
          options={filtered.map((item) => ({ id: keyOf(item), name: displayName(item), description: referenceDescription(item, rail) }))}
          selected={selected.map((item) => ({ id: keyOf(item), name: displayName(item) }))} onSelect={toggle} />
        <div className="flex min-w-0 flex-col gap-6" aria-live="polite">
          {!selected.length ? <EmptyState description={rail ? "역을 선택하면 노선·주소·연락처를 비교할 수 있습니다." : "출발 항구를 최대 5곳 선택하세요. 선택 즉시 저장된 운항편을 비교합니다."} framed title={rail ? "역·노선 비교" : "어디에서 출발하시나요?"} /> : null}
          {!rail && selected.length ? <SectionCard title={effectiveDate === today ? "오늘 운항 비교" : `${effectiveDate} 운항 비교`}>
            <FilterBar>
              <FilterField className="w-full sm:w-72" htmlFor="ferry-route-query" label="도착항·선박 검색">
                <Input id="ferry-route-query" type="search" value={routeQuery} onChange={(event) => setRouteQuery(event.target.value)} placeholder="예: 제주, 퀸" />
              </FilterField>
            </FilterBar>
            {loading ? <p className="text-xs text-text-secondary" role="status">저장된 운항 정보를 확인하는 중입니다…</p> : null}
            {(stored?.service_date === effectiveDate ? stored.items : []).map((table) => <FerryDepartures key={table.port_id} timetable={table} query={routeQuery} name={displayName(items.find((item) => item.provider_id === table.port_id) ?? { name: table.port_id, provider_id: table.port_id })} />)}
            {(stored?.service_date === effectiveDate ? stored.missing_port_ids : []).map((id) => <EmptyState description="이 날짜는 아직 수집 중입니다. 운항편이 없다는 뜻은 아닙니다. 정기 수집 후 저장 정보 새로고침으로 확인해 주세요." framed key={id} title={displayName(items.find((item) => item.provider_id === id) ?? { name: id, provider_id: id })} />)}
          </SectionCard> : null}
          {rail && selected.length ? <RailTimetables placeIds={selected.map((place) => place.id)} /> : null}
          {rail ? selected.map((place) => <section className="border-b border-border pb-6 last:border-b-0" key={place.id}><PlaceDetails place={place} showRailTimetable={false} /></section>) : null}
          {activePlace && !rail ? <details className="rounded-panel border border-border bg-card px-4 py-3">
            <summary className="cursor-pointer text-sm font-medium text-text-primary">{displayName(activePlace)} 항구 상세</summary>
            <div className="mt-3"><PlaceDetails place={activePlace} /></div>
          </details> : null}
        </div>
      </div>
      <div className="flex min-w-0 flex-col gap-2">
        <TransportMap places={mapItems} selectedPlace={activePlace} onSelectPlace={(place) => { setActivePlace(place); if (!selectedIds.includes(keyOf(place)) && selectedIds.length < 5) setSelectedIds((current) => [...current, keyOf(place)]); }} />
        <p className="text-xs text-text-secondary">좌표가 없는 장소는 검색·선택 목록에 계속 표시됩니다. {stored?.items.length ? `저장본 최근 확인 ${dateTime(stored.items[0].fetched_at)}` : ""}</p>
      </div>
    </div>
  </div>;
}
