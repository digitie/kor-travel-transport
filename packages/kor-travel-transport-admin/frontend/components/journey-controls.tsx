"use client";

import { Anchor, Bus, Fuel, Plane, TrainFront, Coffee, MapPin, TriangleAlert, X } from "lucide-react";
import { useId } from "react";
import { dateTime, hasCoordinates, money, serviceTime, type FerryTimetable, type Place } from "@/lib/journey";
import { collectionSourceLabel, fuelProductLabel, placeKindLabel } from "@/lib/transport-presentation";
import { RailTimetables } from "./rail-timetables";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field, FieldGroup, FieldLabel, FieldSet, FieldLegend } from "@/components/ui/field";
import { Checkbox } from "@/components/ui/checkbox";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Badge } from "@/components/ui/badge";
import { Empty, EmptyHeader, EmptyDescription } from "@/components/ui/empty";

export function PlaceIcon({ kind }: { kind: string }) {
  const Icon = ({ fuel_station: Fuel, rail_station: TrainFront, ferry_port: Anchor, airport: Plane, rest_area: Coffee, bus_terminal: Bus, highway_incident: TriangleAlert } as const)[kind as Place["kind"]] ?? MapPin;
  return <Icon size={18} aria-hidden="true" />;
}

export function ViewSwitch({ value, onChange }: { value: "map" | "list"; onChange: (value: "map" | "list") => void }) {
  return <ToggleGroup variant="outline" aria-label="보기 방식" value={[value]} onValueChange={(values) => { if (values[0] === "map" || values[0] === "list") onChange(values[0]); }}>
    <ToggleGroupItem value="map" aria-label="지도">지도</ToggleGroupItem>
    <ToggleGroupItem value="list" aria-label="목록">목록</ToggleGroupItem>
  </ToggleGroup>;
}

export function MultiSearch({ label, query, onQuery, options, selected, onSelect, max = 5, loading = false }: {
  label: string; query: string; onQuery: (value: string) => void;
  options: { id: string; name: string; description?: string }[];
  selected: { id: string; name: string }[]; onSelect: (id: string) => void; max?: number; loading?: boolean;
}) {
  const id = useId();
  return <section className="multi-search">
    <FieldGroup><Field><FieldLabel htmlFor={id}>{label}</FieldLabel><Input id={id} type="search" value={query} onChange={(event) => onQuery(event.target.value)} placeholder="이름·지역으로 검색" autoComplete="off" /></Field></FieldGroup>
    {selected.length ? <div className="flex min-w-0 flex-wrap gap-2" aria-label="선택한 장소">{selected.map((item) => <Button className="max-w-full" variant="secondary" type="button" key={item.id} onClick={() => onSelect(item.id)} aria-label={`${item.name} 선택 해제`} title={item.name}><span className="min-w-0 truncate">{item.name}</span><X data-icon="inline-end" aria-hidden="true" /></Button>)}</div> : null}
    <p className="quiet" role="status">{loading ? "검색 중…" : `${options.length}개 결과 · ${selected.length}/${max}곳 선택`}</p>
    <FieldSet><FieldLegend className="sr-only">{label} 검색 결과</FieldLegend><FieldGroup className="max-h-64 overflow-y-auto gap-2">{options.slice(0, 60).map((item) => {
      const checked = selected.some((value) => value.id === item.id);
      const disabled = max > 1 && selected.length >= max && !checked;
      return <Field orientation="horizontal" key={item.id} data-disabled={disabled} className="min-h-11">
        <Checkbox id={`${id}-${item.id}`} checked={checked} disabled={disabled} onCheckedChange={() => onSelect(item.id)} />
        <FieldLabel htmlFor={`${id}-${item.id}`} className="min-w-0 min-h-11 flex-1"><span className="flex min-w-0 flex-col gap-1"><strong>{item.name}</strong>{item.description ? <small>{item.description}</small> : null}</span></FieldLabel>
      </Field>;
    })}</FieldGroup></FieldSet>
    {!loading && !options.length ? <Empty><EmptyHeader><EmptyDescription>검색 결과가 없습니다. 다른 이름이나 지역을 입력해 주세요.</EmptyDescription></EmptyHeader></Empty> : null}
    {options.length > 60 ? <p className="quiet">상위 60곳을 표시합니다. 검색어를 입력해 범위를 좁혀 주세요.</p> : null}
  </section>;
}

export function PlaceDetails({ place, showRailTimetable = true, showHeading = true }: { place: Place; showRailTimetable?: boolean; showHeading?: boolean }) {
  return <div className="place-details">
    {showHeading ? <><div className="place-title"><PlaceIcon kind={place.kind} /><span>{placeKindLabel(place.kind)}</span></div><h2>{place.name}</h2></> : null}
    {place.brand_name ? <p>{place.brand_name}</p> : null}
    {place.line_names.length ? <div className="flex flex-wrap gap-2">{place.line_names.map((line) => <Badge variant="secondary" key={line}>{line}</Badge>)}</div> : null}
    {place.subtitle ? <p>{place.subtitle}</p> : null}
    {place.prices?.length ? <dl className="price-grid">{place.prices.map((price) => <div key={price.product_code}><dt>{fuelProductLabel(price.product_code)}</dt><dd>{money(price.price, "원/L")}</dd><small>{dateTime(price.provider_updated_at ?? price.observed_at)}</small></div>)}</dl> : place.kind === "fuel_station" ? <p className="quiet">등록된 유가가 없습니다.</p> : null}
    {place.address ? <p>{place.address}</p> : null}
    {place.phone ? <p>전화 {place.phone}</p> : null}
    {place.kind === "ferry_port" ? <p className="quiet">항구 코드 {place.provider_id ?? "미제공"} · 항구명만으로 서로 다른 항구를 합치지 않습니다.</p> : null}
    {place.facilities?.length ? <p>편의시설 · {place.facilities.join(" · ")}</p> : null}
    {place.kind === "rail_station" && showRailTimetable ? <RailTimetables placeIds={[place.id]} /> : null}
    {place.kind === "ferry_port" ? <p className="data-caveat">{hasCoordinates(place) ? place.location_source === "komsa_port_call" ? "한국해양교통안전공단 기항지 위치입니다. 승선 부두·탑승구는 운항사에 확인해 주세요." : "항만 안내 지점입니다. 실제 승선 장소는 여객터미널에 확인해 주세요." : "좌표 미등록 · 목록에서 운항 정보를 확인할 수 있습니다."}</p> : null}
    <p className="quiet">출처 {collectionSourceLabel(place.source)} · 기준정보 반영 {dateTime(place.updated_at)}</p>
  </div>;
}

export function FerryDepartures({ timetable, name, query = "" }: { timetable: FerryTimetable; name: string; query?: string }) {
  const rows = timetable.items.filter((item) => [item.arrival_port_name, item.departure_port_name, item.vessel_name].join(" ").includes(query.trim())).sort((a, b) => (a.departure_planned_time ?? "").localeCompare(b.departure_planned_time ?? ""));
  return <section className="departures" aria-label={`${name} 운항 정보`}>
    <header><h3>{name} · {timetable.service_date}</h3><p className="quiet">항구 코드 {timetable.port_id}{timetable.port_name ? ` · ${timetable.port_name}` : ""}</p><p className="quiet">저장본 확인 {dateTime(timetable.fetched_at)} · {rows.length}편</p></header>
    {rows.length ? rows.map((item, index) => <article className="departure-row" key={index}>
      <div className="departure-time"><strong>{serviceTime(item.departure_planned_time, timetable.service_date)}</strong><span>{item.departure_port_name ?? name}</span></div>
      <div className="departure-route"><span aria-hidden="true">→</span><strong>{item.arrival_port_name ?? "도착항 미제공"}</strong><small>도착 {serviceTime(item.arrival_planned_time, timetable.service_date)}</small></div>
      <div className="departure-meta"><strong>{item.vessel_name ?? "선박명 미제공"}</strong><span>{money(item.fare)}</span></div>
    </article>) : <p className="empty-state">{query ? "조건에 맞는 운항편이 없습니다." : "제공기관의 마지막 저장 응답에 등록된 운항편이 없습니다. 결항을 의미하지는 않습니다."}</p>}
    <p className="quiet">예정 시간·요금은 변경될 수 있습니다. 승선 전 운항사에 확인해 주세요.</p>
  </section>;
}
