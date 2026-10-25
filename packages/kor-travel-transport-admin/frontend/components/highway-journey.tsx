"use client";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { dateTime, transportGet, type Place } from "@/lib/journey";
import { highwayRouteLabel } from "@/lib/transport-presentation";
import { HIGHWAY_SPEED_COLORS, highwaySpeedColor, type HighwayRoadCatalog, type HighwayRoadTraffic } from "@/lib/highway-map";
import { PlaceDetails } from "./journey-controls";
import { MapFilterBar, MapFilterField } from "@kor-travel/ui/map-controls";
import { InfoButton } from "./info-button";
const TransportMap = dynamic(() => import("./transport-map").then((module) => module.TransportMap), { ssr: false });
const HighwayTrafficLayer = dynamic(() => import("./highway-traffic-layer").then((module) => module.HighwayTrafficLayer), { ssr: false });
type Traffic = { identity_key: string; route_no: string | null; route_name: string | null; conzone_name: string | null; direction: string | null; speed: number | null; observed_at: string };
type Incident = { identity_key: string; source: string; route_no: string | null; route_name: string | null; point_name: string | null; message: string | null; incident_type: string | null; process_status: string | null; longitude: number | null; latitude: number | null; observed_at: string };
export function HighwayJourney() {
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
    // eslint-disable-next-line react-hooks/set-state-in-effect
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
  const lineList = <div className="highway-link-list" aria-label="선택 도로 소통 구간">{data?.items.map((row, index) => <button type="button" className="incident-row" key={`${row.link_id}:${index}`} onClick={() => selectLink(index)} aria-pressed={selectedIndex === index}>
    <strong>{row.section_name}</strong><span><i className="highway-speed-dot" style={{ backgroundColor: highwaySpeedColor(row.speed_kmh) }} />{row.speed_kmh == null ? "속도 미제공" : `${row.speed_kmh} km/h`} · {row.length_m == null ? "길이 미제공" : `${(row.length_m / 1000).toFixed(1)} km`}{row.path.length < 2 ? " · 경로 미제공" : ""}</span>
  </button>)}</div>;
  return <section className="journey-workbench highway-journey map-route">
    <div ref={mapTarget} className="journey-map-target map-route-primary"><TransportMap places={places} selectedPlace={selected} onSelectPlace={selectIncident} view={view} onViewChange={setView}
      filterSummary={`${catalog?.items.find((road) => road.road_id === roadId)?.name ?? "도로 선택"} · ${direction === "1" ? "기본 방향" : "반대 방향"}`}
      toolbar={<MapFilterBar><MapFilterField label="고속도로" htmlFor="its-highway"><select id="its-highway" value={roadId} onChange={(event) => changeRoad(event.target.value)}><option value="">도로 선택</option>{catalog?.items.map((road) => <option key={road.road_id} value={road.road_id}>{road.name} ({road.road_number})</option>)}</select></MapFilterField>
      <MapFilterField label="방향" htmlFor="its-direction"><select id="its-direction" value={direction} onChange={(event) => { setDirection(event.target.value); setSelected(null); setSelectedIndex(null); setCameraIndex(null); setVisibleLinks(0); }}><option value="1">기본 방향</option><option value="2">반대 방향</option></select></MapFilterField>
      <button className="secondary" type="button" onClick={() => { setReload((value) => value + 1); setSelectedIndex(null); setCameraIndex(null); setSelected(null); }}>새로고침</button><Link className="inline-link" href="/highways/statistics">운전 지표·저속 구간 통계</Link>
    </MapFilterBar>}
    feedback={<>{errors.map((error) => <p role="alert" className="error" key={error}>{error}</p>)}
    {lookup.key === queryKey && lookup.error ? <p role="alert" className="error">{lookup.error}</p> : null}
    <div className="highway-map-summary" role="status"><span>{pending ? "ITS 도로 소통 조회 중…" : data ? `${data.road_name} · ITS 조회 ${dateTime(data.fetched_at)}` : "도로를 선택해 소통을 확인하세요."}</span>
      <InfoButton label="도로 지도 출처와 범위">선은 선택 도로의 ITS 공개 화면에서 제공한 경로와 속도입니다. 조회 시각은 원본 관측 시각과 다릅니다. 전국 완전성은 보장하지 않으며 경로 미제공 링크는 목록에서 확인할 수 있습니다. 돌발 마커와 아래 저장 통계는 별도 수집 출처이며 ITS 노선 코드와 결합하지 않습니다. 새로고침도 5분 캐시를 사용합니다.</InfoButton>
      <InfoButton label="소통 속도 범례">{Object.entries(HIGHWAY_SPEED_COLORS).map(([key, color]) => <p className="highway-speed-key" key={key}><i className="highway-speed-dot" style={{ backgroundColor: color }} />{({ slow: "40 이하", moderate: "40 초과~80 미만", fast: "80 이상", unknown: "미제공" })[key]}{key === "unknown" ? "" : " km/h"}</p>)}</InfoButton>
    </div>
    {data?.stale || catalog?.stale ? <p role="alert" className="error">ITS 갱신 지연 · 이전 조회 자료입니다.</p> : null}</>}
      onCloseDetails={() => { setSelected(null); setSelectedIndex(null); }} mapFeatureCount={data ? visibleLinks : 0} listFeatureCount={data?.items.length ?? 0} listContent={lineList}
      detailKey={link ? `${queryKey}:${selectedIndex}` : undefined}
      focusRevision={selectionRevision}
      detailTitle={link?.section_name ?? selected?.name}
      details={link ? <section className="place-details"><strong>{link.speed_kmh == null ? "속도 미제공" : `${link.speed_kmh} km/h`}</strong><p>{data?.road_name} · {direction === "1" ? "기본 방향" : "반대 방향"}</p><p>{link.length_m == null ? "길이 미제공" : `${(link.length_m / 1000).toFixed(2)} km`} · ITS 조회 {dateTime(data?.fetched_at)}</p><a href={data?.source_url} target="_blank" rel="noreferrer">ITS 원문 지도</a></section> : selected ? <PlaceDetails place={selected} showHeading={false} /> : undefined}
      layers={<HighwayTrafficLayer data={data} selectedIndex={cameraIndex} selectionRevision={selectionRevision} onSelect={selectLink} onVisibleCount={setVisibleLinks} />} /></div>
    <div className="map-route-followup">
    {!pending && data && !data.items.length ? <p className="empty-state">선택 도로·방향의 소통 정보가 제공되지 않았습니다.</p> : null}
    <div className="journey-data-grid">
      {view === "map" ? <section><h2>선택 도로 소통 {data?.items.length ?? 0}구간</h2>{lineList}</section> : null}
      <section><div className="section-title-row"><h2>저장된 도로 돌발·통제 {incidents.length}건</h2><InfoButton label="저장 돌발 범위">선택 ITS 노선과 무관한 최근 24시간의 저장 관측 최대 1,000행입니다. 상세의 처리 상태와 관측 시각을 확인하세요. 목록은 처음 30건을 표시합니다.</InfoButton></div>{incidents.slice(0, 30).map((row, index) => <button type="button" className="incident-row" key={row.identity_key} onClick={() => selectIncident(places[index])}><strong>{row.point_name ?? highwayRouteLabel(row.route_no, row.route_name)}</strong><span>{row.message ?? row.incident_type ?? "상세 내용 미제공"}</span><small>{row.process_status ?? "처리 상태 미제공"} · {dateTime(row.observed_at)}</small></button>)}</section>
    </div>
    <details><summary>별도 저장 소통 관측 {traffic.length}곳</summary><div className="overflow-x-auto"><table className="operations-table"><thead><tr><th>구간</th><th>노선·방향</th><th>속도</th><th>관측</th></tr></thead><tbody>{traffic.slice(0, 60).map((row) => <tr key={row.identity_key}><th>{row.conzone_name ?? highwayRouteLabel(row.route_no, row.route_name)}</th><td>{highwayRouteLabel(row.route_no, row.route_name)} · {row.direction ?? "방향 미제공"}</td><td>{row.speed == null ? "미제공" : `${row.speed} km/h`}</td><td>{dateTime(row.observed_at)}</td></tr>)}</tbody></table></div><p className="quiet">최근 24시간 최대 1,000행 중 처음 60구간 · 지도 선형과 별도 출처</p></details>
    </div>
  </section>;
}
