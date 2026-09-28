"use client";

import { Anchor, Bus, Fuel, Plane, TrainFront, Coffee, MapPin, TriangleAlert, X } from "lucide-react";
import { useId } from "react";
import { dateTime, hasCoordinates, money, serviceTime, type FerryTimetable, type Place } from "@/lib/journey";
import { collectionSourceLabel, fuelProductLabel, placeKindLabel } from "@/lib/transport-presentation";
import { RailTimetables } from "./rail-timetables";

export function PlaceIcon({ kind }: { kind: string }) {
  const Icon = ({ fuel_station: Fuel, rail_station: TrainFront, ferry_port: Anchor, airport: Plane, rest_area: Coffee, bus_terminal: Bus, highway_incident: TriangleAlert } as const)[kind as Place["kind"]] ?? MapPin;
  return <Icon size={18} aria-hidden="true" />;
}

export function ViewSwitch({ value, onChange }: { value: "map" | "list"; onChange: (value: "map" | "list") => void }) {
  return <div className="view-switch" role="group" aria-label="보기 방식"><button type="button" aria-pressed={value === "map"} onClick={() => onChange("map")}>지도</button><button type="button" aria-pressed={value === "list"} onClick={() => onChange("list")}>목록</button></div>;
}

export function MultiSearch({ label, query, onQuery, options, selected, onSelect, max = 5, loading = false }: {
  label: string; query: string; onQuery: (value: string) => void;
  options: { id: string; name: string; description?: string }[];
  selected: { id: string; name: string }[]; onSelect: (id: string) => void; max?: number; loading?: boolean;
}) {
  const id = useId();
  return <section className="multi-search">
    <label htmlFor={id}>{label}<input id={id} type="search" value={query} onChange={(event) => onQuery(event.target.value)} placeholder="이름·지역으로 검색" autoComplete="off" /></label>
    {selected.length ? <div className="selection-chips" aria-label="선택한 장소">{selected.map((item) => <button type="button" key={item.id} onClick={() => onSelect(item.id)} aria-label={`${item.name} 선택 해제`}><span>{item.name}</span><X size={14} aria-hidden="true" /></button>)}</div> : null}
    <p className="quiet" role="status">{loading ? "검색 중…" : `${options.length}개 결과 · ${selected.length}/${max}곳 선택`}</p>
    <div className="search-options">{options.slice(0, 60).map((item) => <label key={item.id}><input type="checkbox" checked={selected.some((value) => value.id === item.id)} disabled={max > 1 && selected.length >= max && !selected.some((value) => value.id === item.id)} onChange={() => onSelect(item.id)} /><span><strong>{item.name}</strong>{item.description ? <small>{item.description}</small> : null}</span></label>)}</div>
    {!loading && !options.length ? <p className="empty-state">검색 결과가 없습니다. 다른 이름이나 지역을 입력해 주세요.</p> : null}
    {options.length > 60 ? <p className="quiet">상위 60곳을 표시합니다. 검색어를 입력해 범위를 좁혀 주세요.</p> : null}
  </section>;
}

export function PlaceDetails({ place, showRailTimetable = true, showHeading = true }: { place: Place; showRailTimetable?: boolean; showHeading?: boolean }) {
  return <div className="place-details">
    {showHeading ? <><div className="place-title"><PlaceIcon kind={place.kind} /><span>{placeKindLabel(place.kind)}</span></div><h2>{place.name}</h2></> : null}
    {place.brand_name ? <p>{place.brand_name}</p> : null}
    {place.line_names.length ? <div className="line-chips">{place.line_names.map((line) => <span key={line}>{line}</span>)}</div> : null}
    {place.subtitle ? <p>{place.subtitle}</p> : null}
    {place.prices?.length ? <dl className="price-grid">{place.prices.map((price) => <div key={price.product_code}><dt>{fuelProductLabel(price.product_code)}</dt><dd>{money(price.price, "원/L")}</dd><small>{dateTime(price.provider_updated_at ?? price.observed_at)}</small></div>)}</dl> : place.kind === "fuel_station" ? <p className="quiet">등록된 유가가 없습니다.</p> : null}
    {place.address ? <p>{place.address}</p> : null}
    {place.phone ? <p>전화 {place.phone}</p> : null}
    {place.facilities?.length ? <p>편의시설 · {place.facilities.join(" · ")}</p> : null}
    {place.kind === "rail_station" && showRailTimetable ? <RailTimetables placeIds={[place.id]} /> : null}
    {place.kind === "ferry_port" ? <p className="data-caveat">{hasCoordinates(place) ? "항만 안내 지점입니다. 실제 승선 장소는 여객터미널에 확인해 주세요." : "좌표 미등록 · 목록에서 운항 정보를 확인할 수 있습니다."}</p> : null}
    <p className="quiet">출처 {collectionSourceLabel(place.source)} · 기준정보 반영 {dateTime(place.updated_at)}</p>
  </div>;
}

export function FerryDepartures({ timetable, name, query = "" }: { timetable: FerryTimetable; name: string; query?: string }) {
  const rows = timetable.items.filter((item) => [item.arrival_port_name, item.departure_port_name, item.vessel_name].join(" ").includes(query.trim())).sort((a, b) => (a.departure_planned_time ?? "").localeCompare(b.departure_planned_time ?? ""));
  return <section className="departures" aria-label={`${name} 운항 정보`}>
    <header><h3>{name} · {timetable.service_date}</h3><p className="quiet">저장본 확인 {dateTime(timetable.fetched_at)} · {rows.length}편</p></header>
    {rows.length ? rows.map((item, index) => <article className="departure-row" key={index}>
      <div className="departure-time"><strong>{serviceTime(item.departure_planned_time, timetable.service_date)}</strong><span>{item.departure_port_name ?? name}</span></div>
      <div className="departure-route"><span aria-hidden="true">→</span><strong>{item.arrival_port_name ?? "도착항 미제공"}</strong><small>도착 {serviceTime(item.arrival_planned_time, timetable.service_date)}</small></div>
      <div className="departure-meta"><strong>{item.vessel_name ?? "선박명 미제공"}</strong><span>{money(item.fare)}</span></div>
    </article>) : <p className="empty-state">{query ? "조건에 맞는 운항편이 없습니다." : "제공기관의 마지막 저장 응답에 등록된 운항편이 없습니다. 결항을 의미하지는 않습니다."}</p>}
    <p className="quiet">예정 시간·요금은 변경될 수 있습니다. 승선 전 운항사에 확인해 주세요.</p>
  </section>;
}
