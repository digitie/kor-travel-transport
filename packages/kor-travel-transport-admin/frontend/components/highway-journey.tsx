"use client";

import { VirtualTable } from "@kor-travel/ui/virtual-table";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { dateTime, transportGet, type Place } from "@/lib/journey";
import { highwayRouteLabel } from "@/lib/transport-presentation";
import { HIGHWAY_SPEED_COLORS, highwaySpeedColor, type HighwayRoadCatalog, type HighwayRoadTraffic } from "@/lib/highway-map";
import { PlaceDetails } from "./journey-controls";
import { MapFilterBar, MapFilterField } from "@kor-travel/ui/map-controls";
import { EmptyState } from "@/components/empty-state";
import { SectionCard } from "./section-card";
import { InfoButton } from "./info-button";
import { Alert, AlertDescription } from "./ui/alert";
import { Button } from "./ui/button";
const TransportMap = dynamic(() => import("./transport-map").then((module) => module.TransportMap), { ssr: false });
const HighwayTrafficLayer = dynamic(() => import("./highway-traffic-layer").then((module) => module.HighwayTrafficLayer), { ssr: false });
const inlineLink = "rounded-control text-sm font-medium text-brand underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";
const incidentRow = "flex w-full min-w-0 flex-col items-start gap-1 rounded-control border border-border bg-card px-3 py-2 text-left hover:bg-surface-subtle aria-pressed:border-brand aria-pressed:bg-brand-tint focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";
type Traffic = { identity_key: string; route_no: string | null; route_name: string | null; conzone_name: string | null; direction: string | null; speed: number | null; observed_at: string };
type Incident = { identity_key: string; source: string; route_no: string | null; route_name: string | null; point_name: string | null; message: string | null; incident_type: string | null; process_status: string | null; longitude: number | null; latitude: number | null; observed_at: string };
export function HighwayJourney() {
  const { mapTarget, places, selected, selectIncident, view, setView, catalog, roadId, direction, changeRoad, setDirection, setSelected, setSelectedIndex, setCameraIndex, setVisibleLinks, setReload, errors, lookup, queryKey, pending, data, visibleLinks, lineList, link, selectedIndex, selectionRevision, cameraIndex, selectLink, incidents, traffic } = useHighwayJourney();
  return <section className="journey-workbench highway-journey map-route">
    <div ref={mapTarget} className="journey-map-target map-route-primary"><TransportMap places={places} selectedPlace={selected} onSelectPlace={selectIncident} view={view} onViewChange={setView}
      filterSummary={`${catalog?.items.find((road) => road.road_id === roadId)?.name ?? "도로 선택"} · ${direction === "1" ? "기본 방향" : "반대 방향"}`}
      toolbar={<HighwayFilters roadId={roadId} changeRoad={changeRoad} catalog={catalog} direction={direction} setDirection={setDirection} setSelected={setSelected} setSelectedIndex={setSelectedIndex} setCameraIndex={setCameraIndex} setVisibleLinks={setVisibleLinks} setReload={setReload} />}
    feedback={<HighwayFeedback errors={errors} lookup={lookup} queryKey={queryKey} pending={pending} data={data} catalog={catalog} />}
      onCloseDetails={() => { setSelected(null); setSelectedIndex(null); }} mapFeatureCount={data ? visibleLinks : 0} listFeatureCount={data?.items.length ?? 0} listContent={lineList}
      detailKey={link ? `${queryKey}:${selectedIndex}` : undefined}
      focusRevision={selectionRevision}
      detailTitle={link?.section_name ?? selected?.name}
      details={link || selected ? <HighwayDetails link={link} data={data} direction={direction} selected={selected} /> : undefined}
      layers={<HighwayTrafficLayer data={data} selectedIndex={cameraIndex} selectionRevision={selectionRevision} onSelect={selectLink} onVisibleCount={setVisibleLinks} />} /></div>
    <div className="map-route-followup flex flex-col gap-6">
    {!pending && data && !data.items.length ? <EmptyState size="sm" title="선택 도로·방향의 소통 정보가 제공되지 않았습니다." /> : null}
    <div className="journey-data-grid grid gap-6 lg:grid-cols-2">
      {view === "map" ? <SectionCard title={`선택 도로 소통 ${data?.items.length ?? 0}구간`}>{lineList}</SectionCard> : null}
      <SectionCard title={`저장된 도로 돌발·통제 ${incidents.length}건`} actions={<InfoButton label="저장 돌발 범위">선택 ITS 노선과 무관한 최근 24시간의 저장 관측 최대 1,000행입니다. 상세의 처리 상태와 관측 시각을 확인하세요. 목록은 처음 30건을 표시합니다.</InfoButton>}>
        <div className="grid gap-2">{incidents.slice(0, 30).map((row, index) => <button type="button" className={incidentRow} key={row.identity_key} onClick={() => selectIncident(places[index])}><strong className="text-sm">{row.point_name ?? highwayRouteLabel(row.route_no, row.route_name)}</strong><span className="text-sm text-text-secondary">{row.message ?? row.incident_type ?? "상세 내용 미제공"}</span><small className="text-xs text-text-secondary">{row.process_status ?? "처리 상태 미제공"} · {dateTime(row.observed_at)}</small></button>)}</div>
      </SectionCard>
    </div>
    <details className="rounded-panel border border-border bg-card p-4"><summary className="cursor-pointer text-sm font-medium text-text-primary">별도 저장 소통 관측 {traffic.length}곳</summary><div className="mt-4 overflow-x-auto"><VirtualTable ariaLabel="조회 결과" containerClassName="operations-table" data={traffic.slice(0, 60)} getRowId={(row) => String(row.identity_key)} virtualized={false} columns={[{ id: 'column0', header: '구간', cell: ({ row: { original: row } }) => <>{row.conzone_name ?? highwayRouteLabel(row.route_no, row.route_name)}</> },
{ id: 'column1', header: '노선·방향', cell: ({ row: { original: row } }) => <>{highwayRouteLabel(row.route_no, row.route_name)} · {row.direction ?? "방향 미제공"}</> },
{ id: 'column2', header: '속도', cell: ({ row: { original: row } }) => <>{row.speed == null ? "미제공" : `${row.speed} km/h`}</> },
{ id: 'column3', header: '관측', cell: ({ row: { original: row } }) => <>{dateTime(row.observed_at)}</> }]} /></div>{traffic.length > 60 ? <p className="mt-2 text-xs text-text-secondary">최근 관측 {traffic.length}곳 중 60곳만 표시합니다.</p> : null}
      <p className="mt-2 text-xs text-text-secondary">최근 24시간 최대 1,000행 중 처음 60구간 · 지도 선형과 별도 출처</p>
    </details>
    </div>
  </section>;
}


// 조회·선택·요청 수명은 이 도메인 훅이, 아래 컴포넌트는 표현을 소유한다.
function useHighwayJourney() {
  const [traffic, setTraffic] = useState<Traffic[]>([]), [incidents, setIncidents] = useState<Incident[]>([]);
  const [catalog, setCatalog] = useState<HighwayRoadCatalog | null>(null), [roadId, setRoadId] = useState("");
  const [direction, setDirection] = useState("1"), [reload, setReload] = useState(0);
  const [lookup, setLookup] = useState<{ key: string; data?: HighwayRoadTraffic; error?: string }>({ key: "" });
  const [selected, setSelected] = useState<Place | null>(null), [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [cameraIndex, setCameraIndex] = useState<number | null>(null);
  const [visibleLinks, setVisibleLinks] = useState(0), [errors, setErrors] = useState<string[]>([]);
  const [view, setView] = useState<"map" | "list">("map");
  const [selectionRevision, setSelectionRevision] = useState(0);
  const mapTarget = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    // 재조회가 시작되면 이전 오류만 지운다.
    setErrors([]);
    const fail = (message: string) => { if (!controller.signal.aborted) setErrors((value) => [...value, message]); };
    transportGet<HighwayRoadCatalog>("transport/highways/roads", controller.signal).then((data) => {
      if (!controller.signal.aborted) { setCatalog(data); setRoadId((previous) => previous || data.items[0]?.road_id || ""); }
    }).catch((error: Error) => fail(error.message));
    transportGet<{ items: Traffic[] }>("transport/highways/traffic?days=1&limit=1000", controller.signal).then((data) => { if (!controller.signal.aborted) setTraffic(data.items.filter((row, index) => data.items.findIndex((other) => row.identity_key === other.identity_key) === index)); }).catch(() => fail("저장 소통 조회 실패"));
    transportGet<{ items: Incident[] }>("transport/highways/incidents?days=1&limit=1000", controller.signal).then((data) => { if (!controller.signal.aborted) setIncidents(data.items.filter((row, index) => data.items.findIndex((other) => row.identity_key === other.identity_key) === index)); }).catch(() => fail("저장 돌발 조회 실패"));
    return () => controller.abort();
  }, [reload]);
  const queryKey = `${roadId}:${direction}:${reload}`;
  useEffect(() => {
    if (!roadId) return;
    const controller = new AbortController();
    transportGet<HighwayRoadTraffic>(`transport/highways/road-traffic?${new URLSearchParams({ road_id: roadId, direction })}`, controller.signal)
      .then((data) => { if (!controller.signal.aborted) setLookup({ key: queryKey, data }); })
      .catch((error: Error) => { if (!controller.signal.aborted) setLookup({ key: queryKey, error: error.message }); });
    return () => controller.abort();
  }, [roadId, direction, queryKey]);
  const data = lookup.key === queryKey ? lookup.data ?? null : null;
  const pending = Boolean(roadId && lookup.key !== queryKey);
  const link = selectedIndex == null ? null : data?.items[selectedIndex];
  const selectLink = useCallback((index: number) => {
    setSelected(null); setSelectedIndex(index); setCameraIndex(index); setSelectionRevision((value) => value + 1); setView("map"); mapTarget.current?.scrollIntoView({ block: "start" });
  }, []);
  const selectIncident = (place: Place) => { setSelectedIndex(null); setCameraIndex(null); setSelected(place); mapTarget.current?.scrollIntoView({ block: "start" }); };
  const changeRoad = (value: string) => { setRoadId(value); setSelected(null); setSelectedIndex(null); setCameraIndex(null); setVisibleLinks(0); };
  const places: Place[] = incidents.map((row, index) => ({ id: index, kind: "highway_incident", source: row.source, name: row.point_name ?? row.incident_type ?? "도로 돌발", latitude: row.latitude, longitude: row.longitude, line_names: [highwayRouteLabel(row.route_no, row.route_name)], subtitle: [row.incident_type, row.process_status].filter(Boolean).join(" · "), address: row.message, updated_at: row.observed_at, prices: [], facilities: [] }));
  const lineList = <div className="grid gap-2" aria-label="선택 도로 소통 구간">{data?.items.map((row, index) => <button type="button" className={incidentRow} key={row.link_id} onClick={() => selectLink(index)} aria-pressed={selectedIndex === index}>
    <strong className="text-sm">{row.section_name}</strong><span className="flex flex-wrap items-center gap-1.5 text-xs text-text-secondary"><i className="inline-block size-2.5 rounded-full" style={{ backgroundColor: highwaySpeedColor(row.speed_kmh) }} />{row.speed_kmh == null ? "속도 미제공" : `${row.speed_kmh} km/h`} · {row.length_m == null ? "길이 미제공" : `${(row.length_m / 1000).toFixed(1)} km`}{row.path.length < 2 ? " · 경로 미제공" : ""}</span>
  </button>)}</div>;

  return { mapTarget, places, selected, selectIncident, view, setView, catalog, roadId, direction, changeRoad, setDirection, setSelected, setSelectedIndex, setCameraIndex, setVisibleLinks, setReload, errors, lookup, queryKey, pending, data, visibleLinks, lineList, link, selectedIndex, selectionRevision, cameraIndex, selectLink, incidents, traffic };
}


function HighwayFilters({ roadId, changeRoad, catalog, direction, setDirection, setSelected, setSelectedIndex, setCameraIndex, setVisibleLinks, setReload }: Pick<ReturnType<typeof useHighwayJourney>, "roadId" | "changeRoad" | "catalog" | "direction" | "setDirection" | "setSelected" | "setSelectedIndex" | "setCameraIndex" | "setVisibleLinks" | "setReload">) {
  return (<MapFilterBar><MapFilterField label="고속도로" htmlFor="its-highway"><select id="its-highway" value={roadId} onChange={(event) => changeRoad(event.target.value)}><option value="">도로 선택</option>{catalog?.items.map((road) => <option key={road.road_id} value={road.road_id}>{road.name} ({road.road_number})</option>)}</select></MapFilterField>
      <MapFilterField label="방향" htmlFor="its-direction"><select id="its-direction" value={direction} onChange={(event) => { setDirection(event.target.value); setSelected(null); setSelectedIndex(null); setCameraIndex(null); setVisibleLinks(0); }}><option value="1">기본 방향</option><option value="2">반대 방향</option></select></MapFilterField>
      <Button type="button" variant="outline" onClick={() => { setReload((value) => value + 1); setSelectedIndex(null); setCameraIndex(null); setSelected(null); }}>새로고침</Button><Link className={inlineLink} href="/highways/statistics">운전 지표·저속 구간 통계</Link>
    </MapFilterBar>);
}


function HighwayDetails({ link, data, direction, selected }: Pick<ReturnType<typeof useHighwayJourney>, "link" | "data" | "direction" | "selected">) {
  return (link ? <section className="place-details grid gap-2 text-sm"><strong>{link.speed_kmh == null ? "속도 미제공" : `${link.speed_kmh} km/h`}</strong><p>{data?.road_name} · {direction === "1" ? "기본 방향" : "반대 방향"}</p><p>{link.length_m == null ? "길이 미제공" : `${(link.length_m / 1000).toFixed(2)} km`} · ITS 조회 {dateTime(data?.fetched_at)}</p><a className={inlineLink} href={data?.source_url} target="_blank" rel="noreferrer">ITS 원문 지도</a></section> : selected ? <PlaceDetails place={selected} showHeading={false} /> : undefined);
}


function HighwayFeedback({ errors, lookup, queryKey, pending, data, catalog }: Pick<ReturnType<typeof useHighwayJourney>, "errors" | "lookup" | "queryKey" | "pending" | "data" | "catalog">) {
  return (<>{errors.map((error) => <Alert variant="destructive" key={error}><AlertDescription>{error}</AlertDescription></Alert>)}
    {lookup.key === queryKey && lookup.error ? <Alert variant="destructive"><AlertDescription>{lookup.error}</AlertDescription></Alert> : null}
    <div className="highway-map-summary flex flex-wrap items-center gap-2 text-sm" role="status"><span>{pending ? "ITS 도로 소통 조회 중…" : data ? `${data.road_name} · ITS 조회 ${dateTime(data.fetched_at)}` : "도로를 선택해 소통을 확인하세요."}</span>
      <InfoButton label="도로 지도 출처와 범위">선은 선택 도로의 ITS 공개 화면에서 제공한 경로와 속도입니다. 조회 시각은 원본 관측 시각과 다릅니다. 전국 완전성은 보장하지 않으며 경로 미제공 링크는 목록에서 확인할 수 있습니다. 돌발 마커와 아래 저장 통계는 별도 수집 출처이며 ITS 노선 코드와 결합하지 않습니다. 새로고침도 5분 캐시를 사용합니다.</InfoButton>
      <InfoButton label="소통 속도 범례">{Object.entries(HIGHWAY_SPEED_COLORS).map(([key, color]) => <p className="highway-speed-key flex items-center gap-1.5 text-xs text-text-secondary" key={key}><i className="inline-block size-2.5 rounded-full" style={{ backgroundColor: color }} />{({ slow: "40 이하", moderate: "40 초과~80 미만", fast: "80 이상", unknown: "미제공" })[key]}{key === "unknown" ? "" : " km/h"}</p>)}</InfoButton>
    </div>
    {data?.stale || catalog?.stale ? <Alert variant="destructive"><AlertDescription>ITS 갱신 지연 · 이전 조회 자료입니다.</AlertDescription></Alert> : null}</>);
}
