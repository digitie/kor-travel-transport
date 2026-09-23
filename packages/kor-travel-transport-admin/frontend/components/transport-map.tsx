"use client";

import { ClusterLayer, Marker, Popup, VWorldMapView } from "vworld-map-web";
import { useEffect, useMemo, useRef, useState } from "react";

import { fuelProductLabel, placeKindLabel } from "@/lib/transport-presentation";

type PlaceKind = "airport" | "fuel_station" | "rail_station" | "ferry_port" | "rest_area";
type Place = { id: number; kind: PlaceKind; name: string; provider_id?: string | null; longitude: number; latitude: number; subtitle?: string | null; brand_name?: string | null; latest_price?: number | null; price_product_code?: string | null; line_names: string[]; address?: string | null; updated_at: string; location_source?: string | null; location_point_count?: number | null; parking_lot_count?: number | null; parking_available_spaces?: number | null; parking_total_spaces?: number | null; parking_observed_at?: string | null };
type MapPoint = { id: string; lngLat: [number, number]; place: Place };
type PlaceResponse = { items: Place[]; total: number; truncated: boolean };
type MapBounds = { getWest: () => number; getSouth: () => number; getEast: () => number; getNorth: () => number };
const MAP_KINDS: readonly PlaceKind[] = ["airport", "fuel_station", "rail_station", "ferry_port", "rest_area"];
const MAP_KIND_LIMITS = {
  overview: 400,
  regional: 750,
  detail: 1_000,
} as const;
const PLACE_CACHE_TTL_MS = 60_000;
const PLACE_CACHE_MAX_ENTRIES = 32;
const MARKER_FUEL_LABELS: Record<string, string> = {
  B027: "휘발유",
  B034: "고급",
  D047: "경유",
  C004: "등유",
  K015: "LPG",
};

function visiblePlaceLimit(zoom: number) {
  if (zoom < 8) return MAP_KIND_LIMITS.overview;
  if (zoom < 10) return MAP_KIND_LIMITS.regional;
  return MAP_KIND_LIMITS.detail;
}

function timetableLine(item: { departure_port_name?: string; arrival_port_name?: string; departure_planned_time?: string; arrival_planned_time?: string; vessel_name?: string; fare?: string }, fallbackPortName: string) {
  const route = `${item.departure_planned_time ?? "—"} ${item.departure_port_name ?? fallbackPortName} → ${item.arrival_planned_time ?? "—"} ${item.arrival_port_name ?? "—"}`;
  return [route, item.vessel_name, item.fare ? `${item.fare}원` : undefined].filter(Boolean).join(" · ");
}

function PlaceMarkerIcon({ kind }: { kind: PlaceKind }) {
  if (kind === "airport") return <svg aria-hidden="true" className="map-marker-icon" viewBox="0 0 24 24"><path d="m3 16 7-3 3-8 2 1-1 8 6 3-1 2-7-2-4 3-2-1 3-4-6-3Z" /></svg>;
  if (kind === "fuel_station") return <svg aria-hidden="true" className="map-marker-icon" viewBox="0 0 24 24"><path d="M5 21V4a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v17M5 12h8M8 5h3M16 8h1a2 2 0 0 1 2 2v11h-4v-7h2" /></svg>;
  if (kind === "rail_station") return <svg aria-hidden="true" className="map-marker-icon" viewBox="0 0 24 24"><rect height="15" rx="2" width="12" x="6" y="3" /><path d="M8 18l-2 3m10-3 2 3M9 8h.01M15 8h.01M8 14h8" /></svg>;
  if (kind === "ferry_port") return <svg aria-hidden="true" className="map-marker-icon" viewBox="0 0 24 24"><path d="M3 17h18l-2-7H5l-2 7Zm3-7V6h12v4M7 21l2-2 3 2 3-2 2 2" /></svg>;
  return <svg aria-hidden="true" className="map-marker-icon" viewBox="0 0 24 24"><path d="M4 21V8l4-4h8l4 4v13M4 12h16M9 8h.01M15 8h.01M8 16h8" /></svg>;
}

function markerFuelLabel(productCode: string | null | undefined) {
  return MARKER_FUEL_LABELS[productCode ?? ""] ?? fuelProductLabel(productCode);
}

function airportParkingLabel(place: Place) {
  if (place.parking_available_spaces === null || place.parking_available_spaces === undefined || place.parking_total_spaces === null || place.parking_total_spaces === undefined) return null;
  return `주차 ${place.parking_available_spaces.toLocaleString("ko-KR")} / ${place.parking_total_spaces.toLocaleString("ko-KR")}면`;
}

function MapMarker({ point, onSelect, selected }: { point: MapPoint; onSelect: (place: Place) => void; selected: boolean }) {
  const { place } = point;
  const price = place.latest_price === null || place.latest_price === undefined ? null : `${place.latest_price.toLocaleString("ko-KR")}원`;
  const parking = airportParkingLabel(place);
  const fuelLabel = markerFuelLabel(place.price_product_code);
  const markerLabel = price ? `${fuelLabel} ${price}` : parking ?? placeKindLabel(place.kind);
  return <Marker ariaLabel={`${placeKindLabel(place.kind)} ${place.name}${price ? ` ${fuelLabel} ${price}` : parking ? ` ${parking}` : ""} 상세 보기`} className={`transport-map-marker ${place.kind}`} interactionId={point.id} key={point.id} lngLat={point.lngLat} onClick={() => onSelect(place)} selected={selected}>
    <span className={`map-place-marker map-place-marker-${place.kind}${price ? " has-price" : ""}`}><PlaceMarkerIcon kind={place.kind} /><span>{markerLabel}</span></span>
  </Marker>;
}

export function TransportMap() {
  const timetableController = useRef<AbortController | null>(null);
  const timetableRequest = useRef(0);
  const placesController = useRef<AbortController | null>(null);
  const placesRequest = useRef(0);
  const placeCache = useRef(new Map<string, { expiresAt: number; payload: PlaceResponse }>());
  const lastViewportKey = useRef("");
  const moveTimer = useRef<number | null>(null);
  const [items, setItems] = useState<Place[]>([]);
  const [selected, setSelected] = useState<Place | null>(null);
  const [message, setMessage] = useState("지도의 현재 범위에서 저장된 교통정보를 읽는 중입니다…");
  const [mapError, setMapError] = useState("");
  const [operations, setOperations] = useState<string>("");
  const points = useMemo<MapPoint[]>(() => items.filter((place) => Number.isFinite(place.longitude) && Number.isFinite(place.latitude)).map((place) => ({ id: `${place.kind}:${place.id}`, lngLat: [place.longitude, place.latitude], place })), [items]);
  const pointsById = useMemo(() => new Map(points.map((point) => [point.id, point.place])), [points]);

  const selectPlace = (place: Place) => { timetableController.current?.abort(); timetableRequest.current += 1; setSelected(place); setOperations(""); };

  function loadVisiblePlaces(bounds: MapBounds, zoom: number) {
    placesController.current?.abort();
    const controller = new AbortController();
    placesController.current = controller;
    const requestId = ++placesRequest.current;
    const viewport = {
      min_longitude: bounds.getWest().toFixed(4), min_latitude: bounds.getSouth().toFixed(4),
      max_longitude: bounds.getEast().toFixed(4), max_latitude: bounds.getNorth().toFixed(4),
    };
    const perKindLimit = visiblePlaceLimit(zoom);
    const viewportKey = `${perKindLimit}:${Object.values(viewport).join(":")}`;
    if (viewportKey === lastViewportKey.current) return;
    lastViewportKey.current = viewportKey;
    setMessage("지도의 현재 범위에서 저장된 교통정보를 읽는 중입니다…");
    Promise.allSettled(MAP_KINDS.map(async (kind) => {
      const search = new URLSearchParams({ kind, limit: String(perKindLimit), ...viewport });
      const cacheKey = search.toString();
      const cached = placeCache.current.get(cacheKey);
      if (cached && cached.expiresAt > Date.now()) return { kind, payload: cached.payload };
      const response = await fetch(`/api/transport/transport/features/places?${search}`, { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error(`${placeKindLabel(kind)} 정보를 불러오지 못했습니다.`);
      const payload = await response.json() as PlaceResponse;
      placeCache.current.set(cacheKey, { expiresAt: Date.now() + PLACE_CACHE_TTL_MS, payload });
      if (placeCache.current.size > PLACE_CACHE_MAX_ENTRIES) {
        const oldestKey = placeCache.current.keys().next().value;
        if (oldestKey) placeCache.current.delete(oldestKey);
      }
      return { kind, payload };
    })).then((results) => {
      if (requestId !== placesRequest.current) return;
      const fulfilled = results.flatMap((result) => result.status === "fulfilled" ? [result.value] : []);
      const failedKinds = MAP_KINDS.filter((kind) => !fulfilled.some((result) => result.kind === kind));
      const truncatedKinds = fulfilled.filter((result) => result.payload.truncated).map((result) => placeKindLabel(result.kind));
      const places = fulfilled.flatMap((result) => result.payload.items);
      setItems(places);
      if (!places.length) setMessage(failedKinds.length ? `${failedKinds.map(placeKindLabel).join("·")} 정보를 불러오지 못했습니다.` : "현재 지도 범위에 표시할 좌표가 아직 수집되지 않았습니다.");
      else if (truncatedKinds.length) setMessage(`현재 범위의 ${truncatedKinds.join("·")}는 화면 성능을 위해 종류별 ${perKindLimit.toLocaleString("ko-KR")}곳까지만 표시합니다. 지도를 확대하면 더 많은 장소를 확인할 수 있습니다.`);
      else if (failedKinds.length) setMessage(`${failedKinds.map(placeKindLabel).join("·")} 정보는 일시적으로 불러오지 못했습니다. 지도를 다시 움직여 재시도해 주세요.`);
      else setMessage("");
    }).catch(() => undefined);
  }

  useEffect(() => () => {
    placesRequest.current += 1;
    placesController.current?.abort();
    timetableController.current?.abort();
    if (moveTimer.current !== null) window.clearTimeout(moveTimer.current);
  }, []);

  useEffect(() => {
    const handleVWorldTileError = () => setMapError("VWorld 지도 타일을 불러오지 못했습니다. 지도 키·도메인 설정 또는 네트워크를 확인한 뒤 다시 시도해 주세요.");
    window.addEventListener("vworld-tile-error", handleVWorldTileError);
    return () => window.removeEventListener("vworld-tile-error", handleVWorldTileError);
  }, []);

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
    <VWorldMapView apiKey={process.env.NEXT_PUBLIC_VWORLD_API_KEY ?? ""} cameraTarget={selected ? { center: [selected.longitude, selected.latitude], zoom: 11 } : undefined} center={[127.8, 36.2]} className="transport-map-canvas" fallback={() => <p className="loading">VWorld 지도 키가 설정되지 않아 지도 대신 저장된 장소 목록을 표시합니다.</p>} geolocate={false} layerType="Base" lazy loadingSkeleton={<p className="loading">지도를 준비하는 중입니다…</p>} minZoom={5} navigation onError={(event) => { const status = (event.error as { status?: unknown } | undefined)?.status; if (typeof status === "number" && status >= 400) setMapError("VWorld 지도 타일을 불러오지 못했습니다. 지도 키·도메인 설정 또는 네트워크를 확인한 뒤 다시 시도해 주세요."); }} onLoad={(map) => { setMapError(""); loadVisiblePlaces(map.getBounds(), map.getZoom()); }} onMoveEnd={(event) => { const map = event.target as { getBounds: () => MapBounds; getZoom: () => number }; if (moveTimer.current !== null) window.clearTimeout(moveTimer.current); moveTimer.current = window.setTimeout(() => loadVisiblePlaces(map.getBounds(), map.getZoom()), 250); }} scale semanticZoomThreshold={11} unsupportedTileFallback={{ label: "VWorld 지도 타일을 불러오지 못했습니다." }} zoom={7}>
      <ClusterLayer maxZoom={14} points={points} radius={60} renderMarker={(point) => <MapMarker onSelect={selectPlace} point={point as MapPoint} selected={selected?.id === (point as MapPoint).place.id && selected.kind === (point as MapPoint).place.kind} />} />
      {selected ? <Popup className="transport-place-popup" interactionId={`${selected.kind}:${selected.id}`} lngLat={[selected.longitude, selected.latitude]} onClose={() => { setSelected(null); setOperations(""); }}><div className="map-popup"><p className="eyebrow">{placeKindLabel(selected.kind)}</p><h2>{selected.name}</h2>{selected.subtitle ? <p>{selected.subtitle}</p> : null}{selected.brand_name ? <p>{selected.brand_name}</p> : null}{selected.latest_price !== null && selected.latest_price !== undefined ? <strong>{fuelProductLabel(selected.price_product_code)} {selected.latest_price.toLocaleString("ko-KR")}원/L</strong> : null}{airportParkingLabel(selected) ? <><strong>{airportParkingLabel(selected)}</strong><p className="quiet">주차장 {selected.parking_lot_count ?? 0}곳의 최신 저장 현황</p></> : null}{selected.line_names.length ? <p>운행 노선: {selected.line_names.join(", ")}</p> : null}{selected.address ? <p className="quiet">{selected.address}</p> : null}{selected.kind === "ferry_port" ? <><p className="quiet">항만가이드라인 위치 {selected.location_point_count ?? 0}점 기준</p><button className="button" onClick={() => void loadTimetable()} type="button">오늘 운항 보기</button>{operations ? <p className="quiet timetable-result">{operations}</p> : null}</> : null}</div></Popup> : null}
    </VWorldMapView>
    <aside className="transport-map-detail" aria-live="polite">
      <label className="transport-map-picker" htmlFor="transport-map-place-picker">장소 목록에서 선택
        <select id="transport-map-place-picker" value={selected ? `${selected.kind}:${selected.id}` : ""} onChange={(event) => { const place = pointsById.get(event.target.value); if (place) selectPlace(place); }}>
          <option value="">지도에서 장소를 선택하거나 목록을 사용하세요</option>
          {points.map((point) => <option key={point.id} value={point.id}>{placeKindLabel(point.place.kind)} · {point.place.name}{point.place.line_names.length ? ` (${point.place.line_names.join(", ")})` : ""}</option>)}
        </select>
      </label>
      {mapError ? <p className="error-message">{mapError}</p> : null}
      {selected ? <><p className="eyebrow">{placeKindLabel(selected.kind)}</p><h2>{selected.name}</h2><p>{selected.line_names.length ? `운행 노선: ${selected.line_names.join(", ")}` : selected.address ?? "상세 정보는 지도 팝업에서 확인할 수 있습니다."}</p></> : <><h2>교통 장소</h2><p>{message || `현재 지도 범위의 공항·주유소·역·항구·휴게소 ${points.length.toLocaleString("ko-KR")}곳을 표시합니다. 지도 또는 목록을 선택하면 상세 정보를 봅니다.`}</p></>}
    </aside>
  </section>;
}
