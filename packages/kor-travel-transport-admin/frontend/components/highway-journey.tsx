"use client";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { dateTime, transportGet, type Place } from "@/lib/journey";
import { highwayRouteLabel } from "@/lib/transport-presentation";
import { PlaceDetails } from "./journey-controls";
import { MapFilterBar, MapFilterField } from "@kor-travel/ui/map-controls";
import Link from "next/link";
import { InfoButton } from "./info-button";
const TransportMap = dynamic(() => import("./transport-map").then((module) => module.TransportMap), { ssr: false });
type Traffic = { identity_key: string; route_no: string | null; route_name: string | null; conzone_name: string | null; direction: string | null; speed: number | null; observed_at: string };
type Incident = { identity_key: string; source: string; route_no: string | null; route_name: string | null; point_name: string | null; message: string | null; incident_type: string | null; process_status: string | null; longitude: number | null; latitude: number | null; observed_at: string };
export function HighwayJourney() {
  const [traffic, setTraffic] = useState<Traffic[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [routes, setRoutes] = useState<string[]>([]);
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
  const visibleTraffic = traffic.filter((row) => !routes.length || routes.includes(row.route_no ?? ""));
  const visibleIncidents = incidents.filter((row) => !routes.length || routes.includes(row.route_no ?? ""));
  const places: Place[] = visibleIncidents.map((row) => ({ id: incidents.indexOf(row), kind: "highway_incident", source: row.source, name: row.point_name ?? row.incident_type ?? "도로 돌발", latitude: row.latitude, longitude: row.longitude, line_names: [highwayRouteLabel(row.route_no, row.route_name)], subtitle: [row.incident_type, row.process_status].filter(Boolean).join(" · "), address: row.message, updated_at: row.observed_at, prices: [], facilities: [] }));
  return <section className="journey-workbench highway-journey">
    <MapFilterBar><MapFilterField label="고속도로" htmlFor="highway-route"><select id="highway-route" value={routes[0] ?? ""} onChange={(event) => { setSelected(null); setRoutes(event.target.value ? [event.target.value] : []); }}><option value="">조회된 모든 노선</option>{[...names].sort((a, b) => a[1].localeCompare(b[1], "ko")).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></MapFilterField><button className="secondary" type="button" onClick={() => setReload((value) => value + 1)}>새로고침</button><Link className="inline-link" href="/highways/statistics">운전 지표·저속 구간 통계</Link></MapFilterBar>
    {errors.map((error) => <p role="alert" className="error" key={error}>{error} · 이전 조회 자료를 유지합니다.</p>)}
    <TransportMap places={places} selectedPlace={selected} onSelectPlace={setSelected} onCloseDetails={() => setSelected(null)} details={selected ? <PlaceDetails place={selected} /> : undefined} />
    <div className="journey-data-grid">
      <section><h2>도로 돌발·통제 {visibleIncidents.length}건</h2>{visibleIncidents.slice(0, 30).map((row, index) => <button type="button" className="incident-row" key={row.identity_key} onClick={() => setSelected(places[index])}><strong>{row.point_name ?? highwayRouteLabel(row.route_no, row.route_name)}</strong><span>{row.message ?? row.incident_type ?? "상세 내용 미제공"}</span><small>{row.process_status ?? "처리 상태 미제공"} · {dateTime(row.observed_at)}</small></button>)}{!visibleIncidents.length ? <p className="empty-state">선택 노선의 저장된 돌발 정보가 없습니다.</p> : null}</section>
      <section><h2>구간별 소통 {visibleTraffic.length}곳</h2><div className="overflow-x-auto"><table className="operations-table"><thead><tr><th>구간</th><th>노선·방향</th><th>속도</th><th>관측</th></tr></thead><tbody>{visibleTraffic.slice(0, 60).map((row) => <tr key={row.identity_key}><th>{row.conzone_name ?? highwayRouteLabel(row.route_no, row.route_name)}</th><td>{highwayRouteLabel(row.route_no, row.route_name)} · {row.direction ?? "방향 미제공"}</td><td>{row.speed == null ? "미제공" : `${row.speed} km/h`}</td><td>{dateTime(row.observed_at)}</td></tr>)}</tbody></table></div>{visibleTraffic.length > 60 ? <p className="quiet">상위 60구간 표시 · 노선 선택으로 범위를 좁힐 수 있습니다.</p> : null}</section>
    </div>
    <div className="section-title-row"><span className="quiet">저장 관측 기준</span><InfoButton label="도로 관측 범위">최근 24시간 저장 관측 최대 1,000행 기준입니다. 돌발은 상세의 처리 상태와 관측 시각을 확인하세요.</InfoButton></div>
  </section>;
}
