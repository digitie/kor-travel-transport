"use client";

import Link from "next/link";
import { InfoButton } from "./info-button";
import { Anchor, Bus, Fuel, Plane, TrainFront, Coffee, MapPin, TriangleAlert, X } from "lucide-react";
import { useId } from "react";
import { dateTime, hasCoordinates, hasFuelPrice, money, serviceTime, type FerryTimetable, type Place } from "@/lib/journey";
import { collectionSourceLabel, fuelProductLabel, placeKindLabel } from "@/lib/transport-presentation";
import { RailTimetables } from "./rail-timetables";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field, FieldGroup, FieldLabel, FieldSet, FieldLegend } from "@/components/ui/field";
import { Checkbox } from "@/components/ui/checkbox";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Badge } from "@/components/ui/badge";
import { Empty, EmptyHeader, EmptyDescription } from "@/components/ui/empty";
import { FuelBrandIcon } from "./fuel-brand-icon";
import { FuelStationPriceHistory } from "./fuel-station-history";

export function PlaceIcon({ kind, brandCode, brandName }: { kind: string; brandCode?: string | null; brandName?: string | null }) {
  if (kind === "fuel_station") return <FuelBrandIcon code={brandCode} name={brandName} />;
  const Icon = ({ fuel_station: Fuel, rail_station: TrainFront, ferry_port: Anchor, airport: Plane, rest_area: Coffee, bus_terminal: Bus, highway_incident: TriangleAlert } as const)[kind as Place["kind"]] ?? MapPin;
  return <Icon size={18} aria-hidden="true" />;
}

function isOldFuelObservation(observedAt: string) {
  const instant = Date.parse(observedAt);
  return Number.isFinite(instant) && Date.now() - instant > 168 * 3600_000;
}

export function ViewSwitch({ value, onChange }: { value: "map" | "list"; onChange: (value: "map" | "list") => void }) {
  return <ToggleGroup variant="outline" aria-label="보기 방식" value={[value]} onValueChange={(values) => { if (values[0] === "map" || values[0] === "list") onChange(values[0]); }}>
    <ToggleGroupItem value="map" aria-label="지도">지도</ToggleGroupItem>
    <ToggleGroupItem value="list" aria-label="목록">목록</ToggleGroupItem>
  </ToggleGroup>;
}

export function MultiSearch({ label, query, onQuery, options, selected, onSelect, onInspect, max = 5, loading = false, scrollable = true }: {
  label: string; query: string; onQuery: (value: string) => void;
  options: { id: string; name: string; description?: string }[];
  selected: { id: string; name: string }[]; onSelect: (id: string) => void; onInspect?: (id: string) => void; max?: number; loading?: boolean; scrollable?: boolean;
}) {
  const id = useId();
  return <section className="multi-search">
    <FieldGroup><Field><FieldLabel htmlFor={id}>{label}</FieldLabel><Input id={id} type="search" value={query} onChange={(event) => onQuery(event.target.value)} placeholder="이름·지역으로 검색" autoComplete="off" /></Field></FieldGroup>
    {selected.length ? <div className="flex min-w-0 flex-wrap gap-2" aria-label="선택한 장소">{selected.map((item) => <Button className="max-w-full" variant="secondary" type="button" key={item.id} onClick={() => onSelect(item.id)} aria-label={`${item.name} 선택 해제`} title={item.name}><span className="min-w-0 truncate">{item.name}</span><X data-icon="inline-end" aria-hidden="true" /></Button>)}</div> : null}
    <p className="quiet" role="status">{loading ? "검색 중…" : `${options.length}개 결과 · ${selected.length}/${max}곳 선택`}</p>
    <FieldSet><FieldLegend className="sr-only">{label} 검색 결과</FieldLegend><FieldGroup className={scrollable ? "max-h-64 overflow-y-auto gap-2" : "gap-2"}>{options.slice(0, 60).map((item) => {
      const checked = selected.some((value) => value.id === item.id);
      const disabled = max > 1 && selected.length >= max && !checked;
      return <Field orientation="horizontal" key={item.id} data-disabled={disabled} className="min-h-11">
        <Checkbox id={`${id}-${item.id}`} checked={checked} disabled={disabled} onCheckedChange={() => onSelect(item.id)} />
        <FieldLabel htmlFor={`${id}-${item.id}`} className="min-w-0 min-h-11 flex-1"><span className="flex min-w-0 flex-col gap-1"><strong>{item.name}</strong>{item.description ? <small>{item.description}</small> : null}</span></FieldLabel>
        {onInspect ? <Button type="button" variant="outline" size="sm" className="shrink-0" aria-label={`${item.name} 상세 보기`} onClick={() => onInspect(item.id)}>상세</Button> : null}
      </Field>;
    })}</FieldGroup></FieldSet>
    {!loading && !options.length ? <Empty><EmptyHeader><EmptyDescription>검색 결과가 없습니다. 다른 이름이나 지역을 입력해 주세요.</EmptyDescription></EmptyHeader></Empty> : null}
    {options.length > 60 ? <p className="quiet">상위 60곳을 표시합니다. 검색어를 입력해 범위를 좁혀 주세요.</p> : null}
  </section>;
}

export function PlaceDetails({ place, showRailTimetable = true, showHeading = true, onShowMap }: { place: Place; showRailTimetable?: boolean; showHeading?: boolean; onShowMap?: () => void }) {
  const prices = place.kind === "fuel_station" ? place.prices?.filter(hasFuelPrice) : place.prices;
  const address = place.address ? hasCoordinates(place) ? onShowMap
    ? <button type="button" className="inline-link" onClick={onShowMap}>{place.address} · 지도에서 보기</button>
    : <Link className="inline-link" href={`/${place.kind === "fuel_station" ? "fuel" : "map"}?longitude=${place.longitude}&latitude=${place.latitude}`}>{place.address} · 지도에서 보기</Link>
    : place.address : null;
  return <div className="place-details">
    {showHeading ? <><div className="place-title"><PlaceIcon kind={place.kind} brandCode={place.brand_code} brandName={place.brand_name} /><span>{placeKindLabel(place.kind)}</span></div><h2>{place.name}</h2></> : null}
    {place.brand_name && (showHeading || place.kind !== "fuel_station") ? <p>{place.brand_name}</p> : null}
    {place.line_names.length ? <div className="flex flex-wrap gap-2">{place.line_names.map((line) => <Badge variant="secondary" key={line}>{line}</Badge>)}</div> : null}
    {place.subtitle && place.kind !== "fuel_station" ? <p>{place.subtitle}</p> : null}
    {place.kind === "fuel_station" ? <FuelStationPriceHistory key={`${place.source}:${place.id}`} place={place} /> : null}
    {prices?.length ? <><span className="quiet fuel-current-price-label">최근 저장 가격</span><dl className="price-grid">{prices.map((price) => <div key={price.product_code}><dt>{fuelProductLabel(price.product_code)}</dt><dd>{money(price.price, "원/L")}</dd><small><time dateTime={price.observed_at}>관측 {dateTime(price.observed_at)}</time>{place.kind === "fuel_station" && isOldFuelObservation(price.observed_at) ? <span className="fuel-price-old">7일 이전 관측</span> : null}</small></div>)}</dl></> : place.kind === "fuel_station" ? <p className="quiet">등록된 유효 유가가 없습니다.</p> : null}
    {place.kind === "fuel_station" ? <div className="place-metadata-actions">
      {address ? <InfoButton label="주소" icon={<MapPin size={15} aria-hidden="true" />}>{address}</InfoButton> : null}
      <InfoButton label="데이터 출처">{collectionSourceLabel(place.source)}<p>기준정보 반영 {dateTime(place.updated_at)}</p>{prices?.filter((price) => price.provider_updated_at).map((price) => <p key={price.product_code}>{fuelProductLabel(price.product_code)} 제공기관 공시 {dateTime(price.provider_updated_at)}</p>)}</InfoButton>
    </div> : address ? <p>{address}</p> : null}
    {place.phone ? <p>전화 <a className="inline-link" href={`tel:${place.phone.replace(/[^+\d]/g, "")}`}>{place.phone}</a></p> : null}
    {place.kind === "ferry_port" ? <p className="quiet">항구 코드 {place.provider_id ?? "미제공"}</p> : null}
    {place.kind === "bus_terminal" ? <p className="quiet">터미널 코드 {place.provider_id ?? "미제공"}</p> : null}
    {place.facilities?.length ? <p>편의시설 · {place.facilities.join(" · ")}</p> : null}
    {place.kind === "rail_station" && showRailTimetable ? <RailTimetables placeIds={[place.id]} /> : null}
    {place.kind === "ferry_port" ? <InfoButton label="장소 위치의 근거">{hasCoordinates(place) ? place.location_source === "admin_manual" ? "관리자가 근거를 대조해 보정한 항구 위치입니다. 실제 승선 부두는 운항사에 확인해 주세요." : place.location_source === "komsa_port_call" ? "한국해양교통안전공단 기항지 위치입니다. 승선 부두·탑승구는 운항사에 확인해 주세요." : "지도 검색에서 확인한 항만 시설입니다. 실제 승선 장소는 운항사에 확인해 주세요." : "좌표 미등록 · 목록에서 운항 정보를 확인할 수 있습니다."}</InfoButton> : null}
    {place.kind === "bus_terminal" ? <InfoButton label="장소 위치의 근거">{hasCoordinates(place) ? place.location_source === "admin_manual" ? "관리자가 근거를 대조해 보정한 터미널 위치입니다. 실제 승차 홈은 운송사에 확인해 주세요." : place.location_source === "vworld_place" ? "VWorld 시설 검색으로 확인한 터미널 위치입니다. 실제 승차 홈은 운송사에 확인해 주세요." : place.location_source === "kakao_place" ? "카카오맵 장소 검색으로 확인한 터미널 위치입니다. 실제 승차 홈은 운송사에 확인해 주세요." : "지도에서 확인한 터미널 위치입니다. 실제 승차 홈은 운송사에 확인해 주세요." : "좌표 미등록 · 터미널 이름과 코드로 검색할 수 있습니다."}</InfoButton> : null}
    {place.kind !== "fuel_station" ? <p className="quiet">출처 {collectionSourceLabel(place.source)} · 기준정보 반영 {dateTime(place.updated_at)}</p> : null}
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
