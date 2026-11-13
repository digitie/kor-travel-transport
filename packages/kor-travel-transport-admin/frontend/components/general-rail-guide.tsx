"use client";

import dynamic from "next/dynamic";
import { useEffect, useId, useState } from "react";
import { FilterActions, FilterBar, FilterField } from "@/components/filter-bar";
import { hasCoordinates, transportGet, type Place } from "@/lib/journey";
import { useNearbyPosition } from "@/lib/journey-hooks";
import { nearestPlaces } from "@/lib/nearby";
import { HelpTip } from "./help-tip";
import { Alert, AlertDescription } from "./ui/alert";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { NativeSelect } from "./ui/native-select";
import { NativeSelectOption } from "./ui/native-select-option";

const TransportMap = dynamic(() => import("./transport-map").then((m) => m.TransportMap), { ssr: false });
const inlineLink = "rounded-control text-sm font-medium text-brand underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";
const resultButton = "flex min-w-0 flex-col items-start gap-0.5 rounded-control border border-border bg-card px-3 py-2 text-left hover:bg-surface-subtle aria-pressed:border-brand aria-pressed:bg-brand-tint focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";
type Guide = { fetched_at: string; stale: boolean; kind: "ktx" | "main"; category_code: string; total: number;
  categories: { code: string; name: string }[];
  items: { provider_id: string; station_code: string | null; station_name: string; address: string | null; phone: string | null; longitude: number | null; latitude: number | null }[] };

export function GeneralRailGuide() {
  const id = useId();
  const [kind, setKind] = useState<"ktx" | "main">("ktx");
  const [category, setCategory] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Place | null>(null);
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
  const results = position ? nearby.map((row) => row.place) : query || category ? filtered.slice(0, 30) : [];
  function choose(place: Place) { setSelected(place); setFocusRevision((value) => value + 1); }
  return <section className="journey-workbench flex flex-col gap-6" aria-label="철도 역 지도">
    <nav aria-label="철도 화면 바로가기" className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <a className={inlineLink} href="#general-rail-map">역 지도</a>
      <a className={inlineLink} href="#general-rail-timetable">시간표 조회</a>
      <HelpTip label="철도 역 안내">코레일 공개 역 안내입니다. KTX는 노선별, 일반철도는 권역별로 역을 찾습니다. 지도는 역 위치를 표시하며 선로 경로나 정차 순서를 뜻하지 않습니다. 시간표는 아래 TAGO 역 목록에서 출발·도착역을 선택해 조회합니다.</HelpTip>
    </nav>
    <FilterBar>
      <FilterField label="역 안내 구분" htmlFor={`${id}-kind`}>
        <NativeSelect id={`${id}-kind`} value={kind} onChange={(event) => { setKind(event.target.value as "ktx" | "main"); setCategory(""); setQuery(""); setSelected(null); }}>
          <NativeSelectOption value="ktx">KTX 노선</NativeSelectOption>
          <NativeSelectOption value="main">일반철도 권역</NativeSelectOption>
        </NativeSelect>
      </FilterField>
      <FilterField label={kind === "ktx" ? "노선" : "권역"} htmlFor={`${id}-category`}>
        <NativeSelect id={`${id}-category`} value={category} onChange={(event) => { setCategory(event.target.value); setSelected(null); }}>
          <NativeSelectOption value="">{kind === "ktx" ? "노선 선택" : "권역 선택"}</NativeSelectOption>
          {categories.map((row) => <NativeSelectOption key={row.code} value={row.code}>{row.name}</NativeSelectOption>)}
        </NativeSelect>
      </FilterField>
      <FilterField label="역 이름" htmlFor={`${id}-query`}>
        <Input id={`${id}-query`} type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="선택 범위에서 검색" />
      </FilterField>
      <FilterActions>
        <Button type="button" variant="outline" disabled={locating || !category} onClick={locate}>{locating ? "위치 확인 중…" : "내 근처 역"}</Button>
      </FilterActions>
    </FilterBar>
    {current?.error ? <Alert variant="destructive"><AlertDescription>{current.error} <Button type="button" variant="link" size="sm" onClick={() => setReload((value) => value + 1)}>다시 조회</Button></AlertDescription></Alert> : !current?.data ? <p role="status" className="text-sm text-text-secondary">공개 역 안내 조회 중…</p> : null}
    {current?.data?.stale ? <p role="status" className="text-sm text-text-secondary">갱신에 실패한 이전 역 안내입니다.</p> : null}
    {positionError ? <Alert variant="destructive"><AlertDescription>{positionError}</AlertDescription></Alert> : null}
    {results.length ? <div className="station-results grid gap-2 sm:grid-cols-2" aria-label="철도 역 검색 결과">{results.map((place) => <button type="button" className={resultButton} key={place.provider_id} aria-pressed={selected?.provider_id === place.provider_id} onClick={() => choose(place)}><strong className="text-sm">{place.name}</strong><small className="text-xs text-text-secondary">{place.address}</small></button>)}</div> : category && current?.data ? <p className="text-sm text-text-secondary">조건에 맞는 역이 없습니다.</p> : null}
    <div id="general-rail-map" className="scroll-mt-6" tabIndex={-1}>
      <TransportMap places={filtered} selectedPlace={selected} onSelectPlace={choose} focusRevision={focusRevision} onCloseDetails={() => setSelected(null)} details={selected ? <div className="grid gap-2 text-sm">
        <h2 className="text-base font-semibold text-text-primary">{selected.name}</h2>
        <p className="text-text-secondary">{selected.line_names.join(" · ")}</p>
        {selected.address ? <button className={`${inlineLink} text-left`} type="button" disabled={!hasCoordinates(selected)} onClick={() => { choose(selected); document.getElementById("general-rail-map")?.scrollIntoView({ block: "start" }); }}>{selected.address}{hasCoordinates(selected) ? " · 지도에서 보기" : ""}</button> : null}
        <p>전화 {selected.phone ? <a className={inlineLink} href={`tel:${selected.phone.replace(/[^+\d]/g, "")}`}>{selected.phone}</a> : "미제공"}</p>
        <p className="text-xs text-text-secondary">코레일 공개 역 안내 · 편의시설은 역 안내에서 확인</p>
        <div className="flex flex-wrap gap-3">
          <a className={inlineLink} target="_blank" rel="noreferrer" href={`https://www.korail.com/ticket/train/stationGuide/station/view?stationSeq=${encodeURIComponent(selected.provider_id ?? "")}`}>공식 역 안내 ↗</a>
          <a className={inlineLink} href="#general-rail-timetable">예정 시간표 조회</a>
        </div>
      </div> : undefined} />
    </div>
  </section>;
}
