"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState, type CSSProperties, type RefObject, type ReactNode } from "react";
import { ClusterLayer, VWorldMapView, type ClusterPoint, type MapLibreMap } from "vworld-map-web";
import { setWorkerUrl } from "maplibre-gl";
import { clusterAtScale, dateTime, hasCoordinates, hasFuelPrice, transportGet, type Place, type PlaceKind } from "@/lib/journey";
import { collectionSourceLabel, fuelProductLabel, placeKindLabel } from "@/lib/transport-presentation";
import { placeMarkerColor, placeMarkerStyle, priceMarkerLabel, priceSpeech } from "@/lib/place-marker-style";
import { FuelPriceStatus, FuelViewportSummary, type FuelViewportStatistics } from "@/components/fuel-statistics";
import { MAP_FALLBACK_IMAGE } from "@/lib/map-fallback";
import { cn } from "@/lib/utils";
import { CameraRequest, ClusterBubble, MapMarkerButton, MapUnavailable, MarkerBadge, OverlapPopup, useVWorldBasemapHealth, vworldApiKey, ZoomButtons, type CameraTarget } from "./map-overlays";
import { PlaceIcon } from "./journey-controls";
import { PlaceInspector } from "./place-inspector";
import { MapDetailOverlay, MapFilterBar, MapFilterField, MapFilterPanel, MapKindFilter, MapStage, MapWorkspace, MapTabs as Tabs, MapTabPanel as TabsContent, MapViewTabs, type MapViewportReadout } from "@kor-travel/ui/map-controls";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { FilterCombobox } from "./filter-combobox";

type MapPoint = { id: string; lngLat: [number, number]; place: Place };
type Viewport = { min_longitude: string; min_latitude: string; max_longitude: string; max_latitude: string };
type MapCluster = { longitude: number; latitude: number; count: number; kind_counts: Partial<Record<PlaceKind, number>> };
type PlaceResponse = { fuel_statistics?: FuelViewportStatistics[]; items: Place[]; total: number; truncated: boolean; clustered?: boolean; kind_totals?: Partial<Record<PlaceKind, number>>; clusters?: MapCluster[]; available_sources?: string[]; fuel_prices_stale?: boolean; fuel_prices_last_refreshed_at?: string | null };
const KINDS: PlaceKind[] = ["fuel_station", "rail_station", "ferry_port", "bus_terminal", "airport", "rest_area", "highway_incident"];
const TRANSPORT_KINDS: PlaceKind[] = ["rail_station", "ferry_port", "bus_terminal", "airport", "rest_area", "highway_incident"];
const MAP_CLUSTER_CACHE_TTL_MS = 20_000;
const MAP_CLUSTER_CACHE_MAX = 8;
const CLUSTER_NUMBER_FORMATTER = new Intl.NumberFormat("ko-KR", { notation: "compact", maximumFractionDigits: 1 });
const DEFAULT_VIEWPORT: Viewport = { min_longitude: "124", min_latitude: "32", max_longitude: "132", max_latitude: "39" };
const keyOf = (place: Place) => `${place.kind}:${place.id}`;
const canRestoreFocus = (element: HTMLElement | null): element is HTMLElement => Boolean(element?.isConnected && element !== document.body && element.getClientRects().length && !element.closest("[inert], [hidden]") && getComputedStyle(element).visibility !== "hidden");

function quantizeViewport(bounds: { min_longitude: number; min_latitude: number; max_longitude: number; max_latitude: number }, zoom: number): Viewport {
  const precision = zoom >= 14 ? 4 : zoom >= 11 ? 3 : zoom >= 8 ? 2 : 1;
  const factor = 10 ** precision;
  return {
    min_longitude: (Math.floor(Math.max(-180, bounds.min_longitude) * factor) / factor).toFixed(precision),
    min_latitude: (Math.floor(Math.max(-90, bounds.min_latitude) * factor) / factor).toFixed(precision),
    max_longitude: (Math.ceil(Math.min(180, bounds.max_longitude) * factor) / factor).toFixed(precision),
    max_latitude: (Math.ceil(Math.min(90, bounds.max_latitude) * factor) / factor).toFixed(precision),
  };
}

// Next.js는 정적 참조만 번들에 넣는다. 빈 값·자리표시자는 라이브러리 `missing-api-key` 대체 화면으로 간다.
const VWORLD_KEY = vworldApiKey(process.env.NEXT_PUBLIC_VWORLD_API_KEY);
// Map과 같은 배선: v6의 worker와 shared를 predev/prebuild에서 함께 복사한다.
setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

// Map 지도와 같은 마커: 24px 원형 배지(maki 글리프 + 팔레트 색). 이름은 배지에 쓰지 않고 hover 제목과
// 접근 이름으로만 준다. 주유소 가격은 Map 가격 마커처럼 배지 오른쪽의 흰 라벨에 한 줄씩 쓴다.
function MapMarker({ point, onSelect, selected, products }: { point: MapPoint; onSelect: (place: Place) => void; selected: boolean; products: string[] }) {
  const place = point.place;
  const { markerIcon, markerColor } = placeMarkerStyle(place.kind);
  const priceLabel = place.kind === "fuel_station" ? priceMarkerLabel(place.prices, products) : null;
  const title = [place.name, place.brand_name, place.kind === "rail_station" ? place.line_names.join("·") : null].filter(Boolean).join(" · ");
  const ariaLabel = [placeKindLabel(place.kind), place.name, place.line_names.join(" · "), priceLabel ? priceSpeech(place.prices, products) : null, "상세 보기"].filter(Boolean).join(" ");
  // 선택 마커는 묶음 원(z 3) 위(z 4)에 그리되 포인터는 통과시켜 같은 좌표의 묶음 원도 눌린다.
  return <MapMarkerButton lngLat={point.lngLat} interactionId={point.id} zIndex={selected ? 4 : undefined} passThrough={selected} pressed={selected}
    className={`transport-map-marker ${place.kind}${selected ? " is-selected" : ""}`}
    title={priceLabel ? `${title} ${priceLabel.replace(/\n/g, " ")}` : title} ariaLabel={ariaLabel} onClick={() => onSelect(place)}>
    <MarkerBadge markerIcon={markerIcon} markerColor={markerColor} selected={selected} />
    {priceLabel ? <span className="map-marker-price" style={{ "--marker-color": placeMarkerColor(place.kind) } as CSSProperties}>{priceLabel}</span> : null}
  </MapMarkerButton>;
}

// Map `showCoincidentPopup`과 같은 겹친 지점 팝업: 제목·개수 칩과 색 점·종류 배지·이름 행.
function OverlapList({ places, onSelect, listRef }: { places: Place[]; onSelect: (place: Place) => void; listRef: RefObject<HTMLElement | null> }) {
  return <section ref={listRef} className="map-overlap" aria-label="겹친 장소 선택">
    <header><span className="map-overlap-title">겹친 지점</span><span className="map-overlap-count">{places.length}개</span></header>
    <div className="map-overlap-list">{places.map((place) => <button type="button" key={keyOf(place)} aria-label={place.name} style={{ "--marker-color": placeMarkerColor(place.kind) } as CSSProperties} onClick={() => onSelect(place)}>
      <span className="map-overlap-dot" aria-hidden="true" /><span className="map-overlap-kind" aria-hidden="true">{placeKindLabel(place.kind)}</span><span className="map-overlap-name">{place.name}</span>
    </button>)}</div>
  </section>;
}

export function TransportMap({ places, selectedPlace, onSelectPlace, mode = "all", details, detailTitle, onCloseDetails, focusRevision = 0, layers, detailKey, mapFeatureCount = 0, listFeatureCount = 0, listContent, listPlaces = true, toolbar, feedback, filterSummary, view: controlledView, onViewChange }: { places?: Place[]; selectedPlace?: Place | null; onSelectPlace?: (place: Place) => void; mode?: "all" | "transport" | "fuel"; details?: ReactNode; detailTitle?: ReactNode; onCloseDetails?: () => void; focusRevision?: number; layers?: ReactNode; detailKey?: string; mapFeatureCount?: number; listFeatureCount?: number; listContent?: ReactNode; listPlaces?: boolean; toolbar?: ReactNode; feedback?: ReactNode; filterSummary?: string; view?: "map" | "list"; onViewChange?: (view: "map" | "list") => void }) {
  const controlId = useId();
  const embedded = places !== undefined;
  const allowedKinds = mode === "fuel" ? ["fuel_station"] as PlaceKind[] : mode === "transport" ? TRANSPORT_KINDS : KINDS;
  const [loaded, setLoaded] = useState<Record<string, PlaceResponse>>({});
  const [kinds, setKinds] = useState<PlaceKind[]>(allowedKinds);
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [knownSources, setKnownSources] = useState<string[]>([]);
  const [products, setProducts] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [clusterPlaces, setClusterPlaces] = useState<Place[]>([]);
  const [serverClusters, setServerClusters] = useState<MapCluster[]>([]);
  const [serverClustered, setServerClustered] = useState(false);
  const [clusterAnchor, setClusterAnchor] = useState<[number, number]>([127.8, 36.2]);
  const [clusterCamera, setClusterCamera] = useState<{ center: [number, number]; zoom: number }>();
  const [cameraRequest, setCameraRequest] = useState(0);
  const clusterList = useRef<HTMLElement | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [localView, setLocalView] = useState<"map" | "list">("map");
  const view = controlledView ?? localView;
  const setView = (value: "map" | "list") => { setLocalView(value); onViewChange?.(value); };
  const [selected, setSelected] = useState<Place | null>(null);
  const [viewport, setViewport] = useState(DEFAULT_VIEWPORT);
  const [zoom, setZoom] = useState(7);
  const [mapViewport, setMapViewport] = useState<MapViewportReadout | null>(null);
  const [mapSize, setMapSize] = useState({ width: 800, height: 540 });
  const mapContainer = useRef<HTMLDivElement | null>(null);
  const queryInput = useRef<HTMLInputElement | null>(null);
  const filterTrigger = useRef<HTMLButtonElement | null>(null);
  const workspace = useRef<HTMLDivElement | null>(null);
  const [filtersExpanded, setFiltersExpanded] = useState(false);
  const [fuelDetailScopeExpanded, setFuelDetailScopeExpanded] = useState(false);
  const [pending, setPending] = useState<string[]>([]);
  const [failed, setFailed] = useState<string[]>([]);
  const basemap = useVWorldBasemapHealth();
  const [mapUnavailableMessage, setMapUnavailableMessage] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mapResponseCache = useRef(new Map<string, { expiresAt: number; payload: PlaceResponse }>());
  const lastReload = useRef(reload);
  const mapFilterSignature = useRef("");
  const knownSourcesReady = useRef(false);
  useEffect(() => {
    if (embedded) return;
    const search = new URLSearchParams(window.location.search);
    if (!search.has("longitude") || !search.has("latitude")) return;
    const longitude = Number(search.get("longitude")), latitude = Number(search.get("latitude"));
    if (!Number.isFinite(longitude) || !Number.isFinite(latitude) || longitude < 124 || longitude > 132 || latitude < 32 || latitude > 39.5) return;
    // URL이 지정한 지도 위치는 최초 문서에서만 복원한다.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setClusterCamera({ center: [longitude, latitude], zoom: 15 });
    setViewport({ min_longitude: String(longitude - .015), max_longitude: String(longitude + .015), min_latitude: String(latitude - .015), max_latitude: String(latitude + .015) });
    setZoom(15);
  }, [embedded]);
  const current = selectedPlace === undefined ? selected : selectedPlace;
  const kindsKey = kinds.join(",");
  const sourcesKey = selectedSources.join(",");
  const productsKey = products.join(",");
  const perKindLimit = Math.min(300, Math.floor(900 / Math.max(1, kinds.length)));
  const sources = useMemo(() => [...new Set([...knownSources, ...(places ?? []).map((item) => item.source)])], [places, knownSources]);
  const all = useMemo(() => places ?? kinds.flatMap((kind) => loaded[kind]?.items ?? []), [places, kinds, loaded]);
  const items = useMemo(() => all.filter((item) => (!selectedSources.length || selectedSources.includes(item.source)) && (!embedded || !query || [item.name, item.brand_name, item.address, item.subtitle, item.provider_id, ...item.line_names].join(" ").toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())) && (!products.length || item.kind !== "fuel_station" || item.prices?.some((row) => hasFuelPrice(row) && products.includes(row.product_code)))), [all, embedded, selectedSources, query, products]);
  const points = useMemo<MapPoint[]>(() => items.filter(hasCoordinates).map((place) => ({ id: keyOf(place), lngLat: [place.longitude, place.latitude], place })), [items]);
  const visiblePoints = points.filter((point) =>
    point.lngLat[0] >= Number(viewport.min_longitude) && point.lngLat[0] <= Number(viewport.max_longitude)
    && point.lngLat[1] >= Number(viewport.min_latitude) && point.lngLat[1] <= Number(viewport.max_latitude));
  const cluster = !serverClustered && clusterAtScale(zoom, (Number(viewport.min_latitude) + Number(viewport.max_latitude)) / 2, visiblePoints.length, mapSize.width, mapSize.height);
  const markerPoints = embedded ? points : visiblePoints;
  const groupedPoints = useMemo(() => current ? markerPoints.filter((point) => point.id !== keyOf(current)) : markerPoints, [markerPoints, current]);
  const selectedPoint = points.find((point) => current && point.id === keyOf(current))
    ?? (current && hasCoordinates(current) ? { id: keyOf(current), lngLat: [current.longitude, current.latitude] as [number, number], place: current } : undefined);
  // 전환 중 이전 Panel이 잠시 남으므로 각 Panel의 ref를 분리한다. 이전 상세의
  // 언마운트가 새 활성 상세의 ref를 비워 주소 이동 뒤 초점이 body로 빠지지 않게 한다.
  const mapDetail = useRef<HTMLElement | null>(null);
  const listDetail = useRef<HTMLElement | null>(null);
  const detail = view === "map" ? mapDetail : listDetail;
  const detailOpener = useRef<HTMLElement | null>(null);
  const selectedKey = detailKey ?? (current ? keyOf(current) : "");
  const hasEmbeddedDetails = embedded && details !== undefined;
  useEffect(() => {
    if (!selectedKey || (embedded && !hasEmbeddedDetails)) return;
    const active = document.activeElement;
    if (active instanceof HTMLElement && active !== document.body && !detail.current?.contains(active)) detailOpener.current = active;
    const frame = requestAnimationFrame(() => detail.current?.focus({ preventScroll: true }));
    return () => cancelAnimationFrame(frame);
  }, [embedded, hasEmbeddedDetails, selectedKey, focusRevision, cameraRequest, view, detail]);
  const dismissEmbeddedDetail = () => {
    onCloseDetails?.();
    const opener = detailOpener.current;
    detailOpener.current = null;
    requestAnimationFrame(() => {
      if (canRestoreFocus(opener)) opener.focus({ preventScroll: true });
      else focusMapControl();
    });
  };
  // 겹친 지점 팝업을 연 묶음 원. 닫기(×·Escape) 뒤 포커스를 그 자리로 돌려준다. 장소를 고르면 상세로 간다.
  const overlapOpener = useRef<HTMLElement | null>(null);
  const closeOverlap = () => {
    const opener = overlapOpener.current;
    overlapOpener.current = null;
    setClusterPlaces([]);
    const id = opener?.dataset.interactionId;
    const root = mapContainer.current;
    if (!opener || !id || !root) return;
    // 팝업을 지우기 전에 포커스를 묶음 원으로 옮긴다(포커스된 목록 버튼이 먼저 사라지면 body로 간다).
    // 장소 재조회는 목록을 비웠다 다시 채우므로 같은 좌표의 묶음 원 DOM이 곧 새로 만들어질 수 있다. 잠시 동안
    // 포커스가 body로 떨어지면 같은 묶음(data-interaction-id)을 다시 잡는다. 사용자가 다른 곳으로 옮겼으면 건드리지 않는다.
    const find = () => root.querySelector<HTMLElement>(`[data-interaction-id="${CSS.escape(id)}"]`);
    (opener.isConnected ? opener : find())?.focus();
    const observer = new MutationObserver(() => {
      if (document.activeElement && document.activeElement !== document.body) return;
      find()?.focus();
    });
    observer.observe(root, { childList: true, subtree: true });
    setTimeout(() => observer.disconnect(), 2000);
  };
  const selectPlace = (place: Place) => {
    overlapOpener.current = null;
    setClusterPlaces([]); setClusterCamera(undefined);
    // 같은 장소를 다시 골라도(손으로 지도를 옮긴 뒤) 다시 그 자리로 이동하도록 요청 번호를 올린다.
    setCameraRequest((value) => value + 1);
    setSelected(place); onSelectPlace?.(place);
    if (!embedded) requestAnimationFrame(() => {
      detail.current?.focus({ preventScroll: true });
    });
  };

  useEffect(() => {
    if (!mapContainer.current) return;
    const observer = new ResizeObserver(([entry]) => setMapSize({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(mapContainer.current);
    return () => observer.disconnect();
  }, [view]);

  useEffect(() => {
    if (query === searchQuery) return;
    const debounce = setTimeout(() => { setSearchQuery(query); setSelected(null); }, 250);
    return () => clearTimeout(debounce);
  }, [query, searchQuery]);

  useEffect(() => {
    // 지도 이동·크기 변경으로 DB 결과가 갱신되어도 열어 둔 선택 목록은 유지한다.
    // 검색 조건을 바꾸거나 명시적으로 선택/닫기한 경우에만 목록을 닫는다.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setClusterPlaces([]);
  }, [kindsKey, sourcesKey, searchQuery, productsKey, view, mode]);

  useEffect(() => {
    if (embedded) return;
    const controller = new AbortController();
    const selectedKinds = kindsKey ? kindsKey.split(",") : [];
    const filterSignature = `${kindsKey}|${sourcesKey}|${searchQuery}|${productsKey}|${view}`;
    if (lastReload.current !== reload) {
      mapResponseCache.current.clear();
      lastReload.current = reload;
    }
    // 필터가 바뀌면 이전 조건 결과를 비우지만, 이동 중에는 기존 viewport 결과를
    // 유지해 빈 화면 대신 현재 화면 안에 남아 있는 점을 계속 보여준다.
    if (mapFilterSignature.current !== filterSignature || view === "list") {
      setLoaded({}); setServerClusters([]); setServerClustered(false);
      mapFilterSignature.current = filterSignature;
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPending(selectedKinds); setFailed([]);

    const applyPayload = (payload: PlaceResponse) => {
      const perKind: Record<string, PlaceResponse> = {};
      for (const kind of selectedKinds) {
        const kindItems = payload.items.filter((item) => item.kind === kind);
        const kindTotal = payload.kind_totals?.[kind as PlaceKind] ?? kindItems.length;
        perKind[kind] = {
          ...payload,
          items: kindItems,
          total: kindTotal,
          truncated: payload.clustered ? false : kindTotal > kindItems.length,
        };
      }
      setLoaded(perKind);
      setServerClusters(payload.clusters ?? []);
      setServerClustered(payload.clustered ?? false);
      knownSourcesReady.current = true;
      setKnownSources((value) => [...new Set([...value, ...(payload.available_sources ?? payload.items.map((item) => item.source))])]);
      setPending([]);
    };

    if (view === "map" && selectedKinds.length) {
      const search = new URLSearchParams({
        kinds: selectedKinds.join(","),
        limit: String(Math.min(900, perKindLimit * selectedKinds.length)),
        zoom: String(Math.floor(zoom)),
        ...viewport,
      });
      if (!knownSourcesReady.current) search.set("include_sources", "true");
      else search.set("include_sources", "false");
      if (sourcesKey) search.set("sources", sourcesKey);
      if (searchQuery.trim()) search.set("query", searchQuery.trim());
      if (productsKey && selectedKinds.includes("fuel_station")) search.set("product_codes", productsKey);
      if (mode === "fuel") search.set("include_fuel_statistics", "true");
      const cacheKey = search.toString();
      const cached = mapResponseCache.current.get(cacheKey);
      if (cached && cached.expiresAt > Date.now()) {
        mapResponseCache.current.delete(cacheKey);
        mapResponseCache.current.set(cacheKey, cached);
        applyPayload(cached.payload);
        return () => controller.abort();
      }
      mapResponseCache.current.delete(cacheKey);
      transportGet<PlaceResponse>(`transport/features/places?${search}`, controller.signal).then((payload) => {
        if (controller.signal.aborted) return;
        mapResponseCache.current.set(cacheKey, { expiresAt: Date.now() + MAP_CLUSTER_CACHE_TTL_MS, payload });
        while (mapResponseCache.current.size > MAP_CLUSTER_CACHE_MAX) {
          const oldest = mapResponseCache.current.keys().next().value;
          if (oldest === undefined) break;
          mapResponseCache.current.delete(oldest);
        }
        applyPayload(payload);
      }).catch(() => {
        if (!controller.signal.aborted) { setFailed(selectedKinds); setPending([]); }
      });
      return () => controller.abort();
    }

    // 목록은 좌표 없는 항구·터미널도 찾아야 하므로 기존 종류별 reference 조회를 유지한다.
    selectedKinds.forEach((kind) => {
      // 좌표 없는 항구·터미널도 목록에서 코드/이름으로 찾되 지도에는 검증된 위치만 놓는다.
      const referenceList = view === "list" && (kind === "ferry_port" || kind === "bus_terminal");
      const search = new URLSearchParams({ kind, limit: String(referenceList && searchQuery.trim() ? 5000 : perKindLimit),
        ...(referenceList ? { include_unlocated: "true" } : viewport) });
      if (!knownSourcesReady.current) search.set("include_sources", "true");
      else search.set("include_sources", "false");
      if (sourcesKey) search.set("sources", sourcesKey);
      if (searchQuery.trim()) search.set("query", searchQuery.trim());
      if (productsKey && kind === "fuel_station") search.set("product_codes", productsKey);
      transportGet<PlaceResponse>(`transport/features/places?${search}`, controller.signal).then((payload) => {
        if (!controller.signal.aborted) {
          setLoaded((value) => ({ ...value, [kind]: payload }));
          setKnownSources((value) => [...new Set([...value, ...(payload.available_sources ?? payload.items.map((item) => item.source))])]);
        }
      }).catch(() => { if (!controller.signal.aborted) setFailed((value) => [...value, kind]); })
        .finally(() => { if (!controller.signal.aborted) setPending((value) => value.filter((entry) => entry !== kind)); });
    });
    return () => controller.abort();
  }, [embedded, kindsKey, perKindLimit, viewport, zoom, reload, sourcesKey, searchQuery, productsKey, view, mode]);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  const moved = useCallback((map: MapLibreMap) => {
    const bounds = map.getBounds();
    const nextZoom = map.getZoom();
    const center = map.getCenter();
    setMapViewport({ longitude: center.lng, latitude: center.lat, zoom: nextZoom });
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      setZoom(nextZoom);
      setViewport((previous) => {
      const next = quantizeViewport({ min_longitude: bounds.getWest(), min_latitude: bounds.getSouth(), max_longitude: bounds.getEast(), max_latitude: bounds.getNorth() }, nextZoom);
      // 패널 높이/스크롤 변화로 같은 bounds의 moveend가 와도 선택 목록을 지우거나
      // 같은 정밀도 셀 안에서 같은 DB 조회를 반복하지 않는다.
      return (Object.keys(next) as (keyof Viewport)[]).every((key) => next[key] === previous[key]) ? previous : next;
      });
    }, 250);
  }, []);
  // 카메라 요청 정체: 장소 key(부모가 선택을 바꾼 경우)와 요청 번호(같은 묶음·장소를 다시 누른 경우).
  // 현재 zoom은 이동 목표 계산에만 쓰고 정체에는 넣지 않는다 — 넣으면 손으로 확대할 때마다 다시 끌려간다.
  const camera = useMemo<CameraTarget | undefined>(() => clusterCamera ? { ...clusterCamera, id: `cluster:${cameraRequest}` }
    : current && hasCoordinates(current) ? { center: [current.longitude, current.latitude], zoom: Math.max(zoom, 11), id: `${keyOf(current)}:${cameraRequest}:${focusRevision}` } : undefined,
  [current, clusterCamera, cameraRequest, focusRevision]); // eslint-disable-line react-hooks/exhaustive-deps
  const focusMapControl = () => (mapContainer.current?.querySelector<HTMLElement>(".maplibregl-canvas") ?? (filterTrigger.current?.getClientRects().length ? filterTrigger.current : workspace.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')))?.focus({ preventScroll: true });
  const focusFilters = () => { if (queryInput.current?.getClientRects().length) queryInput.current.focus({ preventScroll: true }); else focusMapControl(); };
  const closeDetail = () => { setSelected(null); requestAnimationFrame(() => { if (canRestoreFocus(detailOpener.current)) detailOpener.current.focus({ preventScroll: true }); else focusFilters(); }); };
  const detailPanel = (panelView: "map" | "list") => embedded && details ? <MapDetailOverlay ref={panelView === "map" ? mapDetail : listDetail} className="transport-map-detail" aria-label="선택 장소 상세" header={<h2>{detailTitle ?? current?.name ?? "선택 장소 상세"}</h2>} collapsible onDismiss={dismissEmbeddedDetail}>
    {details}
  </MapDetailOverlay> : !embedded && current ? <MapDetailOverlay className={cn("transport-map-detail weather-inspector", current.kind === "fuel_station" && "fuel-inspector")} ref={panelView === "map" ? mapDetail : listDetail} aria-label="선택 장소 상세" header={current.kind === "fuel_station" ? <div className="fuel-detail-heading"><PlaceIcon kind={current.kind} /><h2>{current.name}</h2>{current.brand_name ? <small>{current.brand_name}</small> : null}</div> : <div><span className="place-title"><PlaceIcon kind={current.kind} />{current.brand_name ?? placeKindLabel(current.kind)}</span><h2>{current.name}</h2></div>} collapsible={current.kind !== "fuel_station"} onDismiss={closeDetail}>
    {current.kind === "fuel_station" && loaded.fuel_station?.fuel_prices_stale ? <div className="inspector-section fuel-price-status"><FuelPriceStatus stale lastRefreshedAt={loaded.fuel_station.fuel_prices_last_refreshed_at} /></div> : null}
    <PlaceInspector key={keyOf(current)} place={current} showHeader={false} onShowMap={() => { setView("map"); setCameraRequest((value) => value + 1); }} onClose={closeDetail} onSaved={(updated) => { setSelected(updated); setReload((value) => value + 1); }} onReload={() => { setSelected(null); setReload((value) => value + 1); focusFilters(); }} />
  </MapDetailOverlay> : null;
  const status = <>
    {feedback}
    {failed.length ? <p className="error" role="alert">{failed.map(placeKindLabel).join("·")} 조회 실패 <Button variant="outline" type="button" onClick={() => setReload((value) => value + 1)}>다시 조회</Button></p> : null}
    {basemap.basemapFailed && view === "map" ? <p className="error" role="alert">지도 타일 오류 · 목록 보기</p> : null}
    {mapUnavailableMessage && view === "map" ? <p className="error" role="alert">{mapUnavailableMessage}</p> : null}
  </>;
  const summary = <>
    <div className="map-feedback">{status}</div>
    {!embedded && mode === "fuel" ? <FuelViewportSummary items={loaded.fuel_station?.fuel_statistics ?? []} pending={pending.length > 0} failed={failed.length > 0}
      detailOpen={Boolean(current)} detailExpanded={fuelDetailScopeExpanded} onDetailExpandedChange={setFuelDetailScopeExpanded}
      pricesStale={loaded.fuel_station?.fuel_prices_stale} pricesLastRefreshedAt={loaded.fuel_station?.fuel_prices_last_refreshed_at} /> : null}
  </>;

  return <section className="map-workbench" aria-label={mode === "fuel" ? "유가 지도" : "교통 장소 지도"}>
    <MapWorkspace expandable ref={workspace} className={embedded ? "embedded-map" : "transport-map-workspace"} onClickCapture={(event) => {
      const opener = event.target instanceof Element ? event.target.closest<HTMLElement>("button, a") : null;
      if (opener && !detail.current?.contains(opener) && (opener.closest(".map-place-list") || opener.closest("[data-interaction-id]"))) detailOpener.current = opener;
    }}>
    {toolbar || !embedded ? <MapFilterPanel label={filterSummary ?? ([query, selectedSources.length ? `${selectedSources.length}개 출처` : "", products.map(fuelProductLabel).join("·"), kinds.length !== allowedKinds.length ? `${kinds.length}종류` : ""].filter(Boolean).join(" · ") || "지도 필터")} expanded={filtersExpanded} onExpandedChange={setFiltersExpanded} triggerRef={filterTrigger}>
    {toolbar ?? <MapFilterBar>
      {mode !== "fuel" ? <MapKindFilter ariaLabel={mode === "transport" ? "교통 종류" : "장소 종류"} options={allowedKinds.map((kind) => ({ value: kind, label: placeKindLabel(kind), icon: <PlaceIcon kind={kind} /> }))} value={kinds} onToggle={(value) => { const kind = value as PlaceKind; setKinds((previous) => previous.includes(kind) ? previous.filter((entry) => entry !== kind) : [...previous, kind]); setSelected(null); }} /> : null}
      <MapFilterField htmlFor={`${controlId}-query`} label="장소 검색"><Input ref={queryInput} id={`${controlId}-query`} type="search" value={query} onChange={(event) => { setQuery(event.target.value); setSelected(null); }} placeholder="이름·브랜드·노선" /></MapFilterField>
      <MapFilterField htmlFor={`${controlId}-source`} label="데이터 출처"><FilterCombobox compact id={`${controlId}-source`} value={selectedSources} onChange={(values) => { setSelectedSources(values); setSelected(null); }} placeholder="모든 출처" options={sources.map((value) => ({ value, label: collectionSourceLabel(value) }))} /></MapFilterField>
      {kinds.includes("fuel_station") ? <MapFilterField htmlFor={`${controlId}-product`} label="표시 유종"><FilterCombobox compact id={`${controlId}-product`} value={products} onChange={(values) => { setProducts(values); setSelected(null); }} placeholder="전체 유종" options={["B027", "D047", "B034", "K015", "C004"].map((value) => ({ value, label: fuelProductLabel(value) }))} /></MapFilterField> : null}
    </MapFilterBar>}
    </MapFilterPanel> : null}
    <Tabs value={view} onValueChange={(value) => { if (value === "map" || value === "list") { setView(value); setFiltersExpanded(false); } }} className="min-h-0">
    <MapViewTabs ariaLabel="장소 보기" viewport={mapViewport} count={view === "list" ? items.length + listFeatureCount : mapFeatureCount + (serverClustered ? serverClusters.reduce((sum, item) => sum + item.count, 0) : visiblePoints.length)} status={pending.length ? "조회 중…" : undefined} />
    <TabsContent className="min-h-0" value="map"><MapStage className={mode === "fuel" ? "fuel-map-stage" : undefined} summary={summary} detail={detailPanel("map")}><div className="map-primary" ref={mapContainer}><VWorldMapView apiKey={VWORLD_KEY} center={mapViewport ? [mapViewport.longitude, mapViewport.latitude] : [127.8, 36.2]} zoom={mapViewport?.zoom ?? 7} minZoom={5}
        className="transport-map-canvas" layerType="Base" navigation={false} geolocate={false} scale
        loadingSkeleton={<p className="loading">지도를 준비하는 중입니다…</p>} fallback={(info) => <MapUnavailable info={info} onMessage={setMapUnavailableMessage} />}
        unsupportedTileFallback={{ imageUrl: MAP_FALLBACK_IMAGE }} transformRequest={basemap.transformRequest}
        onError={basemap.onError} onIdle={basemap.onIdle} onLoad={moved} onMoveEnd={(event) => moved(event.target)}>
        <ZoomButtons />
        <CameraRequest target={camera} />
        {layers}
        {serverClustered ? serverClusters.map((item, index) => <MapMarkerButton key={`${item.longitude}:${item.latitude}:${index}`} lngLat={[item.longitude, item.latitude]} ariaLabel={`${item.count}개 장소 요약 묶음 확대`} interactionId={`server-cluster:${item.longitude.toFixed(6)},${item.latitude.toFixed(6)}`} className="map-cluster" zIndex={3} isCluster onClick={() => {
          setClusterPlaces([]); setClusterCamera({ center: [item.longitude, item.latitude], zoom: Math.min(19, Math.max(12, Math.ceil(zoom) + 2)) });
          setCameraRequest((value) => value + 1);
        }}><ClusterBubble count={item.count} label={CLUSTER_NUMBER_FORMATTER.format(item.count)} /></MapMarkerButton>) : <ClusterLayer points={groupedPoints} radius={cluster ? (products.length === 1 ? 80 : 110) : 60} maxZoom={19}
          renderCluster={(group, count, index) => {
            const coordinates = group.geometry.coordinates;
            const id = group.properties.cluster_id;
            // 묶음 원은 낱개 마커 위(z 3), 선택 마커 아래다. interaction id는 zoom이 든 cluster_id 대신 위치로 잡아
            // 재조회로 묶음 원이 다시 만들어져도 같은 data-interaction-id로 포커스를 찾는다.
            return <MapMarkerButton lngLat={coordinates} ariaLabel={`${count}개 위치 묶음 펼치기`} className="map-cluster" zIndex={3} isCluster
              interactionId={`cluster:${coordinates[0].toFixed(6)},${coordinates[1].toFixed(6)}`} onClick={(element) => {
                if (id === undefined) return;
                const expansion = index.getClusterExpansionZoom(id);
                if (expansion > 19 || zoom >= 19) {
                  // Map과 같이 확대해도 풀리지 않는 묶음은 겹친 지점 팝업으로 고르게 한다.
                  overlapOpener.current = element;
                  setClusterAnchor(coordinates);
                  setClusterPlaces(index.getLeaves(id, count).map((leaf) => (leaf.properties as unknown as MapPoint).place));
                  requestAnimationFrame(() => clusterList.current?.querySelector("button")?.focus());
                } else {
                  setClusterPlaces([]); setClusterCamera({ center: coordinates, zoom: Math.min(19, expansion) });
                  setCameraRequest((value) => value + 1);
                }
              }}><ClusterBubble count={count} label={String(group.properties.point_count_abbreviated ?? count)} /></MapMarkerButton>;
          }}
          renderMarker={(point: ClusterPoint) => <MapMarker point={point as unknown as MapPoint} products={products} onSelect={selectPlace} selected={false} />} />}
        {selectedPoint ? <MapMarker point={selectedPoint} products={products} onSelect={selectPlace} selected /> : null}
        {clusterPlaces.length ? <OverlapPopup lngLat={clusterAnchor} onClose={closeOverlap}>
          <OverlapList places={clusterPlaces} onSelect={selectPlace} listRef={clusterList} />
        </OverlapPopup> : null}
      </VWorldMapView></div>
      </MapStage>
    </TabsContent>
    <TabsContent className="min-h-0" value="list"><MapStage view="list" detail={detailPanel("list")}><div className="map-primary"><div className="map-place-list"><div className="map-feedback">{status}</div>{listContent}{listPlaces ? items.map((place) => <button type="button" className="place-row" key={keyOf(place)} aria-pressed={current ? keyOf(current) === keyOf(place) : false} onClick={() => selectPlace(place)}><PlaceIcon kind={place.kind} /><span><strong>{place.name}</strong><small>{place.line_names.join(" · ") || place.brand_name || place.subtitle || placeKindLabel(place.kind)}</small>{(place.kind === "ferry_port" || place.kind === "bus_terminal") && place.provider_id ? <small>{place.kind === "ferry_port" ? "항구" : "터미널"} 코드 {place.provider_id}</small> : null}{!hasCoordinates(place) ? <small>좌표 미등록</small> : null}</span></button>) : null}</div></div></MapStage></TabsContent>
    {!embedded && !(mode === "fuel" && view === "map") ? <div className="map-feedback map-guidance" role="status">
      {kinds.includes("fuel_station") && loaded.fuel_station?.fuel_prices_stale ? <p className="error">유가 갱신 지연 · 유종·가격은 {dateTime(loaded.fuel_station.fuel_prices_last_refreshed_at)} 기준이며 판매 여부도 다를 수 있습니다.</p> : null}
      {kinds.includes("fuel_station") && loaded.fuel_station?.fuel_prices_last_refreshed_at && !loaded.fuel_station.fuel_prices_stale ? <p>유가 {dateTime(loaded.fuel_station.fuel_prices_last_refreshed_at)} 갱신</p> : null}
    </div> : null}
    </Tabs>
    </MapWorkspace>
  </section>;
}
