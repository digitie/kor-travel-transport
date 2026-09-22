"use client";

import * as maplibregl from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";

import { vworldStyle } from "@/lib/vworld-style";

import "maplibre-gl/dist/maplibre-gl.css";

maplibregl.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

type Place = { id: number; kind: "fuel_station" | "rail_station" | "ferry_port"; name: string; provider_id?: string | null; longitude: number; latitude: number; subtitle?: string | null; brand_name?: string | null; latest_price?: number | null; price_product_code?: string | null; line_names: string[]; address?: string | null; updated_at: string; location_source?: string | null; location_point_count?: number | null };

const label: Record<Place["kind"], string> = { fuel_station: "주유소", rail_station: "역", ferry_port: "항구" };
const symbol: Record<Place["kind"], string> = { fuel_station: "⛽", rail_station: "🚇", ferry_port: "⚓" };
const SOURCE_ID = "transport-place-clusters";

export function TransportMap() {
  const node = useRef<HTMLDivElement | null>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [items, setItems] = useState<Place[]>([]);
  const [selected, setSelected] = useState<Place | null>(null);
  const [message, setMessage] = useState("저장된 교통정보를 읽는 중입니다…");
  const [operations, setOperations] = useState<string>("");
  const places = useMemo(() => ({
    type: "FeatureCollection" as const,
    features: items.filter((place) => Number.isFinite(place.longitude) && Number.isFinite(place.latitude)).map((place) => ({
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [place.longitude, place.latitude] },
      properties: { marker_id: `${place.kind}:${place.id}` },
    })),
  }), [items]);
  const placesById = useRef(new Map<string, Place>());
  placesById.current = new Map(items.map((place) => [`${place.kind}:${place.id}`, place]));

  useEffect(() => {
    let cancelled = false;
    fetch("/api/transport/transport/features/places", { cache: "no-store" })
      .then(async (response) => response.ok ? response.json() : Promise.reject(new Error("장소 정보를 불러오지 못했습니다.")))
      .then((payload) => { if (!cancelled) { setItems(payload.items); setMessage(payload.items.length ? "" : "지도에 표시할 좌표가 아직 수집되지 않았습니다."); } })
      .catch((error: unknown) => { if (!cancelled) setMessage(error instanceof Error ? error.message : "장소 정보를 불러오지 못했습니다."); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!node.current || map.current) return;
    const instance = new maplibregl.Map({ container: node.current, style: vworldStyle(process.env.NEXT_PUBLIC_VWORLD_API_KEY), center: [127.8, 36.2], zoom: 6, minZoom: 5, maxZoom: 19, attributionControl: { compact: true } });
    instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.current = instance;
    return () => { instance.remove(); map.current = null; };
  }, []);

  useEffect(() => {
    const instance = map.current;
    if (!instance || !items.length) return;
    const clusterLayerId = `${SOURCE_ID}-clusters`;
    const pointLayerId = `${SOURCE_ID}-points`;
    const markerPool = new Map<string, maplibregl.Marker>();
    let visible = new Set<string>();
    let frame = 0;
    const makePoint = (place: Place) => {
      const button = document.createElement("button");
      button.className = `transport-map-marker ${place.kind}`;
      button.type = "button";
      button.textContent = symbol[place.kind];
      button.title = `${place.name} 상세 보기`;
      button.setAttribute("aria-label", `${label[place.kind]} ${place.name} 상세 보기`);
      button.onclick = () => { setSelected(place); setOperations(""); instance.easeTo({ center: [place.longitude, place.latitude], zoom: Math.max(instance.getZoom(), 11), duration: 300 }); };
      return button;
    };
    const ensureSource = () => {
      if (!instance.isStyleLoaded()) return false;
      if (!instance.getSource(SOURCE_ID)) instance.addSource(SOURCE_ID, { type: "geojson", data: places, cluster: true, clusterRadius: 60, clusterMaxZoom: 14 });
      if (!instance.getLayer(clusterLayerId)) instance.addLayer({ id: clusterLayerId, type: "circle", source: SOURCE_ID, filter: ["has", "point_count"], paint: { "circle-radius": 1, "circle-opacity": 0 } });
      if (!instance.getLayer(pointLayerId)) instance.addLayer({ id: pointLayerId, type: "circle", source: SOURCE_ID, filter: ["!", ["has", "point_count"]], paint: { "circle-radius": 1, "circle-opacity": 0 } });
      return true;
    };
    const remove = (id: string) => { markerPool.get(id)?.remove(); markerPool.delete(id); };
    const update = () => {
      frame = 0;
      if (!ensureSource()) return;
      const next = new Set<string>();
      for (const feature of instance.querySourceFeatures(SOURCE_ID)) {
        if (feature.geometry.type !== "Point") continue;
        const coordinates = feature.geometry.coordinates as [number, number];
        const properties = feature.properties ?? {};
        if (properties.point_count !== undefined) {
          const clusterId = Number(properties.cluster_id);
          const id = `cluster:${clusterId}`;
          if (!Number.isFinite(clusterId) || next.has(id)) continue;
          next.add(id);
          if (!markerPool.has(id)) {
            const button = document.createElement("button");
            button.className = "transport-map-cluster";
            button.type = "button";
            button.textContent = String(properties.point_count_abbreviated ?? properties.point_count);
            button.setAttribute("aria-label", `교통 장소 ${properties.point_count}개 묶음. 클릭하면 확대합니다.`);
            button.onclick = () => { const source = instance.getSource(SOURCE_ID) as maplibregl.GeoJSONSource | undefined; void source?.getClusterExpansionZoom(clusterId).then((zoom) => instance.easeTo({ center: coordinates, zoom, duration: 300 })); };
            markerPool.set(id, new maplibregl.Marker({ element: button }).setLngLat(coordinates));
          }
        } else {
          const markerId = String(properties.marker_id ?? "");
          const place = placesById.current.get(markerId);
          const id = `place:${markerId}`;
          if (!place || next.has(id)) continue;
          next.add(id);
          if (!markerPool.has(id)) markerPool.set(id, new maplibregl.Marker({ element: makePoint(place) }).setLngLat(coordinates));
        }
      }
      for (const id of visible) if (!next.has(id)) remove(id);
      for (const id of next) if (!visible.has(id)) markerPool.get(id)?.addTo(instance);
      visible = next;
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(update); };
    const source = instance.getSource(SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
    source?.setData(places);
    instance.on("moveend", schedule); instance.on("zoomend", schedule); instance.on("sourcedata", schedule); instance.on("idle", schedule); instance.on("styledata", schedule);
    schedule();
    const bounds = new maplibregl.LngLatBounds(); items.forEach((place) => bounds.extend([place.longitude, place.latitude]));
    if (!bounds.isEmpty()) instance.fitBounds(bounds, { padding: 54, maxZoom: 9, duration: 0 });
    return () => { if (frame) cancelAnimationFrame(frame); instance.off("moveend", schedule); instance.off("zoomend", schedule); instance.off("sourcedata", schedule); instance.off("idle", schedule); instance.off("styledata", schedule); for (const marker of markerPool.values()) marker.remove(); try { if (instance.getLayer(clusterLayerId)) instance.removeLayer(clusterLayerId); if (instance.getLayer(pointLayerId)) instance.removeLayer(pointLayerId); if (instance.getSource(SOURCE_ID)) instance.removeSource(SOURCE_ID); } catch {} };
  }, [items, places]);

  return <section className="transport-map-layout" aria-label="교통 장소 지도">
    <div className="transport-map-canvas" ref={node} role="application" aria-label="VWorld 교통 지도" />
    <aside className="transport-map-detail" aria-live="polite">
      {selected ? <><p className="eyebrow">{label[selected.kind]}</p><h2>{selected.name}</h2>{selected.brand_name ? <p>{selected.brand_name}</p> : null}{selected.latest_price !== null && selected.latest_price !== undefined ? <strong>{selected.price_product_code ?? "유가"} {selected.latest_price.toLocaleString()}원/L</strong> : null}{selected.line_names.length ? <p>노선: {selected.line_names.join(", ")}</p> : null}{selected.address ? <p>{selected.address}</p> : null}{selected.kind === "ferry_port" ? <><p className="quiet">항만가이드라인 위치 {selected.location_point_count ?? 0}점 중 표시 지점입니다.</p><button className="button" type="button" onClick={() => { if (!selected.provider_id) return; setOperations("실시간 운항 정보를 읽는 중입니다…"); fetch(`/api/transport/transport/ports/${encodeURIComponent(selected.provider_id)}/timetable`).then(async (response) => response.ok ? response.json() : Promise.reject(new Error("실시간 운항 정보를 불러오지 못했습니다."))).then((payload) => setOperations(payload.items.length ? payload.items.map((item: { departure_port_name?: string; arrival_port_name?: string; departure_planned_time?: string }) => `${item.departure_planned_time ?? "—"} ${item.departure_port_name ?? selected.name} → ${item.arrival_port_name ?? "—"}`).join("\n") : "오늘 등록된 운항 정보가 없습니다.")).catch((error: unknown) => setOperations(error instanceof Error ? error.message : "실시간 운항 정보를 불러오지 못했습니다.")); }}>오늘 운항 보기</button>{operations ? <p className="quiet">{operations}</p> : null}</> : null}</> : <><h2>교통 장소</h2><p>{message || `주유소·역·항구 ${items.length.toLocaleString()}곳을 표시합니다. 마커를 선택하면 상세 정보를 봅니다.`}</p></>}
    </aside>
  </section>;
}
