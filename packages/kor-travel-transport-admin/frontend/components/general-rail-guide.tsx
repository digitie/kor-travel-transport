"use client";

import dynamic from "next/dynamic";
import { useEffect, useId, useRef, useState } from "react";
import { MapFilterBar, MapFilterField } from "@kor-travel/ui/map-controls";
import { hasCoordinates, transportGet, type Place } from "@/lib/journey";
import { useNearbyPosition } from "@/lib/journey-hooks";
import { nearestPlaces } from "@/lib/nearby";
import { Input } from "./ui/input";
import { InfoButton } from "./info-button";
import { Button } from "./ui/button";

const TransportMap = dynamic(() => import("./transport-map").then((m) => m.TransportMap), { ssr: false });
type Guide = { fetched_at: string; stale: boolean; kind: "ktx" | "main"; category_code: string; total: number;
  categories: { code: string; name: string }[];
  items: { provider_id: string; station_code: string | null; station_name: string; address: string | null; phone: string | null; longitude: number | null; latitude: number | null }[] };

export type GeneralRailStationReference = { provider: "korail_public_guide"; provider_id: string; name: string };
export type GeneralRailStationIntent = { role: "departure" | "arrival"; station: GeneralRailStationReference };
const stationKey = (providerId: string) => JSON.stringify(["korail_public_guide", providerId]);

export function GeneralRailGuide({ onStationIntent }: { onStationIntent?: (intent: GeneralRailStationIntent) => void } = {}) {
  const id = useId();
  const [kind, setKind] = useState<"ktx" | "main">("ktx");
  const [category, setCategory] = useState("");
  const [query, setQuery] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  // 지도 렌더링용 숫자는 외부 역 식별자가 아니다. 목록 순서가 바뀌어도 같은 provider 참조에 유지한다.
  const markerIds = useRef(new Map<string, number>());
  const [view, setView] = useState<"map" | "list">("map");
  const [focusRevision, setFocusRevision] = useState(0);
  const [response, setResponse] = useState<{ key: string; data?: Guide; places?: Place[]; error?: string }>({ key: "" });
  const [reload, setReload] = useState(0);
  const { position, positionError, locating, locate } = useNearbyPosition();
  const key = `${kind}/${category}/${reload}`;
  useEffect(() => {
    const controller = new AbortController();
    transportGet<Guide>(`transport/rail/general/guide?${new URLSearchParams({ kind, category_code: category })}`, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        const places: Place[] = data.items.map((row) => {
          const identity = stationKey(row.provider_id);
          if (!markerIds.current.has(identity)) markerIds.current.set(identity, markerIds.current.size + 1);
          return { id: markerIds.current.get(identity)!, provider_id: row.provider_id,
            kind: "rail_station", source: "korail_public_guide", name: row.station_name, address: row.address, phone: row.phone,
            longitude: row.longitude, latitude: row.latitude, updated_at: data.fetched_at,
            line_names: data.categories.filter((entry) => entry.code === category).map((entry) => entry.name), facilities: [], prices: [] };
        });
        setResponse({ key, data, places });
      })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setResponse({ key, error: reason instanceof Error ? reason.message : "역 안내 조회 실패" }); });
    return () => controller.abort();
  }, [kind, category, key]);
  const current = response.key === key ? response : undefined;
  // 조회 도중에도 같은 구분의 선택 목록은 유지한다. 다른 구분의 노선·권역은 섞지 않는다.
  const categories = response.data?.kind === kind ? response.data.categories : [];
  const places = current?.places ?? [];
  const selected = places.find((place) => stationKey(place.provider_id ?? "") === selectedKey) ?? null;
  const filtered = places.filter((place) => !query.trim() || place.name.includes(query.trim()));
  const nearby = position ? nearestPlaces(filtered, position).slice(0, 10) : [];
  const displayedPlaces = position ? nearby.map((row) => row.place) : filtered;
  const listMessage = current?.data && !displayedPlaces.length ? !category && !query.trim() ? "노선이나 권역을 선택해 역을 찾으세요." : "조건에 맞는 역이 없습니다. 다른 이름이나 노선·권역을 선택해 주세요." : "";
  function choose(place: Place) { setSelectedKey(stationKey(place.provider_id ?? "")); setFocusRevision((value) => value + 1); }
  function requestStation(role: GeneralRailStationIntent["role"]) {
    if (selected?.provider_id?.trim()) onStationIntent?.({ role,
      station: { provider: "korail_public_guide", provider_id: selected.provider_id, name: selected.name } });
  }
  return <section className="journey-workbench rail-journey map-route map-route-primary" aria-label="철도 역 지도">
    <div id="general-rail-map" className="journey-map-target map-route-primary" tabIndex={-1}><TransportMap places={displayedPlaces} selectedPlace={selected} detailKey={selectedKey ?? undefined} onSelectPlace={choose} view={view} onViewChange={setView} focusRevision={focusRevision} onCloseDetails={() => setSelectedKey(null)}
    listContent={listMessage ? <p className="quiet" role="status">{listMessage}</p> : undefined}
    filterSummary={`${kind === "ktx" ? "KTX" : "일반철도"} · ${categories.find((row) => row.code === category)?.name ?? "노선·권역 선택"}${query ? ` · ${query}` : ""}`}
    toolbar={<MapFilterBar>
      <MapFilterField label="역 안내 구분" htmlFor={`${id}-kind`}><select id={`${id}-kind`} value={kind} onChange={(event) => { setKind(event.target.value as "ktx" | "main"); setCategory(""); setQuery(""); setSelectedKey(null); }}><option value="ktx">KTX 노선</option><option value="main">일반철도 권역</option></select></MapFilterField>
      <MapFilterField label={kind === "ktx" ? "노선" : "권역"} htmlFor={`${id}-category`}><select id={`${id}-category`} value={category} onChange={(event) => { setCategory(event.target.value); setSelectedKey(null); }}><option value="">{kind === "ktx" ? "노선 선택" : "권역 선택"}</option>{categories.map((row) => <option key={row.code} value={row.code}>{row.name}</option>)}</select></MapFilterField>
      <MapFilterField label="역 이름" htmlFor={`${id}-query`}><Input id={`${id}-query`} type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="선택 범위에서 검색" /></MapFilterField>
      <button type="button" className="secondary" disabled={locating || !category} onClick={locate}>{locating ? "위치 확인 중…" : "내 근처 역"}</button>
      <a className="inline-link" href="#general-rail-timetable">시간표 조회</a><InfoButton label="철도 역 안내">코레일 공개 역 안내입니다. KTX는 노선별, 일반철도는 권역별로 역을 찾습니다. 지도는 역 위치를 표시하며 선로 경로나 정차 순서를 뜻하지 않습니다. 출발·도착 지정은 역 이름을 시간표 검색에 전달합니다. 지역과 실제 TAGO 후보를 확인해 선택해야 하며, 같은 이름을 같은 역으로 자동 연결하지 않습니다.</InfoButton>
    </MapFilterBar>}
    feedback={<>{current?.error ? <p role="alert">{current.error} <button type="button" className="inline-link" onClick={() => setReload((value) => value + 1)}>다시 조회</button></p> : !current?.data ? <p role="status">공개 역 안내 조회 중…</p> : null}
    {current?.data?.stale ? <p role="status">갱신에 실패한 이전 역 안내입니다.</p> : null}
    {positionError ? <p role="alert">{positionError}</p> : null}</>}
    details={selected ? <div className="station-detail"><p>{selected.line_names.join(" · ")}</p>{onStationIntent ? <div className="flex flex-wrap gap-2"><Button type="button" variant="outline" size="sm" disabled={!selected.provider_id?.trim()} onClick={() => requestStation("departure")}>출발로 지정</Button><Button type="button" variant="outline" size="sm" disabled={!selected.provider_id?.trim()} onClick={() => requestStation("arrival")}>도착으로 지정</Button></div> : null}{selected.address ? <button className="inline-link station-address" type="button" disabled={!hasCoordinates(selected)} onClick={() => { setView("map"); choose(selected); }}>{selected.address}{hasCoordinates(selected) ? " · 지도에서 보기" : ""}</button> : null}<p>전화 {selected.phone ? <a className="inline-link" href={`tel:${selected.phone.replace(/[^+\d]/g, "")}`}>{selected.phone}</a> : "미제공"}</p><p className="quiet">코레일 공개 역 안내 · 편의시설은 역 안내에서 확인</p><a className="inline-link" target="_blank" rel="noreferrer" href={`https://www.korail.com/ticket/train/stationGuide/station/view?stationSeq=${encodeURIComponent(selected.provider_id ?? "")}`}>공식 역 안내 ↗</a> <a className="inline-link" href="#general-rail-timetable">예정 시간표 조회</a></div> : undefined} /></div>
  </section>;
}
