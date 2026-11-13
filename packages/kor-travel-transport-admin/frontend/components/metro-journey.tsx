"use client";
import dynamic from "next/dynamic";
import { useEffect, useId, useRef, useState } from "react";
import { FilterActions, FilterBar, FilterField } from "@/components/filter-bar";
import { dateTime, hasCoordinates, transportGet, type Place } from "@/lib/journey";
import { useNearbyPosition } from "@/lib/journey-hooks";
import { nearestPlaces } from "@/lib/nearby";
import { HelpTip } from "./help-tip";
import { Alert, AlertDescription } from "./ui/alert";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { NativeSelect } from "./ui/native-select";
import { NativeSelectOption } from "./ui/native-select-option";
import { RailTimetables } from "./rail-timetables";

const TransportMap = dynamic(() => import("./transport-map").then((m) => m.TransportMap), { ssr: false });
const inlineLink = "rounded-control text-sm font-medium text-brand underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";
const resultButton = "flex min-w-0 flex-col items-start gap-0.5 rounded-control border border-border bg-card px-3 py-2 text-left hover:bg-surface-subtle aria-pressed:border-brand aria-pressed:bg-brand-tint focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

export function MetroJourney() {
  const id = useId();
  const search = useRef<HTMLInputElement>(null);
  const [items, setItems] = useState<Place[] | null>(null);
  const [error, setError] = useState(false);
  const [query, setQuery] = useState("");
  const [line, setLine] = useState("");
  const [selected, setSelected] = useState<Place | null>(null);
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
  const results = position && !line && !query.trim() ? nearby.map((row) => row.place) : line || query.trim() ? filtered.slice(0, 30) : [];
  const distances = new Map(nearby.map((row) => [row.place.id, row.distance]));
  function choose(place: Place) { setSelected(place); setFocusRevision((v) => v + 1); }
  function close() { setSelected(null); search.current?.focus(); }
  return <section className="journey-workbench flex flex-col gap-6">
    <nav aria-label="도시철도 화면 바로가기" className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <a className={inlineLink} href="#metro-map">지도 보기</a>
      <a className={inlineLink} href="#station-timetable">시간표 보기</a>
      <HelpTip label="역 찾기">노선을 선택하거나 역 이름을 검색하세요. 내 근처 역은 좌표가 등록된 역을 직선 거리 순으로 표시합니다.</HelpTip>
    </nav>
    <FilterBar>
      <FilterField label="노선" htmlFor={`${id}-line`}>
        <NativeSelect id={`${id}-line`} value={line} onChange={(event) => { setLine(event.target.value); setSelected(null); }}>
          <NativeSelectOption value="">노선 선택</NativeSelectOption>
          {[...routes].sort((a, b) => a[1].localeCompare(b[1], "ko")).map(([key, name]) => <NativeSelectOption key={key} value={key}>{name}</NativeSelectOption>)}
        </NativeSelect>
      </FilterField>
      <FilterField label="역 검색" htmlFor={`${id}-query`}>
        <Input ref={search} id={`${id}-query`} type="search" placeholder="역 이름·코드" value={query} onChange={(event) => { setQuery(event.target.value); setSelected(null); }} />
      </FilterField>
      <FilterActions>
        <Button type="button" variant="outline" disabled={locating} onClick={locate}>{locating ? "위치 확인 중…" : "내 근처 역"}</Button>
        <Button type="button" variant="ghost" onClick={() => { setItems(null); setReload((v) => v + 1); }}>새로고침</Button>
      </FilterActions>
    </FilterBar>
    {positionError ? <Alert variant="destructive"><AlertDescription>{positionError}</AlertDescription></Alert> : null}
    {error ? <Alert variant="destructive"><AlertDescription>역 정보를 불러오지 못했습니다.</AlertDescription></Alert> : !items ? <p role="status" className="text-sm text-text-secondary">노선과 역을 불러오는 중입니다…</p> : null}
    {results.length ? <div className="station-results grid gap-2 sm:grid-cols-2" aria-label="역 검색 결과">{results.map((place) => <button type="button" className={resultButton} key={place.id} aria-pressed={selected?.id === place.id} onClick={() => choose(place)}><strong className="text-sm">{place.name}</strong><small className="text-xs text-text-secondary">{place.line_names.join(" · ")}{distances.has(place.id) ? ` · 직선 ${distances.get(place.id)!.toFixed(1)}km` : ""} · {place.subtitle}</small></button>)}</div> : items && (line || query || position) ? <p className="text-sm text-text-secondary">{line || query ? "조건에 맞는 역이 없습니다." : position ? "좌표가 등록된 가까운 역이 없습니다." : ""}</p> : null}
    {position ? <p className="text-sm text-text-secondary">현재 위치 오차 약 {Math.round(position.accuracy)}m · 거리는 직선 거리입니다.</p> : null}
    <div id="metro-map" className="scroll-mt-6" tabIndex={-1}>
      <TransportMap places={line || query ? filtered : items ?? []} selectedPlace={selected} onSelectPlace={choose} focusRevision={focusRevision} onCloseDetails={close} details={selected ? <div className="grid gap-2 text-sm">
        <h2 className="text-base font-semibold text-text-primary">{selected.name} <small className="text-sm font-normal text-text-secondary">{selected.subtitle}</small></h2>
        <p>{selected.line_names.join(" · ")}</p>
        {selected.address ? <button type="button" className={`${inlineLink} text-left`} disabled={!hasCoordinates(selected)} onClick={() => { choose(selected); document.getElementById("metro-map")?.scrollIntoView({ block: "start" }); }}>{selected.address}{hasCoordinates(selected) ? " · 지도에서 보기" : ""}</button> : <p className="text-text-secondary">주소 미제공</p>}
        <p>전화 {selected.phone ? <a className={inlineLink} href={`tel:${selected.phone.replace(/[^+\d]/g, "")}`}>{selected.phone}</a> : "미제공"}</p>
        <p>편의시설 {selected.facilities.length ? selected.facilities.join(" · ") : "등록 정보 없음"}</p>
        <p className="text-xs text-text-secondary">기준정보 {dateTime(selected.updated_at)}</p>
        <a className={inlineLink} href="#station-timetable">이후 시간표 보기</a>
      </div> : undefined} />
    </div>
    <div id="station-timetable">{selected ? <RailTimetables placeIds={[selected.id]} /> : null}</div>
  </section>;
}
