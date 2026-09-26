"use client";

import { ClusterLayer, Marker, Popup, VWorldMapView } from "vworld-map-web";
import { useEffect, useMemo, useRef, useState } from "react";

import { fuelProductLabel, placeKindLabel } from "@/lib/transport-presentation";

type Place = { id: number; kind: "fuel_station" | "rail_station" | "ferry_port"; name: string; provider_id?: string | null; longitude: number; latitude: number; subtitle?: string | null; brand_name?: string | null; latest_price?: number | null; price_product_code?: string | null; line_names: string[]; address?: string | null; updated_at: string; location_source?: string | null; location_point_count?: number | null };
type MapPoint = { id: string; lngLat: [number, number]; place: Place };
type PlaceResponse = { items: Place[]; total: number; truncated: boolean };
type MapBounds = { getWest: () => number; getSouth: () => number; getEast: () => number; getNorth: () => number };
const MAP_KINDS = ["fuel_station", "rail_station", "ferry_port"] as const;
const MAP_KIND_LIMITS = {
  overview: 100,
  regional: 200,
  detail: 300,
} as const;

function visiblePlaceLimit(zoom: number) {
  if (zoom < 8) return MAP_KIND_LIMITS.overview;
  if (zoom < 10) return MAP_KIND_LIMITS.regional;
  return MAP_KIND_LIMITS.detail;
}

function timetableLine(item: { departure_port_name?: string; arrival_port_name?: string; departure_planned_time?: string; arrival_planned_time?: string; vessel_name?: string; fare?: string }, fallbackPortName: string) {
  const route = `${item.departure_planned_time ?? "—"} ${item.departure_port_name ?? fallbackPortName} → ${item.arrival_planned_time ?? "—"} ${item.arrival_port_name ?? "—"}`;
  return [route, item.vessel_name, item.fare ? `${item.fare}원` : undefined].filter(Boolean).join(" · ");
}

function MapMarker({ point, onSelect, selected }: { point: MapPoint; onSelect: (place: Place) => void; selected: boolean }) {
  const { place } = point;
  const price = place.latest_price === null || place.latest_price === undefined ? null : `${place.latest_price.toLocaleString("ko-KR")}원`;
  return <Marker ariaLabel={`${placeKindLabel(place.kind)} ${place.name} 상세 보기`} className={`transport-map-marker ${place.kind}`} interactionId={point.id} key={point.id} lngLat={point.lngLat} onClick={() => onSelect(place)} selected={selected}>
    <span className={price ? "map-price-marker" : "map-place-marker"}>{price ?? placeKindLabel(place.kind)}</span>
  </Marker>;
}

export function TransportMap() {
  const timetableController = useRef<AbortController | null>(null);
  const timetableRequest = useRef(0);
  const placesController = useRef<AbortController | null>(null);
  const placesRequest = useRef(0);
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
    setMessage("지도의 현재 범위에서 저장된 교통정보를 읽는 중입니다…");
    Promise.allSettled(MAP_KINDS.map(async (kind) => {
      const search = new URLSearchParams({ kind, limit: String(perKindLimit), ...viewport });
      const response = await fetch(`/api/transport/transport/features/places?${search}`, { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error(`${placeKindLabel(kind)} 정보를 불러오지 못했습니다.`);
      return { kind, payload: await response.json() as PlaceResponse };
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
    setOperations("저장된 운항 정보를 읽는 중입니다…");
    try {
      const response = await fetch(`/api/transport/transport/ports/${encodeURIComponent(providerId)}/timetable`, { signal: controller.signal });
      if (!response.ok) {
        const body = await response.json().catch(() => null) as { detail?: string } | null;
        const retryAfter = response.headers.get("retry-after");
        throw new Error(response.status === 429 && retryAfter ? `${body?.detail ?? "운항 정보 보충 요청이 제한되었습니다."} 약 ${retryAfter}초 뒤 다시 시도해 주세요.` : body?.detail ?? "저장된 운항 정보를 불러오지 못했습니다.");
      }
      const payload = await response.json() as { items: Array<{ departure_port_name?: string; arrival_port_name?: string; departure_planned_time?: string; arrival_planned_time?: string; vessel_name?: string; fare?: string }> };
      if (timetableRequest.current === requestId) setOperations(payload.items.length ? payload.items.map((item) => timetableLine(item, port.name)).join("\n") : "오늘 등록된 운항 정보가 없습니다.");
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      if (timetableRequest.current === requestId) setOperations(error instanceof Error ? error.message : "저장된 운항 정보를 불러오지 못했습니다.");
    }
  }

  return <section className="transport-map-layout" aria-label="교통 장소 지도">
    <VWorldMapView apiKey={process.env.NEXT_PUBLIC_VWORLD_API_KEY ?? ""} cameraTarget={selected ? { center: [selected.longitude, selected.latitude], zoom: 11 } : undefined} center={[127.8, 36.2]} className="transport-map-canvas" fallback={() => <p className="loading">VWorld 지도 키가 설정되지 않아 지도 대신 저장된 장소 목록을 표시합니다.</p>} geolocate={false} layerType="Base" lazy loadingSkeleton={<p className="loading">지도를 준비하는 중입니다…</p>} minZoom={5} navigation onError={(event) => { const status = (event.error as { status?: unknown } | undefined)?.status; if (typeof status === "number" && status >= 400) setMapError("VWorld 지도 타일을 불러오지 못했습니다. 지도 키·도메인 설정 또는 네트워크를 확인한 뒤 다시 시도해 주세요."); }} onLoad={(map) => { setMapError(""); loadVisiblePlaces(map.getBounds(), map.getZoom()); }} onMoveEnd={(event) => { const map = event.target as { getBounds: () => MapBounds; getZoom: () => number }; if (moveTimer.current !== null) window.clearTimeout(moveTimer.current); moveTimer.current = window.setTimeout(() => loadVisiblePlaces(map.getBounds(), map.getZoom()), 250); }} scale semanticZoomThreshold={11} unsupportedTileFallback={{ label: "VWorld 지도 타일을 불러오지 못했습니다." }} zoom={7}>
      <ClusterLayer maxZoom={14} points={points} radius={60} renderMarker={(point) => <MapMarker onSelect={selectPlace} point={point as MapPoint} selected={selected?.id === (point as MapPoint).place.id && selected.kind === (point as MapPoint).place.kind} />} />
      {selected ? <Popup className="transport-place-popup" interactionId={`${selected.kind}:${selected.id}`} lngLat={[selected.longitude, selected.latitude]} onClose={() => { setSelected(null); setOperations(""); }}><div className="map-popup"><p className="eyebrow">{placeKindLabel(selected.kind)}</p><h2>{selected.name}</h2>{selected.brand_name ? <p>{selected.brand_name}</p> : null}{selected.latest_price !== null && selected.latest_price !== undefined ? <strong>{fuelProductLabel(selected.price_product_code)} {selected.latest_price.toLocaleString("ko-KR")}원/L</strong> : null}{selected.line_names.length ? <p>운행 노선: {selected.line_names.join(", ")}</p> : null}{selected.address ? <p className="quiet">{selected.address}</p> : null}{selected.kind === "ferry_port" ? <><p className="quiet">항만가이드라인 위치 {selected.location_point_count ?? 0}점 기준</p><button className="button" onClick={() => void loadTimetable()} type="button">오늘 운항 보기</button>{operations ? <p className="quiet timetable-result">{operations}</p> : null}</> : null}</div></Popup> : null}
    </VWorldMapView>
    <aside className="transport-map-detail" aria-live="polite">
      <label className="transport-map-picker" htmlFor="transport-map-place-picker">장소 목록에서 선택
        <select id="transport-map-place-picker" value={selected ? `${selected.kind}:${selected.id}` : ""} onChange={(event) => { const place = pointsById.get(event.target.value); if (place) selectPlace(place); }}>
          <option value="">지도에서 장소를 선택하거나 목록을 사용하세요</option>
          {points.map((point) => <option key={point.id} value={point.id}>{placeKindLabel(point.place.kind)} · {point.place.name}{point.place.line_names.length ? ` (${point.place.line_names.join(", ")})` : ""}</option>)}
        </select>
      </label>
      {mapError ? <p className="error-message">{mapError}</p> : null}
      {selected ? <><p className="eyebrow">{placeKindLabel(selected.kind)}</p><h2>{selected.name}</h2><p>{selected.line_names.length ? `운행 노선: ${selected.line_names.join(", ")}` : selected.address ?? "상세 정보는 지도 팝업에서 확인할 수 있습니다."}</p></> : <><h2>교통 장소</h2><p>{message || `현재 지도 범위의 주유소·역·항구 ${points.length.toLocaleString("ko-KR")}곳을 표시합니다. 지도 또는 목록을 선택하면 상세 정보를 봅니다.`}</p></>}
    </aside>
  </section>;
}
