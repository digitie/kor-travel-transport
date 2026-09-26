"use client";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { dateTime, transportGet, type Place } from "@/lib/journey";
import { highwayRouteLabel } from "@/lib/transport-presentation";
import { MultiSearch, PlaceDetails } from "./journey-controls";
const TransportMap = dynamic(() => import("./transport-map").then((module) => module.TransportMap), { ssr: false });
type Traffic = { identity_key: string; route_no: string | null; route_name: string | null; conzone_name: string | null; direction: string | null; speed: number | null; observed_at: string };
type Incident = { identity_key: string; source: string; route_no: string | null; route_name: string | null; point_name: string | null; message: string | null; incident_type: string | null; process_status: string | null; longitude: number | null; latitude: number | null; observed_at: string };
export function HighwayJourney() {
  const [traffic, setTraffic] = useState<Traffic[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [routes, setRoutes] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Place | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    // 외부 조회를 재시작할 때 이전 오류를 지운다.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setErrors([]);
    const fail = (message: string) => { if (!controller.signal.aborted) setErrors((value) => [...value, message]); };
    transportGet<{ items: Traffic[] }>("transport/highways/traffic?days=1&limit=1000", controller.signal).then((data) => { if (!controller.signal.aborted) setTraffic(data.items.filter((row, index) => data.items.findIndex((other) => row.identity_key === other.identity_key) === index)); }).catch(() => fail("소통 조회 실패"));
    transportGet<{ items: Incident[] }>("transport/highways/incidents?days=1&limit=1000", controller.signal).then((data) => { if (!controller.signal.aborted) setIncidents(data.items.filter((row, index) => data.items.findIndex((other) => row.identity_key === other.identity_key) === index)); }).catch(() => fail("돌발 조회 실패"));
    return () => controller.abort();
  }, [reload]);
  const names = new Map([...traffic, ...incidents].filter((row) => row.route_no).map((row) => [row.route_no!, highwayRouteLabel(row.route_no, row.route_name)]));
  const options = [...names].filter(([, name]) => name.includes(query)).map(([id, name]) => ({ id, name }));
  const visibleTraffic = traffic.filter((row) => !routes.length || routes.includes(row.route_no ?? ""));
  const visibleIncidents = incidents.filter((row) => !routes.length || routes.includes(row.route_no ?? ""));
  const places: Place[] = visibleIncidents.map((row) => ({ id: incidents.indexOf(row), kind: "highway_incident", source: row.source, name: row.point_name ?? row.incident_type ?? "도로 돌발", latitude: row.latitude, longitude: row.longitude, line_names: [highwayRouteLabel(row.route_no, row.route_name)], subtitle: [row.incident_type, row.process_status].filter(Boolean).join(" · "), address: row.message, updated_at: row.observed_at, prices: [], facilities: [] }));
  return <section className="journey-workbench"><div className="journey-toolbar"><p className="quiet">최근 24시간 저장 관측 중 최대 1,000행의 최신 구간/돌발을 표시합니다. 전국 전체 상황을 의미하지 않습니다.</p><button className="secondary" type="button" onClick={() => setReload((value) => value + 1)}>새로고침</button></div>{errors.map((error) => <p role="alert" className="error" key={error}>{error} · 이전 조회 자료를 유지합니다.</p>)}<div className="journey-layout">
    <div className="journey-search"><MultiSearch label="고속도로 검색" query={query} onQuery={setQuery} options={options} selected={routes.map((id) => ({ id, name: names.get(id) ?? id }))} onSelect={(id) => { setSelected(null); setRoutes((current) => current.includes(id) ? current.filter((value) => value !== id) : current.length < 5 ? [...current, id] : current); }} /></div>
    <div className="journey-inspector">{selected ? <PlaceDetails place={selected} /> : null}<section><h2>도로 돌발·통제 {visibleIncidents.length}건</h2>{visibleIncidents.slice(0, 30).map((row) => <article className="departure-row" key={row.identity_key}><div><strong>{row.point_name ?? highwayRouteLabel(row.route_no, row.route_name)}</strong><p>{row.incident_type ?? "유형 미제공"}</p></div><p>{row.message ?? "상세 내용 미제공"}</p><small>{row.process_status ?? "처리 상태 미제공"} · {dateTime(row.observed_at)}</small></article>)}{!visibleIncidents.length ? <p className="empty-state">선택 노선의 저장된 돌발 정보가 없습니다.</p> : null}</section><section><h2>구간별 소통 {visibleTraffic.length}곳</h2>{visibleTraffic.slice(0, 60).map((row) => <article className="departure-row" key={row.identity_key}><div><strong>{row.conzone_name ?? highwayRouteLabel(row.route_no, row.route_name)}</strong><p>{highwayRouteLabel(row.route_no, row.route_name)} · {row.direction ?? "방향 미제공"}</p></div><strong>{row.speed == null ? "속도 미제공" : `${row.speed} km/h`}</strong><small>{dateTime(row.observed_at)}</small></article>)}{visibleTraffic.length > 60 ? <p>상위 60구간을 표시합니다. 노선을 선택해 범위를 좁혀 주세요.</p> : null}</section></div>
    <div className="journey-map"><TransportMap places={places} selectedPlace={selected} onSelectPlace={setSelected} /><p className="quiet">좌표가 있는 돌발 정보만 지도에 표시합니다. 구간 속도는 목록에서 확인해 주세요.</p></div>
  </div></section>;
}
