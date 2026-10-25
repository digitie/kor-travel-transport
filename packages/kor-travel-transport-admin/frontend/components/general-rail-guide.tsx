"use client";

import dynamic from "next/dynamic";
import { useEffect, useId, useState } from "react";
import { MapFilterBar, MapFilterField } from "@kor-travel/ui/map-controls";
import { hasCoordinates, transportGet, type Place } from "@/lib/journey";
import { useNearbyPosition } from "@/lib/journey-hooks";
import { nearestPlaces } from "@/lib/nearby";
import { Input } from "./ui/input";
import { InfoButton } from "./info-button";

const TransportMap = dynamic(() => import("./transport-map").then((m) => m.TransportMap), { ssr: false });
type Guide = { fetched_at: string; stale: boolean; kind: "ktx" | "main"; category_code: string; total: number;
  categories: { code: string; name: string }[];
  items: { provider_id: string; station_code: string | null; station_name: string; address: string | null; phone: string | null; longitude: number | null; latitude: number | null }[] };

export function GeneralRailGuide() {
  const id = useId();
  const [kind, setKind] = useState<"ktx" | "main">("ktx");
  const [category, setCategory] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Place | null>(null);
  const [view, setView] = useState<"map" | "list">("map");
  const [focusRevision, setFocusRevision] = useState(0);
  const [response, setResponse] = useState<{ key: string; data?: Guide; error?: string }>({ key: "" });
  const [reload, setReload] = useState(0);
  const { position, positionError, locating, locate } = useNearbyPosition();
  const key = `${kind}/${category}/${reload}`;
  useEffect(() => {
    const controller = new AbortController();
    transportGet<Guide>(`transport/rail/general/guide?${new URLSearchParams({ kind, category_code: category })}`, controller.signal)
      .then((data) => { if (!controller.signal.aborted) setResponse({ key, data }); })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setResponse({ key, error: reason instanceof Error ? reason.message : "역 안내 조회 실패" }); });
    return () => controller.abort();
  }, [kind, category, key]);
  const current = response.key === key ? response : undefined;
  // 조회 도중에도 같은 구분의 선택 목록은 유지한다. 다른 구분의 노선·권역은 섞지 않는다.
  const categories = response.data?.kind === kind ? response.data.categories : [];
  const places: Place[] = (current?.data?.items ?? []).map((row, index) => ({ id: index + 1, provider_id: row.provider_id,
    kind: "rail_station", source: "korail_public_guide", name: row.station_name, address: row.address, phone: row.phone,
    longitude: row.longitude, latitude: row.latitude, updated_at: current!.data!.fetched_at,
    line_names: categories.filter((row) => row.code === category).map((row) => row.name), facilities: [], prices: [] }));
  const filtered = places.filter((place) => !query.trim() || place.name.includes(query.trim()));
  const nearby = position ? nearestPlaces(filtered, position).slice(0, 10) : [];
  function choose(place: Place) { setSelected(place); setFocusRevision((value) => value + 1); }
  return <section className="journey-workbench rail-journey map-route map-route-primary" aria-label="철도 역 지도">
    <div id="general-rail-map" className="journey-map-target map-route-primary" tabIndex={-1}><TransportMap places={position ? nearby.map((row) => row.place) : filtered} selectedPlace={selected} onSelectPlace={choose} view={view} onViewChange={setView} focusRevision={focusRevision} onCloseDetails={() => setSelected(null)}
    filterSummary={`${kind === "ktx" ? "KTX" : "일반철도"} · ${categories.find((row) => row.code === category)?.name ?? "노선·권역 선택"}${query ? ` · ${query}` : ""}`}
    toolbar={<MapFilterBar>
      <MapFilterField label="역 안내 구분" htmlFor={`${id}-kind`}><select id={`${id}-kind`} value={kind} onChange={(event) => { setKind(event.target.value as "ktx" | "main"); setCategory(""); setQuery(""); setSelected(null); }}><option value="ktx">KTX 노선</option><option value="main">일반철도 권역</option></select></MapFilterField>
      <MapFilterField label={kind === "ktx" ? "노선" : "권역"} htmlFor={`${id}-category`}><select id={`${id}-category`} value={category} onChange={(event) => { setCategory(event.target.value); setSelected(null); }}><option value="">{kind === "ktx" ? "노선 선택" : "권역 선택"}</option>{categories.map((row) => <option key={row.code} value={row.code}>{row.name}</option>)}</select></MapFilterField>
      <MapFilterField label="역 이름" htmlFor={`${id}-query`}><Input id={`${id}-query`} type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="선택 범위에서 검색" /></MapFilterField>
      <button type="button" className="secondary" disabled={locating || !category} onClick={locate}>{locating ? "위치 확인 중…" : "내 근처 역"}</button>
      <a className="inline-link" href="#general-rail-timetable">시간표 조회</a><InfoButton label="철도 역 안내">코레일 공개 역 안내입니다. KTX는 노선별, 일반철도는 권역별로 역을 찾습니다. 지도는 역 위치를 표시하며 선로 경로나 정차 순서를 뜻하지 않습니다. 시간표는 아래 TAGO 역 목록에서 출발·도착역을 선택해 조회합니다.</InfoButton>
    </MapFilterBar>}
    feedback={<>{current?.error ? <p role="alert">{current.error} <button type="button" className="inline-link" onClick={() => setReload((value) => value + 1)}>다시 조회</button></p> : !current?.data ? <p role="status">공개 역 안내 조회 중…</p> : null}
    {current?.data?.stale ? <p role="status">갱신에 실패한 이전 역 안내입니다.</p> : null}
    {positionError ? <p role="alert">{positionError}</p> : null}</>}
    details={selected ? <div className="station-detail"><p>{selected.line_names.join(" · ")}</p>{selected.address ? <button className="inline-link station-address" type="button" disabled={!hasCoordinates(selected)} onClick={() => { setView("map"); choose(selected); }}>{selected.address}{hasCoordinates(selected) ? " · 지도에서 보기" : ""}</button> : null}<p>전화 {selected.phone ? <a className="inline-link" href={`tel:${selected.phone.replace(/[^+\d]/g, "")}`}>{selected.phone}</a> : "미제공"}</p><p className="quiet">코레일 공개 역 안내 · 편의시설은 역 안내에서 확인</p><a className="inline-link" target="_blank" rel="noreferrer" href={`https://www.korail.com/ticket/train/stationGuide/station/view?stationSeq=${encodeURIComponent(selected.provider_id ?? "")}`}>공식 역 안내 ↗</a> <a className="inline-link" href="#general-rail-timetable">예정 시간표 조회</a></div> : undefined} /></div>
  </section>;
}
