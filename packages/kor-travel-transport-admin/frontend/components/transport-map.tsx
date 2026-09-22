"use client";

import * as maplibregl from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";

import { vworldStyle } from "@/lib/vworld-style";

import "maplibre-gl/dist/maplibre-gl.css";

maplibregl.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

type Place = { id: number; kind: "fuel_station" | "rail_station" | "ferry_port"; name: string; provider_id?: string | null; longitude: number; latitude: number; subtitle?: string | null; brand_name?: string | null; latest_price?: number | null; price_product_code?: string | null; line_names: string[]; address?: string | null; updated_at: string; location_source?: string | null; location_point_count?: number | null };

const label: Record<Place["kind"], string> = { fuel_station: "주유소", rail_station: "역", ferry_port: "항구" };
const SOURCE_ID = "transport-place-clusters";
const CLUSTER_LAYER_ID = `${SOURCE_ID}-clusters`;
const CLUSTER_COUNT_LAYER_ID = `${SOURCE_ID}-cluster-count`;
const POINT_LAYER_ID = `${SOURCE_ID}-points`;

function timetableLine(item: { departure_port_name?: string; arrival_port_name?: string; departure_planned_time?: string; arrival_planned_time?: string; vessel_name?: string; fare?: string }, fallbackPortName: string) {
  const route = `${item.departure_planned_time ?? "—"} ${item.departure_port_name ?? fallbackPortName} → ${item.arrival_planned_time ?? "—"} ${item.arrival_port_name ?? "—"}`;
  return [route, item.vessel_name, item.fare ? `${item.fare}원` : undefined].filter(Boolean).join(" · ");
}

export function TransportMap() {
  const node = useRef<HTMLDivElement | null>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const timetableController = useRef<AbortController | null>(null);
  const timetableRequest = useRef(0);
  const [items, setItems] = useState<Place[]>([]);
  const [selected, setSelected] = useState<Place | null>(null);
  const [message, setMessage] = useState("저장된 교통정보를 읽는 중입니다…");
  const [operations, setOperations] = useState<string>("");
  const places = useMemo(() => ({
    type: "FeatureCollection" as const,
    features: items.filter((place) => Number.isFinite(place.longitude) && Number.isFinite(place.latitude)).map((place) => ({
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [place.longitude, place.latitude] },
      properties: { marker_id: `${place.kind}:${place.id}`, kind: place.kind },
    })),
  }), [items]);
  const placesById = useRef(new Map<string, Place>());
  placesById.current = new Map(items.map((place) => [`${place.kind}:${place.id}`, place]));

  const selectPlace = (place: Place) => {
    timetableController.current?.abort();
    timetableRequest.current += 1;
    setSelected(place);
    setOperations("");
  };

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
    return () => { timetableController.current?.abort(); instance.remove(); map.current = null; };
  }, []);

  useEffect(() => {
    const instance = map.current;
    if (!instance || !items.length) return;
    const ensureSource = () => {
      if (!instance.isStyleLoaded()) return false;
      if (!instance.getSource(SOURCE_ID)) instance.addSource(SOURCE_ID, { type: "geojson", data: places, cluster: true, clusterRadius: 60, clusterMaxZoom: 14 });
      if (!instance.getLayer(CLUSTER_LAYER_ID)) instance.addLayer({ id: CLUSTER_LAYER_ID, type: "circle", source: SOURCE_ID, filter: ["has", "point_count"], paint: { "circle-color": "#075985", "circle-radius": ["step", ["get", "point_count"], 16, 20, 20, 100, 25], "circle-stroke-color": "#ffffff", "circle-stroke-width": 2 } });
      if (!instance.getLayer(CLUSTER_COUNT_LAYER_ID)) instance.addLayer({ id: CLUSTER_COUNT_LAYER_ID, type: "symbol", source: SOURCE_ID, filter: ["has", "point_count"], layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 12 }, paint: { "text-color": "#ffffff" } });
      if (!instance.getLayer(POINT_LAYER_ID)) instance.addLayer({ id: POINT_LAYER_ID, type: "circle", source: SOURCE_ID, filter: ["!", ["has", "point_count"]], paint: { "circle-color": ["match", ["get", "kind"], "fuel_station", "#dc2626", "rail_station", "#7c3aed", "ferry_port", "#0891b2", "#475569"], "circle-radius": 7, "circle-stroke-color": "#ffffff", "circle-stroke-width": 2 } });
      return true;
    };
    const expandCluster = (event: maplibregl.MapMouseEvent & { features?: maplibregl.MapGeoJSONFeature[] }) => {
      const feature = event.features?.[0];
      const clusterId = Number(feature?.properties?.cluster_id);
      if (!feature || !Number.isFinite(clusterId) || feature.geometry.type !== "Point") return;
      const [longitude, latitude] = feature.geometry.coordinates;
      if (typeof longitude !== "number" || typeof latitude !== "number") return;
      const source = instance.getSource(SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
      void source?.getClusterExpansionZoom(clusterId).then((zoom) => instance.easeTo({ center: [longitude, latitude], zoom, duration: 300 }));
    };
    const selectPoint = (event: maplibregl.MapMouseEvent & { features?: maplibregl.MapGeoJSONFeature[] }) => {
      const markerId = String(event.features?.[0]?.properties?.marker_id ?? "");
      const place = placesById.current.get(markerId);
      if (!place) return;
      selectPlace(place);
      instance.easeTo({ center: [place.longitude, place.latitude], zoom: Math.max(instance.getZoom(), 11), duration: 300 });
    };
    const setPointer = () => { instance.getCanvas().style.cursor = "pointer"; };
    const clearPointer = () => { instance.getCanvas().style.cursor = ""; };
    const add = () => {
      if (!ensureSource()) return;
      (instance.getSource(SOURCE_ID) as maplibregl.GeoJSONSource).setData(places);
      instance.on("click", CLUSTER_LAYER_ID, expandCluster);
      instance.on("click", POINT_LAYER_ID, selectPoint);
      instance.on("mouseenter", CLUSTER_LAYER_ID, setPointer);
      instance.on("mouseenter", POINT_LAYER_ID, setPointer);
      instance.on("mouseleave", CLUSTER_LAYER_ID, clearPointer);
      instance.on("mouseleave", POINT_LAYER_ID, clearPointer);
      const bounds = new maplibregl.LngLatBounds(); items.forEach((place) => bounds.extend([place.longitude, place.latitude]));
      if (!bounds.isEmpty()) instance.fitBounds(bounds, { padding: 54, maxZoom: 9, duration: 0 });
    };
    if (instance.isStyleLoaded()) add(); else instance.once("load", add);
    return () => {
      instance.off("load", add); instance.off("click", CLUSTER_LAYER_ID, expandCluster); instance.off("click", POINT_LAYER_ID, selectPoint); instance.off("mouseenter", CLUSTER_LAYER_ID, setPointer); instance.off("mouseenter", POINT_LAYER_ID, setPointer); instance.off("mouseleave", CLUSTER_LAYER_ID, clearPointer); instance.off("mouseleave", POINT_LAYER_ID, clearPointer);
      try { if (instance.getLayer(CLUSTER_COUNT_LAYER_ID)) instance.removeLayer(CLUSTER_COUNT_LAYER_ID); if (instance.getLayer(CLUSTER_LAYER_ID)) instance.removeLayer(CLUSTER_LAYER_ID); if (instance.getLayer(POINT_LAYER_ID)) instance.removeLayer(POINT_LAYER_ID); if (instance.getSource(SOURCE_ID)) instance.removeSource(SOURCE_ID); } catch { /* map teardown owns residual layers */ }
    };
  }, [items, places]);

  async function loadTimetable() {
    const providerId = selected?.provider_id;
    if (!selected || !providerId) return;
    timetableController.current?.abort();
    const controller = new AbortController();
    timetableController.current = controller;
    const requestId = ++timetableRequest.current;
    const port = selected;
    setOperations("실시간 운항 정보를 읽는 중입니다…");
    try {
      const response = await fetch(`/api/transport/transport/ports/${encodeURIComponent(providerId)}/timetable`, { signal: controller.signal });
      if (!response.ok) {
        const body = await response.json().catch(() => null) as { detail?: string } | null;
        const retryAfter = response.headers.get("retry-after");
        throw new Error(response.status === 429 && retryAfter ? `${body?.detail ?? "실시간 운항 정보 요청이 제한되었습니다."} 약 ${retryAfter}초 뒤 다시 시도해 주세요.` : body?.detail ?? "실시간 운항 정보를 불러오지 못했습니다.");
      }
      const payload = await response.json() as { items: Array<{ departure_port_name?: string; arrival_port_name?: string; departure_planned_time?: string; arrival_planned_time?: string; vessel_name?: string; fare?: string }> };
      if (timetableRequest.current === requestId) setOperations(payload.items.length ? payload.items.map((item) => timetableLine(item, port.name)).join("\n") : "오늘 등록된 운항 정보가 없습니다.");
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      if (timetableRequest.current === requestId) setOperations(error instanceof Error ? error.message : "실시간 운항 정보를 불러오지 못했습니다.");
    }
  }

  return <section className="transport-map-layout" aria-label="교통 장소 지도">
    <div className="transport-map-canvas" ref={node} role="application" aria-label="VWorld 교통 지도. 확대하면 장소 묶음을 세부 위치로 펼칩니다." />
    <aside className="transport-map-detail" aria-live="polite">
      {selected ? <><p className="eyebrow">{label[selected.kind]}</p><h2>{selected.name}</h2>{selected.brand_name ? <p>{selected.brand_name}</p> : null}{selected.latest_price !== null && selected.latest_price !== undefined ? <strong>{selected.price_product_code ?? "유가"} {selected.latest_price.toLocaleString()}원/L</strong> : null}{selected.line_names.length ? <p>노선: {selected.line_names.join(", ")}</p> : null}{selected.address ? <p>{selected.address}</p> : null}{selected.kind === "ferry_port" ? <><p className="quiet">항만가이드라인 위치 {selected.location_point_count ?? 0}점 중 표시 지점입니다.</p><button className="button" type="button" onClick={loadTimetable}>오늘 운항 보기</button>{operations ? <p className="quiet timetable-result">{operations}</p> : null}</> : null}</> : <><h2>교통 장소</h2><p>{message || `주유소·역·항구 ${items.length.toLocaleString()}곳을 표시합니다. 지도에서 점 또는 묶음을 선택하면 상세 정보를 봅니다.`}</p></>}
    </aside>
  </section>;
}
