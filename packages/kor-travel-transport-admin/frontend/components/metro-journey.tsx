"use client";
import dynamic from "next/dynamic";
import { useEffect, useId, useRef, useState } from "react";
import { MapFilterBar, MapFilterField } from "@kor-travel/ui/map-controls";
import { InfoButton } from "./info-button";
import { Input } from "./ui/input";
import { Button } from "./ui/button";
import { RailTimetables } from "./rail-timetables";
import { dateTime, hasCoordinates, transportGet, type Place } from "@/lib/journey";
import { useNearbyPosition } from "@/lib/journey-hooks";
import { nearestPlaces } from "@/lib/nearby";
const TransportMap = dynamic(() => import("./transport-map").then((m) => m.TransportMap), { ssr: false });

export function MetroJourney() {
  const id = useId();
  const search = useRef<HTMLInputElement>(null);
  const [items, setItems] = useState<Place[] | null>(null);
  const [error, setError] = useState(false);
  const [query, setQuery] = useState("");
  const [line, setLine] = useState("");
  const [selected, setSelected] = useState<Place | null>(null);
  const [view, setView] = useState<"map" | "list">("map");
  const [focusRevision, setFocusRevision] = useState(0);
  const [reload, setReload] = useState(0);
  const { position, positionError, locate, locating } = useNearbyPosition();
  useEffect(() => {
    const controller = new AbortController();
    transportGet<{ items: Place[] }>("transport/features/places?kind=rail_station&include_unlocated=true&limit=5000", controller.signal)
      .then((data) => { if (!controller.signal.aborted) { setItems(data.items); setError(false); } })
      .catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [reload]);
  const routeKey = (place: Place, name: string) => `${place.subtitle ?? ""}/${name}`;
  const routes = new Map((items ?? []).flatMap((place) => place.line_names.map((name) => [routeKey(place, name), `${name} · ${place.subtitle ?? "운영기관 미제공"}`] as const)));
  const filtered = (items ?? []).filter((place) => (!line || place.line_names.some((name) => routeKey(place, name) === line)) && (!query.trim() || [place.name, place.provider_id, ...place.line_names].join(" ").toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())));
  const nearby = position ? nearestPlaces(filtered, position).slice(0, 10) : [];
  function choose(place: Place) { setSelected(place); setFocusRevision((v) => v + 1); }
  function close() { setSelected(null); }
  return <section className="journey-workbench rail-journey map-route">
    <div id="metro-map" className="journey-map-target map-route-primary" tabIndex={-1}><TransportMap places={position && !line && !query.trim() ? nearby.map((row) => row.place) : filtered} selectedPlace={selected} onSelectPlace={choose} view={view} onViewChange={setView} focusRevision={focusRevision} onCloseDetails={close}
    listPlaces={Boolean(line || query.trim() || position)} listContent={!line && !query.trim() && !position ? <p className="quiet">필터에서 노선을 선택하거나 역 이름을 검색하세요.</p> : undefined}
    filterSummary={[routes.get(line), query, position ? "내 근처" : ""].filter(Boolean).join(" · ") || "도시철도 필터"}
    toolbar={<MapFilterBar>
      <MapFilterField label="노선" htmlFor={`${id}-line`}><select id={`${id}-line`} value={line} onChange={(event) => { setLine(event.target.value); setSelected(null); }}><option value="">노선 선택</option>{[...routes].sort((a, b) => a[1].localeCompare(b[1], "ko")).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></MapFilterField>
      <MapFilterField label="역 검색" htmlFor={`${id}-query`}><Input ref={search} id={`${id}-query`} type="search" placeholder="역 이름·코드" value={query} onChange={(event) => { setQuery(event.target.value); setSelected(null); }} /></MapFilterField>
      <Button type="button" variant="outline" disabled={locating} onClick={locate}>{locating ? "위치 확인 중…" : "내 근처 역"}</Button>
      <Button type="button" variant="ghost" onClick={() => { setItems(null); setReload((v) => v + 1); }}>새로고침</Button>
      <a className="inline-link" href="#station-timetable">시간표 보기</a><InfoButton label="역 찾기">노선을 선택하거나 역 이름을 검색하세요. 후보는 목록에서 선택할 수 있습니다. 내 근처 역은 좌표가 등록된 역을 직선 거리 순으로 표시합니다.</InfoButton>
    </MapFilterBar>}
    feedback={<>{positionError ? <p role="alert">{positionError}</p> : null}
    {error ? <p role="alert">역 정보를 불러오지 못했습니다.</p> : !items ? <p role="status">노선과 역을 불러오는 중입니다…</p> : null}
    {position ? <p className="quiet">현재 위치 오차 약 {Math.round(position.accuracy)}m · 거리는 직선 거리입니다.</p> : null}</>}
    detailTitle={<>{selected?.name} <small>{selected?.subtitle}</small></>} details={selected ? <div className="station-detail">
      <p>{selected.line_names.join(" · ")}</p>
      {selected.address ? <button type="button" className="inline-link station-address" disabled={!hasCoordinates(selected)} onClick={() => { setView("map"); choose(selected); }}>{selected.address}{hasCoordinates(selected) ? " · 지도에서 보기" : ""}</button> : <p className="quiet">주소 미제공</p>}
      <p>전화 {selected.phone ? <a className="inline-link" href={`tel:${selected.phone.replace(/[^+\d]/g, "")}`}>{selected.phone}</a> : "미제공"}</p>
      <p>편의시설 {selected.facilities.length ? selected.facilities.join(" · ") : "등록 정보 없음"}</p>
      <p className="quiet">기준정보 {dateTime(selected.updated_at)}</p>
      <a className="inline-link" href="#station-timetable">이후 시간표 보기</a>
    </div> : undefined} /></div>
    <div id="station-timetable" className="map-route-followup">{selected ? <><a className="inline-link" href="#metro-map">지도 작업면으로</a><RailTimetables placeIds={[selected.id]} /></> : null}</div>
  </section>;
}
